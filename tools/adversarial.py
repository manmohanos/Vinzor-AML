"""What it costs to walk around each rule.

    python tools/adversarial.py

``typologies.py`` asks whether we recognise the textbook shape. That is the
easy half, and passing it proves less than it appears to: a launderer who
knows the rule does not send the textbook shape. They add a party, split a
payment, or wait a month.

So this asks the harder question. It plants a shape we do detect, perturbs it
the way somebody avoiding detection would, and reports whether the rule still
fires.

**This file was ten trials until 21 August 2026 and is now one.** Every rule
it exercised had a number in it -- three investors, three senders, three
payments in a chain, six hops -- and each trial stepped over one of those
lines. Those rules were removed. The one payment rule left has no number in
it at all: the money came from someone other than the investor, or it did
not. There is no threshold to step over, so nine of the ten trials have no
shape left to plant and were deleted rather than left reporting "could not be
tested".

The one that survives is the door the calibration opened. Declaring an
ownership link between the sender and the investor silences the rule, because
the product refuses to report a structure the firm told it about as though it
were a discovery. That row reads EVADED, and with one rule behind it there is
nothing further back to catch what walks through.

**The number that matters is not detection, it is cost.** A rule that can be
evaded by moving one payment to a second account has bought nothing: the
launderer opens one more account and carries on. A rule that forces them to
open five more accounts and make eight more payments has genuinely raised the
price of the crime, whether or not it ever fires. Detection rates are how AML
products are sold; cost of evasion is closer to what they are actually for.
So each row reports what the evasion cost, in accounts and in payments.

**On reading a HELD.** It means this particular evasion did not work. It is
not a claim that no evasion works, and none of these results say anything
about a launderer who does something nobody here thought of. The perturbations
are the ones the literature names -- intermediary injection, splitting,
merging, timing -- plus the ones that follow from reading our own thresholds.

Nothing here is a model, and nothing here is trained. These are the shipped
rules, read by the same code the product runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from typologies import cast, pay, what_was_said, workspace

#: The phrases each rule uses, so a run can tell which rule spoke rather
#: than only that something did.
RULES = {
    "sender is not the investor": "came from someone other than the investor",
}


def _listed(parts) -> str:
    parts = list(parts)
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def fired(engine) -> set:
    """Which rules spoke, by name."""
    lines = what_was_said(engine)
    return {name for name, phrase in RULES.items()
            if any(phrase in line for line in lines)}


def count(engine) -> tuple:
    """(accounts, payments) the shape needed."""
    from vinzor.model import EventType
    accounts = len(engine.state.graph.entities)
    payments = sum(1 for e in engine.log
                   if e.event_type is EventType.PAYMENT_RECEIVED)
    return accounts, payments


# ---------------------------------------------------------------------------
# the honest shapes, and the same shapes done carefully
# ---------------------------------------------------------------------------


def hub_plain(engine) -> None:
    """One account pays three investors it has no declared link to. Each of
    the three payments opens a third-party file."""
    source = cast(engine, 1, "src")[0]
    for index, who in enumerate(cast(engine, 3, "inv")):
        pay(engine, source, who, index, day=2 + index)


def hub_declared_related(engine) -> None:
    """The same hub, with ownership declared between the sender and each
    investor so that the sender counts as related to all three.

    This evasion did not exist until 20 August 2026. The third-party rule
    opened a file on a feeder paying the investors who hold units in it -- 32
    payments in every hundred on a book with nothing wrong in it -- so it now
    asks the ownership graph whether the book already says the two belong
    together. That is a door, and it is the business of this file to say how
    much it costs to walk through.

    Measured here, 21 August 2026: the plain hub opens three third-party
    files and the declared hub opens none. The rule is evaded completely, for
    the price of three ownership declarations, no extra accounts and no extra
    payments.

    What it used to cost was a worse question rather than silence. A party
    that declares itself the owner of three investors has to name the natural
    people behind itself under 1.3.3, and there were three further payment
    rules underneath this one that a declaration did not reach. Those three
    were removed on 21 August 2026, so the ownership question is now the only
    thing standing behind this door.
    """
    from vinzor.model import EventType

    source = cast(engine, 1, "src")[0]
    for index, who in enumerate(cast(engine, 3, "inv")):
        engine.ingest(event_type=EventType.OWNERSHIP_DECLARED, subject=who,
                      occurred_at="2026-03-01", actor="t",
                      payload={"owner": source, "owned": who,
                               "percentage": 100.0, "relation": "OWNS"})
        pay(engine, source, who, index, day=2 + index)


TRIALS = (
    ("sender is not the investor", "ownership declared between them",
     hub_plain, hub_declared_related),
)


#: What works on 21 August 2026: the only evasion of the only rule.
#:
#: This was 6 of 10 while there were four payment rules to evade. The other
#: nine trials went with the rules they attacked, so the ratio moved from
#: six-in-ten to one-in-one while the product got worse rather than better.
#: Read this number beside the count of trials, never on its own.
#:
#: A step that could not be tested fails too: an evasion nobody could run is
#: not an evasion that failed.
EVADED_WHEN_SET = 1


def main() -> int:
    print()
    print("  Each row plants a shape we do detect, then does the same thing")
    print("  the way somebody avoiding detection would. What matters is not")
    print("  whether the rule still fires -- it is what the evasion cost.")
    print()

    held = evaded = broken = caught_anyway = 0
    print(f"  {'rule':<31}{'evasion':<44}{'':<9}cost")
    print("  " + "-" * 96)

    for rule, how, plain, evasive in TRIALS:
        honest = workspace()
        plain(honest)
        if rule not in fired(honest):
            print(f"  {rule:<31}{how:<44}{'NO BASE':<9}"
                  f"(the plain shape was not detected)")
            broken += 1
            continue
        base_accounts, base_payments = count(honest)

        tried = workspace()
        evasive(tried)
        accounts, payments = count(tried)
        still = rule in fired(tried)

        cost = (f"{accounts - base_accounts:+d} accounts, "
                f"{payments - base_payments:+d} payments")
        # With one rule in the table there is no second rule that could
        # speak instead, so this is empty on every run today. It is kept
        # because it is the machinery that makes the table extensible, and
        # deleting it would quietly remove the distinction between "the rule
        # held" and "something else spoke" the next time a rule is added.
        others = fired(tried) - {rule}
        if still:
            held += 1
            verdict = "held"
        elif others:
            # The rule aimed at was defeated and a different one spoke. The
            # file still reaches an officer, which is what matters, but
            # counting it as a clean hold would hide that the shape itself
            # went unrecognised.
            caught_anyway += 1
            verdict = "caught by"
            cost = _listed(sorted(others)) + f"  ({cost})"
        else:
            evaded += 1
            verdict = "EVADED"
        print(f"  {rule:<31}{how:<44}{verdict:<11}{cost}")

    print()
    print(f"  {held} evasions failed, {evaded} worked"
          + (f", {caught_anyway} were caught by a different rule"
             if caught_anyway else "")
          + (f", {broken} could not be tested" if broken else "") + ".")
    print()
    print("  An evasion that costs nothing is a rule that has bought nothing.")
    print("  A rule worth keeping is one somebody has to work to get around,")
    print("  whether or not it ever fires.")
    print()
    print("  This lab held ten trials against four payment rules until")
    print("  21 August 2026. Those rules were removed, and the trials with")
    print("  them. What is left is the honest summary: the product has one")
    print("  derived payment rule, and declaring an ownership link defeats")
    print("  it for free.")
    print()
    if evaded > EVADED_WHEN_SET or broken:
        print(f"  FAILING: {EVADED_WHEN_SET} evasions worked when this floor "
              f"was set and {evaded} do now"
              + (f"; {broken} could not be tested at all." if broken else "."))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
