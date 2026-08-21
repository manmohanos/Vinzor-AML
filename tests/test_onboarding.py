"""Taking on one investor: eight checks, run for real.

Not unit tests of eight functions. The thing worth holding in place is that a
whole onboarding runs end to end over a real engine, records eight steps as
permanent events, and never once concludes anything.
"""

from __future__ import annotations

import pytest

from vinzor.agents import DONE, FAILED, FOUND_SOMETHING, RECIPES, SKIPPED, TOOLS
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType
from vinzor.onboarding import ORDER

from conftest import WHEN, company, person


@pytest.fixture
def engine() -> Vinzor:
    return Vinzor(EventLog())


def onboard(engine, party: str, when: str = WHEN) -> str:
    task_id = engine.give_task(recipe_key="onboard", actor="Meera Nair",
                               given_at=when, party=party)
    engine.run_task(task_id, when=when, party=party)
    return task_id


def steps(engine, task_id: str) -> list:
    return [e.payload for e in engine.log
            if e.event_type is EventType.TASK_STEP and e.subject == task_id]


# -- the pipeline itself -----------------------------------------------------


def test_the_recipe_runs_every_check_and_records_each_one(engine):
    person(engine, "p1", "Rohan Desai")
    task_id = onboard(engine, "p1")
    ran = steps(engine, task_id)
    assert [s["tool"] for s in ran] == list(ORDER)
    for step in ran:
        assert step["headline"], f"{step['tool']} recorded no headline"
        assert step["how"] in (DONE, FOUND_SOMETHING, FAILED, SKIPPED)


def test_every_step_is_a_permanent_event_as_it_finishes(engine):
    """The progress an officer watches is evidence rather than animation:
    each row lands on the log the moment its tool returns, which is also why
    a run that fails halfway has still recorded the half it did."""
    person(engine, "p1", "Rohan Desai")
    task_id = onboard(engine, "p1")
    assert len(steps(engine, task_id)) == 8
    finished = [e for e in engine.log
                if e.event_type is EventType.TASK_FINISHED
                and e.subject == task_id]
    assert len(finished) == 1


def test_a_run_replays_to_the_same_state(engine):
    """An inspector asking what the machine did on this date gets the same
    answer the officer watched."""
    person(engine, "p1", "Rohan Desai")
    onboard(engine, "p1")
    assert engine.rebuild().casebook.cases == engine.state.casebook.cases


def test_the_same_party_checked_twice_gives_the_same_findings(engine):
    """Determinism, which is the whole reason none of these eight reason.
    A check that answers differently on a Tuesday is not evidence."""
    person(engine, "p1", "Rohan Desai")
    first = [(s["tool"], s["headline"], s["how"])
             for s in steps(engine, onboard(engine, "p1"))]
    second = [(s["tool"], s["headline"], s["how"])
              for s in steps(engine, onboard(engine, "p1", when="2026-08-23"))]
    assert first == second


# -- what each check actually says -------------------------------------------


def test_an_unscreened_party_is_reported_as_unchecked_never_as_clean(engine):
    """The distinction the watchlist adapter exists to protect, carried to
    the one screen where a person acts on it. 'Nobody looked' and 'we looked
    and there was nothing' must never render the same."""
    person(engine, "p1", "Rohan Desai")
    ran = {s["tool"]: s for s in steps(engine, onboard(engine, "p1"))}
    # FOUND_SOMETHING, not FAILED. The absence of a screening record IS the
    # finding, and it is the thing an officer must act on before this party
    # can be taken on. Filing it as a failure would put the most important
    # gap in an onboarding under "something went wrong with our software".
    assert ran["sanctions"]["how"] == FOUND_SOMETHING
    assert "nobody has run" in ran["sanctions"]["headline"].lower()
    assert ran["politically"]["how"] == FOUND_SOMETHING


def test_the_press_not_having_been_searched_is_also_not_clean(engine):
    person(engine, "p1", "Rohan Desai")
    ran = {s["tool"]: s for s in steps(engine, onboard(engine, "p1"))}
    assert ran["adverse"]["how"] == FOUND_SOMETHING
    assert "not been searched" in ran["adverse"]["headline"]


def test_a_person_is_their_own_beneficial_owner(engine):
    person(engine, "p1", "Rohan Desai")
    ran = {s["tool"]: s for s in steps(engine, onboard(engine, "p1"))}
    assert ran["ownership"]["how"] == DONE


def test_a_company_with_nobody_behind_it_is_reported_unresolved(engine):
    company(engine, "c1", "Orion Zenith Enterprises")
    ran = {s["tool"]: s for s in steps(engine, onboard(engine, "c1"))}
    assert ran["ownership"]["how"] == FOUND_SOMETHING
    assert "not established" in ran["ownership"]["headline"]


def test_a_company_is_asked_for_more_documents_than_a_person(engine):
    person(engine, "p1", "Rohan Desai")
    company(engine, "c1", "Orion Zenith Enterprises")
    for_person = {s["tool"]: s for s in steps(engine, onboard(engine, "p1"))}
    for_company = {s["tool"]: s for s in steps(engine, onboard(engine, "c1"))}
    assert for_company["documents"]["headline"] != for_person["documents"]["headline"]


def test_a_party_nobody_named_is_skipped_rather_than_crashed(engine):
    """A run started without a party is our mistake, not the officer's, and
    it must not put a stack trace on their screen."""
    task_id = engine.give_task(recipe_key="onboard", actor="Meera Nair",
                               given_at=WHEN)
    engine.run_task(task_id, when=WHEN)
    ran = steps(engine, task_id)
    assert all(s["how"] == SKIPPED for s in ran)
    assert all("nothing" in s["headline"].lower() for s in ran)


def test_a_party_that_does_not_exist_is_skipped_with_a_sentence(engine):
    task_id = engine.give_task(recipe_key="onboard", actor="Meera Nair",
                               given_at=WHEN, party="nobody")
    engine.run_task(task_id, when=WHEN, party="nobody")
    ran = steps(engine, task_id)
    assert all(s["how"] == SKIPPED for s in ran)


# -- the rules it must not break ---------------------------------------------


def test_no_onboarding_step_can_settle_anything(engine):
    """The read-only facade is what stops this, not discipline. Proved by
    running the whole pipeline and checking nothing was decided."""
    person(engine, "p1", "Rohan Desai")
    before = len([e for e in engine.log
                  if e.event_type is EventType.CASE_DECIDED])
    onboard(engine, "p1")
    after = len([e for e in engine.log
                 if e.event_type is EventType.CASE_DECIDED])
    assert before == after == 0


def test_no_step_concludes_about_the_party_as_a_whole(engine):
    """There is deliberately no score, no traffic light and no
    'recommended: accept'. The report ends at a person."""
    person(engine, "p1", "Rohan Desai")
    said = " ".join(s["headline"] for s in steps(engine, onboard(engine, "p1")))
    for verdict in ("recommend", "approve", "accept", "reject",
                    "low risk", "high risk", "score"):
        assert verdict not in said.lower(), f"a step concluded: {verdict!r}"


def test_no_step_shows_implementation_vocabulary(engine):
    """Every sentence here goes on a permanent event and onto a screen."""
    import re

    person(engine, "p1", "Rohan Desai")
    company(engine, "c1", "Orion Zenith Enterprises")
    said = []
    for party in ("p1", "c1"):
        for step in steps(engine, onboard(engine, party)):
            said.append(step["headline"])
            said.extend(step.get("details") or ())
    text = " ".join(said)
    for pattern in (r"\bPOL_[A-Z]", r"[A-Z][A-Z0-9]{2,}_[A-Z]",
                    r"\bcase_[0-9a-f]{6,}", r"[{}\[\]]", r"\bNone\b"):
        assert not re.search(pattern, text), f"{pattern} leaked: {text[:200]}"


def test_every_tool_in_the_recipe_exists(engine):
    """A step naming a tool that is not registered is silently skipped by
    run_task, which would read on screen as a check that found nothing."""
    for _label, tool in RECIPES["onboard"].steps:
        assert tool in TOOLS, f"{tool} is in the recipe and not in the registry"


def test_only_the_checks_that_reach_outside_may_report_a_failure(engine):
    """The test that would have caught a real bug and did not.

    The first version of this file asserted only that every step's outcome
    was one of the four valid ones -- and FAILED is one of the four. So
    `identification` reading a field name that does not exist crashed on
    every single run, was recorded as "this step could not be completed",
    and the suite stayed green.

    No step here may report a failure at all. FAILED means the tool broke;
    a check that has never been run is a finding, because the absence of a
    screening record is exactly what an officer has to act on. That is also
    what tests/test_runs_audit.py has always asserted across every recipe,
    and it was right.
    """
    person(engine, "p1", "Rohan Desai")
    company(engine, "c1", "Orion Zenith Enterprises")
    for party in ("p1", "c1"):
        for step in steps(engine, onboard(engine, party)):
            assert step["how"] != FAILED, (
                f"{step['tool']} failed reading records we already hold: "
                f"{step['headline']}")


def test_identification_says_which_clause_each_gap_is(engine):
    """A missing field is an argument with an investor; a missing field with
    the clause number beside it is not."""
    company(engine, "c1", "Orion Zenith Enterprises")
    ran = {s["tool"]: s for s in steps(engine, onboard(engine, "c1"))}
    identification = ran["identification"]
    assert identification["how"] == FOUND_SOMETHING
    assert any("5.4.2" in d for d in identification["details"])
