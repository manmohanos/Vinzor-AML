"""The measuring scripts, checked for whether they can report bad news.

BLOCKS.md's "Next" for this block was to run these in CI. Adding them would
have achieved nothing: **10 of the 14 tools ended in a bare ``return 0``**, so
nothing they measured could fail a build. Simulated total detection failure,
in memory, by stubbing the readers each tool uses::

    typologies  -> '0 of 7 shapes are recognised as shapes.'   exit 0
    adversarial -> '0 evasions failed, 0 worked, 10 could not
                    be tested.'                                exit 0
    ordinary    -> 'every payment rule  10000  12820.5'        exit 0

All three green. A build that goes amber on "0 of 7 shapes are recognised" and
still passes is worse than no build, because it is read as evidence.

Each fast tool now carries a floor -- the number measured, written into the
file with the date -- and returns 1 below it. These tests hold the floors in
place and, more importantly, prove each one can actually fire: a guard nobody
has seen fail is a guard nobody should trust.

**Two of the floors moved on 21 August 2026, and one of them stopped being a
floor.** Nine of the ten payment rules were removed that day. ``typologies``
fell from 7 of 7 recognised shapes to 0 of 7, and ``adversarial`` from ten
trials against four rules to one trial against one, which reads EVADED. Both
floors are set to what is now measured, because a floor above what the
product does turns every build red and teaches people to ignore it.

The typology floor at 0 can no longer fire downward -- nothing goes below
zero -- so ``typologies`` has become a tool that can only report an
improvement, which is the exact failure this file was written to fix. It is
recorded here rather than hidden, and the paired test below says in its own
name what it now proves, which is less than it used to.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools"


def load(name):
    """Import a script from ``tools/`` without installing it."""
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(f"_tool_{name}",
                                                  TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- the floors are where they were measured ---------------------------------


def test_no_typology_shape_is_recognised_and_the_tool_says_so():
    """0 of 7 since the counterparty and multi-hop rules were removed.

    The floor is asserted at 0 rather than at ``len(SHAPES)`` because that is
    the measurement. Asserting 7 would be asserting a product we do not have.
    """
    typologies = load("typologies")
    assert typologies.ALL_OF_THEM == 0
    assert typologies.main() == 0


def test_the_duplicate_floors_hold():
    duplicates = load("duplicate_shapes")
    assert duplicates.main() == 0


def test_the_evasion_floor_holds():
    adversarial = load("adversarial")
    assert adversarial.EVADED_WHEN_SET == 1
    assert len(adversarial.TRIALS) == 1
    assert adversarial.main() == 0


def test_an_ordinary_book_stays_under_its_stated_ceiling():
    ordinary = load("ordinary_traffic")
    assert ordinary.LOUDEST_ACCEPTABLE == 30.0
    assert ordinary.main() == 0


# -- and every floor can fire ------------------------------------------------


def test_the_typology_floor_only_proves_the_comparison_works(monkeypatch):
    """What this test proves, stated honestly, because it is now less than
    its old name claimed.

    While the floor stood at 7, raising it to 8 stood in for a shape that had
    stopped being seen: the tool measured 7, the floor wanted 8, the build
    went red. That was a real rehearsal of a real failure.

    The floor is 0 now. Nothing the tool can measure is below zero, so no
    change to the product can make this guard fire -- only moving the
    constant can. Raising it to 1 therefore demonstrates that the comparison
    and the exit code still work, and nothing about detection. The typology
    tool cannot report bad news again until a rule that recognises a shape is
    restored, and that is the thing to fix rather than this test.
    """
    typologies = load("typologies")
    assert typologies.ALL_OF_THEM == 0, "the floor can fire again; rename this"
    monkeypatch.setattr(typologies, "ALL_OF_THEM", 1)
    assert typologies.main() == 1


def test_the_duplicate_floor_fires_when_fewer_are_found(monkeypatch):
    duplicates = load("duplicate_shapes")
    monkeypatch.setattr(duplicates, "FOUND_WHEN_SET", 999)
    assert duplicates.main() == 1


def test_the_duplicate_floor_also_fires_on_a_new_false_alarm(monkeypatch):
    """Both directions matter and they pull against each other: finding
    fewer duplicates hides real ones, raising more namesakes costs an
    officer an hour each."""
    duplicates = load("duplicate_shapes")
    monkeypatch.setattr(duplicates, "ALARMS_WHEN_SET", -1)
    assert duplicates.main() == 1


def test_the_evasion_floor_fires_when_one_more_evasion_works(monkeypatch):
    """This one still fires for the right reason. The lab measures 1 evasion
    and the floor is 1, so lowering the floor to 0 is exactly the situation
    of one more evasion starting to work."""
    adversarial = load("adversarial")
    monkeypatch.setattr(adversarial, "EVADED_WHEN_SET", 0)
    assert adversarial.main() == 1


def test_the_noise_ceiling_fires_when_an_ordinary_book_gets_louder(monkeypatch):
    ordinary = load("ordinary_traffic")
    monkeypatch.setattr(ordinary, "LOUDEST_ACCEPTABLE", 0.0)
    assert ordinary.main() == 1


# -- and the ones CI runs are the ones that can fail -------------------------


def test_ci_runs_the_tools_that_can_report_bad_news():
    ci = (pathlib.Path(__file__).resolve().parent.parent
          / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    for name in ("typologies", "duplicate_shapes", "adversarial",
                 "ordinary_traffic", "ownership_spec", "benchmark"):
        assert f"tools/{name}.py" in ci, f"{name} is not run by CI"
