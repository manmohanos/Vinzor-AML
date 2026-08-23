"""Screening the whole book again, and knowing who is overdue for it.

``screening.py`` answers "what do the watchlists say about this party, today".
It is a boundary, and it does its job the moment an officer asks. What nothing
answered until now is the question underneath it: **when was this party last
looked at, and has the list moved since?**

That gap is the same defect this codebase has found in five other places,
wearing time as a disguise. A party screened clean in April is shown on every
screen as screened. The list is not the same list it was in April -- the
OpenSanctions index this workspace holds is rebuilt continuously, and a person
added to it in May is a person this firm has never been checked against. The
record says "checked"; the truth is "checked against a list that no longer
exists". A check that did not happen must never be reported as a check that
found nothing, and a check that happened against a list four months out of
date is closer to the first than the second.

So two things live here, and deliberately only two.

**Currency** -- :func:`overdue` reads the log and says which parties were
never screened at all, and which were screened against a version other than
the one the service holds now. It computes; it does not fix. That alone closes
the honesty gap, because a number an officer can see is a number an officer
can act on.

**The re-screen** -- :func:`rescreen` walks those parties and screens them
again, once per run, against a version fetched once per run.

**What is not here, on purpose.**

There is no scheduler. A nightly run is ``python -m vinzor rescreen`` on a
timer, and a timer is a line of deployment configuration, not a subsystem.
Building a scheduling framework inside an application that needs one cron
entry is how a codebase acquires a second, worse cron.

There is no delta-file consumption. OpenSanctions publishes what changed
between versions, and using it would narrow a run to the parties whose
watchlist entries actually moved. That is a real optimisation and it is not
needed yet: the cost of screening the whole book is one HTTP call per party
against a service on the same machine. When a book is large enough that this
hurts, the delta files will still be there, and the shape of the answer will
not change -- only which parties :func:`overdue` returns.

There is no separate daily sweep of the UNSC lists. UAPA s.51A requires those
to be verified daily, and a nightly run of this against scope ``default`` --
which contains them -- *is* that verification. A second sweep asking the same
service the same question about the same parties would produce a second record
of the same fact, and two records of one fact is not better evidence than one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .model import EventType

#: What a screening record says about its own currency when it does not say.
#: Every screening written before the version was recorded carries this, and
#: reads as overdue -- correctly. A record that cannot say which list it saw
#: cannot be shown as current, and the first run after this ships will screen
#: the whole book once for exactly that reason.
UNKNOWN_VERSION = ""


@dataclass(frozen=True)
class Currency:
    """When one party was last screened, and against what."""

    party: str
    name: str
    #: "" where this party has never been screened at all.
    last_screened: str = ""
    #: "" where the screening predates versions being recorded.
    version: str = UNKNOWN_VERSION

    @property
    def never(self) -> bool:
        return not self.last_screened

    def stale_against(self, current: str) -> bool:
        """Whether this needs looking at again, given what the service holds.

        A party never screened is overdue. A party screened against an
        unknown version is overdue, because "we cannot say what it was
        checked against" is not a claim of currency. A party screened
        against a version that is not the current one is overdue.

        Where the *service* cannot say what it holds, nothing is overdue on
        that account -- a screen is not stale merely because the catalogue
        was reticent this evening, and treating it as such would re-screen
        the entire book every run for as long as the catalogue stayed quiet.
        """
        if self.never or self.version == UNKNOWN_VERSION:
            return True
        if current == UNKNOWN_VERSION:
            return False
        return self.version != current


def currency(engine) -> tuple[Currency, ...]:
    """When every party on the book was last screened, and against what.

    A fold over the log, in order, keeping the last screening seen per
    party -- the same shape every other read in this system has, for the
    same reason: the answer is derived from the record rather than kept
    beside it, so it cannot drift from what actually happened.
    """
    latest: dict[str, tuple[str, str]] = {}
    for event in engine.log:
        if event.event_type is not EventType.SCREENING_COMPLETED:
            continue
        basis = event.payload.get("basis") or {}
        latest[event.subject] = (
            str(event.occurred_at),
            str(basis.get("list_version") or UNKNOWN_VERSION),
        )

    graph = engine.state.graph
    out = []
    for party_id, entity in graph.entities.items():
        when, version = latest.get(party_id, ("", UNKNOWN_VERSION))
        out.append(Currency(party=party_id, name=entity.name,
                            last_screened=when, version=version))
    out.sort(key=lambda row: (not row.never, row.last_screened, row.name))
    return tuple(out)


def newest_version(engine) -> str:
    """The most recent watchlist version this workspace has ever seen.

    Read off the log rather than asked of the service, because the screens
    that read this are read-side folds and a page that reaches the network
    to render is a page that fails when the network does.

    What it can say is therefore bounded, and the wording that shows it says
    so: this is the newest list *this workspace has been screened against*,
    not necessarily the newest the service holds. If the service has moved on
    and no sweep has run since, nothing here knows that yet -- which is an
    argument for running the sweep, not for guessing on a screen.

    Latest by position in the log, not by sorting the strings. A version is
    whatever the service chose to call itself, and ordering opaque labels
    alphabetically is how "v9" comes after "v10".
    """
    seen = UNKNOWN_VERSION
    for event in engine.log:
        if event.event_type is not EventType.SCREENING_COMPLETED:
            continue
        version = str((event.payload.get("basis") or {}).get("list_version")
                      or UNKNOWN_VERSION)
        if version:
            seen = version
    return seen


def overdue(engine, current_version: str) -> tuple[Currency, ...]:
    """Every party due to be screened again, never-screened ones first."""
    return tuple(row for row in currency(engine)
                 if row.stale_against(current_version))


def settled_alerts(engine, party: str) -> frozenset:
    """Watchlist entities somebody already looked at and closed, for a party.

    Read off the casebook rather than the log, because "settled" is a
    property of a Case and the casebook is the fold that knows it. Only
    closed Cases count: a match still open is a question nobody has answered
    yet, and re-observing it belongs on that same open file as more evidence
    -- which is what happens today and is right.

    This is the list :func:`screening.screen` is told to hold back, and the
    reason it exists is in that function's docstring: a closed Case meeting
    the same finding reopens as a *new* Case, so without this a nightly run
    hands back every dismissed false positive, every night, forever.
    """
    found = set()
    for case in engine.state.casebook.cases.values():
        if case.subject != party or case.is_open:
            continue
        for piece in case.evidence:
            alert = str((piece.detail or {}).get("alert_id") or "")
            if alert:
                found.add(alert)
    return frozenset(found)


@dataclass(frozen=True)
class Swept:
    """What one run of :func:`rescreen` did."""

    version: str
    looked_at: tuple[str, ...] = ()
    #: Parties the service could not be asked about. Named, never counted as
    #: screened -- a run that could not reach the watchlist for half the book
    #: has screened half the book, and says so.
    unreachable: tuple[tuple[str, str], ...] = ()

    @property
    def screened(self) -> int:
        return len(self.looked_at)


def rescreen(engine, *, today: str, client, parties: Optional[Sequence[str]] = None,
             ) -> Swept:
    """Screen every party whose screening is out of date, once.

    ``today`` is passed in, never read from a clock -- the rule every check
    in this system obeys, so that a run can be replayed and reach the same
    answer.

    The version is asked for once and handed to every screen, rather than
    each of them asking the same service the same question. Where the
    service will not say, the run still happens: an unknown version is
    recorded as unknown, which reads as overdue next time, and a screening
    performed is better evidence than one skipped over a missing label.

    A party the service could not be reached about is named in the result
    and is *not* counted as screened. Nothing is recorded for it -- which is
    ``screening.py``'s own discipline, kept: a failed check writes no fact
    at all rather than a fact that reads like a clean one.
    """
    from .screening import ScreeningUnavailable, screen

    version = client.list_version()
    due = (tuple(parties) if parties is not None
           else tuple(row.party for row in overdue(engine, version)))

    looked_at: list[str] = []
    unreachable: list[tuple[str, str]] = []
    for party in due:
        try:
            screen(engine, party, screened_at=today, client=client,
                   list_version=version,
                   settled=settled_alerts(engine, party))
        except ScreeningUnavailable as refused:
            unreachable.append((party, str(refused)))
        except Exception as broke:      # noqa: BLE001 - one party, not the run
            # One party that cannot be screened does not end the run: the
            # other four hundred still need looking at, and a sweep that
            # stops at the first bad name is a sweep that never finishes on
            # a real book. What must not happen is the failure vanishing,
            # so it is carried out in the result.
            unreachable.append((party, f"{type(broke).__name__}: {broke}"))
        else:
            looked_at.append(party)

    return Swept(version=version, looked_at=tuple(looked_at),
                 unreachable=tuple(unreachable))
