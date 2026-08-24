"""The overnight run, and the sentence that admits it did not happen.

Most of this file is about the second thing. A sweep that works is worth
little on its own -- what makes the figures trustworthy is that a workspace
whose timer stopped says so on the page somebody is reading, rather than
going on presenting April's answers in August with no mark on them.
"""

from __future__ import annotations

import pytest

from vinzor.model import EventType
from vinzor.screening import WatchlistClient
from vinzor.sweep import STALE_AFTER_DAYS, Ran, currency, run

from conftest import WHEN, company, person
from test_rescreening import service

TODAY = "2026-08-23"


def Quiet(version="20260823-aaa"):
    """A reachable watchlist that matches nobody.

    Faked at the transport rather than at the client, so the real screening
    path -- the request body, the version read, the provenance written --
    runs exactly as it does against a live yente.
    """
    return WatchlistClient(transport=service(version=version))


def Down():
    """A watchlist nothing can reach."""

    def transport(url, body, headers):
        raise OSError("the watchlist could not be reached")

    return WatchlistClient(transport=transport)


def book(engine):
    company(engine, "c1", "Meridian Capital Ltd")
    person(engine, "p1", "Rohan Desai")


# -- what a run does ---------------------------------------------------------


def test_a_run_screens_the_stale_book_and_records_that_it_happened(engine):
    book(engine)
    ran = run(engine, today=TODAY, client=Quiet())

    assert ran.screened == 2
    assert ran.on == TODAY
    assert ran.complete
    assert any(e.event_type is EventType.SWEEP_COMPLETED for e in engine.log)


def test_a_second_run_the_same_night_finds_nothing_left_to_do(engine):
    """What makes this safe to put on a timer. The first run records which
    version each party was screened against, so the second costs one
    catalogue read and screens nobody."""
    book(engine)
    run(engine, today=TODAY, client=Quiet())
    again = run(engine, today=TODAY, client=Quiet())
    assert again.screened == 0


def test_the_run_is_recorded_even_when_the_watchlist_was_down(engine):
    """The run that matters most. A sweep that recorded nothing when it went
    badly would leave the screens saying "last swept Tuesday" through a
    fortnight of failures -- which is the exact shape of the defect this
    whole module exists to close."""
    book(engine)
    ran = run(engine, today=TODAY, client=Down())

    assert ran.screened == 0
    assert not ran.complete
    assert len(ran.unreachable) == 2
    assert any(e.event_type is EventType.SWEEP_COMPLETED for e in engine.log)


def test_a_party_that_could_not_be_reached_is_named_not_counted(engine):
    book(engine)
    ran = run(engine, today=TODAY, client=Down())
    named = {party for party, _ in ran.unreachable}
    assert named == {"c1", "p1"}
    assert ran.screened == 0, "an unreachable party was counted as screened"


def test_the_run_looks_for_passed_deadlines_too(engine):
    """Screening and the calendar are one run, because they are one night's
    work and a firm that screened but never looked at its filings has done
    half of what the timer was for."""
    from vinzor.licence import Category

    company(engine, "fme_1", "Acme GIFT Fund Managers Ltd")
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="fme_1",
                  occurred_at="2023-04-01",
                  payload={"category": Category.REGISTERED_NON_RETAIL.value,
                           "number": "IFSCA/FME/II/2023-24/084"})

    ran = run(engine, today=TODAY, client=Quiet())
    assert any(e.event_type is EventType.FILING_OVERDUE for e in engine.log)
    assert ran.files_opened > 0


# -- and the part that matters more ------------------------------------------


def test_a_workspace_nobody_swept_says_so(engine):
    """Every figure reads its best and means least: nothing is overdue,
    nothing has matched, and nothing has looked."""
    book(engine)
    how = currency(engine, TODAY)
    assert how.never
    assert how.stale


def test_a_workspace_swept_last_night_is_current(engine):
    book(engine)
    run(engine, today="2026-08-22", client=Quiet())
    how = currency(engine, "2026-08-23")
    assert not how.never
    assert how.days_ago == 1
    assert not how.stale


def test_a_workspace_that_missed_a_night_is_stale(engine):
    book(engine)
    run(engine, today="2026-08-20", client=Quiet())
    how = currency(engine, TODAY)
    assert how.days_ago == 3
    assert how.stale, (
        f"three days without a sweep read as current at a threshold of "
        f"{STALE_AFTER_DAYS}")


def test_currency_reads_the_latest_run_not_the_first(engine):
    book(engine)
    run(engine, today="2026-08-01", client=Quiet())
    run(engine, today="2026-08-22", client=Quiet(version="later/mock"))
    how = currency(engine, TODAY)
    assert how.last.on == "2026-08-22"


def test_the_page_says_it_when_nothing_has_ever_swept(engine):
    from vinzor.briefing import regulatory

    book(engine)
    said = regulatory(engine, TODAY).swept
    assert said
    assert "state of your records, not the state of the world" in said


def test_the_page_names_the_date_and_the_gap_when_stale(engine):
    from vinzor.briefing import regulatory

    book(engine)
    run(engine, today="2026-08-20", client=Quiet())
    said = regulatory(engine, TODAY).swept
    assert "20 August 2026" in said, "a date somebody can go and look at"
    assert "3 days ago" in said


def test_the_page_does_not_call_an_incomplete_run_clean(engine):
    """A run that reached nobody still happened, and the sentence has to
    carry both halves: it ran, and it did not manage."""
    from vinzor.briefing import regulatory

    book(engine)
    run(engine, today=TODAY, client=Down())
    said = regulatory(engine, TODAY).swept
    assert "2 parties" in said
    assert "not screened" in said


def test_the_sentence_reads_as_english_for_one_party(engine):
    from vinzor.briefing import regulatory

    company(engine, "c1", "Meridian Capital Ltd")
    run(engine, today=TODAY, client=Down())
    said = regulatory(engine, TODAY).swept
    assert "1 party" in said and "was not screened" in said


# -- the discipline every other module here keeps ----------------------------


def test_nothing_in_this_module_reads_a_clock():
    """``today`` is passed in, so a page rendered during a replay says what
    it said at the time rather than what it would say now."""
    import ast
    import inspect

    from vinzor import sweep

    tree = ast.parse(inspect.getsource(sweep))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("today", "now"):
            raise AssertionError(f"{node.attr}() is read here")
