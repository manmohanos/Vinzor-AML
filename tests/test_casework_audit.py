"""The one hard permission boundary in the product, tested by walking past it.

Clause 5.5(b)(iii) reserves the clearance of a politically exposed person for
senior management. The product enforces it twice, on the command side and in
the fold, and both were verified to hold. **Both were asking the wrong
question.**

A watchlist match is filed under the most serious thing it is, because that
is what a file should be *called*: a sanctioned head of state is a sanctions
matter first, since that is the one that stops the money. The gate then read
that same single label to decide who may settle the file, and a sanctioned
head of state is not labelled PEP. Against the watchlist this product ships
with, **Vladimir Putin, Bashar Assad and Kim Jong-un all classify as
SANCTIONS and all three carry ``role.pep``** — so the highest-risk customers
an FME can meet were the ones the gate never fired on, and any officer could
clear them.

Measured on the local index, 20 August 2026: of 847 sanctioned persons
sampled, 160 also carried ``role.pep`` and 21 ``role.rca`` — **21.4% were
politically exposed and filed as sanctions**.

The product already held the fact it needed. ``role.pep`` was written to the
permanent record in the screening event's topics, and nothing read it. Every
kind is now recorded beside the headline one, and three readers were asking
the single value: the gate, the queue that routes an escalated file to senior
management, and the risk screen that decides whether an officer categorising
somebody is shown the guidance about public office at all.
"""

from __future__ import annotations

import pytest

from vinzor.cases import is_pep
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType, Outcome, Role
from vinzor.screening import Hit
from vinzor.whosework import waiting_on

WHEN = "2026-08-20"


def a_book(topics, name="A Head Of State"):
    """One party with one watchlist match carrying these topics."""
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera", role=Role.AML_OFFICER, enrolled_at=WHEN)
    engine.enroll(name="Rohan", role=Role.SENIOR_MGMT, enrolled_at=WHEN)
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"kind": EntityKind.PERSON.value, "name": name,
                           "attributes": {}})
    hit = Hit(entity_id="os:x", caption=name, score=1.0,
              topics=tuple(topics), datasets=("default",))
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"matched": True,
                           "list_type": hit.list_type or "WATCHLIST",
                           "list_types": list(hit.list_types) or ["WATCHLIST"],
                           "rule": "match", "alert_id": "os:x", "basis": {}})
    return engine, engine.queue()[0]


# -- the label is still the label --------------------------------------------


def test_a_sanctioned_head_of_state_is_still_filed_under_sanctions():
    """The triage was never wrong. A sanctions match is what stops the
    money, and calling the file something softer would be the opposite
    defect."""
    hit = Hit(entity_id="x", caption="A Head Of State", score=1.0,
              topics=("role.pep", "sanction"), datasets=())
    assert hit.list_type == "SANCTIONS"


def test_but_every_kind_the_match_carries_is_recorded():
    hit = Hit(entity_id="x", caption="A Head Of State", score=1.0,
              topics=("role.pep", "sanction"), datasets=())
    assert hit.list_types == ("SANCTIONS", "PEP")


def test_a_match_that_is_only_one_thing_is_only_one_thing():
    hit = Hit(entity_id="x", caption="A Company", score=1.0,
              topics=("debarment",), datasets=())
    assert hit.list_types == ("DEBARRED",)
    assert hit.list_type == "DEBARRED"


# -- the gate ----------------------------------------------------------------


def test_a_sanctioned_politically_exposed_person_cannot_be_cleared_by_an_officer():
    """The defect. Before this, an AML officer cleared the file and the
    permanent record showed a junior officer's clearance of a head of
    state."""
    engine, case = a_book(("sanction", "role.pep"))
    assert is_pep(case) is True

    from vinzor.cases import SeniorManagementMustApprove

    with pytest.raises(SeniorManagementMustApprove):
        engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                      actor="Meera", role=Role.AML_OFFICER, decided_at=WHEN,
                      rationale="Our investor is a different person of the "
                                "same name; passport and birthplace differ.")


def test_senior_management_can_still_clear_one():
    """A gate nobody can pass is a stopped queue, not a control."""
    engine, case = a_book(("sanction", "role.pep"))
    settled = engine.decide(
        case_id=case.case_id, outcome=Outcome.APPROVE, actor="Rohan",
        role=Role.SENIOR_MGMT, decided_at=WHEN,
        rationale="Passport and birthplace differ from the listed person; "
                  "reviewed the underlying designation myself.")
    assert settled.status.value == "APPROVED"


def test_an_ordinary_sanctions_match_is_not_made_senior_only():
    """Widening what counts as a PEP must not quietly send every sanctions
    file to one person's desk."""
    engine, case = a_book(("sanction",), name="A Sanctioned Company")
    assert is_pep(case) is False
    settled = engine.decide(
        case_id=case.case_id, outcome=Outcome.REJECT, actor="Meera",
        role=Role.AML_OFFICER, decided_at=WHEN,
        rationale="Name, birth year and passport all match the designation.")
    assert settled.status.value == "REJECTED"


def test_a_plain_politically_exposed_person_was_always_caught():
    """The case that did work, kept so the fix is not mistaken for the
    whole of the control."""
    engine, case = a_book(("role.pep",), name="A Minister")
    assert is_pep(case) is True


def test_evidence_recorded_before_this_change_is_still_read():
    """The log cannot be rewritten, so files decided on evidence that
    carries only the old single value have to go on working -- and a PEP
    recorded that way must still be a PEP."""
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera", role=Role.AML_OFFICER, enrolled_at=WHEN)
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"kind": EntityKind.PERSON.value, "name": "A Minister",
                           "attributes": {}})
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"matched": True, "list_type": "PEP",
                           "rule": "match", "alert_id": "old", "basis": {}})
    assert is_pep(engine.queue()[0]) is True


# -- and the two other readers of the same value -----------------------------


def test_an_escalated_sanctioned_pep_waits_for_senior_management_alone():
    """The queue asked the same single value, so a file about a sanctioned
    head of state was offered to whichever officer was free."""
    engine, case = a_book(("sanction", "role.pep"))
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera", role=Role.AML_OFFICER, decided_at=WHEN,
                  rationale="I cannot clear a head of state; passing this up.")
    escalated = engine.state.casebook.get(case.case_id)

    assert waiting_on(escalated, "Rohan", Role.SENIOR_MGMT) is True
    assert waiting_on(escalated, "Aarav", Role.COMPLIANCE) is False


def test_the_risk_screen_shows_public_office_on_a_sanctions_match():
    """The officer categorising this party was shown "may be on a sanctions
    list" and never the guidance that clause 5.5 turns on -- that holding
    public office does not by itself make somebody high risk, and that the
    extra measures apply whatever category is set."""
    from vinzor.risk import what_screening_found

    engine, _case = a_book(("sanction", "role.pep"))
    found = what_screening_found(engine, "p1")

    assert "PEP" in found.kinds
    assert "SANCTIONS" in found.kinds
    assert found.guidance, "no guidance about public office was offered"


# -- the clause the gate enforces --------------------------------------------
#
# The product enforces clause 5.5(b)(iii) twice -- on the command side and in
# the fold -- names it in an exception's docstring, and prints it in a refusal
# an officer reads on screen. It was in the register nowhere. The bare id
# "5.5" held 5.5(a), which is the obligation to *work out* whether somebody is
# a politically exposed person; the limb that reserves clearing one for senior
# management was quoted nowhere a reader could check it. A rule the firm
# cannot show the words of is a rule it cannot defend to the person asking.


def test_the_clause_the_gate_enforces_is_in_the_register():
    from vinzor.citations import CLAUSES

    assert "5.5(b)(iii)" in CLAUSES
    clause = CLAUSES["5.5(b)(iii)"]
    assert "approval from its Senior Management" in clause.extract
    assert clause.page == 29


def test_the_limb_about_an_existing_customer_is_there_too():
    """5.5(b)(iv) is the other half the code's own docstring cites: the same
    approval where somebody already on the book becomes one."""
    from vinzor.citations import CLAUSES

    assert "5.5(b)(iv)" in CLAUSES
    assert "subsequently becoming a PEP" in CLAUSES["5.5(b)(iv)"].extract


def test_a_politically_exposed_file_cites_it():
    """The officer looking at the file was shown the clause about
    identifying a PEP and never the one the button in front of them
    enforces."""
    engine, case = a_book(("role.pep",), name="A Minister")
    cited = {citation["clause"]
             for piece in case.evidence for citation in (piece.citations or ())}
    assert "5.5(b)(iii)" in cited


def test_it_reads_in_plain_words_like_every_other_clause():
    from vinzor.briefing import PLAIN_RULES

    said = PLAIN_RULES["5.5(b)(iii)"]
    assert "senior management" in said.lower()
    assert "5.5" not in said        # the reading, not the reference
