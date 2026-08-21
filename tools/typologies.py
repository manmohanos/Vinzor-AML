"""Which laundering shapes our rules can see, and which they cannot.

    python tools/typologies.py

**As of 21 August 2026 this tool reports 0 of 7, and that is the honest
answer rather than a broken run.** The rules it was written to measure have
been removed. What it measured was this: every amount-and-timing rule we had
scored a lift of 1.00 against twenty thousand alerts a Danish bank's analysts
had judged -- no discriminating power at all -- which is the published result
for shape-only features rather than a defect we introduced. The ICAIF'24
ablation on IBM's AMLworld data puts amount-and-timing features at 21.3%
minority-class F1 and one-hop counterparty features at 50.9-59.7%. So
counterparty and multi-hop rules were written, and they are what took this
tool from 5 of 7 to 7 of 7.

Those rules were deleted, leaving one derived payment rule: the money came
from someone other than the investor. That rule is this tool's **control** --
see below -- because it fires on every payment where the sender is not the
investor, laundering or not. With the signal gone and only the control left,
every named shape now produces exactly what an innocent third-party payment
produces, and nothing survives the subtraction. The argument in the paragraph
above is left standing because it is still true and it is the record of what
was given up.

**Why this and not IBM's AMLSim.** AMLSim is the standard generator for
exactly this job and its licence (Apache-2.0) is clean, but it wants Java 8,
Maven and pygraphviz, emits its own CSV schema, and would then need a
conversion layer into our events -- and a conversion layer is a place for a
bug to hide between the thing measured and the thing shipped. What is actually
valuable about AMLSim is not the code, it is the *named typologies*: the
shapes the literature agrees are worth planting. Those are reproduced here,
under the same names, written directly as the events the product really
records. A number from here is therefore about the shipped rules, with nothing
in between.

**Every shape is scored against a control**, and the first version of this
script was wrong for want of one. It asked whether *anything* was recorded,
and answered "7 of 7" -- because one rule, "the money came from someone other
than the investor", fires on every payment where the sender is not the
investor. That is true of a laundering ring and equally true of a wife paying
her husband's capital call. Counting it as detection is the same error the
product exists to prevent: a signal that fires on everything has told you
nothing.

So a control shape is planted too -- one ordinary third-party payment -- and
any reason that also appears in the control is subtracted. What survives is
what the rule actually recognised about the shape.

**This flatters nothing even so.** Each shape is planted alone, in a clean
workspace, with no legitimate traffic around it. A rule that cannot find its
own typology in laboratory conditions certainly cannot find it in a real book,
so a miss here is conclusive while a hit is only necessary and not sufficient.
Recall against noise is a different and much harder measurement, and this is
not it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType

WHEN = "2026-03-02"


def workspace() -> Vinzor:
    return Vinzor(EventLog())


def party(engine, entity_id: str, name: str) -> None:
    engine.ingest(
        event_type=EventType.ENTITY_REGISTERED, subject=entity_id,
        occurred_at=WHEN,
        payload={"kind": EntityKind.PERSON.value, "name": name,
                 "attributes": {}})


def pay(engine, sender: str, receiver: str, number: int,
        amount: float = 250_000.0, day: int = 2) -> None:
    """One payment, recorded exactly as the importer records one."""
    engine.ingest(
        event_type=EventType.PAYMENT_RECEIVED, subject=receiver,
        occurred_at=f"2026-03-{day:02d}",
        payload={"payment_id": f"pay_{number}", "payment_ref": f"TX-{number}",
                 "amount": amount, "called_amount": amount, "currency": "USD",
                 "expected_currency": "USD", "payer": sender, "anomaly": None})


def cast(engine, count: int, prefix: str) -> list:
    """`count` parties, registered and named."""
    made = []
    for index in range(count):
        entity_id = f"{prefix}{index}"
        party(engine, entity_id, f"{prefix.title()} {index}")
        made.append(entity_id)
    return made


# ---------------------------------------------------------------------------
# the shapes
# ---------------------------------------------------------------------------


def fan_out(engine) -> str:
    """One account funds many. The classic front for a mule network."""
    source = cast(engine, 1, "source")[0]
    for index, receiver in enumerate(cast(engine, 5, "investor")):
        pay(engine, source, receiver, index, day=2 + index)
    return "one account paying 5 different investors"


def fan_in(engine) -> str:
    """Many accounts fund one. Smurfing, seen from the receiving end."""
    target = cast(engine, 1, "target")[0]
    for index, sender in enumerate(cast(engine, 5, "sender")):
        pay(engine, sender, target, index, day=2 + index)
    return "5 different accounts paying one investor"


def cycle(engine) -> str:
    """Money returns to where it started, having acquired a history."""
    ring = cast(engine, 4, "ring")
    for index in range(len(ring)):
        pay(engine, ring[index], ring[(index + 1) % len(ring)], index,
            day=2 + index)
    return "money moving in a closed ring of 4 and returning to the start"


def bipartite(engine) -> str:
    """Every sender pays every receiver: a laundering market, not a payment."""
    senders = cast(engine, 3, "from")
    receivers = cast(engine, 3, "to")
    number = 0
    for sender in senders:
        for receiver in receivers:
            pay(engine, sender, receiver, number, day=2 + number % 20)
            number += 1
    return "3 senders each paying all 3 of the same receivers"


def stack(engine) -> str:
    """A chain: each party passes it on. Layering, in its plainest form."""
    chain = cast(engine, 5, "step")
    for index in range(len(chain) - 1):
        pay(engine, chain[index], chain[index + 1], index, day=2 + index)
    return "a chain of 5 parties each passing the money to the next"


def gather_scatter(engine) -> str:
    """Many in, one hub, many out. The hub is the whole point."""
    hub = cast(engine, 1, "hub")[0]
    number = 0
    for sender in cast(engine, 4, "in"):
        pay(engine, sender, hub, number, day=2 + number)
        number += 1
    for receiver in cast(engine, 4, "out"):
        pay(engine, hub, receiver, number, day=2 + number)
        number += 1
    return "4 accounts paying one hub, which then pays 4 others"


def scatter_gather(engine) -> str:
    """One out, through many, back to one. A hub with the roles reversed."""
    source = cast(engine, 1, "origin")[0]
    sink = cast(engine, 1, "destination")[0]
    number = 0
    for middle in cast(engine, 4, "middle"):
        pay(engine, source, middle, number, day=2 + number)
        number += 1
        pay(engine, middle, sink, number, day=2 + number)
        number += 1
    return "one account paying 4 intermediaries who all pay one destination"


def control(engine) -> str:
    """Not laundering: one person meets another's capital call.

    Kept, and no longer the whole control. See :func:`innocent_book`.
    """
    payer = cast(engine, 1, "relative")[0]
    investor = cast(engine, 1, "investor")[0]
    pay(engine, payer, investor, 0)
    return "one ordinary payment from somebody other than the investor"


def innocent_book(declared: bool = True):
    """A whole book with nothing wrong in it, and what the rules say about it.

    **The control was one payment, and one payment cannot subtract a
    threshold.** Every counterparty rule in this product has a threshold of
    three, so no threshold rule could ever appear in a control of size one --
    and threshold rules are exactly the ones being credited. The shipped
    control produced precisely one reason, "the money came from someone other
    than the investor", and everything else any shape said was scored as
    detection.

    Rescored against the innocent book ``tools/ordinary_traffic.py`` builds --
    nothing wrong in it, by that tool's own construction. Measured while the
    counterparty and multi-hop rules still existed::

        7 of 7   the old control: one third-party payment
        7 of 7   an innocent book, structures declared
        6 of 7   an innocent book, structures NOT declared   (blind on fan-out)

    On a book whose feeder and nominee relationships were not yet recorded,
    three reasons this tool credited appeared anyway -- "the same sender has
    paid 3 / 4 / 5 different investors on this book" -- and those three were
    everything fan-out was credited with. So fan-out was scored as recognised
    on a signal a Cayman feeder subscribing for eight of its own investors
    produces identically.

    Since 21 August 2026 both numbers are 0 of 7, declared or undeclared,
    because the rules that produced every reason above were removed. The gap
    this passage exists to show has closed by both ends falling to the floor,
    which is not the same as the gap being fixed. Both scores are still
    reported, so that a reader sees the two are equal for the reason stated
    rather than assuming the difference was resolved.
    """
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parent))
    import ordinary_traffic

    engine = ordinary_traffic.workspace()
    # The builders declare their own ownership -- a feeder holds units, a
    # nominee holds an interest -- by calling ``holds`` inside themselves,
    # so the undeclared book is made by silencing that one call rather than
    # by leaving a builder out. Nothing else about the traffic changes,
    # which is the point: the same innocent payments, with the structures
    # behind them not yet on the record.
    was = ordinary_traffic.holds
    if not declared:
        ordinary_traffic.holds = lambda *rest, **more: None
    try:
        for _label, build in ordinary_traffic.ORDINARY:
            build(engine)
    finally:
        ordinary_traffic.holds = was
    return engine


SHAPES = (
    ("fan-out", fan_out),
    ("fan-in", fan_in),
    ("cycle", cycle),
    ("bipartite", bipartite),
    ("stack (layering)", stack),
    ("gather-scatter", gather_scatter),
    ("scatter-gather", scatter_gather),
)


def what_was_said(engine) -> list:
    """Every reason the rules recorded, anywhere in this workspace."""
    said = []
    for case in engine.state.casebook.cases.values():
        for evidence in case.evidence:
            because = (evidence.detail or {}).get("because")
            if because and because not in said:
                said.append(because)
    return said


#: What is recognised, measured 21 August 2026: none of them.
#:
#: This was 7 -- every shape in the file -- until the counterparty and
#: multi-hop payment rules were removed. The number is set to the measured
#: present rather than to the number we would like, because a floor above
#: what the product does turns every build red and teaches people to ignore
#: it.
#:
#: **At 0 this constant is no longer a guard, and saying so is the whole
#: reason it has a comment.** A floor of zero cannot be gone below, so this
#: tool can now only ever report an improvement. It was written because a
#: tool that could only report good news is worse than no tool; it has become
#: that tool again, by a different route. Restoring a rule that recognises
#: a shape is what makes it a guard again, and until then ``main()`` prints
#: what has been lost rather than leaving a zero to be read as a pass.
ALL_OF_THEM = 0


def main() -> int:
    print("\n  Each shape is planted alone in an empty workspace, with no")
    print("  ordinary traffic around it. A rule that cannot find its own")
    print("  typology here could not find it in a real book, so a miss is")
    print("  conclusive. A hit only means the rule is not blind.")
    print()

    baseline = workspace()
    described = control(baseline)
    ordinary = set(what_was_said(baseline))
    # A whole book with nothing wrong in it, not one payment. One payment can
    # only ever subtract reasons that fire at n=1, and every counterparty
    # rule here has a threshold of three -- so the rules being credited were
    # precisely the ones the control could not reach.
    ordinary |= set(what_was_said(innocent_book(declared=True)))
    print(f"  control            {described}, and a whole book with")
    print("                     nothing wrong in it")
    for line in sorted(ordinary):
        print(f"               -> {line}")
    print()
    print("  Everything above is said about innocent traffic too, so it is")
    print("  subtracted from every shape below. A rule that fires on")
    print("  everything has told you nothing.")
    print()
    print("  " + "-" * 70)
    print()

    caught = 0
    for name, build in SHAPES:
        engine = workspace()
        described = build(engine)
        said = [line for line in what_was_said(engine)
                if line not in ordinary]
        if said:
            caught += 1
        mark = "sees it  " if said else "BLIND    "
        print(f"  {mark} {name:<18} {described}")
        for line in said:
            print(f"               -> {line}")
        if not said:
            print("               -> nothing an innocent payment would "
                  "not also say")
        print()

    print(f"  {caught} of {len(SHAPES)} shapes are recognised as shapes.")
    missed = len(SHAPES) - caught
    if missed:
        print(f"  {missed} produce nothing an ordinary third-party "
              f"payment would not.")
    print()
    if not ALL_OF_THEM:
        print("  This tool recognised all 7 of these until 21 August 2026,")
        print("  when the counterparty and multi-hop payment rules were")
        print("  removed. There is nothing left to recognise a shape with:")
        print("  the one payment rule that remains is this tool's own")
        print("  control, so every shape now scores as an ordinary")
        print("  third-party payment. Read the 0 as a deletion, not as a")
        print("  regression and not as a bad run.")
        print()
        print("  It is also not a guard while it stands at 0. Nothing can")
        print("  fall below zero, so from here this tool can only ever")
        print("  report an improvement. Restoring a rule that sees a shape")
        print("  is what makes it able to fail again.")
        print()
    # And the same again against a book whose structures nobody has recorded
    # yet, which is the state a firm is in on its first day here. The gap is
    # the finding, so it is printed rather than folded into one number.
    undeclared = ordinary | set(what_was_said(innocent_book(declared=False)))
    blind = []
    for name, build in SHAPES:
        engine = workspace()
        build(engine)
        if not [line for line in what_was_said(engine)
                if line not in undeclared]:
            blind.append(name)
    print(f"  Against a book whose structures nobody has recorded yet, "
          f"{len(SHAPES) - len(blind)} of {len(SHAPES)}"
          + (f" -- blind on {', '.join(blind)}." if blind else "."))
    print("  A firm is in that state on its first day here.")
    print()

    if caught < ALL_OF_THEM:
        # A floor rather than a bare ``return 0``. This tool could not fail:
        # stubbing total detection failure produced "0 of 7 shapes are
        # recognised as shapes" and exit 0, and a build that goes green on
        # that sentence is worse than no build at all, because it is read as
        # evidence.
        print(f"  FAILING: {ALL_OF_THEM} of these were recognised when this "
              f"floor was set, and {caught} are now.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
