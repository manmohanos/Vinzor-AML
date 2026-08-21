"""Whether the firm still has the money its licence requires it to have.

The last enforcement ground with nothing built, and the one that cost
Darwin Platform Aircraft Leasing its registration: minimum capital of USD
0.2 million never infused. It is the simplest obligation in the whole
product and the easiest to stop noticing, because nothing about it moves.
A licence is granted, a figure is required from that day forward, and the
only way anybody finds out it is not there is when somebody looks.

**Where the figures come from.** Until 20 August 2026 they came from two
independent law-firm readings of the Fund Management Regulations, because
no copy of those Regulations was kept anywhere near this code -- a weaker
source than this product accepts anywhere else, and one this module
disclaimed on every screen that used it. They now come from the
Regulations themselves: the Second Schedule on page 89 sets the figure for
each registration category, Regulation 8(1) on page 10 requires it, and
Regulation 107F on page 68 adds the amount for managing money that is not
the firm's own. All three are in ``citations.py`` and are rematched
against the published PDF on every build.

The law firms turn out to have been right to the dollar. That is worth
saying plainly rather than quietly deleting, because it was not knowable
at the time and the caution was not wasted: of the twenty-one clauses that
*were* quoted from a primary source, a machine check found four still
wrong. What changed is not confidence in the number. It is that a firm
told it is short of capital can now be shown the schedule that says so.

**The number is still a floor and not a total.** Regulation 8(3) makes
this minimum separate from and in addition to the minimum for any other
regulated activity the firm carries on inside or outside the IFSC, and
this system knows nothing about those. Regulation 8(2) lets a branch hold
its net worth at its parent. Both mean a firm confirming its own minimum
beats anything computed here, which is why a confirmed figure still wins
outright.

**What is checked, and what cannot be.** That the recorded net worth is at
or above the minimum in force, and that a figure exists at all. What this
cannot do is verify the figure is true; that is an auditor's work and no
software substitutes for it. A firm that reports a number it does not have
is not caught here, and Darwin's capital was never infused at all rather
than misstated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from .licence import Activity, Category
from .model import EventType

#: What each registration category must be worth, in US dollars, from the
#: Second Schedule to the Fund Management Regulations, page 89. Five
#: hundred thousand is written "USD 5,00,000" there -- the Indian grouping
#: of digits, not a misprint of fifty thousand.
PUBLISHED_MINIMUM_USD: Mapping[Category, int] = {
    Category.AUTHORISED: 75_000,
    Category.REGISTERED_NON_RETAIL: 500_000,
    Category.REGISTERED_RETAIL: 1_000_000,
}

#: What Regulation 107F adds where an FME is authorised to manage
#: third-party money. Its Explanation is explicit that this sits on top of
#: the category minimum rather than instead of it.
PUBLISHED_EXTRA_FOR_THIRD_PARTY_USD = 500_000

#: The activities that reading treats as managing somebody else's money.
#: A family investment fund manages the family's own, which is the
#: distinction the extra requirement turns on.
#:
#: Read from what the firm has actually been recorded as doing rather than
#: from what its licence permits, because that is what this system
#: observes. It is a proxy and worth knowing as one: 107F attaches the
#: requirement to *seeking the authorisation*, so a firm authorised for
#: third-party management that has not yet done any is not caught here. It
#: errs toward the firm's real activity, which is the safer of the two
#: directions to be wrong in.
THIRD_PARTY_ACTIVITIES = frozenset({
    Activity.PORTFOLIO_MANAGEMENT_SERVICES,
    Activity.RESTRICTED_SCHEME,
    Activity.RETAIL_SCHEME,
    Activity.VENTURE_CAPITAL_SCHEME,
    Activity.INVESTMENT_TRUST_PRIVATE_PLACEMENT,
    Activity.INVESTMENT_TRUST_PUBLIC_OFFER,
    Activity.EXCHANGE_TRADED_FUND,
})

#: Said wherever a figure nobody at the firm has confirmed is used. It no
#: longer says the figure is unchecked, because it is checked -- it says
#: the figure is a floor, which is the thing that can still be wrong.
NOT_CONFIRMED = (
    "This is the minimum the Second Schedule to the Fund Management "
    "Regulations sets for this registration category. Nobody here has "
    "confirmed it is the minimum that applies to this firm, and three "
    "things change it: the Authority may specify another amount, a branch "
    "may hold its net worth at its parent, and any other regulated "
    "activity the firm carries on — inside the IFSC or outside it — "
    "requires its own minimum on top of this one. Treat it as a floor and "
    "confirm the figure before relying on it."
)


@dataclass(frozen=True)
class Position:
    """What the firm last said it was worth, and when."""

    amount_usd: float
    as_at: str
    reported_by: str
    note: str = ""


@dataclass
class Capital:
    """The firm's own money, as it has been reported."""

    positions: tuple = ()
    #: A minimum somebody has confirmed applies here, in US dollars.
    #: Nothing until they do, which is different from zero.
    confirmed_minimum_usd: Optional[float] = None
    confirmed_by: str = ""
    confirmed_on: str = ""
    #: Which licence category the confirmation was made against. A minimum
    #: is only a minimum for a particular registration, and this was not
    #: recorded -- so it outlived the licence it was confirmed for. See
    #: :func:`required`.
    confirmed_for_category: str = ""

    def apply(self, event) -> None:
        payload = event.payload or {}
        if event.event_type is EventType.NET_WORTH_REPORTED:
            amount = payload.get("amount_usd")
            if not isinstance(amount, (int, float)):
                return
            self.positions = self.positions + (Position(
                amount_usd=float(amount),
                as_at=str(event.occurred_at)[:10],
                reported_by=str(event.actor or ""),
                note=str(payload.get("note") or ""),
            ),)
        elif event.event_type is EventType.MINIMUM_CONFIRMED:
            amount = payload.get("minimum_usd")
            if not isinstance(amount, (int, float)):
                return
            self.confirmed_minimum_usd = float(amount)
            self.confirmed_by = str(event.actor or "")
            self.confirmed_on = str(event.occurred_at)[:10]
            self.confirmed_for_category = str(payload.get("category") or "")

    @property
    def latest(self) -> Optional[Position]:
        if not self.positions:
            return None
        return sorted(self.positions, key=lambda p: p.as_at)[-1]


def required(licence, capital: Optional[Capital] = None) -> tuple:
    """(the minimum in US dollars, whether a person confirmed it, why).

    A confirmed figure wins outright, **for the licence it was confirmed
    against**. Nobody's reading of a regulation beats the firm's own reading
    of its own licence, and the firm is the one the Authority will ask -- but
    a firm that changes category has changed the question, and the old answer
    is no longer an answer to it.

    It used to win on the sole test that a figure existed, and nothing expired
    it. Measured::

        2024-02-01  licence granted, category AUTHORISED
        2024-02-05  confirm_minimum(75,000, "Second Schedule, Authorised")
                    → 75,000, confirmed
        2026-04-01  the firm upgrades to REGISTERED_RETAIL
                    → 75,000, confirmed          ← unchanged
        2026-06-30  net worth 100,000
                    → no shortfall, no file opened
                    → "USD 100,000 against a confirmed minimum of USD 75,000"

    The Second Schedule sets USD 1,000,000 for a Registered (Retail) FME. The
    firm was USD 900,000 below the published floor and the product showed it
    as meeting its minimum, with the reassuring word *confirmed* on it.
    ``LICENCE_GRANTED`` is the only event that can change a category, so this
    is the only way an upgrade can be recorded.

    The confirmation is never thrown away -- it is on the log and it stays on
    the screen. It simply stops being *confirmed* for a licence it was not
    confirmed for, and the sentence says what to do about it.
    """
    category = getattr(licence, "category", None)

    if capital is not None and capital.confirmed_minimum_usd is not None:
        confirmed_for = capital.confirmed_for_category
        now = getattr(category, "value", "") if category is not None else ""
        stale = bool(confirmed_for) and bool(now) and confirmed_for != now
        published = PUBLISHED_MINIMUM_USD.get(category) if category else None
        under = (published is not None
                 and capital.confirmed_minimum_usd < published)
        if not (stale and under):
            return (capital.confirmed_minimum_usd, True,
                    f"Confirmed by {capital.confirmed_by} on "
                    f"{capital.confirmed_on}.")
        return (float(published), False,
                f"{capital.confirmed_by} confirmed USD "
                f"{capital.confirmed_minimum_usd:,.0f} on "
                f"{capital.confirmed_on}, for a licence of a different "
                f"category. This firm's registration is now {now}, for which "
                f"the Second Schedule sets USD {published:,.0f}. The higher "
                f"figure stands until somebody confirms again.")

    if category is None:
        return (None, False,
                "No licence category is recorded, and the minimum depends "
                "on it.")

    minimum = PUBLISHED_MINIMUM_USD.get(category)
    if minimum is None:
        return (None, False, "No figure is held for this licence category.")

    doing = {activity for activity in getattr(licence, "activities", {})
             if activity in THIRD_PARTY_ACTIVITIES}
    why = ("The Second Schedule to the Fund Management Regulations sets "
           "this figure for this registration category.")
    if doing:
        minimum += PUBLISHED_EXTRA_FOR_THIRD_PARTY_USD
        why = ("The Second Schedule to the Fund Management Regulations sets "
               "this figure for this registration category, plus the amount "
               "Regulation 107F adds for managing money that is not the "
               "firm's own.")
    return (float(minimum), False, why)


def shortfall(licence, capital: Capital) -> Optional[float]:
    """How far below the minimum the firm is, or nothing.

    Nothing where no figure has been reported: not knowing is a different
    condition from being short, and reporting a party as short on no
    evidence is how a firm learns to ignore the screen.
    """
    minimum, _confirmed, _why = required(licence, capital)
    standing = capital.latest
    if minimum is None or standing is None:
        return None
    if standing.amount_usd >= minimum:
        return None
    return minimum - standing.amount_usd


def _money(amount: Optional[float]) -> str:
    if amount is None:
        return "an amount nobody has recorded"
    return f"USD {amount:,.0f}"


def in_words(licence, capital: Capital) -> str:
    """One sentence a person can read off a screen."""
    minimum, confirmed, _why = required(licence, capital)
    standing = capital.latest
    if standing is None:
        return ("Nobody has recorded what this firm is worth, so nothing "
                "here can say whether it meets the minimum.")
    short = shortfall(licence, capital)
    settled = "confirmed" if confirmed else "unconfirmed"
    if short is None:
        return (f"{_money(standing.amount_usd)} as at {standing.as_at}, "
                f"against {'a ' + settled + ' minimum of ' + _money(minimum) if minimum is not None else 'no minimum anybody has recorded'}.")
    return (f"{_money(standing.amount_usd)} as at {standing.as_at}, which is "
            f"{_money(short)} below the {settled} minimum of "
            f"{_money(minimum)}.")
