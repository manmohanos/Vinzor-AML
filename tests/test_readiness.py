"""Whether a client book could be handed over, measured against clause 5.4.2.

From 1 September 2026 an IFSC regulated entity must upload each client's
KYC to a registered agency within three working days, and its existing book
by 30 October. These tests hold the check to the clause rather than to a
schema we invented, and to the distinction the clause itself draws between
a natural person and a legal one.
"""

from __future__ import annotations

import pytest

from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind
from vinzor.readiness import (FOR_A_LEGAL_PERSON, FOR_A_PERSON, measure)

from conftest import register


@pytest.fixture
def engine() -> Vinzor:
    return Vinzor(EventLog())


COMPLETE_PERSON = dict(
    nationality="SG", dob="1974-03-02", jurisdiction="SG",
    address="12 Marina Way", phone="+65 6555 0100",
    id_document_number="E1234567X",
)
COMPLETE_COMPANY = dict(
    cin="U74999MH2015PTC000001", address="4 Bandra Kurla Complex",
    date_of_incorporation="2015-04-01", country_of_incorporation="IN",
)


# -- the clause is the specification ----------------------------------------


def test_the_two_lists_are_the_clauses_own(engine):
    """Seven items for a natural person, five for a legal one -- and every
    entry cites the sub-clause it came from."""
    assert len(FOR_A_PERSON) == 7
    assert len(FOR_A_LEGAL_PERSON) == 5
    for clause, what, _ in FOR_A_PERSON:
        assert clause.startswith("5.4.2(a)")
        assert what and not what[0].isupper()
    for clause, what, _ in FOR_A_LEGAL_PERSON:
        assert clause.startswith("5.4.2(b)")


def test_a_complete_person_is_ready(engine):
    register(engine, "p1", EntityKind.PERSON, "Asha Mehta", **COMPLETE_PERSON)
    standing = measure(engine).parties[0]
    assert standing.ready
    assert standing.gaps == ()


def test_a_complete_company_is_ready(engine):
    register(engine, "c1", EntityKind.COMPANY, "Orion Trading",
             **COMPLETE_COMPANY)
    assert measure(engine).parties[0].ready


def test_a_person_is_not_asked_for_a_place_of_incorporation(engine):
    """A check that asked everything of everybody would produce a page of
    failures that mean nothing."""
    register(engine, "p1", EntityKind.PERSON, "Asha Mehta", **COMPLETE_PERSON)
    clauses = {g.clause for g in measure(engine).parties[0].gaps}
    assert not any(c.startswith("5.4.2(b)") for c in clauses)


def test_a_company_is_not_asked_for_a_date_of_birth(engine):
    register(engine, "c1", EntityKind.COMPANY, "Orion Trading",
             **COMPLETE_COMPANY)
    clauses = {g.clause for g in measure(engine).parties[0].gaps}
    assert not any(c.startswith("5.4.2(a)") for c in clauses)


# -- what is missing, and why ------------------------------------------------


def test_each_gap_names_the_clause_and_the_thing(engine):
    register(engine, "p1", EntityKind.PERSON, "Asha Mehta")
    gaps = {g.clause: g.what for g in measure(engine).parties[0].gaps}
    assert gaps["5.4.2(a)(iii)"] == "a date of birth"
    assert gaps["5.4.2(a)(vi)"] == "a residential address"
    assert gaps["5.4.2(a)(vii)"] == "contact details"
    # A name it does have, so that is not a gap.
    assert "5.4.2(a)(i)" not in gaps


def test_any_one_of_several_identifiers_satisfies_the_clause(engine):
    """The clause asks for "a unique identification number", not for a
    particular one. A passport number and a PAN both answer it."""
    for attribute in ("id_document_number", "pan", "customer_reference"):
        engine = Vinzor(EventLog())
        register(engine, "p1", EntityKind.PERSON, "Asha Mehta",
                 **{**COMPLETE_PERSON, "id_document_number": "",
                    attribute: "X12345"})
        clauses = {g.clause for g in measure(engine).parties[0].gaps}
        assert "5.4.2(a)(ii)" not in clauses, attribute


def test_either_a_phone_or_an_email_answers_contact_details(engine):
    for attribute in ("phone", "email"):
        engine = Vinzor(EventLog())
        register(engine, "p1", EntityKind.PERSON, "Asha Mehta",
                 **{**COMPLETE_PERSON, "phone": "",
                    attribute: "a@example.com" if attribute == "email"
                    else "+65 6555 0100"})
        clauses = {g.clause for g in measure(engine).parties[0].gaps}
        assert "5.4.2(a)(vii)" not in clauses, attribute


def test_a_blank_attribute_is_not_a_held_one(engine):
    """A column present but empty is the commonest shape of an incomplete
    export, and reading it as held would report a book ready that is not."""
    register(engine, "p1", EntityKind.PERSON, "Asha Mehta",
             **{**COMPLETE_PERSON, "address": "   "})
    clauses = {g.clause for g in measure(engine).parties[0].gaps}
    assert "5.4.2(a)(vi)" in clauses


def test_a_party_of_unrecorded_type_cannot_be_measured_and_says_so(engine):
    """The two lists ask for different things, so the type has to be
    established before anything else can be."""
    register(engine, "u1", EntityKind.UNKNOWN, "A name off a statement")
    standing = measure(engine).parties[0]
    assert not standing.ready
    assert [g.what for g in standing.gaps] == ["what kind of party this is"]


# -- the whole book ----------------------------------------------------------


def test_the_shortfall_is_counted_by_clause(engine):
    """One missing column usually explains most of a book's shortfall, and
    a firm needs to see that rather than read four hundred rows."""
    for index in range(3):
        register(engine, f"p{index}", EntityKind.PERSON, f"Person {index}",
                 **{**COMPLETE_PERSON, "address": ""})
    register(engine, "p9", EntityKind.PERSON, "Complete Person",
             **COMPLETE_PERSON)

    result = measure(engine)
    assert result.by_clause["5.4.2(a)(vi)"] == 3
    assert len(result.ready) == 1
    assert len(result.short) == 3


def test_parties_short_of_something_are_listed_first(engine):
    register(engine, "p1", EntityKind.PERSON, "Complete", **COMPLETE_PERSON)
    register(engine, "p2", EntityKind.PERSON, "Incomplete")
    assert measure(engine).parties[0].name == "Incomplete"


def test_only_some_parties_can_be_measured_when_asked(engine):
    register(engine, "p1", EntityKind.PERSON, "Asha Mehta")
    register(engine, "p2", EntityKind.PERSON, "Rohan Desai")
    result = measure(engine, only={"p1"})
    assert [p.entity_id for p in result.parties] == ["p1"]


def test_an_empty_workspace_measures_emptily(engine):
    result = measure(engine)
    assert result.parties == ()
    assert result.ready == () and result.short == ()


# -- what an importer can now carry ------------------------------------------


def test_a_sheet_carrying_an_address_makes_the_party_ready(tmp_path, engine):
    """The importer could not accept an address or a telephone number, so a
    sheet that carried them threw them away and the party looked incomplete
    for a reason of our own making."""
    from vinzor.importing import apply, read

    path = tmp_path / "book.csv"
    path.write_text(
        "Name,Type,Nationality,Date of Birth,Domicile,Address,Mobile,"
        "Passport Number\n"
        "Asha Mehta,person,SG,1974-03-02,SG,12 Marina Way,+65 6555 0100,"
        "E1234567X\n",
        encoding="utf-8")

    plan = read(path)
    assert not plan.refusals
    assert {"address", "phone"} <= set(plan.mapped)
    apply(engine, plan, "2026-08-19")

    assert measure(engine).parties[0].ready
