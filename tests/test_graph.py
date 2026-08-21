"""Beneficial ownership under IFSCA 1.3.3, and the cases it cannot resolve."""

from __future__ import annotations

import pytest

from vinzor.graph import IFSCA_TESTS, Conclusion, OwnershipTest
from vinzor.model import EntityKind, Relation

from conftest import company, owns, person, register


# -- the thresholds are the regulator's, not FATF's ------------------------


def test_the_company_threshold_is_ten_percent_not_twenty_five():
    """IFSCA cut it from 25% to 10% by circular in May 2023.

    Anything built to the FATF 25% figure under-reports beneficial owners for
    an IFSCA-regulated entity. This is the test that would have caught it.
    """
    assert IFSCA_TESTS[EntityKind.COMPANY].threshold == 10.0


def test_each_customer_type_has_its_own_test():
    assert IFSCA_TESTS[EntityKind.PARTNERSHIP].threshold == 10.0
    assert IFSCA_TESTS[EntityKind.UNINCORPORATED_BODY].threshold == 15.0
    assert IFSCA_TESTS[EntityKind.TRUST].threshold == 10.0


def test_company_is_strictly_above_but_trust_is_at_or_above():
    """1.3.3(a) says "more than ten"; 1.3.3(d) says "ten per cent or more"."""
    assert IFSCA_TESTS[EntityKind.COMPANY].meets(10.0) is False
    assert IFSCA_TESTS[EntityKind.COMPANY].meets(10.01) is True
    assert IFSCA_TESTS[EntityKind.TRUST].meets(10.0) is True


def test_a_twenty_percent_holder_is_a_beneficial_owner(engine):
    """Under the old 25% assumption this person was invisible."""
    person(engine, "p1", "Alice")
    company(engine, "c1")
    owns(engine, "p1", "c1", 20)

    result = engine.state.graph.resolve_ubo("c1")
    assert result.conclusion is Conclusion.IDENTIFIED
    assert result.owners[0].person_id == "p1"


# -- the arithmetic --------------------------------------------------------


def test_direct_holding(engine):
    person(engine, "p1", "Alice")
    company(engine, "c1")
    owns(engine, "p1", "c1", 100)

    result = engine.state.graph.resolve_ubo("c1")
    assert result.conclusion is Conclusion.IDENTIFIED
    assert result.owners[0].effective_percentage == 100.0


def test_percentages_multiply_along_a_chain(engine):
    """100% of c3, which holds 80% of c2, which holds 70% of c1 -> 56%."""
    person(engine, "p1", "Alice")
    for c in ("c1", "c2", "c3"):
        company(engine, c)
    owns(engine, "p1", "c3", 100)
    owns(engine, "c3", "c2", 80)
    owns(engine, "c2", "c1", 70)

    result = engine.state.graph.resolve_ubo("c1")
    assert result.owners[0].effective_percentage == 56.0
    assert result.owners[0].paths == (("c1", "c2", "c3", "p1"),)


def test_two_routes_to_the_same_person_are_summed(engine):
    person(engine, "p1", "Alice")
    for c in ("c1", "c2", "c3"):
        company(engine, c)
    owns(engine, "p1", "c2", 50)
    owns(engine, "p1", "c3", 50)
    owns(engine, "c2", "c1", 40)
    owns(engine, "c3", "c1", 40)

    result = engine.state.graph.resolve_ubo("c1")
    assert result.owners[0].effective_percentage == 40.0  # 20% + 20%
    assert len(result.owners[0].paths) == 2


def test_a_dilute_holding_falls_below_the_test(engine):
    """Twelve holders of 8% each: nobody is a beneficial owner by ownership."""
    company(engine, "c1")
    for i in range(12):
        person(engine, f"p{i}")
        owns(engine, f"p{i}", "c1", 8)

    result = engine.state.graph.resolve_ubo("c1")
    assert result.conclusion is Conclusion.SENIOR_MANAGING_OFFICIAL_REQUIRED
    assert result.owners == ()
    assert len(result.below_threshold) == 12
    assert "senior managing official" in result.explain()


def test_the_test_can_be_overridden_for_another_jurisdiction(engine):
    person(engine, "p1")
    company(engine, "c1")
    owns(engine, "p1", "c1", 20)

    fatf = OwnershipTest(25.0, False, "FATF R.24")
    assert engine.state.graph.resolve_ubo("c1", test=fatf).owners == ()
    assert engine.state.graph.resolve_ubo("c1").owners  # IFSCA 10%


# -- the chain cannot always be completed ----------------------------------


def test_a_cycle_terminates_and_is_reported(engine):
    for c in ("c1", "c2", "c3"):
        company(engine, c)
    owns(engine, "c1", "c2", 40)
    owns(engine, "c2", "c3", 50)
    owns(engine, "c3", "c1", 30)

    result = engine.state.graph.resolve_ubo("c1")
    assert result.conclusion is Conclusion.INCOMPLETE
    assert result.cycles
    assert "cycle" in result.explain()


def test_a_cycle_is_reported_even_when_an_owner_was_found(engine):
    """A partly-resolved chain is not a resolved one."""
    person(engine, "p1", "Alice")
    for c in ("c1", "c2", "c3"):
        company(engine, c)
    owns(engine, "p1", "c1", 60)
    owns(engine, "c2", "c1", 40)
    owns(engine, "c3", "c2", 50)
    owns(engine, "c2", "c3", 50)

    result = engine.state.graph.resolve_ubo("c1")
    assert result.conclusion is Conclusion.INCOMPLETE
    assert result.owners[0].effective_percentage == 60.0  # still surfaced
    assert result.cycles


def test_undeclared_intermediate_owner_is_a_dead_end(engine):
    company(engine, "c1")
    company(engine, "c2")
    owns(engine, "c2", "c1", 100)

    result = engine.state.graph.resolve_ubo("c1")
    assert result.conclusion is Conclusion.INCOMPLETE
    assert result.dead_ends == ("c2",)


def test_entity_with_nothing_declared(engine):
    company(engine, "c1")
    assert engine.state.graph.resolve_ubo("c1").conclusion is Conclusion.NOT_DECLARED


# -- trusts: 1.3.3(d) ------------------------------------------------------


def trust(engine, entity_id: str, name: str | None = None) -> None:
    register(engine, entity_id, EntityKind.TRUST, name)


def test_a_trust_must_name_its_author_and_trustee_whatever_the_percentages(engine):
    """1.3.3(d) requires the author and trustee regardless of any interest."""
    person(engine, "p1", "Alice")
    trust(engine, "t1", "Family Trust")
    owns(engine, "p1", "t1", 60, relation=Relation.BENEFICIARY_OF)

    result = engine.state.graph.resolve_ubo("t1")
    assert result.owners[0].person_id == "p1"
    # ...but neither mandatory party was ever declared, so this is not done.
    assert result.conclusion is Conclusion.INCOMPLETE
    assert set(result.missing_roles) == {"author of the trust", "trustee"}


def test_a_fully_declared_trust_resolves(engine):
    person(engine, "p1", "Alice")
    person(engine, "p2", "Settlor")
    company(engine, "c1", "Trustee Services Ltd")
    trust(engine, "t1", "Family Trust")
    owns(engine, "p1", "t1", 60, relation=Relation.BENEFICIARY_OF)
    owns(engine, "p2", "t1", 0, relation=Relation.SETTLOR_OF)
    owns(engine, "c1", "t1", 0, relation=Relation.TRUSTEE_OF)

    result = engine.state.graph.resolve_ubo("t1")
    assert result.conclusion is Conclusion.IDENTIFIED
    assert result.missing_roles == ()
    assert {p.role for p in result.mandatory_parties} == {
        "author of the trust",
        "trustee",
    }


def test_every_co_trustee_and_co_settlor_is_named(engine):
    """1.3.3(d) asks who they are, not who one of them is.

    Parties used to be collected into a dict keyed by relation, so a trust
    with three trustees kept only the last one declared and the other two
    vanished -- while the verdict still read IDENTIFIED. An officer was told
    the ownership of the trust was established, from a file that had lost
    two of the people the regulation requires by name.
    """
    trust(engine, "t1", "Al Rashid Family Trust")
    person(engine, "s1", "Hassan Al Rashid")
    person(engine, "s2", "Layla Al Rashid")
    for entity_id, name in (("c1", "Trust Co A"), ("c2", "Trust Co B"),
                            ("c3", "Trust Co C")):
        company(engine, entity_id, name)
        owns(engine, entity_id, "t1", 0, relation=Relation.TRUSTEE_OF)
    owns(engine, "s1", "t1", 0, relation=Relation.SETTLOR_OF)
    owns(engine, "s2", "t1", 0, relation=Relation.SETTLOR_OF)

    result = engine.state.graph.resolve_ubo("t1")
    named = {(p.name, p.role) for p in result.mandatory_parties}
    assert named == {
        ("Hassan Al Rashid", "author of the trust"),
        ("Layla Al Rashid", "author of the trust"),
        ("Trust Co A", "trustee"),
        ("Trust Co B", "trustee"),
        ("Trust Co C", "trustee"),
    }, named
    assert result.missing_roles == ()

def test_a_trustee_confers_control_but_no_economic_interest(engine):
    company(engine, "c1", "Trustee Services Ltd")
    trust(engine, "t1")
    owns(engine, "c1", "t1", 0, relation=Relation.TRUSTEE_OF)

    result = engine.state.graph.resolve_ubo("t1")
    assert result.owners == ()  # a trustee holds nothing
    assert [p.party_id for p in result.mandatory_parties] == ["c1"]


def test_a_beneficiary_at_exactly_ten_percent_qualifies(engine):
    """1.3.3(d) is inclusive where 1.3.3(a) is not."""
    person(engine, "p1")
    person(engine, "p2", "Settlor")
    company(engine, "c1", "Trustee Ltd")
    trust(engine, "t1")
    owns(engine, "p1", "t1", 10, relation=Relation.BENEFICIARY_OF)
    owns(engine, "p2", "t1", 0, relation=Relation.SETTLOR_OF)
    owns(engine, "c1", "t1", 0, relation=Relation.TRUSTEE_OF)

    assert engine.state.graph.resolve_ubo("t1").conclusion is Conclusion.IDENTIFIED


# -- honesty about coverage ------------------------------------------------


def test_the_control_limb_is_declared_unevaluated(engine):
    """1.3.3(a)(ii) is part of the test and this system cannot assess it.

    Saying so on every result is the difference between an incomplete answer
    and a misleading one.
    """
    person(engine, "p1")
    company(engine, "c1")
    owns(engine, "p1", "c1", 100)

    result = engine.state.graph.resolve_ubo("c1")
    assert any("1.3.3(a)(ii)" in limb for limb in result.limbs_not_evaluated)
    assert any("not evaluated" in limb for limb in result.limbs_not_evaluated)


def test_cycle_through_detects_the_closing_edge(engine):
    for c in ("c1", "c2"):
        company(engine, c)
    owns(engine, "c1", "c2", 50)
    owns(engine, "c2", "c1", 50)

    assert engine.state.graph.cycle_through("c2", "c1") is not None
    assert engine.state.graph.cycle_through("c1", "unrelated") is None
