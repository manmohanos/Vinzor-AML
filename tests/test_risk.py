"""How risky a customer is, under the regulator's own list of factors.

Clause 4.2 names nineteen things to take into account and then says the
presence of one or more of them "may not always indicate a high risk". So
the property these tests hold hardest is the negative one: nothing here
computes a category. The records gather evidence, a named person weighs it,
and the category is attributable to them.
"""

from __future__ import annotations

import re

import pytest

from vinzor.cases import DecisionDenied
from vinzor.engine import Vinzor, project
from vinzor.eventlog import EventLog
from vinzor.model import (EntityKind, EventType, Outcome, Relation,
                          Role)
from vinzor.risk import (BY_REF, CALL_FOR_ACTION, FACTORS,
                         INCREASED_MONITORING, observe, unanswered)

from conftest import (WHEN, officer, owns, paid, person, register,
                      screened)

TODAY = "2026-08-19"


@pytest.fixture
def engine() -> Vinzor:
    engine = Vinzor(EventLog())
    officer(engine, "Meera Nair", Role.AML_OFFICER)
    return engine


_GOOD_REASON = "Weighed the factors; nothing points to high risk."


def assess(engine, entity_id, category="LOW", actor="Meera Nair",
           role=Role.AML_OFFICER, reason=_GOOD_REASON, answers=None):
    # ``reason`` is passed through exactly as given, including empty --
    # an ``or`` default here would quietly substitute a good reason for a
    # bad one and make the substance tests pass for the wrong reason.
    return engine.assess_risk(
        entity_id=entity_id, category=category, actor=actor, role=role,
        reason=reason, assessed_at=TODAY, answers=answers)


# -- the list is the regulator's ---------------------------------------------


def test_every_factor_is_a_clause_reference_and_a_sentence():
    assert len(FACTORS) == 19
    for factor in FACTORS:
        assert factor.ref.startswith("4.2(")
        assert factor.group
        assert len(factor.wording.split()) > 4, factor.ref
        assert not factor.wording.startswith("Whether")


def test_the_regulators_own_double_numbering_is_preserved():
    """Group (a) numbers two different items (iv). That is the document's
    numbering, and an officer looking up what we showed them has to find
    it there."""
    assert "4.2(a)(iv)" in BY_REF
    assert "4.2(a)(iv, second)" in BY_REF
    assert "nominee shareholders" in BY_REF["4.2(a)(iv)"].wording
    assert "asset holding" in BY_REF["4.2(a)(iv, second)"].wording


def test_the_two_fatf_lists_do_not_overlap():
    assert not (CALL_FOR_ACTION & INCREASED_MONITORING)
    assert "IR" in CALL_FOR_ACTION and "KP" in CALL_FOR_ACTION


# -- what the records can see for themselves ---------------------------------


def test_a_circular_ownership_is_an_unusual_structure(engine):
    register(engine, "c1", EntityKind.COMPANY, "Orion Holdings")
    register(engine, "c2", EntityKind.COMPANY, "Orion Trading")
    owns(engine, "c1", "c2", 60.0)
    owns(engine, "c2", "c1", 60.0)

    found = observe(engine, "c1")
    assert found["4.2(a)(ii)"].present is True
    assert "circle" in found["4.2(a)(ii)"].because


def test_a_trust_is_a_personal_asset_holding_arrangement(engine):
    register(engine, "t1", EntityKind.TRUST, "Harbour Trust")
    found = observe(engine, "t1")
    assert found["4.2(a)(iv, second)"].present is True
    assert "trust" in found["4.2(a)(iv, second)"].because


def test_a_company_is_not_an_asset_holding_arrangement(engine):
    register(engine, "c1", EntityKind.COMPANY, "Orion Trading")
    assert observe(engine, "c1")["4.2(a)(iv, second)"].present is False


def test_a_blacklisted_jurisdiction_lights_four_country_factors(engine):
    register(engine, "p1", EntityKind.PERSON, "Reza Farahani",
             nationality="IR")
    found = observe(engine, "p1")
    for ref in ("4.2(b)(i)", "4.2(b)(iii)", "4.2(b)(iv)", "4.2(b)(v)"):
        assert found[ref].present is True, ref
        assert "Iran" in found[ref].because
        assert "call for action" in found[ref].because


def test_a_greylisted_jurisdiction_is_not_a_sanctioned_one(engine):
    register(engine, "p1", EntityKind.PERSON, "Linh Tran",
             nationality="VN")
    found = observe(engine, "p1")
    assert found["4.2(b)(i)"].present is True
    assert "increased monitoring" in found["4.2(b)(i)"].because
    # Being watched is not being sanctioned, and the clause distinguishes them.
    assert found["4.2(b)(v)"].present is False


def test_an_unlisted_jurisdiction_is_answered_not_left_blank(engine):
    register(engine, "p1", EntityKind.PERSON, "Asha Mehta",
             nationality="SG")
    found = observe(engine, "p1")
    assert found["4.2(b)(v)"].present is False
    assert "neither FATF list" in found["4.2(b)(v)"].because


def test_the_country_finding_carries_the_date_it_was_true(engine):
    """A country list without its date is a claim about today that will
    quietly become false: the FATF revises these three times a year."""
    from vinzor.risk import FATF_AS_AT

    from vinzor.risk import _written

    register(engine, "p1", EntityKind.PERSON, "Reza Farahani",
             nationality="IR")
    because = observe(engine, "p1")["4.2(b)(v)"].because
    # Written as a person writes a date, not as a machine stores one.
    assert _written(FATF_AS_AT) in because
    assert FATF_AS_AT not in because


def test_a_payment_from_a_stranger_lights_the_channel_factor(engine):
    """This used to use an empty payer, which was the unrecorded-sender rule.
    That rule was removed on 21 August 2026; a named third party is what
    lights the factor now."""
    person(engine, "p1", "Rohan Desai")
    paid(engine, "p1", anomaly=None, payment_id="pay_1", payer="somebody_else")

    found = observe(engine, "p1")
    assert found["4.2(c)(iv)"].present is True
    # One such payment is not yet "frequent", and the clause says frequent.
    assert found["4.2(c)(vi)"].present is False


def test_a_payment_with_no_sender_is_not_reported_as_nothing_found(engine):
    """The honesty edit that had to go with the cut.

    4.2(c)(iv) used to collect two rules: a payment from another party, and a
    payment that arrived with no sender at all. When neither matched it wrote
    "no payment to this party has come from an unknown or unassociated
    sender". The second rule was removed on 21 August 2026, so nothing looks
    for a payment with no sender any more -- and that sentence became a claim
    of knowledge the system does not have, printed onto a regulatory risk
    factor.

    A payment with no sender arrives below and no file opens on it, which is
    correct. What must not happen is the factor reporting that nothing of the
    kind was found.
    """
    person(engine, "p1", "Rohan Desai")
    paid(engine, "p1", anomaly="SANCTIONED_PAYER", payment_id="pay_1")
    paid(engine, "p1", anomaly=None, payment_id="pay_2", payer="")

    because = observe(engine, "p1")["4.2(c)(iv)"].because
    assert "unknown" not in because.lower()
    assert "not examined" in because


def test_a_party_nobody_registered_cannot_be_observed(engine):
    with pytest.raises(KeyError):
        observe(engine, "nobody")


# -- nothing computes the category -------------------------------------------


def test_no_arrangement_of_factors_produces_a_category(engine):
    """The property the clause requires: findings do not add up to an
    answer. A party with a blacklisted jurisdiction and a circular
    structure still has no category until a person gives it one."""
    register(engine, "c1", EntityKind.COMPANY, "Orion Holdings",
             jurisdiction="IR")
    register(engine, "c2", EntityKind.COMPANY, "Orion Trading")
    owns(engine, "c1", "c2", 60.0)
    owns(engine, "c2", "c1", 60.0)

    found = observe(engine, "c1")
    assert any(o.present for o in found.values())
    assert engine.state.risk.get("c1") is None


def test_a_person_sets_the_category_and_it_is_theirs(engine):
    person(engine, "p1", "Rohan Desai")
    assess(engine, "p1", category="HIGH",
           reason="Ownership could not be established from what was given.")

    assessment = engine.state.risk["p1"]
    assert assessment.category == "HIGH"
    assert assessment.by == "Meera Nair"
    assert assessment.on == TODAY
    assert "Ownership could not be established" in assessment.reason


@pytest.mark.parametrize("role", [Role.AI, Role.VIEWER, Role.SYSTEM])
def test_no_automated_actor_may_set_a_risk_category(engine, role):
    """A category sets how often the customer is looked at again under
    clause 5.11, so an automated actor setting it would be an automated
    actor deciding how much scrutiny somebody gets."""
    person(engine, "p1", "Rohan Desai")
    officer(engine, "bot", role)
    with pytest.raises(DecisionDenied):
        assess(engine, "p1", actor="bot", role=role)
    assert "p1" not in engine.state.risk


def test_an_unenrolled_person_cannot_set_one_either(engine):
    person(engine, "p1", "Rohan Desai")
    with pytest.raises(DecisionDenied, match="not enrolled"):
        assess(engine, "p1", actor="intruder", role=Role.COMPLIANCE)


def test_a_forged_assessment_is_refused_on_replay_too(engine):
    person(engine, "p1", "Rohan Desai")
    engine.log.append(
        event_type=EventType.RISK_ASSESSED,
        subject="p1",
        occurred_at=TODAY,
        actor="bot",
        payload={"role": "AI", "category": "LOW", "reason": "Fine by me.",
                 "factors": {}},
    )
    with pytest.raises(DecisionDenied):
        project(engine.log)


@pytest.mark.parametrize("category", ["", "SEVERE", "4", "high risk"])
def test_only_the_three_bands_clause_5_11_names_are_accepted(engine,
                                                             category):
    person(engine, "p1", "Rohan Desai")
    with pytest.raises(ValueError, match="high, medium or low"):
        assess(engine, "p1", category=category)


@pytest.mark.parametrize("reason", ["", "  ", "ok", "checked", "looks fine"])
def test_a_category_needs_a_reason_that_says_something(engine, reason):
    person(engine, "p1", "Rohan Desai")
    with pytest.raises(ValueError):
        assess(engine, "p1", reason=reason)
    assert "p1" not in engine.state.risk


# -- what gets written down --------------------------------------------------


def test_what_the_records_saw_is_written_with_the_category(engine):
    """The evidence travels with the judgement. An inspector reading the
    assessment sees what was in front of the officer, not just what they
    concluded."""
    register(engine, "p1", EntityKind.PERSON, "Reza Farahani",
             nationality="IR")
    assess(engine, "p1", category="HIGH",
           reason="Jurisdiction is subject to a call for action.")

    saved = engine.state.risk["p1"].observations
    assert saved["4.2(b)(v)"].present is True
    assert "Iran" in saved["4.2(b)(v)"].because


def test_the_records_are_gathered_here_not_taken_from_the_caller(engine):
    """A browser that could assert "no factor is present" could hide a
    sanctioned jurisdiction from the permanent record."""
    register(engine, "p1", EntityKind.PERSON, "Reza Farahani",
             nationality="IR")
    assess(engine, "p1", category="LOW",
           reason="Nothing of concern was found in the papers.",
           answers={"4.2(b)(v)": {"present": False, "because": "no it isn't"}})

    saved = engine.state.risk["p1"].observations["4.2(b)(v)"]
    # The officer's answer is recorded as theirs, and the record still
    # holds what the data said -- the disagreement is visible, not resolved.
    assert saved.answered_by == "Meera Nair"
    event = next(e for e in engine.log
                 if e.event_type is EventType.RISK_ASSESSED)
    assert event.payload["factors"]["4.2(b)(v)"]["answered_by"] == "Meera Nair"


def test_a_person_may_answer_what_no_record_can_see(engine):
    person(engine, "p1", "Rohan Desai")
    assess(engine, "p1", category="HIGH",
           reason="The customer operates in a sector we treat as high risk.",
           answers={"4.2(a)(i)": {"present": True,
                                  "because": "Operates a cash-intensive "
                                             "business."}})
    saved = engine.state.risk["p1"].observations["4.2(a)(i)"]
    assert saved.present is True
    assert "cash-intensive" in saved.because
    assert saved.answered_by == "Meera Nair"


def test_factors_nobody_has_answered_are_listed_as_such(engine):
    """A party with a country recorded has the country factors answered
    from data; the factors no record can speak to stay open, and are
    listed rather than left to read as absent."""
    register(engine, "p1", EntityKind.PERSON, "Asha Mehta", nationality="SG")
    assess(engine, "p1")
    still_open = {f.ref for f in unanswered(engine.state.risk["p1"])}

    assert "4.2(b)(v)" not in still_open      # the data answered this one
    assert "4.2(a)(i)" in still_open          # only a person can answer this
    assert "4.2(c)(i)" in still_open


def test_a_party_with_no_country_has_its_country_factors_unanswered(engine):
    """Silence is not a clean answer. Where nothing has been recorded
    about where a party is from, the country factors stay open rather than
    reading as absent."""
    person(engine, "p1", "Rohan Desai")
    assess(engine, "p1")
    still_open = {f.ref for f in unanswered(engine.state.risk["p1"])}
    for ref in ("4.2(b)(i)", "4.2(b)(iii)", "4.2(b)(iv)", "4.2(b)(v)"):
        assert ref in still_open, ref


def test_an_assessment_survives_a_rebuild(engine):
    register(engine, "p1", EntityKind.PERSON, "Reza Farahani",
             nationality="IR")
    assess(engine, "p1", category="HIGH",
           reason="Jurisdiction is subject to a call for action.")

    rebuilt = engine.rebuild().risk["p1"]
    live = engine.state.risk["p1"]
    assert rebuilt.category == live.category
    assert rebuilt.by == live.by
    assert rebuilt.observations.keys() == live.observations.keys()


def test_the_reader_is_told_nothing_technical(engine):
    """Every factor wording and every finding reaches a screen."""
    from test_briefing import JARGON

    register(engine, "c1", EntityKind.COMPANY, "Orion Holdings",
             jurisdiction="IR")
    texts = [(f.ref, f.wording) for f in FACTORS]
    texts += [(ref, o.because) for ref, o in observe(engine, "c1").items()]

    offences = []
    for where, text in texts:
        for pattern, what in JARGON:
            found = re.search(pattern, text)
            if found:
                offences.append(f"{where}: {what} ({found.group(0)!r})")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


# -- when the customer must be looked at again: clause 5.11 ------------------


def test_the_three_default_intervals_are_the_clauses(engine):
    from vinzor.risk import next_review

    assert next_review("HIGH", "2026-08-19").on == "2027-08-19"
    assert next_review("MEDIUM", "2026-08-19").on == "2029-08-19"
    assert next_review("LOW", "2026-08-19").on == "2031-08-19"


def test_a_customer_inside_an_indian_financial_group_is_refreshed_less_often():
    """The proviso inserted on 2 January 2026: the group already holds the
    diligence, so the interval lengthens rather than shortens."""
    from vinzor.risk import next_review

    assert next_review("HIGH", "2026-08-19",
                       in_financial_group=True).on == "2028-08-19"
    assert next_review("MEDIUM", "2026-08-19",
                       in_financial_group=True).on == "2034-08-19"
    assert next_review("LOW", "2026-08-19",
                       in_financial_group=True).on == "2036-08-19"


def test_where_the_group_disagrees_the_stricter_interval_wins():
    """The second proviso. This is the rule an experienced officer is most
    likely to get wrong from memory, which is the reason to compute it."""
    from vinzor.risk import next_review

    due = next_review("LOW", "2026-08-19", in_financial_group=True,
                      group_category="HIGH")
    assert due.on == "2028-08-19"          # two years, not ten
    assert due.years == 2
    assert "stricter of the two" in due.because
    assert "high risk" in due.because and "low" in due.because


def test_where_the_group_would_be_slacker_ours_still_applies():
    from vinzor.risk import next_review

    due = next_review("HIGH", "2026-08-19", in_financial_group=True,
                      group_category="LOW")
    assert due.years == 2
    assert "ours applies" in due.because


def test_a_review_date_never_lands_on_a_day_that_does_not_exist():
    from vinzor.risk import next_review

    assert next_review("HIGH", "2024-02-29").on == "2025-02-28"
    assert next_review("MEDIUM", "2024-02-29").on == "2027-02-28"
    # And a leap year that does have the day keeps it.
    assert next_review("LOW", "2024-02-29").on == "2029-02-28"


def test_an_uncategorised_customer_has_no_review_date():
    from vinzor.risk import next_review

    assert next_review("", "2026-08-19") is None
    assert next_review("SEVERE", "2026-08-19") is None


def test_a_customer_whose_refresh_has_come_due_is_listed(engine):
    from vinzor.risk import due_for_review

    person(engine, "p1", "Rohan Desai")
    engine.assess_risk(entity_id="p1", category="HIGH", actor="Meera Nair",
                       role=Role.AML_OFFICER,
                       reason="Ownership could not be established.",
                       assessed_at="2024-01-10")

    assert due_for_review(engine, "2026-08-19")
    entity_id, assessment, due = due_for_review(engine, "2026-08-19")[0]
    assert entity_id == "p1"
    assert due.on == "2025-01-10"
    assert "clause 5.11" in due.because

    # A day before it falls due, it is not on the list.
    assert not due_for_review(engine, "2024-12-31")


def test_an_uncategorised_party_is_not_quietly_given_a_default(engine):
    """Clause 5.11 keys the interval to a category. Without one there is no
    date to be past, and what needs doing is the assessment -- so the party
    belongs on the never-assessed list, not the overdue one."""
    from vinzor.risk import due_for_review, never_assessed

    person(engine, "p1", "Rohan Desai")
    assert not due_for_review(engine, "2099-01-01")
    assert "p1" in never_assessed(engine)


def test_once_assessed_a_party_leaves_the_never_assessed_list(engine):
    from vinzor.risk import never_assessed

    person(engine, "p1", "Rohan Desai")
    assess(engine, "p1")
    assert "p1" not in never_assessed(engine)


def test_a_deep_chain_is_an_excessively_complex_structure(engine):
    """An owner can be reached by more than one route; the longest is what
    makes a structure hard to follow. Reading the wrong attribute here
    raised on every real party until the dataset sweep caught it."""
    register(engine, "c1", EntityKind.COMPANY, "Layer One")
    register(engine, "c2", EntityKind.COMPANY, "Layer Two")
    register(engine, "c3", EntityKind.COMPANY, "Layer Three")
    register(engine, "c4", EntityKind.COMPANY, "Layer Four")
    register(engine, "p1", EntityKind.PERSON, "Asha Mehta")
    owns(engine, "p1", "c4", 100.0)
    owns(engine, "c4", "c3", 100.0)
    owns(engine, "c3", "c2", 100.0)
    owns(engine, "c2", "c1", 100.0)

    found = observe(engine, "c1")
    assert found["4.2(a)(ii)"].present is True
    assert "layers" in found["4.2(a)(ii)"].because


def test_a_short_chain_is_not_complex(engine):
    register(engine, "c1", EntityKind.COMPANY, "Orion Trading")
    register(engine, "p1", EntityKind.PERSON, "Asha Mehta")
    owns(engine, "p1", "c1", 100.0)

    found = observe(engine, "c1")
    assert found["4.2(a)(ii)"].present is False
    assert "resolves to a named person" in found["4.2(a)(ii)"].because


# -- what the officer sees ---------------------------------------------------


def test_the_party_page_shows_the_evidence_before_anyone_has_judged(engine):
    """The panel exists to put evidence in front of the person who has to
    weigh it, so it is populated before a category is ever set."""
    from vinzor.briefing import party

    register(engine, "p1", EntityKind.PERSON, "Reza Farahani",
             nationality="IR")
    page = party(engine, "p1", today=TODAY)

    assert page.risk_category == ""
    assert "Nobody has categorised this customer yet" in page.risk_summary
    assert any(f.ref == "4.2(b)(v)" and f.present for f in page.risk_factors)
    assert "have not been answered" in page.risk_unanswered


def test_the_party_page_shows_the_category_and_the_next_date(engine):
    from vinzor.briefing import party

    person(engine, "p1", "Rohan Desai")
    engine.assess_risk(entity_id="p1", category="HIGH", actor="Meera Nair",
                       role=Role.AML_OFFICER,
                       reason="Ownership could not be established.",
                       assessed_at="2026-01-10")
    page = party(engine, "p1", today=TODAY)

    assert page.risk_category == "HIGH"
    assert "High risk, set by Meera Nair" in page.risk_summary
    assert "10 January 2026" in page.risk_summary
    assert "10 January 2027" in page.risk_due
    assert "clause 5.11" in page.risk_due


def test_a_review_already_past_is_worded_as_past(engine):
    from vinzor.briefing import party

    person(engine, "p1", "Rohan Desai")
    engine.assess_risk(entity_id="p1", category="HIGH", actor="Meera Nair",
                       role=Role.AML_OFFICER,
                       reason="Ownership could not be established.",
                       assessed_at="2024-01-10")
    page = party(engine, "p1", today=TODAY)
    assert page.risk_due.startswith("Was due")


def test_the_page_says_the_categorisation_is_confidential(engine):
    """Clause 4.1(d): the category and its reasons are kept from the
    customer to avoid tipping off. An officer who does not know that could
    read it out on a call."""
    from vinzor.briefing import party

    person(engine, "p1", "Rohan Desai")
    page = party(engine, "p1", today=TODAY)
    assert "confidential" in page.risk_caveat
    assert "4.1(d)" in page.risk_caveat
    assert "tipped off" in page.risk_caveat


# -- what the watchlists found, beside the factors --------------------------


def test_a_watchlist_match_is_not_filed_under_a_clause_4_2_factor(engine):
    """None of the nineteen covers a watchlist match: (a) is the customer's
    structure and sector, (b) countries, (c) products and channels.
    Screening is clause 5.9, and public office is clause 5.5. Filing it
    under a 4.2 bullet that does not say it would be an invented citation."""
    from vinzor.risk import what_screening_found

    person(engine, "p1", "Kwame Mensah")
    screened(engine, "p1", "PEP")

    found = what_screening_found(engine, "p1")
    assert found.matched
    assert "PEP" in found.kinds
    # and it appears in no factor observation
    assert all(o.present is not True or "watchlist" not in o.because
               for o in observe(engine, "p1").values())


def test_the_match_is_described_in_the_products_own_words(engine):
    from vinzor.risk import what_screening_found

    person(engine, "p1", "Kwame Mensah")
    screened(engine, "p1", "PEP")
    summary = what_screening_found(engine, "p1").summary
    assert "may hold or be close to public office" in summary
    assert "PEP" not in summary


def test_an_open_file_about_the_match_is_counted(engine):
    from vinzor.risk import what_screening_found

    person(engine, "p1", "Vladimir Listed")
    screened(engine, "p1", "SANCTIONS")
    found = what_screening_found(engine, "p1")
    assert found.open_files == 1
    assert "1 file is still open" in found.summary


def test_a_match_still_shows_after_its_file_is_settled(engine):
    """An officer categorising somebody needs to know they matched, not
    only that somebody once had a file about it."""
    from vinzor.risk import what_screening_found

    person(engine, "p1", "Vladimir Listed")
    screened(engine, "p1", "SANCTIONS")
    case = engine.queue()[0]
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  rationale="Different date of birth; not the same person.",
                  decided_at=TODAY)

    found = what_screening_found(engine, "p1")
    assert found.matched
    assert found.open_files == 0
    assert "still open" not in found.summary


def test_a_clean_check_says_so_rather_than_saying_nothing(engine):
    """This asked for a sentence and got one -- but the sentence it settled
    for, "No watchlist check on this party has found anything", was equally
    true of a party nobody had ever screened, and read as reassurance
    either way. A clean check now says which day it was, which is a thing
    only a check that happened can say."""
    from vinzor.risk import what_screening_found

    person(engine, "p1", "Rohan Desai")
    screened(engine, "p1", "SANCTIONS", matched=False)
    found = what_screening_found(engine, "p1")
    assert not found.matched
    assert found.ever_checked
    assert "found nothing against this party" in found.summary
    assert found.last_checked in found.summary or "August" in found.summary


def test_public_office_carries_the_guidance_that_it_is_not_automatically_high(
        engine):
    """Guidance Note (4) under clause 5.5 says a Regulated Entity should
    not automatically treat everyone in public office as high risk. That is
    the same instruction clause 4.2 gives, and the officer about to
    categorise should see the regulator saying it."""
    from vinzor.risk import what_screening_found

    person(engine, "p1", "Kwame Mensah")
    screened(engine, "p1", "PEP")
    guidance = " ".join(what_screening_found(engine, "p1").guidance)
    assert "should not automatically treat" in guidance
    assert "clause 5.5" in guidance
    assert "5.5(b)" in guidance and "5.6" in guidance


def test_a_sanctions_match_carries_no_public_office_guidance(engine):
    from vinzor.risk import what_screening_found

    person(engine, "p1", "Vladimir Listed")
    screened(engine, "p1", "SANCTIONS")
    assert what_screening_found(engine, "p1").guidance == ()


def test_the_party_page_puts_the_match_above_the_category(engine):
    from vinzor.briefing import party

    person(engine, "p1", "Kwame Mensah")
    screened(engine, "p1", "PEP")
    page = party(engine, "p1", today=TODAY)
    assert "may hold or be close to public office" in page.risk_screening
    assert page.risk_guidance
    assert "should not automatically treat" in " ".join(page.risk_guidance)
