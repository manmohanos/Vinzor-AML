"""What the ownership resolver claims, tested by attacking it.

The block carried a known defect and a reason for leaving it: ``resolve_ubo``
enumerates paths without memoisation and is exponential on a densely
reconvergent structure, *"confirmed not reachable by real data; left
unpatched deliberately because the fix changes how effective percentages
accumulate, which is the most legally sensitive number in the system"*.

The caution was right. The confirmation was wrong.

**It is reachable, and not by anything exotic.** Take a group of companies
and enter each one as owned by the others -- which is what a group
structure looks like when somebody fills in a spreadsheet by listing every
company against every other. At eight companies that took **29 seconds**;
at ten, eight seconds more than a minute; at eleven, **106 seconds**. And
beneficial ownership is resolved when money is promised, not when a screen
is opened, so an import carrying that mistake would not have been a slow
page. It would have stopped the write.

**Almost none of that was the exponential walk.** The eight-company case
visits 13,701 edges -- a lattice that visits 147,622 finishes in a quarter
of a second. The time went on ``if cycle not in cycles``, a scan of a list
that grew to 27,391 entries, once per cycle found. Asking a set instead
took that case from 29.46 seconds to 0.05, and moved the wall from eight
companies to about ten.

**The rest is genuinely exponential and now has a stated budget.** Past
:data:`MOST_EDGES` the walk stops and the result says it stopped: the
conclusion is INCOMPLETE, the holdings are described as at least what is
shown, and nothing reads as a clean answer. Every shape that used to hang
now finishes in under a tenth of a second.

**And no percentage moved.** ``tools/ownership_spec.py`` freezes every
number, every route and the order of every route across seventeen
structures. The frozen file was taken from the resolver *as it was before
any of this*, and the check below runs the current one against it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.graph import MOST_EDGES, Conclusion
from vinzor.model import EntityKind, EventType

WHEN = "2026-08-20"


def reg(engine, eid, kind, name=None):
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=eid,
                  occurred_at=WHEN, actor="t",
                  payload={"kind": kind.value, "name": name or eid,
                           "attributes": {}})


def own(engine, owned, owner, pct):
    engine.ingest(event_type=EventType.OWNERSHIP_DECLARED, subject=owned,
                  occurred_at=WHEN, actor="t",
                  payload={"owner": owner, "owned": owned, "percentage": pct,
                           "relation": "OWNS"})


def mutual_group(size: int) -> Vinzor:
    """Companies each declared as owned by all the others.

    Not a contrived graph -- what a spreadsheet produces when a group is
    entered by listing every company against every other.
    """
    engine = Vinzor(EventLog())
    for index in range(size):
        reg(engine, f"c{index}", EntityKind.COMPANY, f"Group Company {index}")
    for index in range(size):
        for other in range(size):
            if index != other:
                own(engine, f"c{index}", f"c{other}", 100.0 / (size - 1))
    return engine


# -- no percentage moved -----------------------------------------------------


def test_every_frozen_percentage_route_and_order_is_unchanged():
    """The spec the block asked for, and the reason the defect sat unfixed.

    A percentage is a sum of floating-point products and floating-point
    addition is not associative, so any change that reaches the same owners
    by a different route order can move the fourth decimal without any
    error in the arithmetic. The frozen file holds each percentage as its
    ``repr`` and each route in the order it was found, so a change in the
    last bit or in the ordering fails here.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import ownership_spec as spec

    frozen = json.loads(spec.FROZEN.read_text(encoding="utf-8"))
    now = spec.taken()

    assert set(now) == set(frozen), "a structure was added or dropped"
    moved = [label for label in sorted(frozen) if frozen[label] != now[label]]
    assert not moved, (
        f"\n{len(moved)} structure(s) produce different numbers than the "
        f"frozen record:\n  " + "\n  ".join(moved) +
        "\nEvery one is a number somebody may have relied on. If the change "
        "is intended, re-freeze deliberately with:\n"
        "  python tools/ownership_spec.py --freeze")


def test_the_frozen_record_covers_the_shapes_that_matter():
    """A freeze of three easy structures would pass anything."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import ownership_spec as spec

    frozen = json.loads(spec.FROZEN.read_text(encoding="utf-8"))
    assert len(frozen) >= 15
    conclusions = {entry["conclusion"] for entry in frozen.values()}
    assert conclusions == {c.value for c in Conclusion}, (
        "the frozen structures do not reach every conclusion the resolver "
        "can draw")
    assert any(entry["cycles"] for entry in frozen.values())
    assert any(entry["dead_ends"] for entry in frozen.values())
    assert any(len(one["routes"]) > 1
               for entry in frozen.values() for one in entry["owners"]), (
        "no frozen owner is reached by more than one route, so nothing here "
        "would notice a change in how routes are summed")


# -- the shape that used to stop the write -----------------------------------


def test_a_carelessly_entered_group_resolves_quickly(engine):
    """Eight companies each owned by the other seven took 29 seconds, and
    almost all of it went on checking a growing list of cycles rather than
    on walking. A hundredfold margin, so this is not a flaky timing test:
    it would have needed 29 seconds and is allowed one."""
    book = mutual_group(8)
    began = time.perf_counter()
    result = book.state.graph.resolve_ubo("c0")
    took = time.perf_counter() - began

    assert took < 1.0, f"took {took:.1f}s"
    assert result.cycles
    assert not result.stopped_early, "eight companies should fit in the budget"


def test_a_group_too_tangled_to_follow_stops_and_says_so(engine):
    """Twelve companies is past any budget. What matters is that it comes
    back at all, and that it does not come back looking like an answer."""
    book = mutual_group(12)
    began = time.perf_counter()
    result = book.state.graph.resolve_ubo("c0")
    took = time.perf_counter() - began

    assert took < 5.0, f"took {took:.1f}s"
    assert result.stopped_early
    assert result.conclusion is Conclusion.INCOMPLETE


def test_a_walk_that_stopped_early_never_reads_as_a_clean_answer(engine):
    """The worst outcome available here is a truncated walk reporting that
    a company has no beneficial owner, or naming one as though the search
    had finished."""
    book = mutual_group(12)
    result = book.state.graph.resolve_ubo("c0")

    assert result.conclusion is not Conclusion.IDENTIFIED
    assert result.conclusion is not Conclusion.NOT_DECLARED
    said = result.explain()
    assert "not established" in said
    assert "at least what is shown" in said
    assert f"{MOST_EDGES:,}" in said


def test_the_budget_is_a_stated_limit_and_not_a_hidden_one():
    """A cap nobody can find is a lie about coverage. The number is a named
    constant and the comment above it says what the cap can cost."""
    import inspect

    import vinzor.graph as graph

    source = inspect.getsource(graph)
    stated = source[:source.index("MOST_EDGES = ")]
    assert "What it can cost" in stated
    assert "spreadsheet" in stated


def test_an_ordinary_structure_is_nowhere_near_the_budget(engine):
    """The margin has to be wide enough that no real firm meets it. Across
    the 94 non-person parties of a real workspace the worst walk visited
    four edges; this is the same point made in miniature."""
    reg(engine, "fund", EntityKind.FUND, "A Fund")
    reg(engine, "gp", EntityKind.COMPANY, "The General Partner")
    reg(engine, "hold", EntityKind.COMPANY, "A Holding Company")
    reg(engine, "per", EntityKind.PERSON, "The Principal")
    own(engine, "fund", "gp", 100.0)
    own(engine, "gp", "hold", 60.0)
    own(engine, "hold", "per", 100.0)

    result = engine.state.graph.resolve_ubo("fund")
    assert not result.stopped_early
    assert result.conclusion is Conclusion.IDENTIFIED
    assert MOST_EDGES > 1000


# -- what the walk still cannot do -------------------------------------------


def test_a_cut_short_walk_keeps_what_it_did_find(engine):
    """Throwing the partial answer away would be worse than keeping it. An
    officer who can see that three people hold at least this much has more
    than one who can see nothing."""
    book = mutual_group(12)
    reg(book, "per", EntityKind.PERSON, "A Real Holder")
    own(book, "c0", "per", 40.0)

    result = book.state.graph.resolve_ubo("c0")
    assert result.stopped_early
    assert result.owners or result.below_threshold, (
        "the walk found nobody at all, so nothing was kept")
