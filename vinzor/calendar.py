"""What the FME owes the regulator, and when.

The third and last of the grounds IFSCA enforces on most often, and the one
that cost Karvy Broking its registration: quarterly reports it simply never
filed. Everything else in this system is *reactive* — something happened, come
and look. This is the other half: something is due, and nobody has done it.

**The schedule is computed, not stored.** Given the date a licence was granted
and a date to look from, every obligation instance since is derivable. Storing
a generated schedule would be storing a conclusion — the same mistake as
persisting a UBO answer. Only the *filings* are events, because only they are
facts about the world.

**On the clock.** ``datetime.date`` arithmetic is used freely here: adding 21
days to a quarter end is deterministic and replays identically. What is still
forbidden is ``date.today()`` — a caller always supplies the date it is asking
about. The distinction matters: date *maths* is pure, date *reading* is I/O.

Sources, all primary:

* **Quarterly report** — circular of 31 May 2023, amended 3 November 2023 to
  change the frequency from half-yearly to quarterly, formats revised 3 April
  2025; due **within 21 calendar days of the end of the quarter**. Enabled by
  Regulation 120 of the Fund Management Regulations, 2025.
* **Flat recurring fee** — fee circular IFSCA-DTFA/1/2026: for years after the
  year of grant it "shall become due on 01st of April and be paid by 30th of
  April of such financial year".
* **Conditional recurring fee, first instalment** — same circular, calculated
  on the preceding year's turnover and "payable by 30th of April".
* **Late charge** — same circular: failure to submit a periodic return on time
  costs **USD 100 for every month or part thereof, for each instance**, and
  paying it is "without prejudice to any other action" the Authority may take.
  Karvy paid with its registration.
* **FIU-IND registration** — circulars of 14 March 2024
  (F. No. 886/IFSCA/FATF-C/Coordination/2023-24) and 25 February 2025
  (F. No. IFSCA/2/2025-AMLCFT/01): every Regulated Entity registers on
  FINGate 2.0 **before commencing business**, and non-compliance "shall be
  treated as a breach of the terms and conditions of registration or licence".
  One obligation, once, and a licence is out of condition every day it goes
  undone — so it is due the day the licence is granted, or the day the 2024
  circular issued for a licence older than the mandate.
* **NISM-IFSCA-01 certification** — circular of 17 November 2025
  (e.F. No. IFSCA-DAC/8/2024-AMLCFT): mandatory for the Principal Officer,
  within **four months**. Read here as four months from appointment or from
  the circular, whichever ends later — an officer appointed before the
  mandate existed cannot have owed it earlier than the mandate did. The
  certificate is personal, so the obligation follows the holder: a new
  Principal Officer starts a new four-month clock, and a vacated one takes
  their instance with them.

**What is deliberately not here.** The monthly 15th-of-the-month reports to
FIU-IND (CTR and the rest, PML Rules rule 8(1)) are due only for the reportable
transactions of rule 3, and this workspace does not yet hold the transaction
feeds that would say whether any occurred. A tracker that showed "CTR overdue"
to a firm that had no reportable transactions would be inventing a breach —
the same defect as reporting an unrun check as clean, pointed the other way.
Those rows arrive when the data that makes them true or false does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Mapping, Optional, Sequence

from .model import StrEnum

#: The Indian financial year runs April to March, so quarters end here.
QUARTER_ENDS = ((6, 30), (9, 30), (12, 31), (3, 31))

#: Circular of 31 May 2023 as amended 3 November 2023.
QUARTERLY_REPORT_DAYS = 21

#: Fee circular IFSCA-DTFA/1/2026: due 1 April, payable by 30 April.
ANNUAL_FEE_DUE = (4, 30)

#: USD per month or part thereof, per instance, for a late periodic return.
LATE_CHARGE_USD_PER_MONTH = 100

#: How far ahead something starts appearing as pressing. A product choice, not
#: a regulatory one -- there is no "warning period" in the circular.
DUE_SOON_DAYS = 7

#: The day FINGate registration became a condition of every licence
#: (circular of 14 March 2024). A licence granted before this owes the
#: registration from this day; one granted after owes it from the grant.
FINGATE_MANDATED_ON = "2024-03-14"

#: The day the NISM-IFSCA-01 requirement issued, and the window it allows.
NISM_MANDATED_ON = "2025-11-17"
NISM_GRACE_MONTHS = 4


class Obligation(StrEnum):
    QUARTERLY_REPORT = "QUARTERLY_REPORT"
    FLAT_RECURRING_FEE = "FLAT_RECURRING_FEE"
    CONDITIONAL_RECURRING_FEE = "CONDITIONAL_RECURRING_FEE"
    FINGATE_REGISTRATION = "FINGATE_REGISTRATION"
    NISM_CERTIFICATION = "NISM_CERTIFICATION"


class Status(StrEnum):
    SUBMITTED = "SUBMITTED"
    UPCOMING = "UPCOMING"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"


def _iso(value: str) -> date:
    year, month, day = (int(part) for part in value.split("-")[:3])
    return date(year, month, day)


def _add_months(start: date, months: int) -> date:
    """``start`` shifted by whole months, clamped to the end of the month.

    31 January plus one month is 28 February, not 3 March. Rolling over would
    make the charge land a few days early every time the due date is late in a
    long month.
    """
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    last = _DAYS_IN_MONTH[month]
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        last = 29
    return date(year, month, min(start.day, last))


_DAYS_IN_MONTH = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
                  7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


@dataclass(frozen=True)
class Schedule:
    obligation: Obligation
    #: What a person calls it.
    label: str
    quarterly: bool
    clause: str
    authority: str
    late_charge: bool
    #: A return is filed; a fee is paid. Using one word for both is the kind of
    #: slip a compliance officer notices immediately.
    verb: str = "filed"


SCHEDULES: Sequence[Schedule] = (
    Schedule(
        obligation=Obligation.QUARTERLY_REPORT,
        label="quarterly report to IFSCA",
        quarterly=True,
        clause="120",
        authority="Circular of 31 May 2023 as amended 3 November 2023; formats "
                  "revised 3 April 2025. Due within 21 calendar days of the "
                  "quarter end.",
        late_charge=True,
        verb="filed",
    ),
    Schedule(
        obligation=Obligation.FLAT_RECURRING_FEE,
        label="annual recurring fee",
        quarterly=False,
        clause="fee-4",
        authority="Fee circular IFSCA-DTFA/1/2026: becomes due on 1 April and "
                  "is payable by 30 April of the financial year it relates to.",
        late_charge=False,
        verb="paid",
    ),
    Schedule(
        obligation=Obligation.CONDITIONAL_RECURRING_FEE,
        label="turnover-based fee, first instalment",
        quarterly=False,
        clause="fee-5",
        authority="Fee circular IFSCA-DTFA/1/2026: calculated on the preceding "
                  "year's turnover and payable by 30 April.",
        late_charge=False,
        verb="paid",
    ),
    Schedule(
        obligation=Obligation.FINGATE_REGISTRATION,
        label="FIU-IND FINGate 2.0 registration",
        quarterly=False,
        clause="10.3",
        authority="Circulars of 14 March 2024 and 25 February 2025: every "
                  "Regulated Entity registers on FINGate 2.0 before "
                  "commencing business, and non-compliance is a breach of "
                  "the conditions of the licence itself.",
        late_charge=False,
        verb="done",
    ),
    Schedule(
        obligation=Obligation.NISM_CERTIFICATION,
        label="NISM-IFSCA-01 certification",
        quarterly=False,
        clause="10.3",
        authority="Circular of 17 November 2025: mandatory for the Principal "
                  "Officer within four months of appointment or of the "
                  "circular, whichever is later.",
        late_charge=False,
        verb="done",
    ),
)

BY_OBLIGATION: Mapping[Obligation, Schedule] = {s.obligation: s for s in SCHEDULES}


def _d(iso: str) -> date:
    year, month, day = (int(p) for p in iso.split("-")[:3])
    return date(year, month, day)


def financial_year(day: date) -> int:
    """The Indian financial year a date falls in, named by its start year."""
    return day.year if day.month >= 4 else day.year - 1


def quarter_label(period_end: date) -> str:
    fy = financial_year(period_end)
    index = [(m, d) for m, d in QUARTER_ENDS].index((period_end.month, period_end.day))
    return f"Q{index + 1} FY{fy}-{str(fy + 1)[-2:]}"


@dataclass(frozen=True)
class Instance:
    """One occurrence of an obligation: a period, a deadline, and its state."""

    obligation: Obligation
    period: str
    period_end: str
    due_on: str
    submitted_on: Optional[str] = None

    @property
    def schedule(self) -> Schedule:
        return BY_OBLIGATION[self.obligation]

    def status(self, today: str) -> Status:
        if self.submitted_on:
            return Status.SUBMITTED
        now, due = _d(today), _d(self.due_on)
        if now > due:
            return Status.OVERDUE
        if (due - now).days <= DUE_SOON_DAYS:
            return Status.DUE_SOON
        return Status.UPCOMING

    def days_late(self, today: str) -> int:
        if self.submitted_on:
            return max(0, (_d(self.submitted_on) - _d(self.due_on)).days)
        return max(0, (_d(today) - _d(self.due_on)).days)

    def late_charge_usd(self, today: str) -> int:
        """USD 100 per month or part thereof, where the charge applies."""
        if not self.schedule.late_charge:
            return 0
        if self.days_late(today) <= 0:
            return 0
        # Calendar months, not thirty-day blocks. Dividing by 30 over-charged
        # by a whole month at every exact anniversary: 21 July to 21 August is
        # one month late and was billed as two, because 31 days rounds up to
        # two thirty-day blocks. An over-charge invented by arithmetic is the
        # kind of number an officer gets asked to justify.
        due, now = _iso(self.due_on), _iso(today)
        months = (now.year - due.year) * 12 + (now.month - due.month)
        anniversary = _add_months(due, months)
        if anniversary < now:      # part of a further month has elapsed
            months += 1
        return max(1, months) * LATE_CHARGE_USD_PER_MONTH

    @property
    def key(self) -> str:
        return f"{self.obligation.value}|{self.period}"


def _quarter_ends(start: date, until: date) -> Iterable[date]:
    year = start.year - 1
    while year <= until.year + 1:
        for month, day in QUARTER_ENDS:
            end = date(year if month != 3 else year + 1, month, day)
            if start <= end <= until:
                yield end
        year += 1


def instances(
    granted_on: str, today: str, submitted: Optional[Mapping[str, str]] = None,
    officers: Sequence[tuple] = (),
) -> list[Instance]:
    """Every obligation instance between the grant of the licence and ``today``.

    Derived, never stored. ``submitted`` maps an instance key to the date it
    was filed. ``officers`` is (person, appointed_on) for whoever currently
    holds the Principal Officer seat -- passed in rather than read here,
    because this module computes from dates and takes no engine, and the one
    caller that knows the officers is the one that holds the licence.
    """
    submitted = submitted or {}
    start, now = _d(granted_on), _d(today)
    found: list[Instance] = []

    # One registration, once, for the licence itself. Due the day the grant
    # made it a condition, or the day the mandate issued for a licence that
    # predates it. The period names the licence rather than a quarter,
    # because there is no period: a firm is registered with FIU-IND or its
    # licence is out of condition.
    fingate_due = max(start, _d(FINGATE_MANDATED_ON))
    item = Instance(
        obligation=Obligation.FINGATE_REGISTRATION,
        period="this licence",
        period_end=fingate_due.isoformat(),
        due_on=fingate_due.isoformat(),
    )
    found.append(
        Instance(**{**item.__dict__, "submitted_on": submitted.get(item.key)})
    )

    # One certification per current Principal Officer, keyed by name: the
    # certificate is personal, so a new holder starts a new clock and a
    # vacated one takes their instance with them. Four months from the later
    # of the appointment and the mandate -- an officer appointed before the
    # requirement existed cannot have owed it before it did.
    for person, appointed_on in officers:
        clock_starts = max(_d(str(appointed_on)), _d(NISM_MANDATED_ON))
        item = Instance(
            obligation=Obligation.NISM_CERTIFICATION,
            period=str(person),
            period_end=clock_starts.isoformat(),
            due_on=_add_months(clock_starts, NISM_GRACE_MONTHS).isoformat(),
        )
        found.append(
            Instance(**{**item.__dict__,
                        "submitted_on": submitted.get(item.key)})
        )

    for end in sorted(set(_quarter_ends(start, now))):
        due = end + timedelta(days=QUARTERLY_REPORT_DAYS)
        item = Instance(
            obligation=Obligation.QUARTERLY_REPORT,
            period=quarter_label(end),
            period_end=end.isoformat(),
            due_on=due.isoformat(),
        )
        found.append(
            Instance(**{**item.__dict__, "submitted_on": submitted.get(item.key)})
        )

    # Annual fees, for every financial year after the one the licence was
    # granted in -- the circular is explicit that the year of grant is handled
    # pro rata on grant instead.
    for fy in range(financial_year(start) + 1, financial_year(now) + 1):
        due = date(fy + 1 if ANNUAL_FEE_DUE[0] < 4 else fy, *ANNUAL_FEE_DUE)
        for obligation in (Obligation.FLAT_RECURRING_FEE,
                           Obligation.CONDITIONAL_RECURRING_FEE):
            item = Instance(
                obligation=obligation,
                period=f"FY{fy}-{str(fy + 1)[-2:]}",
                period_end=date(fy + 1, 3, 31).isoformat(),
                due_on=due.isoformat(),
            )
            found.append(
                Instance(**{**item.__dict__, "submitted_on": submitted.get(item.key)})
            )

    return sorted(found, key=lambda i: (i.due_on, i.obligation.value))


def outstanding(
    granted_on: str, today: str, submitted: Optional[Mapping[str, str]] = None,
    officers: Sequence[tuple] = (),
) -> list[Instance]:
    """Everything not filed, oldest deadline first."""
    return [i for i in instances(granted_on, today, submitted, officers)
            if not i.submitted_on]


def overdue(
    granted_on: str, today: str, submitted: Optional[Mapping[str, str]] = None,
    officers: Sequence[tuple] = (),
) -> list[Instance]:
    return [i for i in outstanding(granted_on, today, submitted, officers)
            if i.status(today) is Status.OVERDUE]


class Calendar:
    """What has been filed. A projection; the schedule itself is computed."""

    def __init__(self) -> None:
        #: instance key -> date filed
        self.submitted: dict[str, str] = {}
        #: instance keys already reported late, so it is said once
        self.reported_late: set[str] = set()

    def apply(self, event) -> None:
        from .model import EventType

        payload = event.payload
        if event.event_type is EventType.FILING_SUBMITTED:
            key = f"{payload['obligation']}|{payload['period']}"
            self.submitted[key] = payload.get("submitted_on", event.occurred_at)
        elif event.event_type is EventType.FILING_OVERDUE:
            self.reported_late.add(f"{payload['obligation']}|{payload['period']}")
