"""Escalation is a handover, not an answer.

Before this slice, ESCALATE closed the file: the queue emptied, nobody was
required to pick it up, and the officer who punted was free to settle their
own escalation. Examiners name both as findings -- the dead-end because an
unresolved alert left "referred" is an unresolved alert, and the self-settle
because four eyes that can belong to one person are two eyes. These tests
hold the new shape: the file stays open, the escalating officer is locked
out of it, and the reason written on any decision has to say something.
"""

from __future__ import annotations

import pytest

from vinzor.cases import (
    DecisionDenied,
    EscalationNeedsAnotherOfficer,
    thin_reason,
)
from vinzor.engine import project
from vinzor.model import CaseStatus, EventType, Outcome, Role

from conftest import WHEN, officer, person, screened
from test_briefing import JARGON, _strings


@pytest.fixture
def hit(engine):
    """One screening case with two enrolled officers and a senior."""
    officer(engine, "Meera Nair", Role.AML_OFFICER)
    officer(engine, "Aarav Shah", Role.COMPLIANCE)
    officer(engine, "Devika Rao", Role.SENIOR_MGMT)
    person(engine, "p1", "Vladimir Listed")
    screened(engine, "p1", "SANCTIONS")
    return engine


def only_case(engine):
    return engine.queue(open_only=False)[0]


def escalate(engine, by="Meera Nair", role=Role.AML_OFFICER):
    return engine.decide(
        case_id=only_case(engine).case_id, outcome=Outcome.ESCALATE,
        actor=by, role=role,
        rationale="The record cannot resolve this either way.",
        decided_at=WHEN,
    )


# -- the handover ------------------------------------------------------------


def test_an_escalated_file_stays_open_and_in_the_queue(hit):
    case = escalate(hit)
    assert case.status is CaseStatus.ESCALATED
    assert case.is_open, "an escalation is a handover, not an answer"
    assert case.decision is None, "nothing was settled"
    assert [c.case_id for c in hit.queue()] == [case.case_id]


def test_the_handover_itself_goes_on_the_record(hit):
    case = escalate(hit)
    assert case.escalations[-1]["by"] == "Meera Nair"
    assert case.escalations[-1]["why"] == \
        "The record cannot resolve this either way."
    assert case.evidence[-1].kind.value == "DECISION"
    assert case.evidence[-1].summary.startswith("ESCALATE")


def test_a_different_officer_settles_it(hit):
    case = escalate(hit)
    settled = hit.decide(
        case_id=case.case_id, outcome=Outcome.APPROVE, actor="Devika Rao",
        role=Role.SENIOR_MGMT,
        rationale="Different date of birth; not the same person.",
        decided_at=WHEN,
    )
    assert settled.status is CaseStatus.APPROVED
    assert settled.decision.actor == "Devika Rao"
    assert not settled.is_open


# -- four eyes ---------------------------------------------------------------


def test_the_escalating_officer_cannot_settle_their_own_escalation(hit):
    case = escalate(hit)
    with pytest.raises(EscalationNeedsAnotherOfficer):
        hit.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                   actor="Meera Nair", role=Role.AML_OFFICER,
                   rationale="On reflection this is a different person.",
                   decided_at=WHEN)
    assert case.is_open


def test_nor_can_they_escalate_it_twice(hit):
    case = escalate(hit)
    with pytest.raises(EscalationNeedsAnotherOfficer):
        escalate(hit)
    assert len(case.escalations) == 1


def test_a_second_escalation_locks_out_both_officers(hit):
    case = escalate(hit)
    hit.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
               actor="Aarav Shah", role=Role.COMPLIANCE,
               rationale="Needs a decision above my desk.", decided_at=WHEN)

    for name, role in (("Meera Nair", Role.AML_OFFICER),
                       ("Aarav Shah", Role.COMPLIANCE)):
        with pytest.raises(EscalationNeedsAnotherOfficer):
            hit.decide(case_id=case.case_id, outcome=Outcome.REJECT,
                       actor=name, role=role,
                       rationale="Confirmed as the listed party.",
                       decided_at=WHEN)

    settled = hit.decide(
        case_id=case.case_id, outcome=Outcome.REJECT, actor="Devika Rao",
        role=Role.SENIOR_MGMT, rationale="Confirmed as the listed party.",
        decided_at=WHEN)
    assert settled.status is CaseStatus.REJECTED
    assert len(settled.escalations) == 2


def test_a_refused_self_settle_writes_nothing_to_the_log(hit):
    case = escalate(hit)
    before = len(hit.log)
    with pytest.raises(EscalationNeedsAnotherOfficer):
        hit.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                   actor="Meera Nair", role=Role.AML_OFFICER,
                   rationale="Actually this is fine after all.",
                   decided_at=WHEN)
    assert len(hit.log) == before


def test_a_forged_self_settle_is_refused_on_replay_too(hit):
    """The fold enforces it as well as the command: a decision written
    straight into the log by the escalating officer fails on every rebuild,
    so the guard cannot be bypassed by whoever holds the database file."""
    case = escalate(hit)
    hit.log.append(
        event_type=EventType.CASE_DECIDED,
        subject=case.subject,
        occurred_at=WHEN,
        actor="Meera Nair",
        payload={"case_id": case.case_id, "outcome": "APPROVE",
                 "role": "AML_OFFICER", "rationale": "Settling my own file."},
    )
    with pytest.raises(EscalationNeedsAnotherOfficer):
        project(hit.log)


def test_escalation_state_survives_a_rebuild(hit):
    case = escalate(hit)
    rebuilt = hit.rebuild().casebook.get(case.case_id)
    assert rebuilt.status is CaseStatus.ESCALATED
    assert rebuilt.is_open
    assert rebuilt.escalations == case.escalations


# -- reasons that say something ----------------------------------------------


@pytest.mark.parametrize("rationale", [
    "ok", "checked", "Looks fine.", "No issues found", "as discussed",
    "cleared", "x", "yes", "reviewed and cleared",
])
def test_a_reason_that_says_nothing_is_refused(hit, rationale):
    case = only_case(hit)
    before = len(hit.log)
    with pytest.raises(ValueError, match="says nothing"):
        hit.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                   actor="Meera Nair", role=Role.AML_OFFICER,
                   rationale=rationale, decided_at=WHEN)
    assert case.is_open
    assert len(hit.log) == before


@pytest.mark.parametrize("rationale", [
    "Different birth dates entirely.",
    "Same passport number; confirmed match.",
    "Referring to the Principal Officer.",
])
def test_a_short_reason_that_says_something_passes(hit, rationale):
    case = only_case(hit)
    hit.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
               actor="Meera Nair", role=Role.AML_OFFICER,
               rationale=rationale, decided_at=WHEN)
    assert not case.is_open


def test_thin_reason_grades_the_words_not_the_punctuation():
    assert thin_reason("  OK!!  ")
    assert thin_reason("No issues found.")
    assert not thin_reason("Different birth dates entirely")
    assert thin_reason("")
    assert thin_reason(None)


# -- reason codes ------------------------------------------------------------


def test_the_picked_reason_code_is_on_the_decision_and_in_the_log(hit):
    case = only_case(hit)
    hit.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
               actor="Meera Nair", role=Role.AML_OFFICER,
               rationale="Date of birth differs by nine years.",
               decided_at=WHEN, reason_code="different-birth")
    assert case.decision.reason_code == "different-birth"
    event = next(e for e in hit.log
                 if e.event_type is EventType.CASE_DECIDED)
    assert event.payload["reason_code"] == "different-birth"


def test_a_decision_without_a_code_is_still_a_decision(hit):
    """The code is countable structure on top of the written reason, never a
    second gate: the free-text reason is what carries the substance."""
    case = only_case(hit)
    hit.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
               actor="Meera Nair", role=Role.AML_OFFICER,
               rationale="Date of birth differs by nine years.",
               decided_at=WHEN)
    assert case.decision.reason_code == ""


def test_a_code_this_system_does_not_offer_is_refused_not_cut(hit):
    """This test used to assert the opposite -- that a 200-character code was
    stored, cut to forty. Cutting writes a value nobody chose onto a
    permanent record, and the codes exist so that reasons can be *counted*;
    a count over invented values counts nothing. Refused now, with the
    remedy in the sentence."""
    case = only_case(hit)
    with pytest.raises(ValueError) as refusal:
        hit.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                   actor="Meera Nair", role=Role.AML_OFFICER,
                   rationale="Date of birth differs by nine years.",
                   decided_at=WHEN, reason_code="q" * 200)
    assert "Pick one from the list" in str(refusal.value)
    assert case.decision is None


def test_a_code_belonging_to_a_different_outcome_is_refused(hit):
    """``same-party`` is the REJECT-only code captioned "Confirmed as the
    same party". It was accepted and recorded against an APPROVE."""
    case = only_case(hit)
    with pytest.raises(ValueError) as refusal:
        hit.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                   actor="Meera Nair", role=Role.AML_OFFICER,
                   rationale="Date of birth differs by nine years.",
                   decided_at=WHEN, reason_code="same-party")
    assert "not a reason this system offers for approve" in str(refusal.value)


def test_a_code_the_screen_offers_is_recorded_whole(hit):
    case = only_case(hit)
    hit.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
               actor="Meera Nair", role=Role.AML_OFFICER,
               rationale="Date of birth differs by nine years.",
               decided_at=WHEN, reason_code="different-birth")
    assert case.decision.reason_code == "different-birth"


def test_every_code_the_screen_offers_is_one_the_engine_accepts():
    """Derived from one list rather than typed twice, so the two cannot
    drift into disagreeing about what an officer may pick."""
    from vinzor.briefing import REASON_CODES, SCREENING_REASONS

    for choice in SCREENING_REASONS:
        assert choice.code in REASON_CODES[choice.when]


# -- what the reader sees ----------------------------------------------------


def test_a_name_check_offers_the_reason_checklist(hit):
    from vinzor.briefing import case_file

    file = case_file(hit, only_case(hit).case_id)
    assert file.reasons, "a name check without its checklist"
    assert {r.when for r in file.reasons} == {"APPROVE", "REJECT", "ESCALATE"}
    for choice in file.reasons:
        assert choice.label[0].isupper()
        assert choice.code == choice.code.lower()


def test_every_outcome_keeps_a_way_out_of_the_list(hit):
    """A fixed list that claims to be exhaustive teaches people to pick the
    nearest wrong answer, which is worse than no list."""
    from vinzor.briefing import case_file

    file = case_file(hit, only_case(hit).case_id)
    for when in ("APPROVE", "REJECT", "ESCALATE"):
        assert any(r.code == "another-reason" for r in file.reasons
                   if r.when == when)


def test_the_case_page_says_who_passed_it_up_and_why(hit):
    from vinzor.briefing import case_file

    case = escalate(hit)
    file = case_file(hit, case.case_id, today="2026-08-16")
    assert "Meera Nair passed this file up" in file.escalated
    assert "cannot resolve this either way" in file.escalated
    assert "different officer" in file.escalated
    assert file.settled == "", "nothing was settled"


def test_an_unescalated_file_carries_no_handover_line(hit):
    from vinzor.briefing import case_file

    file = case_file(hit, only_case(hit).case_id)
    assert file.escalated == ""


def test_the_timeline_tells_a_handover_from_a_settlement(hit):
    from vinzor.briefing import case_file

    case = escalate(hit)
    file = case_file(hit, case.case_id, today="2026-08-16")
    assert any("passed this file up" in moment.what
               for moment in file.timeline)
    assert not any("settled this file" in moment.what
                   for moment in file.timeline)


def test_nothing_new_speaks_jargon(hit):
    """The checklist labels, the handover line and the refusal messages all
    reach a reader; the sweep that guards every other surface guards these."""
    import re

    from vinzor.briefing import MESSAGES, case_file

    case = escalate(hit)
    file = case_file(hit, case.case_id, today="2026-08-16")
    texts = [(path, text) for path, text in _strings(file, "case_file")]
    texts += [(f"messages.{key}", MESSAGES[key])
              for key in ("four_eyes", "reason_too_thin")]

    offences = []
    for path, text in texts:
        for pattern, what in JARGON:
            found = re.search(pattern, text)
            if found:
                offences.append(f"{path}: {what} ({found.group(0)!r})")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


# -- clause 5.5(b)(iii): senior management approves a PEP -------------------


@pytest.fixture
def pep(engine):
    """One politically exposed person, waiting on a decision."""
    officer(engine, "Meera Nair", Role.AML_OFFICER)
    officer(engine, "Aarav Shah", Role.COMPLIANCE)
    officer(engine, "Devika Rao", Role.SENIOR_MGMT)
    person(engine, "p1", "Kwame Mensah")
    screened(engine, "p1", "PEP")
    return engine


@pytest.mark.parametrize("name,role", [("Meera Nair", Role.AML_OFFICER),
                                       ("Aarav Shah", Role.COMPLIANCE)])
def test_no_officer_below_senior_management_may_clear_a_pep(pep, name, role):
    """Clause 5.5(b)(iii): a Regulated Entity shall obtain approval from
    its Senior Management before opening an account of a PEP. Clearing the
    match is that approval in practice."""
    from vinzor.cases import SeniorManagementMustApprove

    case = only_case(pep)
    before = len(pep.log)
    with pytest.raises(SeniorManagementMustApprove):
        pep.decide(case_id=case.case_id, outcome=Outcome.APPROVE, actor=name,
                   role=role,
                   rationale="Different date of birth; not the same person.",
                   decided_at=WHEN)
    assert case.is_open
    assert len(pep.log) == before, "a refused decision writes nothing"


def test_senior_management_may_clear_a_pep(pep):
    case = only_case(pep)
    settled = pep.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                         actor="Devika Rao", role=Role.SENIOR_MGMT,
                         rationale="Different date of birth; a false positive.",
                         decided_at=WHEN)
    assert settled.status is CaseStatus.APPROVED
    assert settled.decision.actor == "Devika Rao"


@pytest.mark.parametrize("outcome", [Outcome.REJECT, Outcome.ESCALATE])
def test_stopping_or_passing_up_a_pep_needs_no_seniority(pep, outcome):
    """A rule that made refusing business harder than accepting it would
    have the incentive exactly backwards."""
    case = only_case(pep)
    pep.decide(case_id=case.case_id, outcome=outcome, actor="Meera Nair",
               role=Role.AML_OFFICER,
               rationale="The papers do not resolve this either way.",
               decided_at=WHEN)
    assert case.status in (CaseStatus.REJECTED, CaseStatus.ESCALATED)


def test_a_sanctions_hit_is_not_subject_to_the_pep_rule(engine):
    """The clause is about politically exposed persons. Applying it to
    every screening file would be inventing a control the rules do not
    ask for."""
    officer(engine, "Meera Nair", Role.AML_OFFICER)
    person(engine, "p1", "Vladimir Listed")
    screened(engine, "p1", "SANCTIONS")

    case = only_case(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  rationale="Different date of birth; not the same person.",
                  decided_at=WHEN)
    assert case.status is CaseStatus.APPROVED


def test_a_forged_junior_clearance_of_a_pep_fails_on_replay(pep):
    """Enforced on the fold as well as the command, so a clearance written
    straight into the log fails every replay rather than standing because
    nobody looked again."""
    from vinzor.cases import SeniorManagementMustApprove

    case = only_case(pep)
    pep.log.append(
        event_type=EventType.CASE_DECIDED,
        subject=case.subject,
        occurred_at=WHEN,
        actor="Meera Nair",
        payload={"case_id": case.case_id, "outcome": "APPROVE",
                 "role": "AML_OFFICER",
                 "rationale": "Cleared on my own authority."},
    )
    with pytest.raises(SeniorManagementMustApprove):
        project(pep.log)


def test_whether_a_file_is_about_a_pep_is_read_off_the_record(pep):
    """Read from the evidence the policy recorded rather than recomputed,
    so a later change to how lists are classified cannot retrospectively
    make somebody a PEP who was not one when the officer decided."""
    from vinzor.cases import is_pep

    assert is_pep(only_case(pep))


def test_a_close_associate_needs_senior_approval_too(engine):
    """Clause 5.5 Guidance Note (3): relationships with relatives and close
    associates carry similar risks, and the measures applied to PEPs should
    also apply to them -- senior management approval among them."""
    from vinzor.cases import SeniorManagementMustApprove

    officer(engine, "Meera Nair", Role.AML_OFFICER)
    officer(engine, "Devika Rao", Role.SENIOR_MGMT)
    person(engine, "p1", "Amara Mensah")
    screened(engine, "p1", "PEP_ASSOCIATE")

    case = only_case(engine)
    with pytest.raises(SeniorManagementMustApprove):
        engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                      actor="Meera Nair", role=Role.AML_OFFICER,
                      rationale="Different date of birth; not the same person.",
                      decided_at=WHEN)

    settled = engine.decide(
        case_id=case.case_id, outcome=Outcome.APPROVE, actor="Devika Rao",
        role=Role.SENIOR_MGMT,
        rationale="Different date of birth; not the same person.",
        decided_at=WHEN)
    assert settled.status is CaseStatus.APPROVED


def test_a_wanted_match_does_not_need_senior_approval(engine):
    """Only clause 5.5 reserves a decision to senior management, and it is
    about public office. Extending it to every serious match would be
    inventing a control the rules do not ask for."""
    officer(engine, "Meera Nair", Role.AML_OFFICER)
    person(engine, "p1", "Somebody Wanted")
    screened(engine, "p1", "CRIMINAL")

    case = only_case(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  rationale="Different date of birth; not the same person.",
                  decided_at=WHEN)
    assert case.status is CaseStatus.APPROVED
