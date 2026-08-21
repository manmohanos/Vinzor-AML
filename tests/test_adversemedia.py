"""The news boundary — retrieved, never judged, and never silently clean.

No network. The transport is injected, so what is under test is the contract:
that the adversity lives in the query rather than in a reading, that a check
which did not happen writes nothing, and that a rate-limit notice cannot
become "we searched the world's news and found nothing".
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from vinzor.adversemedia import (
    ADVERSE_THEMES,
    AdverseMediaUnavailable,
    NewsClient,
    check,
    query_for,
)
from vinzor.model import EventType

from conftest import WHEN, person

#: What GDELT actually answers a rate-limited caller with: prose, and a 429.
RATE_LIMITED = (
    b"Please limit requests to one every 5 seconds or contact "
    b"kalev.leetaru5@gmail.com for larger queries."
)


def news(*articles, status=None, body=None):
    """A fake GDELT. Records the URL it was asked for."""
    asked = []

    def transport(url):
        asked.append(url)
        if status is not None:
            raise urllib.error.HTTPError(url, status, "no", {}, None)
        if body is not None:
            return body
        return json.dumps({"articles": list(articles)}).encode()

    transport.asked = asked
    return transport


def article(title="Fraud charges laid", domain="example.com",
            seen="20260820T124500Z", url="https://example.com/1"):
    return {"title": title, "url": url, "domain": domain,
            "seendate": seen, "language": "English", "sourcecountry": "India"}


# -- the query is the finding ------------------------------------------------


def test_the_search_is_the_name_and_the_themes_and_nothing_else():
    """A firm has to be able to show what it searched for. If adversity were
    decided by reading, there would be nothing to show."""
    q = query_for("Nirav Modi")
    assert '"Nirav Modi"' in q
    for theme in ADVERSE_THEMES:
        assert f"theme:{theme}" in q


def test_a_name_with_query_syntax_in_it_cannot_rewrite_the_search():
    """A party genuinely called "Smith AND Co (Holdings)" would otherwise
    turn its own screening into a different question."""
    q = query_for("Smith AND Co (Holdings)")
    assert "(" not in q.split("(")[1] if "(" in q else True
    assert q.startswith('"Smith AND Co Holdings"')


def test_a_name_too_short_to_search_is_refused_not_guessed_at():
    with pytest.raises(AdverseMediaUnavailable):
        query_for("Li")


def test_the_window_and_the_cap_travel_on_the_record():
    client = NewsClient(transport=news(article()), window="6m", most=5)
    _found, basis = client.search("Nirav Modi")
    assert basis["window"] == "6m"
    assert basis["capped_at"] == 5
    assert basis["query"] == query_for("Nirav Modi")


# -- a check that did not happen writes nothing ------------------------------


def test_a_rate_limit_notice_is_never_an_empty_result(engine):
    """The defect this module was written around. GDELT answers 429 with
    prose, and a parser looking for articles finds none -- which reads as
    'we searched the world's news and there was nothing about this person'.
    """
    person(engine, "p1", "Nirav Modi")
    with pytest.raises(AdverseMediaUnavailable) as refusal:
        check(engine, "p1", checked_at=WHEN,
              client=NewsClient(transport=news(status=429)))
    assert "slow down" in str(refusal.value)


def test_prose_returned_with_a_200_is_also_refused(engine):
    """A maintenance banner and a gateway page both arrive as HTML with a
    200 on them. Neither is a search."""
    person(engine, "p1", "Nirav Modi")
    with pytest.raises(AdverseMediaUnavailable):
        check(engine, "p1", checked_at=WHEN,
              client=NewsClient(transport=news(body=RATE_LIMITED)))


def test_a_refused_check_writes_nothing_at_all(engine):
    person(engine, "p1", "Nirav Modi")
    before = len(engine.log)
    with pytest.raises(AdverseMediaUnavailable):
        check(engine, "p1", checked_at=WHEN,
              client=NewsClient(transport=news(status=429)))
    assert len(engine.log) == before


def test_an_unreachable_service_is_refused_rather_than_reported_clean(engine):
    person(engine, "p1", "Nirav Modi")

    def dead(url):
        raise TimeoutError("no answer")

    with pytest.raises(AdverseMediaUnavailable):
        check(engine, "p1", checked_at=WHEN,
              client=NewsClient(transport=dead))


# -- what gets recorded ------------------------------------------------------


def test_finding_nothing_is_still_recorded(engine):
    """Unlike the watchlist, this index is always built, so an empty answer
    is a real answer -- and 'we looked and there was nothing' is the whole
    evidentiary point."""
    person(engine, "p1", "Ordinary Person")
    check(engine, "p1", checked_at=WHEN,
          client=NewsClient(transport=news()))
    written = [e for e in engine.log
               if e.event_type is EventType.ADVERSE_MEDIA_CHECKED]
    assert len(written) == 1
    assert written[0].payload["found"] == 0


def test_the_articles_themselves_are_on_the_record(engine):
    """The finding rests on a dated snapshot of the press, because the news
    is not the same tomorrow and nothing may re-query on replay."""
    person(engine, "p1", "Nirav Modi")
    check(engine, "p1", checked_at=WHEN,
          client=NewsClient(transport=news(
              article(title="Fraud charges laid", domain="bbc.co.uk"),
              article(title="Assets frozen", domain="reuters.com"))))
    written = [e for e in engine.log
               if e.event_type is EventType.ADVERSE_MEDIA_CHECKED][-1]
    kept = written.payload["basis"]["articles"]
    assert [a["domain"] for a in kept] == ["bbc.co.uk", "reuters.com"]
    assert kept[0]["seen_on"] == "2026-08-20", "a person reads a date"


def test_the_same_answer_replays_without_asking_again(engine):
    """Deterministic where it can be: the record is read back, never
    re-queried, so a file does not change because the news moved on."""
    person(engine, "p1", "Nirav Modi")
    check(engine, "p1", checked_at=WHEN,
          client=NewsClient(transport=news(article(), article(), article())))
    before = engine.state.casebook.cases
    rebuilt = engine.rebuild()
    assert rebuilt.casebook.cases == before


# -- when it opens a file ----------------------------------------------------


def three_sources():
    return news(article(domain="bbc.co.uk", url="https://bbc.co.uk/1"),
                article(domain="reuters.com", url="https://reuters.com/1"),
                article(domain="ft.com", url="https://ft.com/1"))


def test_a_run_of_coverage_from_several_publications_opens_a_file(engine):
    person(engine, "p1", "Nirav Modi")
    result = check(engine, "p1", checked_at=WHEN,
                   client=NewsClient(transport=three_sources()))
    assert result.cases, "three articles from three publications is a file"
    opened = result.cases[0]
    # Cited to 4.2 and to nothing else. There is no IFSCA clause requiring an
    # adverse media check, and citing an adjacent one would be exactly the
    # fabricated legal reference the register exists to prevent.
    cited = json.dumps(opened.evidence[0].citations, default=str)
    assert "4.2" in cited


def test_one_article_is_a_coincidence_not_a_file(engine):
    """A single piece naming somebody is very often a namesake, and a queue
    full of those teaches people to close files without reading them."""
    person(engine, "p1", "Nirav Modi")
    result = check(engine, "p1", checked_at=WHEN,
                   client=NewsClient(transport=news(article())))
    assert not result.cases


def test_one_story_syndicated_many_times_is_still_one_story(engine):
    """Twelve copies of one wire piece is one fact. Counting it as twelve is
    how a morning list fills up with the same thing."""
    person(engine, "p1", "Nirav Modi")
    same = news(*[article(domain="syndicated.com", url=f"https://s.com/{i}")
                  for i in range(12)])
    result = check(engine, "p1", checked_at=WHEN,
                   client=NewsClient(transport=same))
    assert not result.cases


def test_the_file_says_what_was_searched_for(engine):
    """An officer opening this has to be able to see the question, because
    the question is the only thing that decided what 'adverse' meant."""
    person(engine, "p1", "Nirav Modi")
    result = check(engine, "p1", checked_at=WHEN,
                   client=NewsClient(transport=three_sources()))
    detail = result.cases[0].evidence[0].detail
    assert "searched_for" in detail
    assert "theme:FRAUD" in detail["searched_for"]
    assert sorted(detail["sources"]) == ["bbc.co.uk", "ft.com", "reuters.com"]
