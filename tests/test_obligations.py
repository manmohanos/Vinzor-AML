"""The two obligations a firm loses its licence over quietly.

Both are one-time, not periodic, which is what makes them easy to miss:
nothing recurs to remind anybody. FINGate registration is a condition of the
licence itself, and the NISM certificate is personal to whoever holds the
Principal Officer seat -- so a firm that changed officers has a new clock and
usually does not know it.
"""

from __future__ import annotations

import pytest

from vinzor.calendar import (
    FINGATE_MANDATED_ON,
    NISM_GRACE_MONTHS,
    NISM_MANDATED_ON,
    Obligation,
    Status,
    instances,
    outstanding,
)
from vinzor.licence import Category, Office, principal_officers
from vinzor.model import EventType

from conftest import WHEN, company

GRANTED = "2023-04-01"
TODAY = "2026-08-23"


def fme(engine, when=GRANTED):
    company(engine, "fme_1", "Acme GIFT Fund Managers Ltd")
    engine.ingest(
        event_type=EventType.LICENCE_GRANTED, subject="fme_1", occurred_at=when,
        payload={"category": Category.REGISTERED_NON_RETAIL.value,
                 "number": "IFSCA/FME/II/2023-24/084"})


def appoint(engine, person, when):
    engine.ingest(
        event_type=EventType.OFFICE_APPOINTED, subject="fme_1",
        occurred_at=when,
        payload={"office": Office.PRINCIPAL_OFFICER.value, "person": person,
                 "based_in_ifsc": True})


def only(rows, obligation):
    return [row for row in rows if row.obligation is obligation]


# -- FINGate: a condition of the licence, owed once --------------------------


def test_fingate_registration_is_owed_from_the_day_it_became_a_condition():
    """A licence granted before the March 2024 circular cannot have owed the
    registration earlier than the circular did."""
    rows = only(instances(GRANTED, TODAY), Obligation.FINGATE_REGISTRATION)
    assert len(rows) == 1, "one registration, once -- not one per quarter"
    assert rows[0].due_on == FINGATE_MANDATED_ON


def test_a_licence_granted_after_the_mandate_owes_it_from_the_grant():
    rows = only(instances("2025-06-10", TODAY),
                Obligation.FINGATE_REGISTRATION)
    assert rows[0].due_on == "2025-06-10", (
        "the circular says before commencing business, and business commences "
        "at the grant")


def test_registering_settles_it_and_it_does_not_come_back():
    key = f"{Obligation.FINGATE_REGISTRATION.value}|this licence"
    rows = only(outstanding(GRANTED, TODAY, {key: "2024-03-01"}),
                Obligation.FINGATE_REGISTRATION)
    assert rows == [], "a registration on record is still showing as owed"


def test_an_unregistered_licence_is_overdue_not_merely_upcoming(engine):
    """Non-compliance is a breach of the conditions of the licence itself, so
    this is not a reminder -- it is a file."""
    rows = only(instances(GRANTED, TODAY), Obligation.FINGATE_REGISTRATION)
    assert rows[0].status(TODAY) is Status.OVERDUE


# -- NISM: personal to the officer, not to the seat ---------------------------


def test_the_clock_starts_at_the_later_of_appointment_and_the_mandate(engine):
    """An officer appointed in 2023 did not owe a certificate that did not
    exist until November 2025."""
    fme(engine)
    appoint(engine, "Meera Nair", "2023-05-01")

    rows = only(instances(GRANTED, TODAY, {},
                          principal_officers(engine.state.licence)),
                Obligation.NISM_CERTIFICATION)
    assert len(rows) == 1
    assert rows[0].period_end == NISM_MANDATED_ON, (
        "the clock should start at the circular, not the 2023 appointment")
    assert rows[0].due_on == "2026-03-17", (
        f"{NISM_GRACE_MONTHS} months from the mandate")


def test_an_officer_appointed_after_the_mandate_starts_their_own_clock(engine):
    fme(engine)
    appoint(engine, "Asha Mehta", "2026-01-10")

    rows = only(instances(GRANTED, TODAY, {},
                          principal_officers(engine.state.licence)),
                Obligation.NISM_CERTIFICATION)
    assert rows[0].due_on == "2026-05-10"


def test_the_obligation_follows_the_person_not_the_seat(engine):
    """The certificate is personal. A firm that replaced its Principal
    Officer has a new four-month clock, and the old holder's instance goes
    with them -- a certificate the previous officer held is not one this firm
    can rely on for the new one."""
    fme(engine)
    appoint(engine, "Meera Nair", "2026-01-10")
    rows = only(instances(GRANTED, TODAY, {},
                          principal_officers(engine.state.licence)),
                Obligation.NISM_CERTIFICATION)
    assert [row.period for row in rows] == ["Meera Nair"]

    engine.ingest(event_type=EventType.OFFICE_VACATED, subject="fme_1",
                  occurred_at="2026-06-01",
                  payload={"office": Office.PRINCIPAL_OFFICER.value})
    appoint(engine, "Rohit Verma", "2026-06-02")

    rows = only(instances(GRANTED, TODAY, {},
                          principal_officers(engine.state.licence)),
                Obligation.NISM_CERTIFICATION)
    assert [row.period for row in rows] == ["Rohit Verma"]
    assert rows[0].due_on == "2026-10-02", "a new holder, a new clock"


def test_a_certificate_on_record_settles_only_that_person(engine):
    fme(engine)
    appoint(engine, "Meera Nair", "2026-01-10")
    key = f"{Obligation.NISM_CERTIFICATION.value}|Meera Nair"

    rows = only(outstanding(GRANTED, TODAY, {key: "2026-02-01"},
                            principal_officers(engine.state.licence)),
                Obligation.NISM_CERTIFICATION)
    assert rows == []

    # A different officer's certificate does not answer for this one.
    rows = only(outstanding(GRANTED, TODAY,
                            {f"{Obligation.NISM_CERTIFICATION.value}|Someone Else":
                             "2026-02-01"},
                            principal_officers(engine.state.licence)),
                Obligation.NISM_CERTIFICATION)
    assert [row.period for row in rows] == ["Meera Nair"]


def test_a_vacant_seat_owes_no_certificate(engine):
    """Nobody holds the post, so nobody owes the certificate. The vacancy
    itself is already a Case under Regulation 7 -- inventing a second,
    personal obligation with no person to attach it to would be reporting a
    breach that has no subject."""
    fme(engine)
    assert principal_officers(engine.state.licence) == ()
    rows = only(instances(GRANTED, TODAY, {},
                          principal_officers(engine.state.licence)),
                Obligation.NISM_CERTIFICATION)
    assert rows == []


# -- they reach an officer as files, not as silence --------------------------


def test_both_become_files_on_the_sweep(engine):
    """Never silently green. The sweep is what turns a passed deadline into
    something on somebody's desk, and these have to travel that same path as
    every other missed filing."""
    fme(engine)
    appoint(engine, "Meera Nair", "2026-01-10")

    opened = engine.observe_deadlines(TODAY)
    kinds = set()
    for event in engine.log:
        if event.event_type is EventType.FILING_OVERDUE:
            kinds.add(event.payload["obligation"])

    assert Obligation.FINGATE_REGISTRATION.value in kinds
    assert Obligation.NISM_CERTIFICATION.value in kinds
    assert opened, "the sweep opened no files at all"


def test_the_sweep_reports_each_of_them_once(engine):
    """The log records that lateness was observed, not that it is still true
    every time somebody loads a page."""
    fme(engine)
    appoint(engine, "Meera Nair", "2026-01-10")

    engine.observe_deadlines(TODAY)
    first = sum(1 for e in engine.log
                if e.event_type is EventType.FILING_OVERDUE)
    engine.observe_deadlines(TODAY)
    second = sum(1 for e in engine.log
                 if e.event_type is EventType.FILING_OVERDUE)
    assert first == second, "the same breach was recorded twice"


def test_they_are_named_in_words_an_officer_reads(engine):
    """An obligation shown as FINGATE_REGISTRATION is an obligation nobody
    acts on."""
    from vinzor.briefing import regulatory

    fme(engine)
    appoint(engine, "Meera Nair", "2026-01-10")
    page = regulatory(engine, TODAY)
    said = " ".join(row.what for row in page.owed)

    assert "FIU-IND FINGate 2.0 registration" in said
    assert "NISM-IFSCA-01 certification" in said
    assert "_" not in said, "an internal name reached the screen"
