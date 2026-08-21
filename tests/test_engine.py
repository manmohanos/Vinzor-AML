"""The human gate, and the promise that state is nothing but a replay."""

from __future__ import annotations

import pytest

from vinzor.cases import (DecisionDenied, EscalationNeedsAnotherOfficer,
                          SeniorManagementMustApprove, UnknownCase)
from vinzor.engine import project
from vinzor.model import CaseStatus, EventType, Outcome, Role

from conftest import WHEN, company, officer, person, screened


#: One enrolled person per deciding role, so tests pick the right actor.
DECIDERS = {
    Role.COMPLIANCE: "aarav",
    Role.AML_OFFICER: "meera",
    Role.SENIOR_MGMT: "rohan",
}


def _one_open_case(engine):
    for name, role in (("aarav", Role.COMPLIANCE), ("meera", Role.AML_OFFICER),
                       ("rohan", Role.SENIOR_MGMT)):
        officer(engine, name, role)
    person(engine, "p1", "Alice")
    return screened(engine, "p1", "SANCTIONS").cases[0]


# -- the human gate --------------------------------------------------------


@pytest.mark.parametrize("role", [Role.COMPLIANCE, Role.AML_OFFICER, Role.SENIOR_MGMT])
def test_a_human_in_a_deciding_role_can_close_a_case(engine, role):
    case = _one_open_case(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                  actor=DECIDERS[role], role=role,
                  rationale="Reviewed, false positive.", decided_at=WHEN)
    assert case.status is CaseStatus.APPROVED


@pytest.mark.parametrize("role", [Role.AI, Role.VIEWER, Role.SYSTEM])
def test_no_one_else_can(engine, role):
    """Even *enrolled* as AI or viewer, closing a Case is impossible."""
    case = _one_open_case(engine)
    officer(engine, "bot", role)  # enrolled, and still denied
    with pytest.raises(DecisionDenied):
        engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE, actor="bot",
                      role=role, rationale="Looks fine.", decided_at=WHEN)
    assert case.status is CaseStatus.OPEN


def test_an_unenrolled_person_cannot_decide_whatever_role_they_claim(engine):
    """The other half of the gate: a deciding role is not enough.

    Who may decide is workspace data, recorded by enrolment events -- not
    an argument a caller gets to assert.
    """
    case = _one_open_case(engine)
    with pytest.raises(DecisionDenied, match="not enrolled"):
        engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                      actor="intruder", role=Role.COMPLIANCE,
                      rationale="Let me in.", decided_at=WHEN)
    assert case.status is CaseStatus.OPEN


def test_a_refused_decision_writes_nothing_to_the_log(engine):
    case = _one_open_case(engine)
    before = len(engine.log)
    with pytest.raises(DecisionDenied):
        engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE, actor="bot",
                      role=Role.AI, rationale="Looks fine.", decided_at=WHEN)
    assert len(engine.log) == before


def test_a_decision_requires_a_rationale(engine):
    case = _one_open_case(engine)
    with pytest.raises(ValueError, match="rationale"):
        engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE, actor="aarav",
                      role=Role.COMPLIANCE, rationale="   ", decided_at=WHEN)


def test_a_case_is_decided_once(engine):
    case = _one_open_case(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE, actor="aarav",
                  role=Role.COMPLIANCE, rationale="Reviewed; a false positive.",
                  decided_at=WHEN)
    with pytest.raises(ValueError, match="already"):
        engine.decide(case_id=case.case_id, outcome=Outcome.REJECT, actor="meera",
                      role=Role.AML_OFFICER, rationale="Changed my mind.",
                      decided_at=WHEN)


def test_deciding_an_unknown_case_fails(engine):
    officer(engine, "aarav", Role.COMPLIANCE)
    with pytest.raises(UnknownCase):
        engine.decide(case_id="case_nope", outcome=Outcome.APPROVE, actor="aarav",
                      role=Role.COMPLIANCE, rationale="x", decided_at=WHEN)


def test_a_forged_decision_is_refused_on_replay_too(engine):
    """Bypassing the command path does not buy an AI a decision.

    Writing the event straight to the log skips ``engine.decide``. The
    fold still refuses it -- the gate holds on read as well as on write.
    """
    case = _one_open_case(engine)
    engine.log.append(
        event_type=EventType.CASE_DECIDED,
        subject=case.subject,
        occurred_at=WHEN,
        actor="bot",
        payload={"case_id": case.case_id, "outcome": "APPROVE",
                 "role": "AI", "rationale": "Approved myself."},
    )
    with pytest.raises(DecisionDenied):
        project(engine.log)


def test_a_forged_enrolment_claim_is_refused_on_replay(engine):
    """A forged decision claiming a deciding role fails without a forged
    enrolment to back it -- and that would sit in the audit trail too.
    """
    case = _one_open_case(engine)
    engine.log.append(
        event_type=EventType.CASE_DECIDED,
        subject=case.subject,
        occurred_at=WHEN,
        actor="intruder",
        payload={"case_id": case.case_id, "outcome": "APPROVE",
                 "role": "COMPLIANCE", "rationale": "Nothing to see."},
    )
    with pytest.raises(DecisionDenied, match="not enrolled"):
        project(engine.log)


def test_a_decided_case_leaves_the_queue_but_keeps_its_history(engine):
    case = _one_open_case(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.REJECT, actor="meera",
                  role=Role.AML_OFFICER,
                  rationale="Same party as the listed record.", decided_at=WHEN)

    assert engine.queue() == []
    assert len(engine.queue(open_only=False)) == 1
    assert case.status is CaseStatus.REJECTED
    assert case.decision.rationale == "Same party as the listed record."
    assert case.evidence[-1].kind.value == "DECISION"


# -- recurrence after a Case is decided -------------------------------------


def _licensed_fme(engine):
    """A staffed, licensed FME -- so the only Case in play is the one the
    test is about, not a governance Case for an empty office.

    Offices are appointed before the grant, as Regulation 7 requires: no
    category is required yet, so appointing early opens no vacancy Case that
    the grant would then have to fill.
    """
    company(engine, "fme", "Acme FME")
    engine.ingest(
        event_type=EventType.OFFICE_APPOINTED, subject="fme", occurred_at=WHEN,
        payload={"office": "PRINCIPAL_OFFICER", "person": "Rohan Kapoor",
                 "based_in_ifsc": True},
    )
    engine.ingest(
        event_type=EventType.OFFICE_APPOINTED, subject="fme", occurred_at=WHEN,
        payload={"office": "COMPLIANCE_OFFICER", "person": "Meera Nair",
                 "based_in_ifsc": True},
    )
    engine.ingest(
        event_type=EventType.LICENCE_GRANTED, subject="fme", occurred_at=WHEN,
        payload={"category": "REGISTERED_NON_RETAIL", "number": "TEST-1"},
    )


def _undertake_retail_scheme(engine):
    return engine.ingest(
        event_type=EventType.ACTIVITY_UNDERTAKEN, subject="fme", occurred_at=WHEN,
        payload={"activity": "RETAIL_SCHEME"},
    )


def test_a_breach_that_recurs_after_the_case_is_closed_opens_a_new_case(engine):
    """``finding_specs`` used to treat any *existing* case_id as "extend this
    Case", with no check that it was still open. A breach that recurred after
    the Case was approved silently folded onto the closed Case as one more
    piece of evidence and never came back to the officer's queue -- ``r2.cases``
    was empty and the recurrence was invisible to ``engine.queue()``.
    """
    officer(engine, "Meera Nair", Role.AML_OFFICER)
    _licensed_fme(engine)
    first = _undertake_retail_scheme(engine)
    case_id = first.cases[0].case_id

    engine.decide(case_id=case_id, outcome=Outcome.APPROVE, actor="Meera Nair",
                  role=Role.AML_OFFICER, rationale="Reviewed; a false positive.", decided_at=WHEN)

    second = _undertake_retail_scheme(engine)  # the same breach, again

    assert second.cases, "the recurrence must open a Case, not disappear"
    reopened = second.cases[0]
    assert reopened.case_id != case_id, "must not fold onto the closed Case"
    assert reopened.is_open
    assert [c.case_id for c in engine.queue()] == [reopened.case_id]

    # The original Case is untouched: still approved, and its evidence is
    # exactly what it was when it was decided -- the recurrence's finding
    # was not written onto it. (One RULE entry from the original breach, one
    # DECISION entry from approving it -- nothing from the recurrence.)
    original = engine.state.casebook.get(case_id)
    assert original.status is CaseStatus.APPROVED
    assert len(original.evidence) == 2
    assert [e.kind.value for e in original.evidence] == ["RULE", "DECISION"]


def test_a_still_open_case_keeps_being_extended_as_before(engine):
    """The fix must not touch the ordinary path: while a Case is still open,
    the same breach recurring is more evidence on the one Case, not a new one.
    """
    _licensed_fme(engine)
    first = _undertake_retail_scheme(engine)
    case_id = first.cases[0].case_id

    second = _undertake_retail_scheme(engine)

    assert second.cases[0].case_id == case_id
    assert len(engine.state.casebook.get(case_id).evidence) == 2
    assert len(engine.state.casebook) == 1


def test_the_reopened_case_id_survives_a_rebuild(engine):
    """The new id after a recurrence must be derived from the log, not from
    anything positional -- so a rebuild reaches exactly the same id, and a
    future ``CASE_DECIDED`` on it still resolves on replay.
    """
    officer(engine, "Meera Nair", Role.AML_OFFICER)
    _licensed_fme(engine)
    case_id = _undertake_retail_scheme(engine).cases[0].case_id
    engine.decide(case_id=case_id, outcome=Outcome.APPROVE, actor="Meera Nair",
                  role=Role.AML_OFFICER, rationale="Reviewed; a false positive.", decided_at=WHEN)
    reopened_id = _undertake_retail_scheme(engine).cases[0].case_id

    rebuilt = engine.rebuild()
    assert sorted(rebuilt.casebook.cases) == sorted(engine.state.casebook.cases)
    assert reopened_id in rebuilt.casebook.cases
    assert rebuilt.casebook.get(reopened_id).is_open


# -- replay ----------------------------------------------------------------


def test_live_state_equals_a_full_replay(engine):
    """The property the whole design rests on.

    There is one ``apply_event``; the live path and the rebuild path both use
    it, so these cannot drift apart without a test failing.
    """
    officer(engine, "aarav", Role.COMPLIANCE)
    person(engine, "p1", "Alice")
    person(engine, "p2", "Bob")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    screened(engine, "p2", "PEP", alert_id="alt_2")
    case = engine.queue()[0]
    engine.decide(case_id=case.case_id, outcome=Outcome.REJECT, actor="aarav",
                  role=Role.COMPLIANCE, rationale="Confirmed match with the listed record.", decided_at=WHEN)

    rebuilt = engine.rebuild()
    assert rebuilt.casebook.cases == engine.state.casebook.cases
    assert rebuilt.actors == engine.state.actors
    assert rebuilt.last_seq == engine.state.last_seq


def test_replaying_twice_gives_the_same_answer(engine):
    person(engine, "p1")
    screened(engine, "p1", "SANCTIONS")
    assert project(engine.log).casebook.cases == project(engine.log).casebook.cases


def test_case_ids_survive_a_rebuild(engine):
    """A decision references a Case id, so ids must not be positional."""
    person(engine, "p1")
    screened(engine, "p1", "SANCTIONS")
    before = sorted(engine.state.casebook.cases)
    assert sorted(engine.rebuild().casebook.cases) == before


def test_replay_never_runs_policies(engine, monkeypatch):
    """Replay is a pure fold. If it ever evaluates a rule, this explodes.

    This is what makes history immune to rule changes: what the system said
    is read back from the log, not recomputed by whatever the rules say today.
    """
    import vinzor.engine as engine_module

    _one_open_case(engine)

    def boom(*args, **kwargs):
        raise AssertionError("replay evaluated a policy")

    monkeypatch.setattr(engine_module, "evaluate", boom)
    rebuilt = engine.rebuild()
    assert rebuilt.casebook.cases == engine.state.casebook.cases


def test_history_survives_the_deletion_of_every_policy(engine):
    """The proof of the design: fold the same log with an EMPTY rulepack.

    Before findings were recorded as events, this exact experiment rewrote
    history -- a case the officer saw as CRITICAL replayed as LOW, citing
    amended clause text that did not exist when they decided.
    """
    case = _one_open_case(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.REJECT, actor="aarav",
                  role=Role.COMPLIANCE, rationale="Confirmed match with the listed record.", decided_at=WHEN)

    from vinzor.engine import Vinzor

    bare = Vinzor(engine.log, policies=())
    assert bare.state.casebook.cases == engine.state.casebook.cases
    survivor = bare.state.casebook.get(case.case_id)
    assert survivor.severity is case.severity
    assert survivor.evidence[0].citations == case.evidence[0].citations
    assert survivor.decision == case.decision


def test_a_fact_and_its_findings_are_one_transaction(engine):
    """The log never holds half a thought.

    A fact whose findings were lost to a crash would replay as a fact the
    rules never saw. Batch append is atomic: poison one spec and nothing at
    all is written.
    """
    import pytest as _pytest

    from vinzor.eventlog import EventLog

    log = EventLog()
    before = len(log)
    with _pytest.raises(ValueError):
        log.append_batch([
            {"event_type": "ENTITY_REGISTERED", "subject": "s",
             "occurred_at": WHEN, "actor": "system",
             "payload": {"kind": "PERSON", "name": "P"}},
            {"event_type": "NOT_A_REAL_EVENT", "subject": "s",
             "occurred_at": WHEN, "actor": "system", "payload": {}},
        ])
    assert len(log) == before
    assert log.verify() == (True, None)


def test_findings_are_stamped_with_the_rulepack_that_made_them(engine):
    from vinzor.model import EventType as ET
    from vinzor.policies import RULEPACK

    _one_open_case(engine)
    findings = [e for e in engine.log if e.event_type is ET.CASE_OPENED]
    assert findings
    assert all(e.payload["rulepack"] == RULEPACK for e in findings)


def test_a_reader_of_state_actors_is_not_disrupted_by_a_concurrent_enrolment(engine):
    """``apply_event`` used to mutate ``state.actors`` in place.

    server.py runs under ``ThreadingHTTPServer`` -- one thread per request --
    and reads ``engine.state.actors`` directly rather than through the
    lock-guarded ``Vinzor.actors()`` (so do briefing.py, screening.py,
    compare.py, __main__.py). A reader mid ``.items()`` on one thread, with
    an enrolment landing on another, used to blow up with "dictionary
    changed size during iteration" -- the same failure ``queue()`` was once
    fixed against, but for a caller this engine cannot force to take a lock.
    Folding now replaces the dict rather than mutating it, so a reader's
    already-fetched reference is a frozen snapshot no writer can disturb.
    """
    import threading

    stop = threading.Event()
    errors: list[Exception] = []

    def hammer_reads():
        while not stop.is_set():
            try:
                for _name, _entry in engine.state.actors.items():
                    pass
            except RuntimeError as exc:  # pragma: no cover - the bug, if back
                errors.append(exc)
                return

    reader = threading.Thread(target=hammer_reads)
    reader.start()
    try:
        for i in range(500):
            officer(engine, f"officer-{i}", Role.COMPLIANCE)
    finally:
        stop.set()
        reader.join(timeout=5)

    assert errors == []


def test_the_decision_is_in_the_log_not_beside_it(engine):
    """There is no separate audit store to fall out of step with."""
    case = _one_open_case(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE, actor="aarav",
                  role=Role.COMPLIANCE, rationale="Reviewed; a false positive.",
                  decided_at=WHEN)

    decisions = [e for e in engine.log if e.event_type is EventType.CASE_DECIDED]
    assert len(decisions) == 1
    assert decisions[0].actor == "aarav"
    assert decisions[0].payload["rationale"] == "Reviewed; a false positive."
    assert engine.verify() == (True, None)


# -- replay determinism, fuzzed rather than only over hand-picked scenarios -
#
# ``test_live_state_equals_a_full_replay`` above proves the property on one
# scripted scenario. Event-sourcing testing guidance (see the project's
# research for this pass) is explicit that a fold must be checked against
# adversarial input, not just the happy path a human thought to script --
# and this system's own design note names *out-of-order facts* as a real
# case: "a deadline passing enters as an observed event, exactly like a
# payment", and nothing says a payment must be recorded in the order it
# happened. This walks many random, independently-seeded event sequences --
# random entities, random ownership percentages and relations (including
# ones that close ownership cycles), random screenings and payments, random
# decisions, and dates picked with no regard for chronological order -- and
# checks live state equals a full replay after every one.


def _random_iso_date(rng):
    from datetime import date

    year = rng.randint(2019, 2029)
    month = rng.randint(1, 12)
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    day = rng.randint(1, [31, 29 if leap else 28, 31, 30, 31, 30,
                           31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day).isoformat()


def _assert_replay_matches_live(eng):
    from vinzor.engine import project

    rebuilt = project(eng.log)
    assert rebuilt.casebook.cases == eng.state.casebook.cases
    assert rebuilt.actors == eng.state.actors
    assert rebuilt.last_seq == eng.state.last_seq
    assert rebuilt.calendar.submitted == eng.state.calendar.submitted
    assert rebuilt.calendar.reported_late == eng.state.calendar.reported_late
    assert rebuilt.graph.entities == eng.state.graph.entities
    assert rebuilt.graph._owners_of == eng.state.graph._owners_of
    assert rebuilt.graph._controllers_of == eng.state.graph._controllers_of
    assert eng.verify()[0]


def _run_one_random_walk(seed: int, steps: int = 80) -> None:
    import random

    from vinzor.engine import Vinzor
    from vinzor.eventlog import EventLog
    from vinzor.model import EntityKind, EventType as ET, Relation

    rng = random.Random(seed)
    eng = Vinzor(EventLog())
    deciders = [("aarav", Role.COMPLIANCE), ("meera", Role.AML_OFFICER),
                ("rohan", Role.SENIOR_MGMT)]
    for name, role in deciders:
        eng.enroll(name=name, role=role, enrolled_at=_random_iso_date(rng))

    entities: list[str] = []
    counters = {"entity": 0, "alert": 0, "payment": 0}

    def register_entity():
        counters["entity"] += 1
        eid = f"ent_{counters['entity']}"
        kind = rng.choice(list(EntityKind))
        eng.ingest(event_type=ET.ENTITY_REGISTERED, subject=eid,
                   occurred_at=_random_iso_date(rng),
                   payload={"kind": kind.value, "name": eid, "attributes": {}})
        entities.append(eid)

    for _ in range(5):
        register_entity()

    for step in range(steps):
        choice = rng.random()
        if choice < 0.10 and len(entities) < 25:
            register_entity()
        elif choice < 0.40 and len(entities) >= 2:
            owner, owned = rng.sample(entities, 2)
            eng.ingest(
                event_type=ET.OWNERSHIP_DECLARED, subject=owned,
                occurred_at=_random_iso_date(rng),
                payload={"owner": owner, "owned": owned,
                         "percentage": round(rng.uniform(0, 100), 4),
                         "relation": rng.choice(list(Relation)).value},
            )
        elif choice < 0.60 and entities:
            counters["alert"] += 1
            eng.ingest(
                event_type=ET.SCREENING_COMPLETED, subject=rng.choice(entities),
                occurred_at=_random_iso_date(rng),
                payload={"list_type": rng.choice(["SANCTIONS", "PEP", "ADVERSE_MEDIA"]),
                         "matched": rng.choice([True, False]),
                         "alert_id": f"alt_{counters['alert']}"},
            )
        elif choice < 0.80 and entities:
            counters["payment"] += 1
            eng.ingest(
                event_type=ET.PAYMENT_RECEIVED, subject=rng.choice(entities),
                occurred_at=_random_iso_date(rng),
                payload={
                    "payment_id": f"pay_{counters['payment']}",
                    "payment_ref": f"TX-{counters['payment']}",
                    "amount": round(rng.uniform(1, 1_000_000), 2),
                    "currency": rng.choice(["USD", "INR", "EUR"]),
                    # Only the first of these is read by anything. The
                    # others are here so the walk keeps meeting labels the
                    # rules ignore, which is the state a real feed arrives
                    # in. Two rule names were dropped from this list on
                    # 21 August 2026 because the rules went: a generator
                    # naming rules that do not exist teaches the next reader
                    # that they do.
                    "anomaly": rng.choice([None, "SANCTIONED_PAYER",
                                           "A_LABEL_NOBODY_READS",
                                           "SOMETHING_UNRECOGNISED"]),
                },
            )
        else:
            queue = eng.queue()
            if queue:
                case = rng.choice(queue)
                name, role = rng.choice(deciders)
                outcome = rng.choice(list(Outcome))
                try:
                    eng.decide(case_id=case.case_id, outcome=outcome, actor=name,
                               role=role, rationale="fuzz-generated decision",
                               decided_at=_random_iso_date(rng))
                except EscalationNeedsAnotherOfficer:
                    pass  # the escalating officer was drawn again; a
                          # different officer must settle, which is the rule
                except SeniorManagementMustApprove:
                    pass  # a junior role was drawn to clear a politically
                          # exposed person, which clause 5.5(b)(iii) forbids

        if step % 10 == 9:
            _assert_replay_matches_live(eng)

    _assert_replay_matches_live(eng)


def test_live_state_equals_replay_across_many_random_event_sequences():
    """The core invariant, checked over many random walks instead of one script.

    80 seeds, each driving 80 random operations -- entities, ownership edges
    (including ones that close a cycle), screenings, payments and decisions,
    dated with no regard for chronological order -- with live state checked
    against a full replay every ten steps and at the end. A single scripted
    scenario cannot cover the combinations an adversarial or merely
    out-of-order feed could produce; this is that coverage.
    """
    for seed in range(80):
        _run_one_random_walk(seed)


# -- a finding names the rules that actually made it -------------------------


def test_an_injected_policy_pack_is_not_stamped_with_the_shipped_version():
    """engine read the module-level RULEPACK unconditionally, so a workspace
    running any other pack wrote the shipped pack's version onto findings the
    shipped pack never made -- unfixably, in an append-only log."""
    from vinzor.engine import Vinzor
    from vinzor.policies import POLICIES, RULEPACK, screening_hit

    assert Vinzor(policies=POLICIES).rulepack == RULEPACK
    assert Vinzor(policies=[screening_hit]).rulepack != RULEPACK


def test_the_same_custom_pack_always_stamps_the_same_way():
    """Replay must reach the same stamp it wrote."""
    from vinzor.engine import rulepack_of
    from vinzor.policies import screening_hit, payment_anomaly

    assert rulepack_of([screening_hit]) == rulepack_of([screening_hit])
    assert rulepack_of([screening_hit]) != rulepack_of([payment_anomaly])


def test_a_finding_records_the_pack_that_produced_it():
    from vinzor.engine import Vinzor
    from vinzor.model import EventType
    from vinzor.policies import screening_hit

    from conftest import person, screened

    custom = Vinzor(policies=[screening_hit])
    person(custom, "p1", "Alice")
    screened(custom, "p1", "SANCTIONS")
    opened = [e for e in custom.log if e.event_type is EventType.CASE_OPENED]
    assert opened
    assert opened[0].payload["rulepack"] == custom.rulepack


# -- a model may judge, never establish --------------------------------------


def test_the_rulepack_never_runs_over_a_model_authored_event(engine):
    """ingest evaluated every event identically, including the assistant's own
    DRAFT_PREPARED, and was inert only because none of the seven shipped
    policies happens to name that type. One policy that did, or one agent with
    a write-capable tool, and a model would have established a Finding -- the
    single thing the AI design exists to prevent. The human gate does not
    cover it: that stops a model closing a Case, not opening one.
    """
    from vinzor.engine import MODEL_AUTHORED, may_produce_findings
    from vinzor.model import Event, EventType

    draft = Event(seq=1, event_type=EventType.DRAFT_PREPARED, subject="p1",
                  occurred_at=WHEN, actor="assistant", payload={})
    assert EventType.DRAFT_PREPARED in MODEL_AUTHORED
    assert may_produce_findings(engine.state, draft) is False


def test_an_actor_enrolled_as_ai_cannot_produce_findings(engine):
    """Belt and braces beside the event-type check: an AI given any event type
    still establishes nothing."""
    from vinzor.engine import may_produce_findings
    from vinzor.model import Event, EventType, Role

    engine.enroll(name="the assistant", role=Role.AI, enrolled_at=WHEN)
    posing = Event(seq=1, event_type=EventType.SCREENING_COMPLETED, subject="p1",
                   occurred_at=WHEN, actor="the assistant", payload={})
    assert may_produce_findings(engine.state, posing) is False


def test_machine_minted_facts_about_the_world_still_produce_findings(engine):
    """The bar is model *judgement*, not automation. A deadline passing and a
    screening result are legitimate facts and must still open Cases."""
    from vinzor.engine import may_produce_findings
    from vinzor.model import Event, EventType

    for kind in (EventType.SCREENING_COMPLETED, EventType.FILING_OVERDUE,
                 EventType.PAYMENT_RECEIVED):
        fact = Event(seq=1, event_type=kind, subject="p1", occurred_at=WHEN,
                     actor="system", payload={})
        assert may_produce_findings(engine.state, fact) is True, kind


def test_a_recorded_draft_opens_no_case_even_if_a_policy_wants_it(engine):
    """End to end through ingest with a policy that deliberately fires on the
    assistant's own event. It must produce nothing."""
    from vinzor.engine import Vinzor
    from vinzor.model import EventType, Finding, Severity
    from vinzor.citations import cite

    from vinzor.policies import screening_hit

    def greedy(ctx):
        if ctx.event.event_type is not EventType.DRAFT_PREPARED:
            return ()
        return (Finding(policy_id="POL_GREEDY", case_type="SCREENING_HIT",
                        severity=Severity.CRITICAL, summary="from a model",
                        dedupe_key="greedy", citations=cite("5.9")),)

    # A real screening Case first, so the draft has something to attach to and
    # the only thing under test is whether the greedy policy gets to fire.
    v = Vinzor(policies=[screening_hit, greedy])
    person(v, "p1", "Alice")
    case = screened(v, "p1", "SANCTIONS").cases[0]
    before = len(v.queue())

    result = v.ingest(event_type=EventType.DRAFT_PREPARED, subject="p1",
                      occurred_at=WHEN, actor="assistant",
                      payload={"case_id": case.case_id,
                               "recommendation": "CANNOT_TELL"})

    assert result.cases == [], "a model authored this; it may establish nothing"
    assert len(v.queue()) == before
    assert not any(e.policy_id == "POL_GREEDY"
                   for c in v.queue(open_only=False) for e in c.evidence)


def test_payments_arriving_at_once_survive_concurrent_use(engine):
    """The server hands each request its own thread, and a projection is
    written on every ingest while the queue reads it. An earlier projection in
    this system turned 22 overdue filings into 73 permanent records under
    exactly this pressure, so no projection gets the benefit of the doubt.

    This used to hold the payment window, which was removed on 21 August 2026
    with the rules that read it. The property it was bought by is not about
    that window -- it is about payments arriving on many threads at once -- so
    it is pointed at the casebook and the actor table instead. Both are
    written on ingest, both are read on request threads, and both are still
    here.

    Every payment below comes from a party other than the investor, so each
    one opens a file and the casebook is genuinely being written to
    throughout, rather than the threads racing over a projection nothing
    touches.
    """
    import threading

    from vinzor.engine import project
    from vinzor.model import EntityKind, EventType

    for i in range(8):
        engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=f"p{i}",
                      occurred_at="2026-08-01",
                      payload={"kind": EntityKind.PERSON.value,
                               "name": f"P{i}", "attributes": {}})

    trouble: list = []

    def pay(n):
        try:
            for j in range(25):
                engine.ingest(
                    event_type=EventType.PAYMENT_RECEIVED, subject=f"p{n}",
                    occurred_at="2026-08-02",
                    payload={"payment_id": f"pay_{n}_{j}", "amount": 500.0,
                             "called_amount": 500.0, "currency": "USD",
                             "expected_currency": "USD",
                             "payer": "somebody_else"})
        except Exception as problem:            # noqa: BLE001 - reported below
            trouble.append(problem)

    def read():
        try:
            for _ in range(120):
                engine.queue()
                engine.actors()
        except Exception as problem:            # noqa: BLE001
            trouble.append(problem)

    threads = ([threading.Thread(target=pay, args=(i,)) for i in range(6)]
               + [threading.Thread(target=read) for _ in range(3)])
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not trouble, f"concurrent use raised: {trouble[:2]}"
    intact, why = engine.verify()
    assert intact, why

    # 6 threads x 25 payments, each from a third party, each its own file.
    assert len(engine.queue()) == 150

    # And the casebook a reader saw is the casebook a replay rebuilds.
    assert (sorted(engine.state.casebook.cases)
            == sorted(project(engine.log).casebook.cases))
