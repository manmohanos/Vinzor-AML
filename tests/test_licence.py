"""Licence scope and required offices — Regulations 3(4), 7, 10 and 137.

Built from IFSCA's published enforcement orders. Where a test mirrors a real
action, the docstring says which.
"""

from __future__ import annotations

import pytest

from vinzor.licence import (
    AUM_KMP_THRESHOLD_USD,
    Activity,
    Category,
    Office,
    PERMITTED,
)
from vinzor.model import EventType, Severity

from conftest import WHEN, company


def fme(engine, category=Category.REGISTERED_NON_RETAIL, when=WHEN):
    company(engine, "fme_1", "Acme GIFT Fund Managers Ltd")
    return engine.ingest(
        event_type=EventType.LICENCE_GRANTED, subject="fme_1", occurred_at=when,
        payload={"category": category.value, "number": "IFSCA/FME/II/2023-24/084"},
    )


def appoint(engine, office, person="Meera Nair", in_ifsc=True, when=WHEN):
    return engine.ingest(
        event_type=EventType.OFFICE_APPOINTED, subject="fme_1", occurred_at=when,
        payload={"office": office.value, "person": person, "based_in_ifsc": in_ifsc},
    )


def vacate(engine, office, when=WHEN):
    return engine.ingest(
        event_type=EventType.OFFICE_VACATED, subject="fme_1", occurred_at=when,
        payload={"office": office.value},
    )


def undertake(engine, activity, when=WHEN):
    return engine.ingest(
        event_type=EventType.ACTIVITY_UNDERTAKEN, subject="fme_1", occurred_at=when,
        payload={"activity": activity.value},
    )


def staffed(engine, category=Category.REGISTERED_NON_RETAIL):
    """A licence with every ordinarily-required post filled.

    Posts are appointed before the grant, which is the real sequence:
    Regulation 7 is a condition of registration, not something done
    afterwards.
    """
    company(engine, "fme_1", "Acme GIFT Fund Managers Ltd")
    appoint(engine, Office.PRINCIPAL_OFFICER, "Rohan Kapoor")
    appoint(engine, Office.COMPLIANCE_OFFICER, "Meera Nair")
    engine.ingest(
        event_type=EventType.LICENCE_GRANTED, subject="fme_1", occurred_at=WHEN,
        payload={"category": category.value,
                 "number": "IFSCA/FME/II/2023-24/084"},
    )
    return engine


# -- scope: Regulation 3(4) and 137 ----------------------------------------


def test_the_categories_nest_as_the_regulation_says():
    """3(4)(b) and (c) each include everything the category below may do."""
    assert PERMITTED[Category.AUTHORISED] < PERMITTED[Category.REGISTERED_NON_RETAIL]
    assert (PERMITTED[Category.REGISTERED_NON_RETAIL]
            < PERMITTED[Category.REGISTERED_RETAIL])


def test_a_permitted_activity_opens_nothing(engine):
    staffed(engine)
    assert undertake(engine, Activity.RESTRICTED_SCHEME).cases == []


def test_an_activity_outside_the_category_is_critical(engine):
    """Mirrors Ashoka WhiteOak and Bonanza: business outside the licence."""
    staffed(engine)
    result = undertake(engine, Activity.RETAIL_SCHEME)

    case = next(c for c in result.cases if c.case_type == "LICENCE_SCOPE")
    assert case.severity is Severity.CRITICAL
    assert case.evidence[0].policy_id == "POL_ACTIVITY_OUTSIDE_LICENCE"
    clauses = {c["clause"] for c in case.evidence[0].citations}
    assert clauses == {"137", "3(4)"}


def test_a_retail_licence_may_do_what_a_non_retail_one_may_not(engine):
    staffed(engine, Category.REGISTERED_RETAIL)
    scope = [c for c in undertake(engine, Activity.RETAIL_SCHEME).cases
             if c.case_type == "LICENCE_SCOPE"]
    assert scope == []


def test_an_authorised_fme_may_not_run_portfolio_management(engine):
    fme(engine, Category.AUTHORISED)
    appoint(engine, Office.PRINCIPAL_OFFICER, "Rohan Kapoor")
    scope = [c for c in undertake(engine, Activity.PORTFOLIO_MANAGEMENT_SERVICES).cases
             if c.case_type == "LICENCE_SCOPE"]
    assert len(scope) == 1


def test_with_no_licence_on_file_nothing_is_permitted(engine):
    """Fail closed. An unknown category must not read as unrestricted."""
    company(engine, "fme_1", "Acme GIFT Fund Managers Ltd")
    scope = [c for c in undertake(engine, Activity.RESTRICTED_SCHEME).cases
             if c.case_type == "LICENCE_SCOPE"]
    assert len(scope) == 1


# -- offices: Regulation 7 -------------------------------------------------


def test_a_new_licence_with_nobody_appointed_raises_both_posts(engine):
    cases = fme(engine).cases
    posts = {c.evidence[0].detail["office"] for c in cases}
    assert posts == {"PRINCIPAL_OFFICER", "COMPLIANCE_OFFICER"}
    assert all(c.severity is Severity.HIGH for c in cases)


def test_an_authorised_fme_needs_only_a_principal_officer(engine):
    """7(2) attaches to a Registered FME, not to an Authorised one."""
    cases = fme(engine, Category.AUTHORISED).cases
    posts = {c.evidence[0].detail["office"] for c in cases}
    assert posts == {"PRINCIPAL_OFFICER"}


def test_a_fully_staffed_licence_raises_nothing(engine):
    staffed(engine)
    assert engine.queue() == []


def test_a_resignation_reopens_the_question(engine):
    """The precondition for what IFSCA found at Neo Asset Management."""
    staffed(engine)
    result = vacate(engine, Office.COMPLIANCE_OFFICER, when="2026-03-01")

    case = result.cases[0]
    assert case.evidence[0].policy_id == "POL_OFFICE_VACANT"
    assert case.evidence[0].detail["office"] == "COMPLIANCE_OFFICER"
    assert {c["clause"] for c in case.evidence[0].citations} == {"7(2)", "10(1)"}


def test_a_holder_not_based_in_the_ifsc_is_a_finding(engine):
    """Regulation 7(5): appointed is not the same as present."""
    fme(engine)
    appoint(engine, Office.COMPLIANCE_OFFICER, "Meera Nair", in_ifsc=True)
    result = appoint(engine, Office.PRINCIPAL_OFFICER, "Rohan Kapoor", in_ifsc=False)

    case = next(c for c in result.cases
                if c.evidence[0].policy_id == "POL_OFFICE_NOT_BASED_IN_IFSC")
    assert "7(5)" in {c["clause"] for c in case.evidence[0].citations}
    assert case.evidence[0].detail["person"] == "Rohan Kapoor"


def test_the_case_says_what_it_cannot_see(engine):
    """No screen should imply the office was actually staffed on the day."""
    detail = fme(engine).cases[0].evidence[0].detail
    assert any("surprise visit" in note for note in detail["not_evaluated"])


# -- the AUM trigger: Regulation 7(4) --------------------------------------


def test_crossing_one_billion_requires_another_kmp(engine):
    staffed(engine)
    result = engine.ingest(
        event_type=EventType.AUM_REPORTED, subject="fme_1", occurred_at="2026-04-15",
        payload={"amount_usd": AUM_KMP_THRESHOLD_USD, "as_at": "2026-03-31"},
    )
    case = result.cases[0]
    assert case.evidence[0].detail["office"] == "FUND_MANAGEMENT_KMP"
    assert "7(4)" in {c["clause"] for c in case.evidence[0].citations}


def test_the_six_month_grace_period_is_derived_not_guessed(engine):
    """7(4) proviso: six months from the end of that financial year.

    31 March is the one as-at date where "six months from the as-at date"
    and "six months from the end of the financial year" happen to agree, so
    this alone cannot tell the two readings apart -- see the mid-year cases
    below for that.
    """
    staffed(engine)
    result = engine.ingest(
        event_type=EventType.AUM_REPORTED, subject="fme_1", occurred_at="2026-04-15",
        payload={"amount_usd": 2e9, "as_at": "2026-03-31"},
    )
    assert result.cases[0].evidence[0].detail["due_by"] == "2026-09-01"


def test_the_grace_period_for_a_mid_year_aum_report_uses_the_fy_end(engine):
    """An as-at date that isn't 31 March used to be answered wrong.

    Before the fix, ``_kmp_due_by`` added six months to the as-at date
    itself: an AUM report as at 2026-05-15 produced a due_by of
    2026-11-01. But the proviso runs six months from the end of the
    financial year the as-at date falls in -- 2026-05-15 sits in
    FY2026-27 (April 2026 to March 2027), so the grace period should run
    to six months past 31 March 2027, i.e. 2027-09-01, ten months later
    than the old (wrong) answer.
    """
    staffed(engine)
    result = engine.ingest(
        event_type=EventType.AUM_REPORTED, subject="fme_1", occurred_at="2026-06-01",
        payload={"amount_usd": 2e9, "as_at": "2026-05-15"},
    )
    assert result.cases[0].evidence[0].detail["due_by"] == "2027-09-01"


def test_the_grace_period_for_a_december_aum_report_uses_the_fy_end(engine):
    """Another mid-year as-at date the old formula got wrong.

    2026-12-31 also falls in FY2026-27 (which ends 31 March 2027), so it
    should carry the same due_by as the 15 May report above --
    2027-09-01. The old code, which added six months straight to the
    as-at date, produced 2027-06-01 instead.
    """
    staffed(engine)
    result = engine.ingest(
        event_type=EventType.AUM_REPORTED, subject="fme_1", occurred_at="2027-01-05",
        payload={"amount_usd": 2e9, "as_at": "2026-12-31"},
    )
    assert result.cases[0].evidence[0].detail["due_by"] == "2027-09-01"


def test_below_the_threshold_nothing_is_required(engine):
    staffed(engine)
    result = engine.ingest(
        event_type=EventType.AUM_REPORTED, subject="fme_1", occurred_at="2026-04-15",
        payload={"amount_usd": AUM_KMP_THRESHOLD_USD - 1, "as_at": "2026-03-31"},
    )
    assert result.cases == []


def test_a_retail_fme_needs_the_extra_kmp_once_it_launches(engine):
    """7(3): before the first retail scheme or ETF, not after."""
    staffed(engine, Category.REGISTERED_RETAIL)
    assert engine.queue() == []

    result = undertake(engine, Activity.EXCHANGE_TRADED_FUND)
    case = next(c for c in result.cases if c.case_type == "GOVERNANCE")
    assert case.evidence[0].detail["office"] == "FUND_MANAGEMENT_KMP"
    assert "7(3)" in {c["clause"] for c in case.evidence[0].citations}


# -- it is all still a projection ------------------------------------------


def test_filling_a_seat_updates_the_case_but_does_not_close_it(engine):
    """The file must not keep saying nobody is there once someone is.

    It also must not close itself: a person confirms the appointment was
    made and notified, and that confirmation is the audit record.
    """
    staffed(engine)
    vacate(engine, Office.COMPLIANCE_OFFICER, when="2026-03-01")
    opened = engine.queue()
    assert len(opened) == 1

    appoint(engine, Office.COMPLIANCE_OFFICER, "Anita Verma", when="2026-08-12")
    case = engine.state.casebook.get(opened[0].case_id)
    assert case.is_open, "only a person closes a Case"
    assert len(case.evidence) == 2
    latest = case.evidence[-1]
    assert latest.detail["resolved"] is True
    assert "Anita Verma" in latest.summary
    assert "2026-03-01" in latest.summary


def test_a_filled_post_never_reads_as_an_empty_one(engine):
    """The screen must not say a seat is empty when the log says it is not.

    Evidence accumulates on the open Case, and the briefing used to render
    line one -- the vacancy -- however many appointments came after it. A
    Principal Officer was told they had no compliance officer, in the record
    that goes to IFSCA, while the same system showed one appointed.
    """
    from vinzor.briefing import brief

    staffed(engine)
    vacate(engine, Office.COMPLIANCE_OFFICER, when="2026-03-01")
    appoint(engine, Office.COMPLIANCE_OFFICER, "Anita Verma", when="2026-08-12")
    assert engine.state.licence.holders[Office.COMPLIANCE_OFFICER].person == "Anita Verma"

    briefing = brief(engine, person="Rohan Kapoor", today="2026-08-13")
    words = " ".join(
        [g.title for g in briefing.groups]
        + [i.headline for g in briefing.groups for i in g.items]
        + [s for g in briefing.groups for i in g.items for s in i.because]
        + [s for g in briefing.groups for s in g.because]
    )
    assert "no compliance officer" not in words.lower(), words
    assert "unfilled" not in words.lower(), words
    assert "Anita Verma" in words, words
    # still on the list: an appointment is not complete until IFSCA is told
    assert engine.queue(), "the Case must stay open for a person to confirm"


def test_a_post_filled_after_the_grant_is_reported_as_filled(engine):
    """A seat can be empty without anyone having vacated it.

    Keying the refill off an explicit vacate meant a licence granted before
    the post was filled produced no 'filled' evidence at all, so the vacancy
    Case went on saying nobody held the post after somebody did.
    """
    fme(engine)  # a licence with nobody appointed
    assert engine.queue()

    result = appoint(engine, Office.PRINCIPAL_OFFICER, "Arjun Mehta", when="2026-08-12")
    assert result is not None
    case = next(c for c in engine.queue()
                if c.evidence[0].detail.get("office") == Office.PRINCIPAL_OFFICER.value)
    assert case.evidence[-1].detail.get("resolved") is True, [
        e.detail for e in case.evidence
    ]
    assert "Arjun Mehta" in case.evidence[-1].summary
def test_licence_state_survives_a_replay(engine):
    staffed(engine, Category.REGISTERED_RETAIL)
    undertake(engine, Activity.EXCHANGE_TRADED_FUND)
    vacate(engine, Office.PRINCIPAL_OFFICER)

    rebuilt = engine.rebuild()
    assert rebuilt.casebook.cases == engine.state.casebook.cases
    assert rebuilt.licence.category is engine.state.licence.category
    assert set(rebuilt.licence.holders) == set(engine.state.licence.holders)


def test_the_reader_is_told_in_plain_words(engine):
    from vinzor.briefing import brief

    staffed(engine)
    vacate(engine, Office.PRINCIPAL_OFFICER)
    undertake(engine, Activity.RETAIL_SCHEME)

    briefing = brief(engine, person="Meera Nair", today="2026-08-12")
    titles = " ".join(g.title for g in briefing.groups)
    assert "required post is unfilled" in titles
    assert "outside what your licence permits" in titles
    for group in briefing.groups:
        assert group.because and group.to_close_this and group.rules


# -- the KMP grace-period date maths, fuzzed rather than only at three dates -
#
# The three tests above each fix one specific bug found at one specific
# as-at date (31 March, 15 May, 31 December). They prove those three dates
# are right; they do not prove every day of the year is. This sweeps every
# day of many years, including leap days, against an independently-written
# reference for "six months past the end of the financial year this date
# falls in".


def test_the_kmp_due_by_matches_an_independent_reference_for_every_day_of_many_years():
    """``_kmp_due_by`` against a reference built the other direction.

    The production code computes the financial year, then walks forward
    ``fy_end_month + 6`` and carries the year with integer division. The
    reference here instead counts whole years and a month offset separately
    with no shared arithmetic step, so the two are unlikely to share a
    mistake. Run across every day of 2016-2035 (7,305 dates, leap days
    included), not just the three the earlier fixes were pinned to.
    """
    from datetime import date, timedelta

    from vinzor.licence import AUM_KMP_GRACE_MONTHS, Licence

    def reference_due_by(as_at: str) -> str:
        d = date.fromisoformat(as_at)
        fy = d.year if d.month >= 4 else d.year - 1
        fy_end = date(fy + 1, 3, 31)
        # Six months past the financial year end, landing on the 1st.
        total_months = fy_end.month + AUM_KMP_GRACE_MONTHS
        extra_years = (total_months - 1) // 12
        month = (total_months - 1) % 12 + 1
        return date(fy_end.year + extra_years, month, 1).isoformat()

    day = date(2016, 1, 1)
    end = date(2035, 12, 31)
    checked = 0
    while day <= end:
        licence = Licence()
        licence.aum_as_at = day.isoformat()
        assert licence._kmp_due_by() == reference_due_by(day.isoformat()), day
        checked += 1
        day += timedelta(days=1)
    assert checked == 7305
