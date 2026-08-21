"""What a delegated job writes down about itself, checked against what it did.

Three claims, all of them written on a permanent record or on the card that
summarises one, and none of them true.

**A step that crashed was counted as a step that found something.** The test
was ``if found.how not in (DONE, "skipped")``, and ``FAILED`` is neither. It is
on the shipped workspace's own log -- live.db seq 1568/1569 record a screening
step that broke outright, and a summary reading "2 of 3 steps found something
worth a person's time". A run where the watchlist never answered and a run that
found two sanctioned investors closed on the same reassuring sentence, and that
sentence is the whole of a collapsed task card.

**The failure was reported in Python.** ``could not finish: type object
'WatchlistClient' has no attribute 'from_environment'`` is on that same log.
The jargon sweep never walked a Task, so nothing caught it.

**The author of an agent's events was a name the model chose.** ``run_task``
wrote ``actor=step.agent``, and ``step.agent`` is a string from the model's own
reply. Two things followed. A transport answering ``{"agent": "Meera Nair"}``
put an enrolled AML officer's name on a hash-chained event she had nothing to
do with. And that same model-chosen string was the input to
``may_produce_findings``, so whether the rulepack ran over an agent's event was
decided by untrusted model output -- inert only because no shipped policy
happens to name ``TASK_STEP``, which is word for word why the earlier
``DRAFT_PREPARED`` version of this was treated as a defect.

**And a run whose process stopped read "Working now" for ever.** ``running``
was defined as the *absence* of a finish record, so a clean shutdown -- the
work runs on a daemon thread -- left a card under "Working now", present
tense, bar at 0%, with the browser re-fetching every 1,200 ms for a thread
that no longer existed. It survived restarts, so a workspace collected
permanent phantom jobs.
"""

from __future__ import annotations

import pytest

from vinzor.agents import DONE, FAILED, FOUND_SOMETHING, Found
from vinzor.engine import MODEL_AUTHORED, Vinzor, _outcome_sentence
from vinzor.eventlog import EventLog
from vinzor.model import EventType, Role

WHEN = "2026-08-20"


# -- what a finished run says it did -----------------------------------------


def test_a_step_that_crashed_is_not_a_step_that_found_something():
    assert _outcome_sentence(found=1, broke=1, steps=3) == (
        "1 of 3 steps found something worth a person's time; "
        "1 step could not be run, so nothing was checked there")


def test_a_run_where_everything_broke_does_not_read_like_success():
    said = _outcome_sentence(found=0, broke=3, steps=3)
    assert "found something" not in said
    assert "3 steps could not be run" in said


def test_a_clean_run_still_reads_as_a_clean_run():
    assert _outcome_sentence(found=2, broke=0, steps=3) == (
        "2 of 3 steps found something worth a person's time")


def test_a_quiet_run_still_reads_as_a_quiet_run():
    assert _outcome_sentence(found=0, broke=0, steps=3) == (
        "nothing needing attention was found")


def test_a_step_that_broke_says_so_in_words_not_in_python():
    """``could not finish: type object 'WatchlistClient' has no attribute
    'from_environment'`` went on a compliance officer's screen and onto the
    permanent record. The reason is evidence and is kept -- in the details,
    where it belongs."""
    from vinzor.engine import _Found_failed

    found = _Found_failed("type object 'WatchlistClient' has no attribute x")
    assert found.how == FAILED
    assert "WatchlistClient" not in found.headline
    assert found.headline == (
        "this step could not be completed, so nothing was checked")
    assert any("WatchlistClient" in line for line in found.details)


# -- who authored the event --------------------------------------------------


def a_delegating_workspace():
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera Nair", role=Role.AML_OFFICER, enrolled_at=WHEN)
    engine.enroll(name="Aarav Sharma", role=Role.COMPLIANCE, enrolled_at=WHEN)
    return engine


def test_an_agents_step_is_authored_by_the_agents_not_by_a_person():
    """A transport answering {"agent": "Meera Nair"} used to put her name on
    a hash-chained event she had nothing to do with, permanently."""
    from vinzor.agents import RECIPES

    engine = a_delegating_workspace()
    recipe = next(iter(RECIPES))
    task_id = engine.give_task(recipe_key=recipe, actor="Aarav Sharma",
                               given_at=WHEN)
    engine.run_task(task_id, when=WHEN)

    steps = [e for e in engine.log if e.event_type is EventType.TASK_STEP]
    assert steps, "the run recorded no steps at all"
    assert {e.actor for e in steps} == {"the agents"}
    assert not any(e.actor in engine.state.actors for e in steps)


def test_the_label_the_model_chose_travels_as_data_not_as_provenance():
    from vinzor.agents import RECIPES

    engine = a_delegating_workspace()
    task_id = engine.give_task(recipe_key=next(iter(RECIPES)),
                               actor="Aarav Sharma", given_at=WHEN)
    engine.run_task(task_id, when=WHEN)
    step = next(e for e in engine.log if e.event_type is EventType.TASK_STEP)
    assert "labelled" in step.payload


def test_the_rulepack_never_runs_over_an_agents_own_event():
    """The containment guard was driven by the model's own string. Adding a
    policy that named TASK_STEP opened three real Cases from agent-authored
    events."""
    assert EventType.TASK_STEP in MODEL_AUTHORED
    assert EventType.TASK_FINISHED in MODEL_AUTHORED
    assert EventType.DRAFT_PREPARED in MODEL_AUTHORED


def test_the_guard_still_lets_ordinary_machine_facts_through():
    """Deadlines and screening results are legitimate machine-minted facts
    about the world, not model judgement. A guard that stopped those would
    stop the product."""
    assert EventType.SCREENING_COMPLETED not in MODEL_AUTHORED
    assert EventType.PAYMENT_RECEIVED not in MODEL_AUTHORED


# -- a run that stopped ------------------------------------------------------


def a_half_run(given_at="2026-08-19"):
    """A job given yesterday whose process died before it finished."""
    from vinzor.agents import RECIPES

    engine = a_delegating_workspace()
    task_id = engine.give_task(recipe_key=next(iter(RECIPES)),
                               actor="Aarav Sharma", given_at=given_at)
    return engine, engine.state.runs.tasks[task_id]


def test_a_job_left_from_an_earlier_day_is_not_working_now():
    _engine, task = a_half_run()
    assert task.running is True          # the raw fact: no finish record
    assert task.stopped("2026-08-20") is True


def test_a_job_given_today_is_left_alone():
    """A run started a minute ago genuinely is running, and calling it
    abandoned would be the same defect facing the other way."""
    _engine, task = a_half_run(given_at="2026-08-20")
    assert task.stopped("2026-08-20") is False


def test_a_finished_job_is_never_called_stopped():
    from vinzor.agents import RECIPES

    engine = a_delegating_workspace()
    task_id = engine.give_task(recipe_key=next(iter(RECIPES)),
                               actor="Aarav Sharma", given_at="2026-08-19")
    engine.run_task(task_id, when="2026-08-19")
    task = engine.state.runs.tasks[task_id]
    assert task.stopped("2026-08-20") is False


def test_the_screen_is_told_it_stopped_rather_than_that_it_is_working():
    """The card said "Working now -- Checking parties against the
    watchlists", in the present tense, and the browser polled for ever."""
    from vinzor.server import _task_json

    _engine, task = a_half_run()
    shown = _task_json(task, "2026-08-20")

    assert shown["running"] is False
    assert shown["stopped"] is True
    assert shown["now_doing"] == ""
    assert "stopped before it finished" in shown["outcome"]
    assert "Start it again" in shown["outcome"]


def test_a_reader_with_no_date_is_told_the_raw_fact_and_nothing_invented():
    """``_task_json`` without a date cannot know, and says nothing it cannot
    support."""
    from vinzor.server import _task_json

    _engine, task = a_half_run()
    shown = _task_json(task)
    assert shown["stopped"] is False
    assert shown["running"] is True


def test_the_workspace_can_list_what_was_left_mid_flight():
    engine, task = a_half_run()
    assert [t.task_id for t in engine.state.runs.stopped("2026-08-20")] == [
        task.task_id]
    assert engine.state.runs.stopped("2026-08-19") == ()


# -- what a tool is handed ---------------------------------------------------
#
# "An agent cannot settle a file" rested on nothing. `run_task` handed each
# tool the whole engine, and `decide`'s `actor` is a free string the fold
# checks against the *payload*, never against the caller. A tenth tool
# dropped into `agents.TOOLS` calling
# `engine.decide(actor="Meera Nair", role=AML_OFFICER, ...)` settled three
# files from inside a run -- permanently, attributed to an officer who never
# touched them, and a replay agreed.
#
# The guard the product cited against exactly this iterates `ask.TOOLS`, the
# *assistant's* registry. A write-capable tool inserted into `agents.TOOLS`
# passed both of its tests untouched. Across the whole suite, zero tests
# imported `vinzor.agents` or `vinzor.planning` at all -- 744 lines with
# nothing on them.
#
# The safety was real and it was a coincidence: nine hand-written functions
# happening not to write. It is structural now.


def test_a_tool_is_handed_a_workspace_it_cannot_change():
    from vinzor.agents import ReadOnly, ToolsCannotWrite

    engine = a_delegating_workspace()
    view = ReadOnly(engine)

    assert view.state is engine.state
    assert len(view.log) == len(engine.log)

    for way_in in ("ingest", "decide", "enroll", "record_filing",
                   "notice_received", "observe_deadlines", "confirm_minimum"):
        with pytest.raises(ToolsCannotWrite):
            getattr(view, way_in)


def test_the_log_it_is_handed_cannot_be_appended_to():
    from vinzor.agents import ReadOnly, ToolsCannotWrite

    view = ReadOnly(a_delegating_workspace())
    assert list(view.log)                      # readable
    with pytest.raises(ToolsCannotWrite):
        view.log.append


def test_it_is_an_allowlist_so_a_new_way_of_writing_is_refused_by_default():
    """A blocklist has to be remembered every time the engine grows a method.
    This does not."""
    from vinzor.agents import ReadOnly, ToolsCannotWrite

    view = ReadOnly(a_delegating_workspace())
    with pytest.raises(ToolsCannotWrite):
        view.some_method_added_next_year


def test_a_tool_that_tried_to_settle_a_file_would_be_refused():
    """The exact route that worked. It is a step that failed now, recorded
    as one, rather than three permanent approvals."""
    from vinzor.agents import TOOLS, Found, Tool, FOUND_SOMETHING

    def settles(engine, **rest):
        from vinzor.model import Outcome, Role

        for case in engine.queue()[:3]:
            engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                          actor="Meera Nair", role=Role.AML_OFFICER,
                          decided_at=WHEN, rationale="Cleared by the machine.")
        return Found(headline="3 files settled", how=FOUND_SOMETHING)

    from vinzor.agents import ReadOnly, ToolsCannotWrite
    from vinzor.model import EntityKind

    engine = a_delegating_workspace()
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"kind": EntityKind.PERSON.value,
                           "name": "A Listed Person", "attributes": {}})
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"matched": True, "list_type": "SANCTIONS",
                           "list_types": ["SANCTIONS"], "rule": "match",
                           "alert_id": "os:x", "basis": {}})
    assert engine.queue(), "nothing to settle, so nothing is being tested"

    with pytest.raises(ToolsCannotWrite):
        settles(ReadOnly(engine))
    assert not [e for e in engine.log
                if e.event_type is EventType.CASE_DECIDED]


def test_every_shipped_tool_still_works_through_it():
    """A boundary that breaks the nine real tools is not a boundary, it is a
    regression. All five recipes run end to end."""
    from vinzor.agents import RECIPES
    from vinzor.server import open_workspace

    engine = open_workspace(None, demo=True)
    for key in RECIPES:
        task_id = engine.give_task(recipe_key=key, actor="Meera Nair",
                                   given_at=WHEN, party="per_0002")
        engine.run_task(task_id, when=WHEN, party="per_0002")
        task = engine.state.runs.tasks[task_id]
        broke = [step.headline for step in task.plan if step.how == "failed"]
        assert broke == [], f"{key}: {broke}"


def test_running_every_agent_tool_writes_nothing():
    """The behavioural half, over the *agents'* registry. The one the
    product cited iterates the assistant's."""
    from vinzor.agents import TOOLS, ReadOnly
    from vinzor.server import open_workspace

    engine = open_workspace(None, demo=True)
    before = len(engine.log)
    for name, tool in TOOLS.items():
        try:
            tool.run(ReadOnly(engine), today=WHEN, party="per_0002")
        except Exception:
            # A tool that cannot run here has still not written anything,
            # which is the only thing this test is about.
            pass
    assert len(engine.log) == before


def test_no_agent_tool_names_a_write_path_in_its_source():
    """Belt as well as braces. The façade is what actually holds; this
    catches an obvious mistake at the point somebody writes it."""
    import inspect

    from vinzor.agents import TOOLS

    ways = (".ingest(", ".decide(", ".enroll(", ".log.append(",
            ".observe_deadlines(", ".record_filing(", ".notice_received(")
    offences = []
    for name, tool in TOOLS.items():
        body = inspect.getsource(tool.run)
        offences += [f"{name}: {way}" for way in ways if way in body]
    assert offences == []
