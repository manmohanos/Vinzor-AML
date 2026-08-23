"""Clause 5.11's other half: a refresh owed because something changed.

The periodic sweep answers "has enough time passed". This answers "has the
customer stopped being the customer we checked" -- and the distinction that
makes it hard is that the triggering fact looks identical to a fact recorded
during onboarding. Only when it arrived tells them apart.
"""

from __future__ import annotations

import pytest

from vinzor.model import EventType, Relation, Role, Severity

from conftest import company, officer, owns, person


def rate(engine, entity_id, category, on, actor="Meera Nair"):
    if actor not in engine.actors():
        officer(engine, actor, Role.AML_OFFICER)
    return engine.assess_risk(
        entity_id=entity_id, category=category, actor=actor,
        role=Role.AML_OFFICER,
        reason="Recorded for the purposes of this test.", assessed_at=on)


def declare(engine, owner, owned, pct, when):
    return engine.ingest(
        event_type=EventType.OWNERSHIP_DECLARED, subject=owned,
        occurred_at=when,
        payload={"owner": owner, "owned": owned, "percentage": pct,
                 "relation": Relation.OWNS.value})


def triggered(cases):
    return [c for c in cases
            if any(p.policy_id == "POL_OWNERSHIP_CHANGED_AFTER_DILIGENCE"
                   for p in c.evidence)]


def book(engine):
    company(engine, "c1", "Meridian Capital Ltd")
    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Anita Rao")


# -- it fires when the customer has genuinely changed ------------------------


def test_ownership_changing_after_diligence_opens_a_file(engine):
    book(engine)
    owns(engine, "p1", "c1", 60.0)
    rate(engine, "c1", "MEDIUM", "2026-01-10")

    result = declare(engine, "p2", "c1", 55.0, "2026-06-01")
    opened = triggered(result.cases)
    assert opened, "the customer changed hands and nothing was opened"
    said = " ".join(p.summary for p in opened[0].evidence)
    assert "Meridian Capital Ltd" in said
    assert "Anita Rao" in said
    assert "2026-01-10" in said, "the file does not say when it was checked"


def test_the_file_cites_the_clause_that_requires_the_refresh(engine):
    book(engine)
    rate(engine, "c1", "MEDIUM", "2026-01-10")
    opened = triggered(declare(engine, "p2", "c1", 55.0, "2026-06-01").cases)
    cited = {str(c) for p in opened[0].evidence for c in p.citations}
    assert any("5.11" in c for c in cited)


def test_a_high_risk_customer_changing_hands_outranks_a_medium_one(engine):
    book(engine)
    company(engine, "c2", "Kestrel Holdings Ltd")
    rate(engine, "c1", "HIGH", "2026-01-10")
    rate(engine, "c2", "LOW", "2026-01-10")

    high = triggered(declare(engine, "p2", "c1", 55.0, "2026-06-01").cases)[0]
    low = triggered(declare(engine, "p2", "c2", 55.0, "2026-06-01").cases)[0]
    assert high.severity is Severity.HIGH
    assert low.severity is Severity.MEDIUM


# -- and not when it has not -------------------------------------------------


def test_ownership_declared_during_onboarding_is_not_a_change(engine):
    """The fact that makes this hard. An ownership declaration recorded while
    the customer is being onboarded is identical in every respect to one
    recorded two years later, except when it arrived. Treating the first as a
    trigger would open a file on every party the moment they were entered."""
    book(engine)
    owns(engine, "p1", "c1", 60.0)
    result = rate(engine, "c1", "MEDIUM", "2026-01-10")
    assert not triggered(result.cases)

    # Declared the same day the diligence was settled: still onboarding.
    same_day = declare(engine, "p2", "c1", 40.0, "2026-01-10")
    assert not triggered(same_day.cases), (
        "a declaration on the day of the assessment is part of it")


def test_a_customer_nobody_has_categorised_does_not_trigger(engine):
    """Re-KYC presupposes KYC. A party with no settled category has not been
    finished with, so their ownership arriving is diligence in progress --
    and the uncategorised figure on the regulatory page is what covers them,
    not a file saying their diligence is out of date."""
    book(engine)
    assert not triggered(declare(engine, "p1", "c1", 60.0, "2026-06-01").cases)


def test_the_same_change_is_not_reported_twice(engine):
    """Two owners declared in the same restructuring is one thing to look at,
    not two files. It becomes reportable again once the diligence is redone,
    because the key is the assessment it is measured against."""
    book(engine)
    person(engine, "p3", "Vikram Sen")
    rate(engine, "c1", "MEDIUM", "2026-01-10")

    first = triggered(declare(engine, "p2", "c1", 55.0, "2026-06-01").cases)
    second = triggered(declare(engine, "p3", "c1", 20.0, "2026-06-02").cases)
    assert first
    assert not second or second[0].case_id == first[0].case_id

    rate(engine, "c1", "MEDIUM", "2026-07-01")        # diligence redone
    later = triggered(declare(engine, "p3", "c1", 30.0, "2026-09-01").cases)
    assert later and later[0].case_id != first[0].case_id, (
        "a change after the refresh is a new matter")


def test_a_sanctions_hit_does_not_also_open_a_review_file(engine):
    """Each of those already opens its own file, at its own severity, citing
    the clause that governs it. A second quieter file saying "and also
    refresh the diligence" splits one matter across two records."""
    from conftest import screened

    book(engine)
    rate(engine, "c1", "MEDIUM", "2026-01-10")
    result = screened(engine, "c1", "SANCTIONS", matched=True)
    assert result.cases, "the sanctions hit itself should still open a file"
    assert not triggered(result.cases)
