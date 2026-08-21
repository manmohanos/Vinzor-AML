"""Adverse media — what the press has said, retrieved rather than judged.

The third external boundary, after the watchlist and the model. It asks GDELT,
a public index of world news, whether a party's name appears alongside coverage
of financial crime, and records what came back.

**It does not decide whether the coverage is adverse, and that is deliberate.**
A model reading an article and pronouncing on its sentiment would be exactly
the thing this architecture refuses: a fact established by a machine's
judgement, unrepeatable, and impossible to defend eleven months later. So the
adversity is in the *query*, not in the reading. A fixed set of financial-crime
themes is asked about by name, the articles that come back are recorded with
their source and date, and an officer reads them. The finding this produces is
"eleven articles matched this name alongside fraud and corruption coverage",
which is a fact, not "this person looks bad", which is an opinion.

**No IFSCA clause requires an adverse media check.** There is no such clause,
and this module says so rather than citing something adjacent. What there is
is clause 4.2, which lists the factors a firm shall take into account when
judging whether a customer is high risk, and negative press is plainly one of
the things a person weighing those factors would want in front of them. So the
finding cites 4.2 and describes itself as a risk factor, not as a breach.

## The failure that matters

GDELT rate-limits to one request every five seconds and answers a refusal with
**plain text and HTTP 429**, not JSON:

    Please limit requests to one every 5 seconds or contact ...

Read carelessly that is an empty article list, which is to say "we searched the
world's news and found nothing about this person" — a clean record for a check
that never happened. That is the same defect ``screening.py`` exists to make
impossible, arriving through a different door, and it is closed the same way:
anything that is not a JSON body this module recognises is a named refusal, and
a refusal writes nothing at all.

## Determinism, honestly

The watchlist replays because the answer was recorded. This cannot be
re-queried to the same result — the news changes, that is what news is — so
the same discipline applies and matters more: the articles seen, the query
used, the window asked about and the day it was asked are all written into the
event. **Replay reads the record; nothing re-queries.** A finding therefore
rests on a dated snapshot of the press, which is exactly what a firm can
defend, and never on what GDELT happens to say today.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from .engine import IngestResult, Vinzor
from .model import EventType

#: GDELT's document API. Public, no key, and no account to hold.
DEFAULT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

#: How far back to look. Two years is long enough to catch a matter that has
#: gone quiet and short enough that a name shared with a footballer does not
#: bury the file. Stated rather than defaulted silently, because the window
#: is part of what was checked and appears on the record.
DEFAULT_WINDOW = "24m"

#: Most articles asked for. A person is going to read these; a hundred is not
#: a finding, it is a reading list. The count of everything matched is
#: reported separately, so a truncated list never reads as a complete one.
MOST_ARTICLES = 25

#: The GDELT themes this asks about, and the whole of what this module means
#: by "adverse". Written down rather than inferred from tone, because a firm
#: should be able to say precisely what it searched for and a tone score
#: cannot be explained to anybody.
#:
#: Deliberately financial crime and nothing else. Adding, say, terrorism or
#: armed conflict would return every executive who has ever been quoted in a
#: story about a war, and an alert nobody can act on trains people to close
#: alerts without reading them.
ADVERSE_THEMES: tuple[str, ...] = (
    "FRAUD",
    "CORRUPTION",
    "ECON_BANKRUPTCY",
    "SCANDAL",
    "TAX_FNCACT_INVESTIGATOR",
    "TRIAL",
    "ARREST",
    "SEIZE",
    "MONEY_LAUNDERING",
)

#: Seconds. A person is waiting, and GDELT is slow when it is busy.
TIMEOUT_SECONDS = 12

#: GDELT allows one request every five seconds and refuses the rest. That is
#: a shared limit rather than a per-caller one, so an ordinary onboarding
#: meets it -- measured on the deployed instance, which was refused on its
#: first real search.
#:
#: Waiting and asking again is the honest remedy, and a bounded number of
#: times so a busy service cannot hold an officer indefinitely. Six seconds
#: rather than five, because the limit is theirs to measure and not ours.
#: Exhausting the retries is still a refusal, never a clean result.
#: One retry, not more. Two cost a minute and a half of an officer's
#: attention before the first check could even start, and the press is the
#: least decisive of the eight -- a sanctions match stops the money and this
#: does not. Asking twice recovers the ordinary case where the shared limit
#: happened to be busy; asking five times just makes somebody wait.
RETRIES = 1
WAIT_BETWEEN = 6

#: Seconds this whole search may take, retries and all. GDELT is slow when it
#: is busy and there is somebody watching a screen.
GIVE_UP_AFTER = 25

#: A body larger than this is not an article list.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class AdverseMediaUnavailable(RuntimeError):
    """The news index could not be asked, or answered in a form this system
    does not recognise.

    Never a finding, and never a clean record. A check that did not happen is
    not the same as a check that found nothing, and the difference is the
    whole reason this class exists.
    """


Transport = Callable[[str], bytes]


def _http(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json",
                      # GDELT refuses a request with no agent, and a name is
                      # more courteous than a blank to whoever reads its logs.
                      "User-Agent": "vinzor-compliance/1.0"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:
        return answer.read(MAX_RESPONSE_BYTES + 1)


#: A name reduced to what can safely go in a query. GDELT's syntax gives
#: meaning to quotes, brackets and boolean words, so a party actually called
#: "Smith AND Co (Holdings)" would otherwise rewrite the search.
_UNSAFE = re.compile(r'[^\w\s.\'-]', re.UNICODE)


def query_for(name: str, themes: Sequence[str] = ADVERSE_THEMES) -> str:
    """The exact search this module makes for a name.

    Its own function because it is the thing a firm has to be able to show:
    *this is what we searched for*. Quoted, so the words stay together, and
    combined with the themes so an ordinary person sharing a name with an
    ordinary story does not become a finding.
    """
    clean = _UNSAFE.sub(" ", name or "").strip()
    clean = " ".join(clean.split())
    if len(clean) < 3:
        raise AdverseMediaUnavailable(
            "There is not enough of a name here to search the news for."
        )
    themed = " OR ".join(f"theme:{t}" for t in themes)
    return f'"{clean}" ({themed})'


@dataclass(frozen=True)
class Article:
    """One piece of coverage, as it will be shown to a person."""

    title: str
    url: str
    domain: str
    seen_on: str
    language: str = ""
    country: str = ""


@dataclass(frozen=True)
class NewsClient:
    """A GDELT document search, or anything that answers like one."""

    url: str = DEFAULT_URL
    window: str = DEFAULT_WINDOW
    themes: tuple[str, ...] = ADVERSE_THEMES
    most: int = MOST_ARTICLES
    #: Seconds to wait before asking again after a rate-limit refusal.
    #: A field rather than a constant so a test can prove the refusal without
    #: paying twelve real seconds for it.
    wait: float = WAIT_BETWEEN
    transport: Transport = field(default=_http)

    def search(self, name: str) -> tuple[list[Article], dict[str, Any]]:
        """What the press has carried about this name, and what was asked.

        Returns the articles and the provenance to record beside them. An
        empty list is a real answer here and is recorded as one -- unlike the
        watchlist, this index is always built -- but only when the service
        actually answered in JSON.
        """
        query = query_for(name, self.themes)
        asked = (f"{self.url}?query={urllib.parse.quote_plus(query)}"
                 f"&mode=artlist&format=json"
                 f"&maxrecords={int(self.most)}"
                 f"&timespan={urllib.parse.quote_plus(self.window)}"
                 f"&sort=datedesc")
        raw, refusal = None, None
        for attempt in range(RETRIES + 1):
            try:
                raw = self.transport(asked)
                break
            except urllib.error.HTTPError as answered:
                refusal = answered
                if answered.code == 429 and attempt < RETRIES:
                    # Their limit, so their pace. A sleep at an I/O boundary
                    # is not a clock reading -- nothing here asks what time
                    # it is, and nothing derived from it reaches the log.
                    time.sleep(self.wait)
                    continue
                break
            except (urllib.error.URLError, OSError, TimeoutError) as broke:
                refusal = broke
                break

        if raw is None:
            if isinstance(refusal, urllib.error.HTTPError):
                if refusal.code == 429:
                    # The one that would have been silent. GDELT answers this
                    # with plain text, so a parser looking for articles finds
                    # none and calls the party clean.
                    raise AdverseMediaUnavailable(
                        "The news service asked us to slow down, so no search "
                        "was made. Nothing was recorded. Try again in a "
                        "moment."
                    ) from None
                raise AdverseMediaUnavailable(
                    "The news service answered %s and no search was made. "
                    "Nothing was recorded." % refusal.code
                ) from None
            raise AdverseMediaUnavailable(
                "The news service could not be reached, so no search was "
                "made. Nothing was recorded."
            ) from None

        if len(raw) > MAX_RESPONSE_BYTES:
            raise AdverseMediaUnavailable(
                "The news service sent more than this system will read. "
                "Nothing was recorded."
            )

        text = raw.decode("utf-8", "replace").strip()
        if not text.startswith("{"):
            # Rate-limit notices, gateway pages and maintenance banners all
            # arrive as prose with a 200 on them. None of those is a search
            # that found nothing.
            raise AdverseMediaUnavailable(
                "The news service answered in a form this system does not "
                "recognise, so nothing was recorded."
            )
        try:
            body = json.loads(text)
            found = body.get("articles")
            if found is None:
                found = []
            if not isinstance(found, list):
                raise TypeError("articles was not a list")
            articles = [
                Article(
                    title=str(item.get("title") or "").strip(),
                    url=str(item.get("url") or "").strip(),
                    domain=str(item.get("domain") or "").strip(),
                    seen_on=_as_date(item.get("seendate")),
                    language=str(item.get("language") or "").strip(),
                    country=str(item.get("sourcecountry") or "").strip(),
                )
                for item in found if isinstance(item, Mapping)
            ]
        except (ValueError, TypeError, AttributeError) as broken:
            raise AdverseMediaUnavailable(
                "The news service answered in a form this system does not "
                "recognise, so nothing was recorded."
            ) from broken

        provenance = {
            "service": self.url,
            "query": query,
            "window": self.window,
            "themes": list(self.themes),
            "articles_seen": len(articles),
            "capped_at": int(self.most),
            "articles": [
                {"title": a.title, "url": a.url, "domain": a.domain,
                 "seen_on": a.seen_on}
                for a in articles[:self.most]
            ],
        }
        return articles, provenance


def _as_date(raw: Any) -> str:
    """GDELT stamps an article ``20260820T124500Z``. A person reads a date."""
    text = str(raw or "")
    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return ""


def check(engine: Vinzor, entity_id: str, *, checked_at: str,
          client: Optional[NewsClient] = None) -> IngestResult:
    """Search the news for one party and record what was found.

    The record is written whether or not anything was found, for the reason
    the watchlist writes a clean screen: "we looked and there was nothing" is
    the evidence, and an absent record is indistinguishable from an absent
    check.
    """
    client = client or NewsClient()
    entity = engine.state.graph.entities.get(entity_id)
    if entity is None:
        raise AdverseMediaUnavailable(
            "There is no party on the record with that reference."
        )

    articles, provenance = client.search(entity.name)
    return engine.ingest(
        event_type=EventType.ADVERSE_MEDIA_CHECKED,
        subject=entity_id,
        occurred_at=checked_at,
        actor="system",
        payload={
            "name": entity.name,
            "found": len(articles),
            # The finding rests on this snapshot rather than on a re-query,
            # because the news is not the same tomorrow and a compliance
            # record that changes underneath itself is not a record.
            "basis": provenance,
        },
    )
