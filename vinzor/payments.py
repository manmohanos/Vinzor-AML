"""Working out what is wrong with a payment, instead of being told.

Until now the payment rule read a field called ``anomaly`` that arrived on the
event already saying "STRUCTURING". That is fine for a demonstration and
useless for a customer: 136 of the 195 files on the demo queue were payment
queries, every one of them traceable to a label somebody else had written. Point
the system at a real bank feed and that entire category produces nothing,
because no bank sends a field called ``anomaly``.

What replaced that label was a suite of ten rules. On 21 August 2026 nine of
them were removed and one derived rule is left: the money came from someone
other than the investor. It reads the payer field and the ownership graph and
nothing else, and it cites clauses 10.2 and 5.4.5.

**What this module no longer looks for.** Written out rather than left to be
inferred from what is missing, because the one thing this product may never do
is let a reader believe something was examined when it was not. A payment
split into instalments below a reporting threshold. A payment larger than the
call. A payment in a currency nobody expected. A payment that arrived with no
sender recorded at all -- 29 of them in the demonstration dataset, and the
case the importer's blank-remitter path was built to produce. One account
funding several unrelated investors. One investor funded from several
accounts. Money that left an investor and came back through other hands.
Money passed along a chain of parties each paying it on. None of these opens a
file. Nothing in the product will say they were considered, because they were
not.

The surviving rule is quiet where the book already declares that the payer and
the investor belong together. That is ``related()`` below, and it is the whole
reason the rule is bearable on a real book: without it, a feeder vehicle
paying for the investors in it opened a file on 32 payments in every hundred.

A payment from a sanctioned party is still reported and is not derived here:
it needs the screening record for the payer, which a policy cannot see, so it
stays a declared input and says so rather than pretending otherwise.
"""

from __future__ import annotations

from typing import Any, Optional

from .model import Event

#: What a feed writes in the payer field when it does not have one. A literal
#: "UNKNOWN" is not a party called Unknown, and reading it as one turns a
#: payment from nowhere into a payment from a third party -- a different
#: finding, a lesser one, and the wrong one. Since the rule that fired on a
#: payment from nowhere was removed, the effect is that such a payment is
#: silent rather than mis-described, which is the right way round.
_NO_PAYER = frozenset({
    "", "unknown", "n/a", "na", "none", "null", "not provided", "notprovided",
    "unavailable", "-", "--", "?", "anonymous", "not disclosed",
})


# ---------------------------------------------------------------------------
# What is wrong with this payment
# ---------------------------------------------------------------------------


#: How far up an ownership chain two parties may be from each other and
#: still count as related. Kept short on purpose: a feeder and the investors
#: in it are one step apart, a master and its feeder two, and past that
#: "related" stops meaning anything a reader would recognise.
RELATED_WITHIN = 3


def related(graph, payer: str, investor: str, within: int = RELATED_WITHIN) -> bool:
    """Whether the book already says these two parties belong together.

    Used to stop "the money came from someone other than the investor"
    firing on the ordinary furniture of a fund. A feeder vehicle paying for
    the investors in it is what a feeder *is*; a private bank paying out of
    an omnibus account for its clients is what a nominee *is*. Measured on
    a book with nothing wrong in it, that rule opened a file on 32 payments
    in every hundred, and every one was a feeder or a nominee doing its job.

    Related means the book declares a link: one holds the other, or both
    are held by the same party. It is not an assumption of innocence -- a
    laundering ring's mule is not declared as anybody's owner, so the shape
    the rule exists for still fires. It is a refusal to report a structure
    the firm told us about as though we had discovered it.

    It is also, now, the only door out of the only payment rule there is.
    Declaring an ownership link silences the finding, and there is no second
    rule behind it to catch what walks through. The adversarial lab says so
    in one row rather than eight.
    """
    if not graph or not payer or not investor or payer == investor:
        return False

    def upward(start: str) -> set:
        found, edge = {start}, [start]
        for _ in range(within):
            nxt = []
            for node in edge:
                for one in graph._owners_of.get(node, ()):
                    if one.owner not in found:
                        found.add(one.owner)
                        nxt.append(one.owner)
            edge = nxt
            if not edge:
                break
        return found

    over_payer, over_investor = upward(payer), upward(investor)
    # One holds the other, or somebody holds both.
    return bool(over_payer & over_investor)


def anomalies(event: Event,
              graph: Optional[Any] = None) -> list[tuple[str, str]]:
    """(name, what to tell a person) for everything wrong with one payment.

    Order matters: a payment can be several things at once, and the list is
    returned worst first so a reader meets the reason that stops the money
    before the one that merely queries it. Two things can still be said about
    a payment, and only one of them is worked out here.
    """
    payload = event.payload or {}
    found: list[tuple[str, str]] = []

    # Not derivable here. It needs the screening record for the payer, which
    # a policy cannot reach, so it stays an input from whoever cross-checked.
    if payload.get("anomaly") == "SANCTIONED_PAYER":
        found.append(("SANCTIONED_PAYER",
                      "the payer matches a name on a sanctions list"))

    payer = str(payload.get("payer") or "").strip()
    if payer.lower() in _NO_PAYER:
        payer = ""

    # A payment with no payer recorded now falls through in silence. It used
    # to open a file of its own; that rule is gone, and this comment is here
    # so the empty branch is read as a deletion rather than an oversight.
    if payer and payer != event.subject:
        # Only reachable where the feed distinguishes who paid from whose
        # commitment is being met. The demonstration dataset makes the
        # payment's subject the payer itself, so there is nothing to compare
        # and this never fires there -- correctly, and worth knowing before
        # anyone reads its absence as the rule being broken.
        if not related(graph, payer, event.subject):
            found.append((
                "THIRD_PARTY",
                "the money came from someone other than the investor"))

    return found
