"""Passing a file up, walked to the end of where it leads.

Escalation records who passed a file up and never who it is passed *to*, and
four eyes locks every escalator out permanently. With the three deciding roles
enrolled -- an ordinary GIFT City FME -- each passing the file up in turn::

    status ESCALATED | open True | passed up by Meera, Aarav, Devika
    Meera   AML officer         waiting on you: no   can settle: no
    Aarav   Compliance officer  waiting on you: no   can settle: no
    Devika  Senior management   waiting on you: no   can settle: no

A file open forever, waiting on nobody, sitting in the ordinary band of every
screen with no marker on it. The period report then said of that file, on a
page with the firm's name and a print button:

    "1 file is waiting for a second officer after being passed up ...
     Nobody who passed a file up can settle it."

which tells the reader the opposite of what is true. On a politically exposed
file it takes **one** click, because only senior management may clear one -- so
the sole enrolled senior manager passing it up ends it there.

An unresolved alert parked in "referred" is the finding examiners write. The
escalations are permanent events, so there was no taking it back.

Three changes: the escalation that would leave nobody is refused at the source
with a remedy; a file already in that state (a log written before the guard
cannot be rewritten) gets its own group above everything, on every screen; and
the report says what is actually true of it.

Separately, the group heading read "1 file is waiting for you and nobody else
can settle it" -- shown to two officers at once about the same file, either of
whom could settle it, so it was false for both.
"""

from __future__ import annotations

import pytest

from vinzor.briefing import brief
from vinzor.cases import EscalationNeedsAnotherOfficer
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType, Outcome, Role
from vinzor.whosework import STUCK, stuck, who_could_settle

WHEN = "2026-08-07"
PASSING_UP = "I cannot settle this one; passing it up to somebody senior."


def a_book(topics=("SANCTIONS",), people=(("Meera", Role.AML_OFFICER),
                                          ("Aarav", Role.COMPLIANCE),
                                          ("Devika", Role.SENIOR_MGMT))):
    engine = Vinzor(EventLog())
    for name, role in people:
        engine.enroll(name=name, role=role, enrolled_at=WHEN)
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"kind": EntityKind.PERSON.value,
                           "name": "A Listed Person", "attributes": {}})
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"matched": True, "list_type": topics[0],
                           "list_types": list(topics), "rule": "match",
                           "alert_id": "os:x", "basis": {}})
    return engine, engine.queue()[0]


def pass_up(engine, case_id, who, role):
    return engine.decide(case_id=case_id, outcome=Outcome.ESCALATE, actor=who,
                         role=role, decided_at=WHEN, rationale=PASSING_UP)


# -- the dead end ------------------------------------------------------------


def test_the_last_officer_cannot_pass_a_file_up_to_nobody():
    """The defect, exactly as reproduced. The third escalation is the one
    that ends the file, so the third escalation is the one refused."""
    engine, case = a_book()
    pass_up(engine, case.case_id, "Meera", Role.AML_OFFICER)
    pass_up(engine, case.case_id, "Aarav", Role.COMPLIANCE)

    with pytest.raises(EscalationNeedsAnotherOfficer) as refusal:
        pass_up(engine, case.case_id, "Devika", Role.SENIOR_MGMT)

    assert "nobody else enrolled could settle it" in str(refusal.value)
    assert "Enrol another officer" in str(refusal.value)


def test_the_file_is_still_settleable_after_the_refusal():
    """A refusal that leaves the file stuck anyway would be no better than
    the dead end it replaced."""
    engine, case = a_book()
    pass_up(engine, case.case_id, "Meera", Role.AML_OFFICER)
    pass_up(engine, case.case_id, "Aarav", Role.COMPLIANCE)

    settled = engine.decide(
        case_id=case.case_id, outcome=Outcome.APPROVE, actor="Devika",
        role=Role.SENIOR_MGMT, decided_at=WHEN,
        rationale="Birthplace and passport differ from the listed person.")
    assert settled.status.value == "APPROVED"


def test_ordinary_escalation_is_untouched():
    engine, case = a_book()
    passed = pass_up(engine, case.case_id, "Meera", Role.AML_OFFICER)
    assert passed.status.value == "ESCALATED"
    assert who_could_settle(passed, engine.state.actors) == ["Aarav", "Devika"]


def test_a_public_office_file_ends_with_the_only_senior_manager():
    """One click, not three: clause 5.5(b)(iii) sends a politically exposed
    file to senior management alone, so the sole senior manager passing it up
    leaves nobody who may clear it."""
    engine, case = a_book(topics=("SANCTIONS", "PEP"))
    with pytest.raises(EscalationNeedsAnotherOfficer):
        pass_up(engine, case.case_id, "Devika", Role.SENIOR_MGMT)


def test_a_junior_officer_may_still_pass_a_public_office_file_up():
    """Refusing business must never be harder than accepting it."""
    engine, case = a_book(topics=("SANCTIONS", "PEP"))
    passed = pass_up(engine, case.case_id, "Meera", Role.AML_OFFICER)
    assert who_could_settle(passed, engine.state.actors) == ["Devika"]


def test_a_book_with_one_officer_cannot_pass_anything_up():
    engine, case = a_book(people=(("Meera", Role.AML_OFFICER),))
    with pytest.raises(EscalationNeedsAnotherOfficer):
        pass_up(engine, case.case_id, "Meera", Role.AML_OFFICER)


def test_a_read_only_reader_does_not_count_as_somebody_who_could_settle():
    """``VIEWER`` is on the book and can decide nothing. Counting them would
    make the guard pass while leaving the file exactly as stuck."""
    engine, case = a_book(people=(("Meera", Role.AML_OFFICER),
                                  ("Priya", Role.VIEWER)))
    with pytest.raises(EscalationNeedsAnotherOfficer):
        pass_up(engine, case.case_id, "Meera", Role.AML_OFFICER)


# -- a file already in that state --------------------------------------------


def already_stuck():
    """A workspace written before the guard existed. The log cannot be
    rewritten, so the product has to be able to show one."""
    engine, case = a_book()
    for who, role in (("Meera", Role.AML_OFFICER), ("Aarav", Role.COMPLIANCE),
                      ("Devika", Role.SENIOR_MGMT)):
        engine.ingest(event_type=EventType.CASE_DECIDED, subject="p1",
                      occurred_at=WHEN, actor=who,
                      payload={"case_id": case.case_id, "outcome": "ESCALATE",
                               "role": role.value, "rationale": PASSING_UP})
    return engine, engine.state.casebook.get(case.case_id)


def test_a_file_nobody_can_settle_is_recognised_as_one():
    engine, case = already_stuck()
    assert who_could_settle(case, engine.state.actors) == []
    assert stuck(case, engine.state.actors) is True


def test_it_is_at_the_top_of_every_screen_rather_than_lost_in_the_middle():
    for person, _role in (("Meera", Role.AML_OFFICER),
                          ("Aarav", Role.COMPLIANCE),
                          ("Devika", Role.SENIOR_MGMT)):
        engine, _case = already_stuck()
        page = brief(engine, person=person, today="2026-08-20")
        assert page.groups, f"{person} saw no groups at all"
        top = page.groups[0]
        assert "passed up by everybody who could settle" in top.title


def test_the_period_report_does_not_call_it_waiting_for_a_second_officer():
    """It said exactly that, on a printable page with the firm's name on
    it."""
    from vinzor.reporting import period_report

    engine, _case = already_stuck()
    page = period_report(engine, today="2026-08-20", since="2026-08-01")
    tail = " ".join(s.tail for s in page.sections if s.tail)

    assert "waiting for a second officer" not in tail
    assert "passed up by everybody who could settle" in tail
    assert "Enrol another officer" in tail


def test_an_ordinary_passed_up_file_still_reads_as_waiting_for_somebody():
    from vinzor.reporting import period_report

    engine, case = a_book()
    pass_up(engine, case.case_id, "Meera", Role.AML_OFFICER)
    page = period_report(engine, today="2026-08-20", since="2026-08-01")
    tail = " ".join(s.tail for s in page.sections if s.tail)

    assert "waiting for a second officer" in tail
    assert "passed up by everybody" not in tail


# -- what the group heading claims -------------------------------------------


def test_the_screen_does_not_claim_the_reader_is_the_only_one_who_can_settle():
    """The same sentence was shown to Aarav and to Devika about one file, and
    either could have settled it, so it was false for both."""
    engine, case = a_book()
    pass_up(engine, case.case_id, "Meera", Role.AML_OFFICER)

    for person in ("Aarav", "Devika"):
        page = brief(engine, person=person, today="2026-08-20")
        titles = [group.title for group in page.groups]
        assert not any("nobody else can settle" in title for title in titles)
        assert any("passed up and is waiting for you" in title
                   for title in titles), titles


def test_the_stuck_group_sorts_above_work_waiting_on_the_reader():
    from vinzor.whosework import WAITING, rank_of

    assert rank_of(STUCK, Role.AML_OFFICER) < rank_of(WAITING, Role.AML_OFFICER)
