"""The FME's own licence: what it may do, and who must be in post.

Built after reading IFSCA's published enforcement orders, which say plainly
what costs an entity its registration. Two of the three most common grounds are
here.

**Scope.** Regulation 3(4) sorts FMEs into three categories and says what each
may undertake; the categories nest, so a Registered FME (Retail) may do
everything the other two may. Regulation 137 closes it: no other business
activity at all without the Authority's prior approval. IFSCA has penalised
entities under this heading for providing distribution services without
registration and for unauthorised trading access.

**Governance.** Regulation 7 sets out who must hold office — a principal
officer always, a compliance officer for any Registered FME, an additional
fund-management KMP for a retail FME before its first offer document and for
any FME once AUM reaches USD 1 billion — and 7(5) requires all of them to be
*based out of IFSC*. Regulation 10 requires office space and manpower
commensurate with the operation.

**What this cannot do, stated plainly.** IFSCA's finding against Neo Asset
Management came from walking into the office on four separate days and finding
it shut. No software can see an empty room. What it can see is the precondition:
an office nobody holds, a holder who is not based in the IFSC, or a threshold
crossed with the clock running. Those are knowable, and they are what precedes
the visit. ``UNOBSERVABLE`` below says so on every result rather than letting a
green screen imply more than it knows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from .model import Event, EventType, StrEnum


class Category(StrEnum):
    """Regulation 3(4). The three registration categories."""

    AUTHORISED = "AUTHORISED"
    REGISTERED_NON_RETAIL = "REGISTERED_NON_RETAIL"
    REGISTERED_RETAIL = "REGISTERED_RETAIL"


class Activity(StrEnum):
    """What an FME can be doing, as Regulation 3(4) enumerates it."""

    VENTURE_CAPITAL_SCHEME = "VENTURE_CAPITAL_SCHEME"
    FAMILY_INVESTMENT_FUND = "FAMILY_INVESTMENT_FUND"
    RESTRICTED_SCHEME = "RESTRICTED_SCHEME"
    PORTFOLIO_MANAGEMENT_SERVICES = "PORTFOLIO_MANAGEMENT_SERVICES"
    INVESTMENT_TRUST_PRIVATE_PLACEMENT = "INVESTMENT_TRUST_PRIVATE_PLACEMENT"
    RETAIL_SCHEME = "RETAIL_SCHEME"
    INVESTMENT_TRUST_PUBLIC_OFFER = "INVESTMENT_TRUST_PUBLIC_OFFER"
    EXCHANGE_TRADED_FUND = "EXCHANGE_TRADED_FUND"


#: Regulation 3(4)(a). An Authorised FME's own activities.
_AUTHORISED = frozenset({
    Activity.VENTURE_CAPITAL_SCHEME,
    Activity.FAMILY_INVESTMENT_FUND,
})

#: 3(4)(b), which adds to and includes everything at (a).
_NON_RETAIL = _AUTHORISED | {
    Activity.RESTRICTED_SCHEME,
    Activity.PORTFOLIO_MANAGEMENT_SERVICES,
    Activity.INVESTMENT_TRUST_PRIVATE_PLACEMENT,
}

#: 3(4)(c), which adds to and includes everything at (a) and (b).
_RETAIL = _NON_RETAIL | {
    Activity.RETAIL_SCHEME,
    Activity.INVESTMENT_TRUST_PUBLIC_OFFER,
    Activity.EXCHANGE_TRADED_FUND,
}

PERMITTED: Mapping[Category, frozenset] = {
    Category.AUTHORISED: _AUTHORISED,
    Category.REGISTERED_NON_RETAIL: frozenset(_NON_RETAIL),
    Category.REGISTERED_RETAIL: frozenset(_RETAIL),
}


class Office(StrEnum):
    """A post Regulation 7 requires someone to hold.

    Distinct from ``model.Role``, which is what an actor is allowed to *do* in
    this system. An Office is a seat at the regulated entity.
    """

    PRINCIPAL_OFFICER = "PRINCIPAL_OFFICER"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    FUND_MANAGEMENT_KMP = "FUND_MANAGEMENT_KMP"


#: The clause that requires each office, for citation on the Case.
OFFICE_CLAUSE = {
    Office.PRINCIPAL_OFFICER: "7(1)",
    Office.COMPLIANCE_OFFICER: "7(2)",
    Office.FUND_MANAGEMENT_KMP: "7(4)",
}

#: Regulation 7(4): the trigger, and the grace period the proviso allows.
AUM_KMP_THRESHOLD_USD = 1_000_000_000
AUM_KMP_GRACE_MONTHS = 6

#: What the regulator establishes by visiting, and software cannot.
UNOBSERVABLE = (
    "physical presence on any given day (Regulation 7(5), 10(1)): IFSCA "
    "establishes this by surprise visit, and this system cannot. It reports "
    "only whether an office is filled and whether its holder is recorded as "
    "based in the IFSC."
)


@dataclass(frozen=True)
class Holder:
    person: str
    since: str
    based_in_ifsc: bool


@dataclass(frozen=True)
class Filled:
    """A seat that was empty and is now taken.

    Recorded so the Case opened for the vacancy does not go stale. A Case
    is still closed by a person -- but it should say the post was filled,
    by whom and when, rather than continuing to read as though nobody is
    there.
    """

    office: Office
    person: str
    vacated_on: str
    filled_on: str
    based_in_ifsc: bool


@dataclass(frozen=True)
class Gap:
    """A governance requirement that is not currently met."""

    office: Office
    clause: str
    reason: str
    person: Optional[str] = None
    #: Set where the regulation allows time to put it right.
    due_by: Optional[str] = None


def principal_officers(licence) -> tuple:
    """(person, appointed_on) for the current Principal Officer seat.

    The shape ``calendar.instances`` takes for the NISM clock. A tuple of at
    most one today, but shaped as a sequence because the obligation is per
    holder, not per seat -- if a second certified post ever joins the
    mandate, the callers do not change.
    """
    holder = licence.holders.get(Office.PRINCIPAL_OFFICER)
    if holder is None:
        return ()
    return ((holder.person, holder.since),)


class Licence:
    """The entity's registration, its offices and what it has been doing.

    A projection like any other: rebuilt from the log, never authoritative on
    its own.
    """

    def __init__(self) -> None:
        self.category: Optional[Category] = None
        self.number: str = ""
        self.granted_on: str = ""
        self.holders: dict[Office, Holder] = {}
        self.vacated: dict[Office, str] = {}
        self.activities: dict[Activity, str] = {}
        #: Refills since the last event, for the policy to report on.
        self.just_filled: list[Filled] = []
        self.aum_usd: Optional[float] = None
        self.aum_as_at: str = ""

    # -- projection -------------------------------------------------------

    def apply(self, event: Event) -> None:
        self.just_filled = []
        payload = event.payload
        if event.event_type is EventType.LICENCE_GRANTED:
            self.category = Category(payload["category"])
            self.number = payload.get("number", "")
            self.granted_on = event.occurred_at
        elif event.event_type is EventType.OFFICE_APPOINTED:
            office = Office(payload["office"])
            holder = Holder(
                person=payload["person"],
                since=event.occurred_at,
                based_in_ifsc=bool(payload.get("based_in_ifsc", False)),
            )
            was_vacant = self.vacated.pop(office, None)
            # A seat can be empty without anyone ever having vacated it: a
            # licence granted before the post was filled, or a requirement
            # that only arose later when AUM crossed the threshold. Keying the
            # refill off ``vacated`` alone meant those appointments produced no
            # "filled" evidence, so the HIGH vacancy Case went on saying nobody
            # held the post after somebody did.
            #
            # Only for a post the rules actually require, though: filling a
            # seat nobody had to fill resolves nothing, because no vacancy was
            # ever raised. Appointments made before the grant are covered by
            # that too -- there is no category yet, so nothing is required.
            was_empty = office not in self.holders and office in self.required_offices()
            self.holders[office] = holder
            if was_vacant or was_empty:
                self.just_filled = [Filled(
                    office=office, person=holder.person,
                    vacated_on=was_vacant, filled_on=event.occurred_at,
                    based_in_ifsc=holder.based_in_ifsc,
                )]
        elif event.event_type is EventType.OFFICE_VACATED:
            office = Office(payload["office"])
            self.holders.pop(office, None)
            self.vacated[office] = event.occurred_at
        elif event.event_type is EventType.ACTIVITY_UNDERTAKEN:
            self.activities.setdefault(Activity(payload["activity"]), event.occurred_at)
        elif event.event_type is EventType.AUM_REPORTED:
            self.aum_usd = float(payload["amount_usd"])
            self.aum_as_at = payload.get("as_at", event.occurred_at)

    # -- scope ------------------------------------------------------------

    def permits(self, activity: Activity) -> bool:
        """Regulation 3(4). Unknown category permits nothing — fail closed."""
        if self.category is None:
            return False
        return activity in PERMITTED[self.category]

    # -- governance -------------------------------------------------------

    def required_offices(self) -> set[Office]:
        """Which posts Regulation 7 requires, given category, activity and AUM."""
        if self.category is None:
            return set()
        required = {Office.PRINCIPAL_OFFICER}                      # 7(1)
        if self.category in (Category.REGISTERED_NON_RETAIL,
                             Category.REGISTERED_RETAIL):
            required.add(Office.COMPLIANCE_OFFICER)                # 7(2)
        retail_launched = bool(
            {Activity.RETAIL_SCHEME, Activity.EXCHANGE_TRADED_FUND}
            & set(self.activities)
        )
        if self.category is Category.REGISTERED_RETAIL and retail_launched:
            required.add(Office.FUND_MANAGEMENT_KMP)               # 7(3)
        if self.aum_usd is not None and self.aum_usd >= AUM_KMP_THRESHOLD_USD:
            required.add(Office.FUND_MANAGEMENT_KMP)               # 7(4)
        return required

    def gaps(self) -> list[Gap]:
        """Every Regulation 7 requirement not currently met."""
        found: list[Gap] = []
        for office in sorted(self.required_offices(), key=lambda o: o.value):
            holder = self.holders.get(office)
            if holder is None:
                found.append(Gap(
                    office=office,
                    clause=self._clause_for(office),
                    reason="vacant",
                    due_by=self._kmp_due_by() if office is Office.FUND_MANAGEMENT_KMP
                    else None,
                ))
            elif not holder.based_in_ifsc:
                found.append(Gap(
                    office=office,
                    clause="7(5)",
                    reason="holder is not recorded as based in the IFSC",
                    person=holder.person,
                ))
        return found

    def _clause_for(self, office: Office) -> str:
        if office is Office.FUND_MANAGEMENT_KMP:
            # 7(3) for a retail launch, 7(4) once AUM crosses the threshold.
            if self.category is Category.REGISTERED_RETAIL and (
                {Activity.RETAIL_SCHEME, Activity.EXCHANGE_TRADED_FUND}
                & set(self.activities)
            ):
                return "7(3)"
            return "7(4)"
        return OFFICE_CLAUSE[office]

    def _kmp_due_by(self) -> Optional[str]:
        """Regulation 7(4) proviso: six months from the end of that year.

        "That year" is the financial year the as-at date falls in (April to
        March), not the as-at date itself -- an AUM report as at, say, 15 May
        2026 sits in FY2026-27, which ends 31 March 2027, so the grace period
        runs to six months past *that*, not six months past 15 May. The two
        readings only coincide when the report is as at 31 March.

        Derived from the reported AUM date rather than from a clock, so it
        replays identically.
        """
        if not self.aum_as_at:
            return None
        try:
            year, month, _ = (int(p) for p in self.aum_as_at.split("-")[:3])
        except ValueError:
            return None
        financial_year = year if month >= 4 else year - 1
        fy_end_year, fy_end_month = financial_year + 1, 3
        month = fy_end_month + AUM_KMP_GRACE_MONTHS
        year = fy_end_year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        return f"{year:04d}-{month:02d}-01"
