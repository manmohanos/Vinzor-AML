"""The overnight run, and -- more importantly -- saying when it did not happen.

Everything this system needs to do on a schedule already existed and nothing
ran it. ``rescreening.rescreen`` screens the stale book. ``observe_deadlines``
turns a passed date into a file on somebody's desk. Both were reachable from
a command line and neither was ever on a timer, so a workspace could sit for
a month while the watchlists moved underneath it and every screen kept saying
what it said in April.

That is this codebase's oldest defect at the scale of the whole system. A
party page reading "screened, nothing found" is a claim about the past
pretending to be a claim about the present, and a regulatory page reading
"nothing is overdue" is only true if something looked. So the sweep is half
of what lives here, and the other half is the part that matters more:

**A workspace that has not been swept says so, everywhere the sweep would
have mattered.** :func:`currency` reads the log for the last run and
:func:`briefing` renders it above the figures it would have refreshed. Not a
log line, not a dashboard nobody opens -- the sentence sits on the page the
officer is reading, because the failure being guarded against is precisely
that the timer stopped and everything continued to look fine.

**What is not here, on purpose.**

There is no scheduler. ``python -m vinzor nightly`` on a systemd timer is the
schedule, and ``deploy/vinzor-nightly.timer`` is that line. An application
that grows its own scheduler is an application with two of them, and the
second one has no monitoring.

There is no partial-success flag. A run that could not reach the watchlist
for four hundred parties records those four hundred by name. Anyone reading
the record can see the run happened and see what it did not manage; a boolean
saying "ok" would be the summary lying about its own detail.

There is no locking against two sweeps at once. The engine already takes a
re-entrant lock around ingest and the fold, a second run finds nothing out of
date because the first one recorded the version, and a timer that overlaps
itself is a deployment mistake that shows up as a duplicate record rather
than as corruption.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .model import EventType

#: How long a workspace may go unswept before the screens stop presenting
#: their figures as current. One day: the sweep is nightly, so a workspace
#: swept yesterday is doing what it should, and one swept the day before
#: that has missed a night. UAPA s.51A requires the UNSC lists to be
#: verified daily, which is the same interval arrived at from the law
#: rather than from the deployment.
STALE_AFTER_DAYS = 1


def _days_between(earlier: str, later: str) -> int:
    """Whole days from one ISO date to another. Never negative."""
    from datetime import date

    def _d(iso: str) -> date:
        return date(*(int(part) for part in str(iso)[:10].split("-")))

    return max(0, (_d(later) - _d(earlier)).days)


@dataclass(frozen=True)
class Ran:
    """One overnight run, as the log recorded it."""

    on: str
    screened: int = 0
    files_opened: int = 0
    #: Parties the watchlist could not be asked about, by name and reason.
    #: Carried rather than counted: see the module docstring.
    unreachable: tuple[tuple[str, str], ...] = ()
    version: str = ""

    @property
    def complete(self) -> bool:
        return not self.unreachable


@dataclass(frozen=True)
class Currency:
    """Whether this workspace's figures have been refreshed lately."""

    #: The last run, or None where nothing has ever swept this workspace.
    last: Optional[Ran] = None
    #: Days since that run, as of the date the reader passed in.
    days_ago: int = 0

    @property
    def never(self) -> bool:
        return self.last is None

    @property
    def stale(self) -> bool:
        """Whether the figures should stop being presented as current.

        A workspace nobody has ever swept is stale, and emphatically so: it
        is the case where every screen reads its best and means least.
        """
        return self.never or self.days_ago > STALE_AFTER_DAYS


def currency(engine, today: str) -> Currency:
    """When this workspace was last swept, as of ``today``.

    ``today`` is passed in, never read from a clock -- the rule every read in
    this system obeys, so that a page rendered during a replay says what it
    said at the time rather than what it would say now.
    """
    found: Optional[Ran] = None
    for event in engine.log:
        if event.event_type is not EventType.SWEEP_COMPLETED:
            continue
        payload = event.payload or {}
        found = Ran(
            on=str(event.occurred_at)[:10],
            screened=int(payload.get("screened", 0) or 0),
            files_opened=int(payload.get("files_opened", 0) or 0),
            unreachable=tuple(
                (str(row[0]), str(row[1]))
                for row in (payload.get("unreachable") or ()) if len(row) >= 2
            ),
            version=str(payload.get("list_version", "") or ""),
        )
    if found is None:
        return Currency()
    return Currency(last=found, days_ago=_days_between(found.on, today))


def run(engine, *, today: str, client, parties: Optional[Sequence[str]] = None,
        ) -> Ran:
    """Screen what is out of date, look for passed deadlines, record both.

    The order is deliberate. Screening first means a party who landed on a
    watchlist overnight has a Case open before the deadline pass runs, so an
    officer opening the queue in the morning sees the sanctions match above
    the missed quarterly return rather than below it.

    The record is written last and always, including when the watchlist was
    unreachable throughout. A run that failed is a fact about this workspace
    -- it is *the* fact, if it keeps happening -- and a sweep that recorded
    nothing when it went badly would leave the screens saying "last swept
    Tuesday" through a fortnight of failures.
    """
    from .rescreening import rescreen

    before = len(engine.log)
    swept = rescreen(engine, today=today, client=client, parties=parties)
    engine.observe_deadlines(today)

    opened = sum(1 for event in list(engine.log)[before:]
                 if event.event_type is EventType.CASE_OPENED)
    ran = Ran(on=str(today)[:10], screened=swept.screened,
              files_opened=opened, unreachable=swept.unreachable,
              version=swept.version)

    engine.ingest(
        event_type=EventType.SWEEP_COMPLETED,
        subject=engine.state.licence.number or "the entity",
        occurred_at=today,
        actor="system",
        payload={
            "screened": ran.screened,
            "files_opened": ran.files_opened,
            "unreachable": [list(row) for row in ran.unreachable],
            "list_version": ran.version,
        },
    )
    return ran
