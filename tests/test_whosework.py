"""Four people, four mornings, one book.

Everyone used to see the same list in the same order, which meant three of
the four were reading somebody else's morning. These tests hold the two
promises that make reordering safe: nothing is ever hidden from anybody,
and work that is blocked on one particular person reaches them and nobody
else.
"""

from __future__ import annotations

import pytest

from vinzor.briefing import brief
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType, Outcome, Role
from vinzor.whosework import (FIRST_FOR, WHAT_YOURS_IS_FOR, rank_of,
                              waiting_on)

WHEN = "2026-08-01"
TODAY = "2026-08-20"


@pytest.fixture
def engine() -> Vinzor:
    engine = Vinzor(EventLog())
    for name, role in (("Meera Nair", Role.AML_OFFICER),
                       ("Aarav Sharma", Role.COMPLIANCE),
                       ("Rohan Kapoor", Role.SENIOR_MGMT),
                       ("Priya Rao", Role.VIEWER)):
        engine.enroll(name=name, role=role, enrolled_at=WHEN)
    return engine


def party(engine, entity_id, name, kind=EntityKind.PERSON):
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=entity_id,
                  occurred_at=WHEN,
                  payload={"kind": kind.value, "name": name,
                           "attributes": {}})


def screened(engine, entity_id, list_type, alert):
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject=entity_id,
                  occurred_at=WHEN,
                  payload={"list_type": list_type, "matched": True,
                           "alert_id": alert})


def a_pep(engine, entity_id="p1", name="Dev Kumar"):
    party(engine, entity_id, name)
    screened(engine, entity_id, "PEP", "alt_pep")
    return next(case for case in engine.state.casebook.cases.values()
                if case.subject == entity_id)


def titles(engine, person):
    return [group.title for group in
            brief(engine, person=person, today=TODAY).groups]


# -- nothing is hidden from anybody ------------------------------------------


def test_every_role_sees_every_file(engine):
    """A system that shows senior management a shorter list has decided on
    their behalf what is beneath them, and the one time that judgement is
    wrong is the time it matters."""
    party(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", "alt_1")
    party(engine, "c1", "Orion Holdings", EntityKind.COMPANY)
    screened(engine, "c1", "ADVERSE_MEDIA", "alt_2")

    counts = set()
    for person in ("Meera Nair", "Aarav Sharma", "Rohan Kapoor", "Priya Rao"):
        page = brief(engine, person=person, today=TODAY)
        counts.add(sum(len(group.items) for group in page.groups))
    assert len(counts) == 1, "somebody is seeing fewer files than a colleague"


def test_only_the_order_differs(engine):
    party(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", "alt_1")
    a_pep(engine, "p2", "Dev Kumar")

    seen = {}
    for person in ("Meera Nair", "Rohan Kapoor"):
        seen[person] = set(titles(engine, person))
    assert seen["Meera Nair"] == seen["Rohan Kapoor"]


# -- the order actually differs ----------------------------------------------


def test_each_role_says_what_its_screen_is_for(engine):
    """Written on the screen, so nobody has to guess why their list differs
    from a colleague's, and a firm that disagrees can see what it is."""
    for role in Role:
        if role in WHAT_YOURS_IS_FOR:
            assert WHAT_YOURS_IS_FOR[role].strip()


def test_the_officer_leads_with_names_and_money(engine):
    party(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", "alt_1")
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="lic",
                  occurred_at=WHEN,
                  payload={"category": "REGISTERED_NON_RETAIL",
                           "number": "lic"})
    engine.report_net_worth(amount_usd=1_000, as_at=WHEN,
                            actor="Meera Nair", note="Very little indeed.")

    first = titles(engine, "Meera Nair")[0]
    assert "sanctions list" in first


def test_senior_management_leads_with_the_firm(engine):
    """The same book, and the top of the screen is the thing about the firm
    rather than the thing about a customer."""
    party(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", "alt_1")
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="lic",
                  occurred_at=WHEN,
                  payload={"category": "REGISTERED_NON_RETAIL",
                           "number": "lic"})
    engine.report_net_worth(amount_usd=1_000, as_at=WHEN,
                            actor="Meera Nair", note="Very little indeed.")

    assert "capital" in titles(engine, "Rohan Kapoor")[0]


def test_a_roles_own_work_outranks_the_oldest_files(engine):
    """The first version put aged files above everything for everybody,
    which undid the whole change: eighty-nine old files were the top of all
    four screens. Age is a reason to look at something, not a reason to
    look at it before the one thing on the screen that is yours."""
    for index in range(4):
        party(engine, f"old{index}", f"Old Party {index}")
        engine.ingest(event_type=EventType.SCREENING_COMPLETED,
                      subject=f"old{index}", occurred_at="2025-01-01",
                      payload={"list_type": "ADVERSE_MEDIA", "matched": True,
                               "alert_id": f"alt_old{index}"})
    party(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", "alt_new")

    assert "sanctions list" in titles(engine, "Meera Nair")[0]


def test_a_policy_no_role_names_keeps_its_ordinary_place(engine):
    assert rank_of("POL_SANCTIONS_HIT", Role.AML_OFFICER) < \
        rank_of("POL_NOTHING_NAMED_HERE", Role.AML_OFFICER)


# -- work waiting on one particular person -----------------------------------


def test_a_file_passed_up_reaches_the_person_who_can_settle_it(engine):
    case = a_pep(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  decided_at=TODAY,
                  rationale="Public office match needs a senior decision.")
    assert "waiting for you" in titles(engine, "Rohan Kapoor")[0]


def test_it_does_not_come_back_to_whoever_passed_it_up(engine):
    """The whole of the four-eyes rule. A file cannot be waiting on the
    person who said they could not settle it."""
    case = a_pep(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  decided_at=TODAY,
                  rationale="Public office match needs a senior decision.")
    assert not any("waiting for you" in title
                   for title in titles(engine, "Meera Nair"))


def test_a_public_office_file_waits_only_on_senior_management(engine):
    """Clause 5.5(b)(iii). The compliance officer is senior, and still may
    not settle this one, so it is not waiting on them however it looks."""
    case = a_pep(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  decided_at=TODAY,
                  rationale="Public office match needs a senior decision.")
    assert not any("waiting for you" in title
                   for title in titles(engine, "Aarav Sharma"))
    assert waiting_on(engine.state.casebook.get(case.case_id),
                      "Rohan Kapoor", Role.SENIOR_MGMT)


def test_an_ordinary_file_passed_up_reaches_any_other_officer(engine):
    party(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", "alt_1")
    case = next(iter(engine.state.casebook.cases.values()))
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  decided_at=TODAY,
                  rationale="I cannot resolve this either way on the papers.")
    assert waiting_on(case, "Aarav Sharma", Role.COMPLIANCE)


def test_nothing_ever_waits_on_a_reader_who_cannot_settle_anything(engine):
    case = a_pep(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  decided_at=TODAY,
                  rationale="Public office match needs a senior decision.")
    assert not waiting_on(case, "Priya Rao", Role.VIEWER)


def test_a_file_nobody_passed_up_waits_on_nobody(engine):
    case = a_pep(engine)
    assert not waiting_on(case, "Rohan Kapoor", Role.SENIOR_MGMT)


# -- the lists themselves ----------------------------------------------------


def test_every_role_has_a_stated_order(engine):
    """A weighting nobody can inspect is how a queue quietly stops
    reflecting what a firm cares about."""
    for role in Role:
        if role in FIRST_FOR:
            assert FIRST_FOR[role]
            assert len(set(FIRST_FOR[role])) == len(FIRST_FOR[role])


def test_nothing_new_speaks_jargon(engine):
    import re

    from test_briefing import JARGON, _strings

    case = a_pep(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  decided_at=TODAY,
                  rationale="Public office match needs a senior decision.")

    offences = []
    page = brief(engine, person="Rohan Kapoor", today=TODAY)
    for path, text in _strings(page, "briefing"):
        for pattern, what in JARGON:
            found = re.search(pattern, text)
            if found:
                offences.append(f"{path}: {what} ({found.group(0)!r})")
    assert not offences, ("jargon reached the reader:\n  "
                          + "\n  ".join(offences))
