"""Every percentage this resolver produces, frozen, so a change cannot move one.

    python tools/ownership_spec.py            # check against the frozen file
    python tools/ownership_spec.py --freeze   # record a new one, deliberately

The block that holds beneficial ownership carried a known defect for weeks
and said why it was left alone: the fix "changes how effective percentages
accumulate, which is the most legally sensitive number in the system". That
is the right reason to be careful and the wrong reason to do nothing. What
it needed was this -- a statement of which numbers must not move, checkable
by machine, so that a change either preserves them or is caught.

**What is frozen.** For each structure below, every field a reader or a
policy can see: the effective percentage of each beneficial owner to the
fourth decimal, the exact routes by which each was reached and their order,
which owners fall below the threshold, the cycles, the dead ends, the
conclusion, and the sentence the result explains itself with.

**Why the routes and their order.** A percentage is a sum of floating-point
products, and floating-point addition is not associative: 0.1 + 0.2 + 0.3
and 0.3 + 0.2 + 0.1 can differ in the last bit. Any change that reaches the
same owners by a different path order can therefore produce a different
number in the fourth decimal without any error in the arithmetic. Freezing
the order is what makes "byte-identical" a testable claim rather than a
hope.

**The structures.** Chains, diamonds where one person is reached twice,
cycles, dead ends, a trust with and without its mandatory parties, holdings
either side of both thresholds -- and the reconvergent lattices that made
the walk exponential in the first place, small enough to stay well inside
the budget.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vinzor.engine import Vinzor                          # noqa: E402
from vinzor.eventlog import EventLog                      # noqa: E402
from vinzor.model import EntityKind, EventType            # noqa: E402

WHEN = "2026-08-20"
FROZEN = Path(__file__).resolve().parent.parent / "tests" / "ownership_frozen.json"


def workspace() -> Vinzor:
    return Vinzor(EventLog())


def reg(engine, eid, kind, name=None):
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=eid,
                  occurred_at=WHEN, actor="spec",
                  payload={"kind": kind.value, "name": name or eid,
                           "attributes": {}})


def own(engine, owned, owner, pct, relation="OWNS"):
    engine.ingest(event_type=EventType.OWNERSHIP_DECLARED, subject=owned,
                  occurred_at=WHEN, actor="spec",
                  payload={"owner": owner, "owned": owned, "percentage": pct,
                           "relation": relation})


# -- the structures ----------------------------------------------------------


def one_person_one_company():
    engine = workspace()
    reg(engine, "co", EntityKind.COMPANY)
    reg(engine, "p1", EntityKind.PERSON, "Sole Holder")
    own(engine, "co", "p1", 100.0)
    return engine, "co"


def a_chain_of_three():
    engine = workspace()
    for eid in ("co", "mid", "top"):
        reg(engine, eid, EntityKind.COMPANY)
    reg(engine, "p1", EntityKind.PERSON, "Chain Holder")
    own(engine, "co", "mid", 60.0)
    own(engine, "mid", "top", 50.0)
    own(engine, "top", "p1", 100.0)
    return engine, "co"


def two_routes_to_one_person():
    """The sum that makes float order matter: 30% one way, 30% another."""
    engine = workspace()
    for eid in ("co", "left", "right"):
        reg(engine, eid, EntityKind.COMPANY)
    reg(engine, "p1", EntityKind.PERSON, "Both Ways")
    own(engine, "co", "left", 30.0)
    own(engine, "co", "right", 30.0)
    own(engine, "left", "p1", 100.0)
    own(engine, "right", "p1", 100.0)
    return engine, "co"


def thirds_that_do_not_divide():
    """Three routes of a third each -- the arithmetic that does not close."""
    engine = workspace()
    reg(engine, "co", EntityKind.COMPANY)
    reg(engine, "p1", EntityKind.PERSON, "A Third Each")
    for index in range(3):
        reg(engine, f"h{index}", EntityKind.COMPANY)
        own(engine, "co", f"h{index}", 100.0 / 3.0)
        own(engine, f"h{index}", "p1", 100.0 / 3.0)
    return engine, "co"


def just_above_and_just_below():
    engine = workspace()
    reg(engine, "co", EntityKind.COMPANY)
    reg(engine, "over", EntityKind.PERSON, "Just Over")
    reg(engine, "under", EntityKind.PERSON, "Just Under")
    reg(engine, "exact", EntityKind.PERSON, "Exactly Ten")
    own(engine, "co", "over", 10.01)
    own(engine, "co", "under", 9.99)
    own(engine, "co", "exact", 10.0)
    return engine, "co"


def everyone_below_the_threshold():
    """Nobody reaches ten per cent, so 1.3.3(c)'s explanation applies and
    the senior managing official has to be recorded instead."""
    engine = workspace()
    reg(engine, "co", EntityKind.COMPANY)
    for index in range(12):
        reg(engine, f"p{index}", EntityKind.PERSON, f"Small Holder {index}")
        own(engine, "co", f"p{index}", 100.0 / 12.0)
    return engine, "co"


def unincorporated_at_fifteen():
    engine = workspace()
    reg(engine, "body", EntityKind.UNINCORPORATED_BODY)
    reg(engine, "over", EntityKind.PERSON, "Sixteen")
    reg(engine, "under", EntityKind.PERSON, "Fourteen")
    own(engine, "body", "over", 16.0)
    own(engine, "body", "under", 14.0)
    return engine, "body"


def a_trust_with_its_parties():
    engine = workspace()
    reg(engine, "tr", EntityKind.TRUST)
    reg(engine, "settlor", EntityKind.PERSON, "The Author")
    reg(engine, "trustee", EntityKind.PERSON, "The Trustee")
    reg(engine, "ben", EntityKind.PERSON, "A Beneficiary")
    own(engine, "tr", "settlor", 0.0, relation="SETTLOR_OF")
    own(engine, "tr", "trustee", 0.0, relation="TRUSTEE_OF")
    own(engine, "tr", "ben", 10.0, relation="BENEFICIARY_OF")
    return engine, "tr"


def a_trust_missing_its_author():
    engine = workspace()
    reg(engine, "tr", EntityKind.TRUST)
    reg(engine, "trustee", EntityKind.PERSON, "The Trustee")
    own(engine, "tr", "trustee", 0.0, relation="TRUSTEE_OF")
    return engine, "tr"


def a_loop():
    engine = workspace()
    for eid in ("a", "b", "c"):
        reg(engine, eid, EntityKind.COMPANY)
    own(engine, "a", "b", 100.0)
    own(engine, "b", "c", 100.0)
    own(engine, "c", "a", 100.0)
    return engine, "a"


def a_chain_that_runs_out():
    engine = workspace()
    reg(engine, "co", EntityKind.COMPANY)
    reg(engine, "mid", EntityKind.COMPANY)
    own(engine, "co", "mid", 100.0)
    return engine, "co"


def nothing_declared():
    engine = workspace()
    reg(engine, "co", EntityKind.COMPANY)
    return engine, "co"


def deeper_than_the_walk_goes():
    engine = workspace()
    reg(engine, "c0", EntityKind.COMPANY)
    for index in range(1, 20):
        reg(engine, f"c{index}", EntityKind.COMPANY)
        own(engine, f"c{index - 1}", f"c{index}", 100.0)
    reg(engine, "p1", EntityKind.PERSON, "Far Away")
    own(engine, "c19", "p1", 100.0)
    return engine, "c0"


def a_lattice(layers, width):
    """The reconvergent shape that made the walk exponential."""
    def build():
        engine = workspace()
        reg(engine, "top", EntityKind.COMPANY)
        below = ["top"]
        for layer in range(layers):
            here = [f"c{layer}_{i}" for i in range(width)]
            for cid in here:
                reg(engine, cid, EntityKind.COMPANY)
            for child in below:
                for cid in here:
                    own(engine, child, cid, 100.0 / width)
            below = here
        reg(engine, "person", EntityKind.PERSON, "At The Top")
        for cid in below:
            own(engine, cid, "person", 100.0)
        return engine, "top"
    return build


def a_mutual_group(size):
    """Companies each declared as owned by all the others."""
    def build():
        engine = workspace()
        for index in range(size):
            reg(engine, f"c{index}", EntityKind.COMPANY)
        reg(engine, "per", EntityKind.PERSON, "The Owner")
        for index in range(size):
            for other in range(size):
                if index != other:
                    own(engine, f"c{index}", f"c{other}", 100.0 / (size - 1))
        own(engine, "c0", "per", 1.0)
        return engine, "c0"
    return build


STRUCTURES = [
    ("one person, one company", one_person_one_company),
    ("a chain of three", a_chain_of_three),
    ("two routes to one person", two_routes_to_one_person),
    ("thirds that do not divide", thirds_that_do_not_divide),
    ("just above and just below ten", just_above_and_just_below),
    ("everyone below the threshold", everyone_below_the_threshold),
    ("an unincorporated body at fifteen", unincorporated_at_fifteen),
    ("a trust with its parties", a_trust_with_its_parties),
    ("a trust missing its author", a_trust_missing_its_author),
    ("a loop", a_loop),
    ("a chain that runs out", a_chain_that_runs_out),
    ("nothing declared", nothing_declared),
    ("deeper than the walk goes", deeper_than_the_walk_goes),
    ("a lattice 2 wide, 4 deep", a_lattice(4, 2)),
    ("a lattice 3 wide, 4 deep", a_lattice(4, 3)),
    ("a lattice 3 wide, 6 deep", a_lattice(6, 3)),
    ("a mutual group of four", a_mutual_group(4)),
    ("a mutual group of six", a_mutual_group(6)),
]


def as_written(result) -> dict:
    """Everything about a result that anyone can see."""
    def owner(one):
        return {
            "person": one.person_id,
            "name": one.name,
            # repr, not round: the frozen file has to hold the number that
            # is actually there, not a tidied one, or a change in the last
            # bit would pass unnoticed.
            "percentage": repr(one.effective_percentage),
            "routes": [list(route) for route in one.paths],
        }

    return {
        "subject": result.subject,
        "kind": result.subject_kind.value if result.subject_kind else None,
        "test": result.test.describe(),
        "clause": result.clause,
        "conclusion": result.conclusion.value,
        "owners": [owner(one) for one in result.owners],
        "below_threshold": [owner(one) for one in result.below_threshold],
        "mandatory_parties": [
            {"party": one.party_id, "name": one.name, "role": one.role}
            for one in result.mandatory_parties],
        "missing_roles": list(result.missing_roles),
        "cycles": [list(cycle) for cycle in result.cycles],
        "dead_ends": list(result.dead_ends),
        "stopped_early": result.stopped_early,
        "explain": result.explain(),
    }


def taken() -> dict:
    out = {}
    for label, build in STRUCTURES:
        engine, subject = build()
        out[label] = as_written(engine.state.graph.resolve_ubo(subject))
    return out


def main() -> int:
    now = taken()
    if "--freeze" in sys.argv:
        FROZEN.write_text(json.dumps(now, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
        print(f"\n  froze {len(now)} structures into {FROZEN.name}\n")
        return 0

    if not FROZEN.exists():
        print(f"\n  no frozen file yet -- run with --freeze\n")
        return 1

    was = json.loads(FROZEN.read_text(encoding="utf-8"))
    moved = [label for label in sorted(set(was) | set(now))
             if was.get(label) != now.get(label)]
    print()
    for label, _ in STRUCTURES:
        print(f"  {'MOVED   ' if label in moved else 'same    '}{label}")
    print()
    if moved:
        print(f"  {len(moved)} of {len(STRUCTURES)} structures changed. "
              f"Every one is a number somebody may have relied on.")
        for label in moved:
            print(f"\n  -- {label} --")
            print(f"     was: {json.dumps(was.get(label), sort_keys=True)[:400]}")
            print(f"     now: {json.dumps(now.get(label), sort_keys=True)[:400]}")
        return 1
    print(f"  all {len(STRUCTURES)} structures identical.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
