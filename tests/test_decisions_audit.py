"""The human gate, attacked from the side the command checks do not cover.

``cases.py`` says the gate is enforced twice on purpose, "so a guarantee that
holds in only one direction is a guarantee someone will eventually route
around". The two sides had drifted. ``engine.decide`` applied six checks and
the fold applied four; the two missing ones were *a Case is decided once* and
*a decision has a reason*.

Measured before this was closed, on a file an AML officer had rejected in
writing::

    honest decision            REJECTED | REJECT by Meera |
                               'Same passport number as the listed party.'
    command-side second        refused: already REJECTED; Cases are decided once
    raw second decision        ACCEPTED -> APPROVED APPROVE by Devika |
                               rationale ''
    CASE_DECIDED in the log    2
    rows on the audit tab      1

A written rejection of a sanctions match became an approval with an empty
reason, on every replay, on every machine, with no way to take it back -- and
the sheet headed "Every decision on this book" showed only the second one.

The same tables carried a name and no role, so the one thing an inspector
opens the pack to check -- that a politically exposed person was cleared by
senior management, per clause 5.5(b)(iii) -- was the one thing they could not
show. The product enforces that rule twice and then printed a pack that could
not evidence it.
"""

from __future__ import annotations

import pytest

from vinzor.cases import (DecisionAlreadyRecorded, DecisionNeedsAReason,
                          SeniorManagementMustApprove)
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType, Outcome, Role

WHEN = "2026-08-09"
A_REASON = "Same passport number as the listed party; not proceeding."


def a_book(topics=("sanction",)):
    """One officer, one senior manager, one open name check."""
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera", role=Role.AML_OFFICER, enrolled_at=WHEN)
    engine.enroll(name="Devika", role=Role.AML_OFFICER, enrolled_at=WHEN)
    engine.enroll(name="Rohan", role=Role.SENIOR_MGMT, enrolled_at=WHEN)
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"kind": EntityKind.PERSON.value,
                           "name": "Vladimir Listed", "attributes": {}})
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"matched": True, "list_type": "SANCTIONS",
                           "list_types": [t.upper() for t in topics],
                           "rule": "match", "alert_id": "os:x", "basis": {}})
    return engine, engine.queue()[0]


def _raw_decision(engine, case_id, **rest):
    """Straight past ``engine.decide`` and into the log -- the way migration
    code, an importer, or anyone with the file does it."""
    payload = {"case_id": case_id, "outcome": "APPROVE",
               "role": Role.AML_OFFICER.value, "rationale": "Fine by me."}
    payload.update(rest)
    engine.ingest(event_type=EventType.CASE_DECIDED, subject="p1",
                  occurred_at=WHEN, actor=payload.pop("actor", "Devika"),
                  payload=payload)


# -- decided once ------------------------------------------------------------


def test_a_settled_file_cannot_be_settled_again_by_writing_to_the_log():
    """The defect, exactly as it was reproduced."""
    engine, case = a_book()
    engine.decide(case_id=case.case_id, outcome=Outcome.REJECT, actor="Meera",
                  role=Role.AML_OFFICER, decided_at=WHEN, rationale=A_REASON)

    with pytest.raises(DecisionAlreadyRecorded):
        _raw_decision(engine, case.case_id)

    settled = engine.state.casebook.get(case.case_id)
    assert settled.status.value == "REJECTED"
    assert settled.decision.actor == "Meera"
    assert settled.decision.rationale == A_REASON


def test_the_refused_second_decision_never_reaches_the_log():
    """A rejected event that was appended anyway would leave a log that
    cannot be replayed, which is a worse outcome than the defect."""
    engine, case = a_book()
    engine.decide(case_id=case.case_id, outcome=Outcome.REJECT, actor="Meera",
                  role=Role.AML_OFFICER, decided_at=WHEN, rationale=A_REASON)
    before = len(list(engine.log))

    with pytest.raises(DecisionAlreadyRecorded):
        _raw_decision(engine, case.case_id)

    assert len(list(engine.log)) == before
    assert engine.verify()[0] is True


def test_a_passed_up_file_is_still_open_and_can_still_be_settled():
    """Escalation is a handover, not an answer. A decide-once rule that
    counted it as settled would stop every escalated file dead."""
    engine, case = a_book()
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera", role=Role.AML_OFFICER, decided_at=WHEN,
                  rationale="I cannot clear this one; passing it up.")
    settled = engine.decide(
        case_id=case.case_id, outcome=Outcome.APPROVE, actor="Rohan",
        role=Role.SENIOR_MGMT, decided_at=WHEN,
        rationale="Birthplace and passport differ from the listed person.")
    assert settled.status.value == "APPROVED"


def test_an_escalated_file_cannot_be_escalated_around_the_four_eyes_rule():
    """The guard that was already there, kept so the new one is not mistaken
    for the whole of the control."""
    engine, case = a_book()
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera", role=Role.AML_OFFICER, decided_at=WHEN,
                  rationale="I cannot clear this one; passing it up.")
    from vinzor.cases import EscalationNeedsAnotherOfficer

    with pytest.raises(EscalationNeedsAnotherOfficer):
        _raw_decision(engine, case.case_id, actor="Meera")


# -- a decision has a reason -------------------------------------------------


def test_a_decision_with_nothing_written_in_it_is_refused_by_the_fold():
    """A cleared sanctions match with an empty box is indistinguishable from
    one nobody looked at."""
    engine, case = a_book()
    with pytest.raises(DecisionNeedsAReason):
        _raw_decision(engine, case.case_id, rationale="")


def test_whitespace_is_not_a_reason():
    engine, case = a_book()
    with pytest.raises(DecisionNeedsAReason):
        _raw_decision(engine, case.case_id, rationale="  " + chr(10) + " ")




def test_a_thin_reason_still_only_fails_on_the_command_side():
    """Deliberate, not an oversight. ``thin_reason`` is a calibration of what
    counts as saying something, and calibrations move; hardening one into the
    fold would make a log written under yesterday's wording unreplayable
    tomorrow. Emptiness is different -- it will never become a reason."""
    engine, case = a_book()
    _raw_decision(engine, case.case_id, rationale="ok")
    assert engine.state.casebook.get(case.case_id).status.value == "APPROVED"

    engine, case = a_book()
    with pytest.raises(ValueError):
        engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                      actor="Meera", role=Role.AML_OFFICER, decided_at=WHEN,
                      rationale="ok")


def test_an_ordinary_decision_is_untouched():
    """A gate nobody can pass is a stopped queue, not a control."""
    engine, case = a_book()
    settled = engine.decide(case_id=case.case_id, outcome=Outcome.REJECT,
                            actor="Meera", role=Role.AML_OFFICER,
                            decided_at=WHEN, rationale=A_REASON)
    assert settled.status.value == "REJECTED"


# -- what the tables show ----------------------------------------------------


def _cleared_pep():
    """A sanctioned politically exposed person, cleared by the only role that
    may clear one."""
    engine, case = a_book(topics=("sanctions", "pep"))
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE, actor="Rohan",
                  role=Role.SENIOR_MGMT, decided_at=WHEN,
                  rationale="Birthplace and passport differ from the listed "
                            "person; I reviewed the designation myself.")
    return engine


def test_the_evidence_pack_shows_the_capacity_the_decider_acted_in():
    """Without it the pack cannot evidence clause 5.5(b)(iii), which is the
    one rule this product enforces twice."""
    from vinzor.evidence import decisions

    row = decisions(_cleared_pep())[0]
    assert row["who"] == "Rohan"
    assert row["as"] == "Senior management"


def test_the_pack_says_it_in_words_not_in_a_constant():
    """The reader never meets ``SENIOR_MGMT``."""
    from vinzor.evidence import pack

    page = pack(_cleared_pep(), workspace="A Firm", today=WHEN)["evidence.html"]
    assert "Senior management" in page
    assert "SENIOR_MGMT" not in page
    assert "Acting as" in page


def test_the_exported_audit_tab_carries_the_same_column():
    from vinzor.exporting import decisions_sheet

    sheet = decisions_sheet(_cleared_pep())
    assert "Acting as" in sheet.columns
    where = sheet.columns.index("Acting as")
    assert sheet.rows[0][where] == "Senior management"


def test_a_passed_up_file_shows_who_passed_it_up_and_in_what_capacity():
    """A handover is a decision too, and the sheet says "every decision"."""
    from vinzor.exporting import decisions_sheet

    engine, case = a_book()
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera", role=Role.AML_OFFICER, decided_at=WHEN,
                  rationale="I cannot clear this one; passing it up.")
    sheet = decisions_sheet(engine)
    where = sheet.columns.index("Acting as")
    assert [row[4] for row in sheet.rows] == ["Passed up"]
    assert sheet.rows[0][where] == "AML officer"


def test_a_role_nobody_has_a_word_for_is_shown_rather_than_dropped():
    from vinzor.briefing import role_word

    assert role_word("BOARD_MEMBER") == "Board member"
    assert role_word("") == ""


# -- the file that names the person settling it ------------------------------
#
# Four eyes was scoped to escalation alone: both guards compared the actor
# against `case.escalations` and against nothing else. Nothing compared the
# decider to the *subject*. A governance file names its subject in as many
# words -- "the compliance officer (Aarav Sharma) is not recorded as based in
# the IFSC" -- and Aarav Sharma could settle it, with no refusal and no
# marker, on a permanent record.


def a_governance_file():
    """The shape the rules actually produce: a required post, and the name of
    the person holding it, on the evidence."""
    from vinzor.model import Severity

    engine = Vinzor(EventLog())
    engine.enroll(name="Aarav Sharma", role=Role.COMPLIANCE, enrolled_at=WHEN)
    engine.enroll(name="Meera", role=Role.AML_OFFICER, enrolled_at=WHEN)
    engine.ingest(
        event_type=EventType.CASE_OPENED, subject="FME-1", occurred_at=WHEN,
        actor="system",
        payload={"case_id": "case_governance01", "case_type": "GOVERNANCE",
                 "policy_id": "POL_OFFICER_NOT_LOCAL",
                 "severity": Severity.HIGH.value,
                 "summary": "the compliance officer (Aarav Sharma) is not "
                            "recorded as based in the IFSC",
                 "detail": {"office": "COMPLIANCE_OFFICER",
                            "person": "Aarav Sharma"},
                 "source_seq": 1,
                 "citations": [], "rulepack": "test"})
    return engine, engine.state.casebook.get("case_governance01")


def test_the_person_a_file_is_about_cannot_settle_it():
    from vinzor.cases import TheFileIsAboutThem

    engine, case = a_governance_file()
    with pytest.raises(TheFileIsAboutThem) as refusal:
        engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                      actor="Aarav Sharma", role=Role.COMPLIANCE,
                      decided_at=WHEN,
                      rationale="I am based in the IFSC; the record is stale.")
    assert "another officer has to settle it" in str(refusal.value)


def test_the_fold_refuses_it_too():
    """The log cannot be rewritten, so a guard on the write path alone is
    not a guard."""
    from vinzor.cases import TheFileIsAboutThem

    engine, case = a_governance_file()
    with pytest.raises(TheFileIsAboutThem):
        engine.ingest(event_type=EventType.CASE_DECIDED, subject="FME-1",
                      occurred_at=WHEN, actor="Aarav Sharma",
                      payload={"case_id": case.case_id, "outcome": "APPROVE",
                               "role": Role.COMPLIANCE.value,
                               "rationale": "I am based in the IFSC."})


def test_anybody_else_can_still_settle_it():
    """A gate nobody can pass is a stopped queue, not a control."""
    engine, case = a_governance_file()
    settled = engine.decide(
        case_id=case.case_id, outcome=Outcome.APPROVE, actor="Meera",
        role=Role.AML_OFFICER, decided_at=WHEN,
        rationale="Checked the lease and the visa; he is based in the IFSC.")
    assert settled.status.value == "APPROVED"


def test_a_customer_file_is_untouched():
    """Customer files name an entity id, not a person, and adding a
    name-matching rule that fired on those would stop ordinary work."""
    engine, case = a_book()
    settled = engine.decide(
        case_id=case.case_id, outcome=Outcome.REJECT, actor="Meera",
        role=Role.AML_OFFICER, decided_at=WHEN, rationale=A_REASON)
    assert settled.status.value == "REJECTED"


def test_an_unnamed_actor_is_not_everybody():
    from vinzor.cases import names

    _engine, case = a_governance_file()
    assert names(case, "Aarav Sharma") is True
    assert names(case, "  aarav sharma ") is True
    assert names(case, "") is False
    assert names(case, "Meera") is False
