"""Does it still work with a real firm's worth of investors in it?

    python tools/at_scale.py                 # 2,000 investors
    python tools/at_scale.py --investors 200 --payments 4

Builds a workspace of a given size and times every surface a person waits on:
the queue, a file, a party, screening coverage, the regulator, and the export.
Nothing here checks correctness -- the two harnesses beside it do that. This
one only asks whether the thing is usable when it holds more than a demo.

Sizes are deliberately generous. A GIFT City FME with 2,000 investors is a
large one, so if it holds there it holds. What it cannot tell you is how a
hosted deployment behaves, because there isn't one: this is one process
reading one file on one machine, which is the whole architecture.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vinzor.briefing import brief, case_file, party, regulatory, screening
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.evidence import pack
from vinzor.model import EntityKind, EventType, Role

WHEN = "2026-08-07"

FIRST = ("Aarav", "Diya", "Kabir", "Meera", "Rohan", "Saanvi", "Vihaan",
         "Anaya", "Arjun", "Ishita", "Kiara", "Nikhil", "Priya", "Rahul")
LAST = ("Iyer", "Kapoor", "Menon", "Nair", "Patel", "Rao", "Sharma", "Verma",
        "Desai", "Gupta", "Joshi", "Malhotra", "Reddy", "Singh")

#: One payment in this many is deliberately odd, which is roughly what the
#: synthetic book already carries and enough to keep the queue realistic.
#: One payment in this many is built odd, so a load run is not made entirely
#: of traffic the rules ignore.
ODD_IN = 7

#: How each odd payment is made odd. There is one shape, because after
#: 21 August 2026 there is one derived payment rule.
#:
#: This list had four entries -- a third party paid, short of what was
#: called, more than was called, a currency nobody expected -- chosen because
#: they were what the rules of the day actually read. Three of the four rules
#: are gone, so three of the four shapes now produce a perfectly ordinary
#: payment. Leaving them would have made a load run report a realistic queue
#: while three sevenths of its odd payments opened nothing, which is the same
#: fault this comment was written to record the first time.
#:
#: That first fault, kept because it is the reason the knob is checked at
#: all: these used to be values of a field called ``anomaly`` that nothing
#: has read since the payment rules were derived rather than declared, and
#: the builder never set a ``payer``. Measured at 300 investors x 3 payments
#: before it was fixed::
#:
#:     payments 900   files opened 901
#:       POL_PAY_UNKNOWN_SOURCE  900   100.0 per 100 payments
#:       POL_UBO_NOT_DECLARED      1     0.1 per 100 payments
#:
#: Every payment in the load book opened a file, and the one-in-seven knob
#: the tool advertises did nothing at all.
ODDITIES = ("a third party paid",)


def took(label, work):
    started = time.perf_counter()
    result = work()
    return label, (time.perf_counter() - started) * 1000, result


def build(investors: int, payments_each: int) -> Vinzor:
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera Nair", role=Role.AML_OFFICER, enrolled_at=WHEN)

    for index in range(investors):
        who = f"inv_{index:05}"
        person = index % 3                      # two in three are people
        name = (f"{FIRST[index % len(FIRST)]} {LAST[(index // 3) % len(LAST)]}"
                if person else f"{LAST[index % len(LAST)]} Holdings {index}")
        engine.ingest(
            event_type=EventType.ENTITY_REGISTERED, subject=who,
            occurred_at=WHEN,
            payload={"kind": (EntityKind.PERSON if person
                              else EntityKind.COMPANY).value,
                     "name": name,
                     "attributes": {"nationality": "IN"} if person else
                                   {"jurisdiction": "SG"}})
        # Every third company is owned by the investor before it, which gives
        # the resolver real chains to walk rather than a flat list.
        if not person and index > 2:
            engine.ingest(
                event_type=EventType.OWNERSHIP_DECLARED, subject=who,
                occurred_at=WHEN,
                payload={"owner": f"inv_{index - 1:05}", "owned": who,
                         "percentage": 30.0, "relation": "OWNS",
                         "edge_id": f"edg_{index}"})
        engine.ingest(event_type=EventType.COMMITMENT_MADE, subject=who,
                      occurred_at=WHEN,
                      payload={"investor": who, "fund": "fnd_1",
                               "amount": 1_000_000.0 + index,
                               "currency": "USD",
                               "commitment_id": f"ccm_{index}"})

        for n in range(payments_each):
            odd = (index * payments_each + n) % ODD_IN == 0
            payload = {"payment_id": f"pay_{index}_{n}",
                       "payment_ref": f"TX-{index}-{n}",
                       "amount": 250_000.0, "called_amount": 250_000.0,
                       "currency": "USD", "expected_currency": "USD",
                       # The ordinary case: the investor met their own call.
                       # Without this every payment in the book had no payer
                       # and every one of them opened a file.
                       "payer": who,
                       "fund": "fnd_1"}
            if odd:
                shape = ODDITIES[n % len(ODDITIES)]
                payload["payer"] = f"inv_{(index + 1) % investors:05}"
                payload["why_odd"] = shape
            engine.ingest(event_type=EventType.PAYMENT_RECEIVED, subject=who,
                          occurred_at=WHEN, payload=payload)
    return engine


def main(argv) -> int:
    investors = 2_000
    payments_each = 3
    if "--investors" in argv:
        investors = int(argv[argv.index("--investors") + 1])
    if "--payments" in argv:
        payments_each = int(argv[argv.index("--payments") + 1])

    print()
    print(f"  building {investors:,} investors, {payments_each} payments each")
    started = time.perf_counter()
    engine = build(investors, payments_each)
    seeding = time.perf_counter() - started
    open_files = engine.queue()
    print(f"  {len(engine.log):,} records written in {seeding:.1f}s "
          f"({len(engine.log) / seeding:,.0f}/s)")
    # Per hundred payments as well as raw, so a drift like the one this
    # replaced -- 100 files per 100 payments, reported only as "6,001 files
    # open" -- shows up in the output instead of needing an audit.
    payments = investors * payments_each
    print(f"  {len(open_files):,} files open "
          f"({len(open_files) / payments * 100:.1f} per 100 payments; "
          f"one payment in {ODD_IN} was built odd)")
    print()

    a_case = open_files[0].case_id
    a_party = next(iter(engine.state.graph.entities))
    measures = [
        took("the queue (what an officer waits for)",
             lambda: brief(engine, person="Meera Nair", today=WHEN)),
        took("one file", lambda: case_file(engine, a_case, today=WHEN)),
        took("one party", lambda: party(engine, a_party, today=WHEN)),
        took("screening coverage", lambda: screening(engine, WHEN)),
        took("where you stand with IFSCA", lambda: regulatory(engine, WHEN)),
        took("rebuilding state from the log", engine.rebuild),
        took("verifying the whole chain", engine.verify),
        took("the evidence pack", lambda: pack(engine, "scale", WHEN)),
    ]

    print(f"  {'surface':44} {'time':>10}")
    for label, millis, _ in measures:
        flag = "" if millis < 1000 else "   <-- over a second"
        print(f"  {label:44} {millis:>8.0f}ms{flag}")

    # The queue is the one a person sits in front of every morning, so it gets
    # measured properly rather than once.
    runs = [took("", lambda: brief(engine, person="Meera Nair", today=WHEN))[1]
            for _ in range(5)]
    print()
    print(f"  queue over 5 runs: median {statistics.median(runs):.0f}ms, "
          f"worst {max(runs):.0f}ms")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
