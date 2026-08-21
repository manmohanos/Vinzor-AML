"""Letters from the regulator, and whether they were answered in time.

Scored against IFSCA's twenty-five published enforcement actions, this is
the ground with the most orders against it and nothing built: three of the
twenty-five. It is also the one that behaves least like the rest of the
product. Everything else here is reactive -- a payment arrived, a name
matched, come and look. The calendar is the other half: something recurs,
and nobody has filed it.

A notice is neither. It arrives when the Authority chooses, asks for
something nobody anticipated, and sets its own date. Regulation 120 requires
an FME to furnish what is asked "accurately and timely", and the failure
mode is the quietest one in compliance: nothing happens. No alert fires
because no transaction was made, no rule was broken at the moment of
breach, and the file simply sits. By the time anybody notices, the breach is
the silence itself and it is already months long.

**Which is why nothing here is stored as a state.** A notice arriving is a
fact and an answer being sent is a fact; both are events. Whether an answer
is late is computed from those two and the date being asked about. A stored
"overdue" flag would have to be set by something at some moment -- and the
thing that sets it is exactly what nobody does when a notice is being
ignored. The one condition this module exists to catch would be the one
condition it could not see.

**A notice with no date on it is not given one.** Some letters set a
deadline and some do not. Inventing one would put a date on a compliance
record that the regulator never wrote, and every later report would repeat
it as though it were theirs. An undated notice is carried as open and
unmeasurable, and says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .model import EventType

#: How long before a deadline the file starts asking for attention. A
#: regulator's letter usually wants something gathered from several people,
#: so a week is the point at which starting still leaves time to finish.
WARN_WITHIN_DAYS = 7

#: Who a notice can come from, in the words a reader uses. Not a closed
#: list -- anything else is carried through as written, because a firm
#: hearing from an authority we have not anticipated should not be told
#: their letter is unrecognised.
SENDERS = {
    "IFSCA": "IFSCA",
    "FIU": "FIU-IND",
    "FIU-IND": "FIU-IND",
    "RBI": "the Reserve Bank",
    "SEBI": "SEBI",
}


def _as_date(value: str) -> Optional[date]:
    """A date from a record, or nothing. Never a guess."""
    text = str(value or "")[:10]
    try:
        year, month, day = (int(part) for part in text.split("-"))
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class Notice:
    """One letter, and what has been done about it."""

    reference: str
    from_whom: str
    about: str
    received_on: str
    #: The date the regulator set, where they set one. Empty otherwise, and
    #: empty means unmeasurable rather than "no rush".
    answer_by: str = ""
    answered_on: str = ""
    answered_by: str = ""
    answer: str = ""

    @property
    def is_open(self) -> bool:
        return not self.answered_on

    def days_left(self, today: str) -> Optional[int]:
        """How long there is, or nothing where no date was set.

        Negative once the date has passed, which is the number that
        matters: an answer eleven days late is a different conversation
        from one a day late, and rounding both to "overdue" loses it.
        """
        due, asking = _as_date(self.answer_by), _as_date(today)
        if due is None or asking is None:
            return None
        return (due - asking).days

    def was_late(self) -> Optional[int]:
        """How many days late the answer was, once one was sent."""
        due, sent = _as_date(self.answer_by), _as_date(self.answered_on)
        if due is None or sent is None:
            return None
        return max(0, (sent - due).days)


@dataclass
class Correspondence:
    """Every letter from a regulator, and every answer to one."""

    notices: dict = field(default_factory=dict)
    #: References whose lateness has already been put on the record. The
    #: log says the lateness was observed, not that it is still true every
    #: time somebody opens the page.
    reported_late: frozenset = frozenset()

    def apply(self, event) -> None:
        if event.event_type is EventType.NOTICE_OVERDUE:
            reference = str((event.payload or {}).get("reference") or "")
            if reference:
                self.reported_late = self.reported_late | {reference}
            return

        if event.event_type is EventType.NOTICE_RECEIVED:
            payload = event.payload or {}
            reference = str(payload.get("reference") or "").strip()
            if not reference:
                return
            # Replaced rather than mutated: a reader may hold this while
            # another thread folds.
            self.notices = {**self.notices, reference: Notice(
                reference=reference,
                from_whom=str(payload.get("from_whom") or ""),
                about=str(payload.get("about") or ""),
                received_on=str(event.occurred_at)[:10],
                answer_by=str(payload.get("answer_by") or "")[:10],
            )}
            return

        if event.event_type is EventType.NOTICE_ANSWERED:
            payload = event.payload or {}
            reference = str(payload.get("reference") or "").strip()
            standing = self.notices.get(reference)
            if standing is None:
                return
            from dataclasses import replace
            self.notices = {**self.notices, reference: replace(
                standing,
                answered_on=str(event.occurred_at)[:10],
                answered_by=str(event.actor or ""),
                answer=str(payload.get("answer") or ""),
            )}

    def open_notices(self) -> tuple:
        """Soonest deadline first.

        Sorted on the parsed date rather than the stored string. It used to
        sort on ``(n.answer_by or "9999", …)``, so an unpadded month put a
        nearer deadline below a further one: three open letters due 25 Aug,
        1 Sep (typed ``2026-9-01``) and 1 Oct listed as 6 days, 43 days,
        13 days. ``days_left`` was right all along; only the order was wrong,
        and it was wrong on the dashboard panel, the CLI listing and
        everywhere else that reads this. The log already holds unpadded
        values and cannot be rewritten, so the key is hardened here as well
        as at ingest.
        """
        return tuple(sorted(
            (n for n in self.notices.values() if n.is_open),
            key=lambda n: (_as_date(n.answer_by) or date.max, n.reference)))

    def answered(self) -> tuple:
        return tuple(sorted((n for n in self.notices.values()
                             if not n.is_open),
                            key=lambda n: n.answered_on))

    def overdue(self, today: str) -> tuple:
        """Open notices whose date has passed."""
        out = []
        for notice in self.open_notices():
            left = notice.days_left(today)
            if left is not None and left < 0:
                out.append(notice)
        return tuple(out)

    def due_soon(self, today: str, within: int = WARN_WITHIN_DAYS) -> tuple:
        out = []
        for notice in self.open_notices():
            left = notice.days_left(today)
            if left is not None and 0 <= left <= within:
                out.append(notice)
        return tuple(out)

    def undated(self) -> tuple:
        """Open notices nobody can measure, which is its own problem."""
        return tuple(n for n in self.open_notices()
                     if n.days_left("2000-01-01") is None)


def who_sent_it(from_whom: str) -> str:
    """The sender, named the way a person would say it."""
    return SENDERS.get(str(from_whom or "").strip().upper(),
                       str(from_whom or "").strip() or "a regulator")


def _counted_days(days: int) -> str:
    return f"{days} day" + ("" if days == 1 else "s")


def how_late(notice: Notice, today: str) -> str:
    """"18 days past the date they set" -- or nothing to say."""
    left = notice.days_left(today)
    if left is None or left >= 0:
        return ""
    return f"{_counted_days(-left)} past the date they set"


def how_long_left(notice: Notice, today: str) -> str:
    left = notice.days_left(today)
    if left is None:
        return "no date was set, so nothing here can tell you when it is late"
    if left == 0:
        return "the date they set is today"
    if left < 0:
        return how_late(notice, today)
    return f"{_counted_days(left)} left"
