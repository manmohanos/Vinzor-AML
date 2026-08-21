"""What the firm told the regulator, beside what its own records show.

The last enforcement ground, and the one whose published action is least
like what the name suggests. Prowess Insurance Brokers did not misstate a
number: it "recorded reinsurance income as risk management fees". The
failure was that what went on the record was not what happened, and the
authorisation was cancelled for it.

For a fund manager the shape is the same and the material is figures. A
quarterly return says how much is under management and how many investors
there are. The log holds every commitment made and every payment received.
Nobody had ever put the two side by side, and until a filing could carry
what it claimed there was nothing to put.

**This does not decide which one is wrong, and that is the design.** The
tempting rule is that a reported figure must equal something computed from
the book, and it is not true. Assets under management are not the sum of
commitments: capital is called in tranches, values move, and a fund can
properly be worth more or less than was promised to it. A product that
raised a finding on that difference would raise one every quarter of every
firm's life, and be switched off by March.

So two things are separated. A **difference** is shown -- both numbers,
what they are, and how far apart -- and left to a person, because the gap
between a reported figure and the book is ordinary and explaining it is
the officer's job rather than ours. A **finding** is opened only where the
records cannot support the claim at all: a figure reported against a book
with nothing in it. That is not a difference of degree. It is a number
from nowhere, and it is the closest thing in our data to income booked
under the wrong name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from .model import EventType

#: What a return can claim, and the plain words for each. Deliberately
#: short: every entry here has to be something the log can genuinely speak
#: to, and a field the product cannot check is worse than one it does not
#: offer, because a reader assumes a shown figure was compared.
CLAIMS: Mapping[str, str] = {
    "aum_usd": "assets under management",
    "investors": "how many investors",
    "schemes": "how many schemes",
    "capital_received_usd": "capital received",
}


@dataclass(frozen=True)
class SideBySide:
    """One figure, as reported and as the records have it."""

    what: str
    reported: str
    records_show: str
    #: The plain-language gap, or empty where they agree.
    apart: str = ""
    #: True only where the records hold nothing at all to support it.
    unsupported: bool = False


def _money(amount) -> str:
    if not isinstance(amount, (int, float)):
        return "nothing recorded"
    return f"USD {amount:,.0f}"


def _count(number) -> str:
    if not isinstance(number, (int, float)):
        return "nothing recorded"
    return f"{int(number):,}"


@dataclass
class Book:
    """The running totals a reported figure ought to be recognisable against.

    A projection rather than a scan of the log, for the ordinary reason and
    one particular one. The ordinary reason is cost. The particular one is
    that a policy is handed one event and the projections and nothing else,
    and reaching past that for the whole log is how a rule comes to depend
    on something that is not there when it replays. The first attempt at
    this did exactly that, guarded the reach with a default, and so did
    nothing at all -- silently, which is the worst of the three.
    """

    commitments_usd: float = 0.0
    capital_received_usd: float = 0.0
    investors: frozenset = frozenset()
    schemes: frozenset = frozenset()
    #: Payments this book knows about and did not add up, because they are
    #: not in US dollars. Kept because a bare "USD 0" beside a reported
    #: figure asserts that nothing arrived, and on the shipped demo book
    #: **83 of 805 payments** are in AED, EUR, GBP, INR, JPY or SGD. The
    #: decision not to convert is right and is argued below; the decision
    #: not to *say so* was never argued anywhere the reader could see it.
    other_currency_payments: int = 0
    other_currencies: frozenset = frozenset()

    def apply(self, event) -> None:
        payload = event.payload or {}
        # Only US dollars are added up. Converting would need a rate this
        # system does not hold, and a total that quietly assumes one is a
        # number an officer might repeat to a regulator.
        currency = str(payload.get("currency") or "USD").upper()
        in_dollars = currency == "USD"
        amount = payload.get("amount")
        if event.event_type is EventType.COMMITMENT_MADE:
            if isinstance(amount, (int, float)) and in_dollars:
                self.commitments_usd += float(amount)
            if payload.get("fund"):
                self.schemes = self.schemes | {str(payload["fund"])}
            self.investors = self.investors | {event.subject}
        elif event.event_type is EventType.PAYMENT_RECEIVED:
            if isinstance(amount, (int, float)) and in_dollars:
                self.capital_received_usd += float(amount)
            elif isinstance(amount, (int, float)):
                self.other_currency_payments += 1
                self.other_currencies = self.other_currencies | {currency}
            # Whoever paid is somebody this book knows is an investor. It
            # used to count investors from commitments alone, and a firm
            # whose registrar sends an investor list with no commitment
            # column -- which the intake explicitly supports -- had 87
            # parties, 87 payments and an investor count of nought. A return
            # claiming 87, every figure of it true, then produced this
            # module's gravest accusation: "a figure was filed that the
            # records hold nothing for".
            if payload.get("payer"):
                self.investors = self.investors | {str(payload["payer"])}
            else:
                self.investors = self.investors | {event.subject}

    def as_figures(self) -> dict:
        return {
            "commitments_usd": self.commitments_usd,
            "capital_received_usd": self.capital_received_usd,
            "investors": len(self.investors),
            "schemes": len(self.schemes),
            "other_currency_payments": self.other_currency_payments,
            "other_currencies": tuple(sorted(self.other_currencies)),
        }


def what_the_records_show(book: "Book") -> dict:
    """The figures this log can actually speak to.

    Not a valuation and not an accounting. It is what was committed, what
    arrived, and how many investors and schemes the book carries -- the
    raw material a reported figure ought to be recognisable against.
    """
    return book.as_figures()


def compare(book: "Book", reported: Mapping) -> tuple:
    """Each claimed figure, beside what the records hold."""
    show = what_the_records_show(book)
    rows = []

    for key, plain in CLAIMS.items():
        claimed = reported.get(key)
        if claimed is None:
            continue
        if key == "aum_usd":
            # Deliberately not compared to a computed figure. What the book
            # can say is how much was ever committed to it, which is
            # context for the claim rather than a test of it.
            held = show["commitments_usd"]
            rows.append(SideBySide(
                what=plain,
                reported=_money(claimed),
                records_show=f"{_money(held)} ever committed",
                apart=_apart_money(claimed, held,
                                   "more than has ever been committed",
                                   "of what was committed"),
                unsupported=(bool(claimed) and not held
                             and not show["capital_received_usd"]),
            ))
        elif key == "capital_received_usd":
            held = show["capital_received_usd"]
            others = show["other_currency_payments"]
            shown = _money(held)
            if others:
                shown = (f"{shown}, and {others:,} more "
                         f"{'payment' if others == 1 else 'payments'} in "
                         f"{_listed(show['other_currencies'])} that are not "
                         f"converted here")
            rows.append(SideBySide(
                what=plain,
                reported=_money(claimed),
                records_show=shown,
                # "more than arrived" asserts something the record does not
                # support whenever a payment was left out of the total.
                apart=_apart_money(
                    claimed, held,
                    "more than the dollars this book counts" if others
                    else "more than arrived",
                    "of what arrived"),
                unsupported=bool(claimed) and not held and not others,
            ))
        else:
            held = show[key]
            counted = _as_count(claimed)
            rows.append(SideBySide(
                what=plain,
                reported=_count(claimed),
                records_show=_count(held),
                apart=("" if counted is None or counted == held
                       else f"{abs(counted - held):,} "
                            f"{'more' if counted > held else 'fewer'}"
                            f" than the book holds"),
                unsupported=bool(claimed) and not held,
            ))
    return tuple(rows)


def _listed(names) -> str:
    """AED, EUR and GBP -- rather than a list with brackets in it."""
    names = list(names)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _as_count(claimed):
    """A reported count as a number, or ``None`` if it is not one.

    ``int(claimed or 0)`` raised straight out of a policy and out of
    ``ingest`` on ``{"investors": "twelve"}`` and on a list -- a raw Python
    message where the caller should get a sentence. Worse, ``compare`` runs on
    every render of the regulatory page, so a value of that shape recorded by
    an actor whose findings are gated off would have taken the page down for
    good. Refusing the figure at the boundary is the real fix; this is the
    belt, so a bad value can never raise from inside a page render.
    """
    if isinstance(claimed, bool) or not isinstance(claimed, (int, float, str)):
        return None
    try:
        return int(float(str(claimed).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _apart_money(claimed, held, over: str, under: str) -> str:
    if not isinstance(claimed, (int, float)) or not held:
        return ""
    if claimed > held:
        return f"{_money(claimed - held)} {over}"
    if claimed < held:
        share = claimed / held if held else 0
        return f"{share:.0%} {under}"
    return ""


def nothing_behind_it(rows) -> tuple:
    """The claims the records cannot support at all.

    Not a difference of degree. A figure reported against a book holding
    nothing is a number from nowhere, and it is the nearest thing in this
    data to income booked under the wrong name.
    """
    return tuple(row for row in rows if row.unsupported)
