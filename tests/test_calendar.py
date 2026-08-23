"""The obligation calendar — what is owed to IFSCA, and when.

Built because Karvy Broking lost its registration for quarterly reports it
never filed, and nothing in this system knew anything was due.
"""

from __future__ import annotations

import threading

import pytest

from vinzor.calendar import (
    DUE_SOON_DAYS,
    LATE_CHARGE_USD_PER_MONTH,
    QUARTERLY_REPORT_DAYS,
    Obligation,
    Status,
    financial_year,
    instances,
    outstanding,
    overdue,
)
from vinzor.licence import Category
from vinzor.model import EventType, Severity

from conftest import company
from test_licence import staffed

GRANTED = "2025-01-10"


def licensed(engine, granted=GRANTED):
    """A staffed licence, granted on a known date."""
    staffed(engine, Category.REGISTERED_NON_RETAIL)
    engine.state.licence.granted_on = granted
    return engine


def filed(engine, obligation, period, on):
    return engine.ingest(
        event_type=EventType.FILING_SUBMITTED, subject="fme_1", occurred_at=on,
        payload={"obligation": obligation.value, "period": period, "submitted_on": on},
    )


# -- the schedule itself ---------------------------------------------------


def test_the_indian_financial_year_runs_april_to_march():
    from datetime import date

    assert financial_year(date(2026, 3, 31)) == 2025
    assert financial_year(date(2026, 4, 1)) == 2026


def test_a_quarterly_report_is_due_twenty_one_days_after_the_quarter():
    quarterly = [i for i in instances(GRANTED, "2025-12-31")
                 if i.obligation is Obligation.QUARTERLY_REPORT]
    q1 = next(i for i in quarterly if i.period == "Q1 FY2025-26")
    assert q1.period_end == "2025-06-30"
    assert q1.due_on == "2025-07-21"
    assert QUARTERLY_REPORT_DAYS == 21


def test_all_four_quarters_appear_in_a_full_year():
    quarterly = [i for i in instances("2025-04-01", "2026-06-30")
                 if i.obligation is Obligation.QUARTERLY_REPORT]
    assert [i.period for i in quarterly] == [
        "Q1 FY2025-26", "Q2 FY2025-26", "Q3 FY2025-26", "Q4 FY2025-26",
        "Q1 FY2026-27",
    ]


def test_the_annual_fee_falls_due_on_the_thirtieth_of_april():
    fees = [i for i in instances(GRANTED, "2026-12-31")
            if i.obligation is Obligation.FLAT_RECURRING_FEE]
    assert [(i.period, i.due_on) for i in fees] == [
        ("FY2025-26", "2025-04-30"),
        ("FY2026-27", "2026-04-30"),
    ]


def test_no_annual_fee_for_the_year_the_licence_was_granted():
    """The circular handles the year of grant pro rata on grant instead.

    A licence granted 10 January 2025 falls in FY2024-25, so that year carries
    no annual fee and the first one is FY2025-26, due 30 April 2025. Getting
    this backwards would invent a deadline that never existed.
    """
    fees = [i for i in instances(GRANTED, "2026-12-31")
            if i.obligation is Obligation.FLAT_RECURRING_FEE]
    assert "FY2024-25" not in {i.period for i in fees}

    # ...and a licence granted in April is in the *new* year, so its first
    # annual fee is the April after.
    april = [i for i in instances("2025-04-15", "2026-12-31")
             if i.obligation is Obligation.FLAT_RECURRING_FEE]
    assert [i.period for i in april] == ["FY2026-27"]


def test_the_annual_fee_period_end_falls_inside_its_own_financial_year():
    """period_end must mark the end of the FY named in ``period``, not the FY before it.

    CONDITIONAL_RECURRING_FEE for "FY2025-26" used to set period_end to
    2025-03-31 -- the last day of FY2024-25, before FY2025-26 even starts, and
    before its own due_on of 2025-04-30. A field meant to say "this fee
    relates to the period ending here" cannot point at a date the period
    hasn't reached yet.
    """
    fees = [i for i in instances(GRANTED, "2026-12-31")
            if i.obligation is Obligation.CONDITIONAL_RECURRING_FEE]
    by_period = {i.period: i.period_end for i in fees}
    assert by_period["FY2025-26"] == "2026-03-31"
    assert by_period["FY2026-27"] == "2027-03-31"


def test_period_end_always_falls_within_the_financial_year_named_in_period():
    """Regression sweep: period_end must belong to the FY that ``period`` names,
    for every instance this module produces, across many years -- not just the
    one hand-picked FY2025-26 example that surfaced the bug.

    CONDITIONAL_RECURRING_FEE and FLAT_RECURRING_FEE used to set period_end to
    31 March of the year *before* the one in their own period label (so
    "FY2025-26" got period_end 2025-03-31, which is the last day of FY2024-25
    -- a different year than the one named). ``financial_year(period_end)``
    must equal the FY encoded in ``period`` for every obligation this module
    emits, quarterly or annual.
    """
    from datetime import date

    for grant_year in range(2020, 2031):
        granted = f"{grant_year}-01-10"
        today = f"{grant_year + 5}-12-31"
        for i in instances(granted, today):
            if "FY" not in i.period:
                # The one-time obligations (FINGate, NISM) name no financial
                # year on purpose: there is no period, only a deadline. Their
                # own invariant is checked in the random sweep below.
                continue
            named_fy = int(i.period.split("FY")[1][:4])
            period_end = date.fromisoformat(i.period_end)
            assert financial_year(period_end) == named_fy, (
                f"{i.obligation.value} {i.period}: period_end {i.period_end} "
                f"falls in FY{financial_year(period_end)}, not the FY{named_fy} "
                f"its own period label names"
            )


def test_the_annual_fee_period_end_no_longer_precedes_its_own_due_on():
    """The specific bug: CONDITIONAL_RECURRING_FEE FY2025-26 had period_end
    2025-03-31, which is before its own due_on of 2025-04-30 -- a field meant
    to mark when the period a fee relates to *ends* pointed at a date before
    the deadline to pay it. After the fix period_end is 2026-03-31, correctly
    on or after due_on."""
    from datetime import date

    fee = next(i for i in instances(GRANTED, "2026-12-31")
               if i.obligation is Obligation.CONDITIONAL_RECURRING_FEE
               and i.period == "FY2025-26")
    assert date.fromisoformat(fee.period_end) >= date.fromisoformat(fee.due_on)


def test_the_schedule_is_derived_not_stored():
    """Same inputs, same answer. No clock, no state, no ordering wobble."""
    a = instances(GRANTED, "2026-08-12")
    b = instances(GRANTED, "2026-08-12")
    assert [i.key for i in a] == [i.key for i in b]


# -- status ----------------------------------------------------------------


def test_status_moves_from_upcoming_through_due_soon_to_overdue():
    q1 = next(i for i in instances("2026-04-01", "2026-12-31")
              if i.period == "Q1 FY2026-27"
              and i.obligation is Obligation.QUARTERLY_REPORT)
    assert q1.due_on == "2026-07-21"
    assert q1.status("2026-07-01") is Status.UPCOMING
    assert q1.status("2026-07-20") is Status.DUE_SOON
    assert q1.status("2026-07-21") is Status.DUE_SOON  # due today is not late
    assert q1.status("2026-07-22") is Status.OVERDUE


def test_due_soon_is_a_product_choice_not_a_regulatory_one():
    """There is no warning period in the circular; ours is stated, not implied."""
    assert DUE_SOON_DAYS == 7


def test_something_filed_is_never_overdue(engine):
    licensed(engine)
    filed(engine, Obligation.QUARTERLY_REPORT, "Q4 FY2024-25", "2025-04-15")
    left = outstanding(GRANTED, "2026-08-12", engine.state.calendar.submitted)
    assert "Q4 FY2024-25" not in {i.period for i in left}


def test_the_late_charge_is_a_hundred_dollars_a_month_or_part_of_one():
    q = next(i for i in instances("2026-04-01", "2026-12-31")
             if i.period == "Q1 FY2026-27"
             and i.obligation is Obligation.QUARTERLY_REPORT)
    assert LATE_CHARGE_USD_PER_MONTH == 100
    assert q.late_charge_usd("2026-07-21") == 0
    assert q.late_charge_usd("2026-07-22") == 100      # one day is one month
    assert q.late_charge_usd("2026-08-25") == 200      # 35 days is two


def test_a_fee_carries_no_late_submission_charge():
    """The charge in the circular is for returns, not for the fee itself."""
    fee = next(i for i in instances(GRANTED, "2026-12-31")
               if i.obligation is Obligation.FLAT_RECURRING_FEE)
    assert fee.late_charge_usd("2026-12-31") == 0


def test_a_return_is_filed_and_a_fee_is_paid():
    from vinzor.calendar import BY_OBLIGATION

    assert BY_OBLIGATION[Obligation.QUARTERLY_REPORT].verb == "filed"
    assert BY_OBLIGATION[Obligation.FLAT_RECURRING_FEE].verb == "paid"


# -- observing lateness ----------------------------------------------------


def test_observing_deadlines_opens_a_case_for_each_overdue_item(engine):
    licensed(engine)
    opened = engine.observe_deadlines("2026-08-12")
    assert opened
    assert {c.case_type for c in opened} == {"FILING"}
    late = overdue(GRANTED, "2026-08-12")
    assert len(opened) == len(late)


def test_lateness_is_reported_once_not_every_time_someone_looks(engine):
    licensed(engine)
    first = engine.observe_deadlines("2026-08-12")
    before = len(engine.log)
    second = engine.observe_deadlines("2026-08-12")

    assert first and second == []
    assert len(engine.log) == before, "a second look must write nothing"


def test_a_new_deadline_passing_is_still_picked_up(engine):
    licensed(engine)
    engine.observe_deadlines("2026-07-01")
    later = engine.observe_deadlines("2026-08-12")
    assert any(c.evidence[0].detail["period"] == "Q1 FY2026-27" for c in later)


def test_two_people_opening_the_screen_at_once_do_not_double_report(engine):
    """A breach is recorded once however many people are looking.

    The served screen observes deadlines on every request, and the server
    hands each request to its own thread. Deciding what is newly late and
    recording it has to be one indivisible act: threads that each read the
    'already reported' set before any of them wrote to it all concluded the
    same filing was newly late, and the log carried the same breach several
    times -- permanently, because nothing can be removed from it. The officer
    then saw one period twice, at two different severities.
    """
    licensed(engine)
    start = threading.Barrier(6)
    failures: list[BaseException] = []

    def look() -> None:
        try:
            start.wait()
            engine.observe_deadlines("2026-08-12")
        except BaseException as exc:  # a crash here is also a failure
            failures.append(exc)

    watchers = [threading.Thread(target=look) for _ in range(6)]
    for w in watchers:
        w.start()
    for w in watchers:
        w.join()

    assert not failures, failures
    reported = [
        (e.payload["obligation"], e.payload["period"])
        for e in engine.log.read()
        if e.event_type is EventType.FILING_OVERDUE
    ]
    assert len(reported) == len(set(reported)), "the same breach was recorded twice"
    assert sorted(reported) == sorted(
        (i.obligation.value, i.period) for i in overdue(GRANTED, "2026-08-12")
    )
    assert engine.verify()[0]

def test_the_first_missed_return_is_serious_and_a_pattern_is_critical(engine):
    licensed(engine)
    opened = engine.observe_deadlines("2026-08-12")
    assert opened[0].severity is Severity.HIGH
    assert opened[0].evidence[0].policy_id == "POL_FILING_OVERDUE"
    assert any(c.severity is Severity.CRITICAL for c in opened[1:])
    assert any(c.evidence[0].policy_id == "POL_FILING_REPEATEDLY_LATE"
               for c in opened[1:])


def test_the_case_records_the_charge_that_has_accrued(engine):
    licensed(engine)
    opened = engine.observe_deadlines("2026-08-12")
    report = next(c for c in opened
                  if c.evidence[0].detail["obligation"] == "QUARTERLY_REPORT")
    assert report.evidence[0].detail["late_charge_usd"] > 0
    assert report.evidence[0].detail["days_late"] > 0


def test_nothing_is_observed_without_a_licence(engine):
    company(engine, "fme_1", "Acme GIFT Fund Managers Ltd")
    assert engine.observe_deadlines("2026-08-12") == []


def test_filing_before_the_deadline_means_no_case(engine):
    licensed(engine, granted="2026-04-01")
    filed(engine, Obligation.QUARTERLY_REPORT, "Q1 FY2026-27", "2026-07-10")
    opened = engine.observe_deadlines("2026-07-25")
    assert not any(c.evidence[0].detail["period"] == "Q1 FY2026-27" for c in opened)


# -- what a person sees ----------------------------------------------------


def test_the_briefing_shows_what_is_coming_before_it_is_a_problem(engine):
    from vinzor.briefing import brief

    licensed(engine, granted="2026-04-01")
    briefing = brief(engine, person="Rohan Kapoor", today="2026-07-18")

    assert briefing.coming_up
    item = briefing.coming_up[0]
    assert "quarterly report" in item.what
    assert "21 July 2026" in item.when
    assert item.pressing is True


def test_an_overdue_item_is_a_case_not_a_reminder(engine):
    from vinzor.briefing import brief

    licensed(engine, granted="2026-04-01")
    engine.observe_deadlines("2026-08-12")
    briefing = brief(engine, person="Rohan Kapoor", today="2026-08-12")

    assert not any("Q1 FY2026-27" in d.what for d in briefing.coming_up)
    assert any("overdue" in g.title for g in briefing.groups)


def test_an_unpaid_fee_is_never_described_as_a_return_to_file(engine):
    """A return is filed; a fee is paid, and the screen must not confuse them.

    An officer holding an overdue fee used to be told to file a return in the
    IFSCA Downloads format. There is no such document: they would have filed
    nothing and still owed the money. The group text matters most, because it
    is the only explanation the screen draws for the whole group.
    """
    from vinzor.briefing import brief

    licensed(engine, granted="2024-01-15")
    engine.observe_deadlines("2026-08-12")
    briefing = brief(engine, person="Rohan Kapoor", today="2026-08-12")

    fee_groups = [g for g in briefing.groups if "fee" in g.title]
    assert fee_groups, "fees are not grouped separately from returns"
    for group in fee_groups:
        words = " ".join(group.because + group.to_close_this)
        assert "Downloads" not in words, words
        assert "File the" not in words, words
        assert any("Pay the" in a for a in group.to_close_this), group.to_close_this
        for item in group.items:
            assert "unpaid" in item.headline, item.headline

    # and a fee is not counted among the filings, nor a return among the fees
    for group in briefing.groups:
        if "filing" in group.title:
            assert not any("fee" in i.headline for i in group.items), group.title
        if "fee" in group.title:
            assert not any("report" in i.headline for i in group.items), group.title

def test_the_reader_is_told_in_plain_words(engine):
    from vinzor.briefing import brief

    licensed(engine)
    engine.observe_deadlines("2026-08-12")
    briefing = brief(engine, person="Rohan Kapoor", today="2026-08-12")

    group = next(g for g in briefing.groups if "overdue" in g.title)
    joined = " ".join(group.because) + " ".join(group.to_close_this)
    assert "has not been" in joined
    assert "21 calendar days" in group.rules[0].says
    assert "120" in {r.clause for r in group.rules}


# -- still a projection ----------------------------------------------------


def test_calendar_state_survives_a_replay(engine):
    licensed(engine)
    filed(engine, Obligation.QUARTERLY_REPORT, "Q1 FY2025-26", "2025-07-15")
    engine.observe_deadlines("2026-08-12")

    rebuilt = engine.rebuild()
    assert rebuilt.casebook.cases == engine.state.casebook.cases
    assert rebuilt.calendar.submitted == engine.state.calendar.submitted
    assert rebuilt.calendar.reported_late == engine.state.calendar.reported_late


# -- the late charge counts calendar months, not thirty-day blocks ----------
# It divided days by 30, so 21 July to 21 August — one month — billed as two.
# An over-charge invented by arithmetic is a number an officer gets asked to
# justify to the regulator.


def _quarterly(due_on="2025-07-21"):
    from vinzor.calendar import Instance, Obligation

    return Instance(obligation=Obligation.QUARTERLY_REPORT, period="Q1 FY2025-26",
                    period_end="2025-06-30", due_on=due_on)


def test_one_calendar_month_late_costs_one_month():
    assert _quarterly().late_charge_usd("2025-08-21") == 100


def test_a_day_past_the_month_costs_two():
    """"Every month or part thereof" — one day into the second month counts."""
    assert _quarterly().late_charge_usd("2025-08-22") == 200


def test_the_day_before_the_anniversary_still_costs_one():
    assert _quarterly().late_charge_usd("2025-08-20") == 100


def test_three_calendar_months_cost_three():
    assert _quarterly().late_charge_usd("2025-10-21") == 300


def test_a_short_month_does_not_add_a_charge():
    """31 January plus one month is 28 February, not 3 March. Rolling over
    would land the charge days early every time the due date is late."""
    assert _quarterly(due_on="2025-01-31").late_charge_usd("2025-02-28") == 100
    assert _quarterly(due_on="2025-01-31").late_charge_usd("2025-03-01") == 200


def test_nothing_is_owed_before_the_deadline():
    assert _quarterly().late_charge_usd("2025-07-20") == 0
    assert _quarterly().late_charge_usd("2025-07-21") == 0


# -- fuzzed against many random dates, not just the hand-picked ones --------
#
# The late charge and the schedule are exactly the kind of date arithmetic
# the property-based-testing literature warns hand-picked examples miss --
# month-end clamping and leap years interact in ways a handful of chosen
# dates can look right on and still hide a boundary case. There is no
# Hypothesis-style dependency here (the project takes none), so this is a
# seeded random walk over the same stdlib `date`/`timedelta` the code uses:
# deterministic across runs, but covering thousands of dates a human would
# not have picked by hand, including leap days and month-end clamps.


def _random_date(rng):
    from datetime import date

    year = rng.randint(2018, 2036)
    month = rng.randint(1, 12)
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days_in_month = [31, 29 if leap else 28, 31, 30, 31, 30,
                      31, 31, 30, 31, 30, 31][month - 1]
    day = rng.randint(1, days_in_month)
    return date(year, month, day)


def test_the_late_charge_matches_an_independent_month_count_across_many_random_dates():
    """late_charge_usd against a reference that counts month-anniversaries.

    The reference is built from ``_add_months`` too (there is no other
    definition of "a calendar month" to check against without a dependency),
    but it counts up one month at a time rather than computing a year/month
    delta and correcting it -- a structurally different route to the same
    answer, over 2,000 random due-dates (including leap days and month-end
    clamps) and random lateness in days. Before the fix documented above,
    dividing days by 30 disagreed with this reference at every exact
    anniversary of a 31-day month; this sweep is what would have caught it
    without anyone having to think of 21 July specifically.
    """
    import random
    from datetime import timedelta

    from vinzor.calendar import _add_months

    rng = random.Random(20260812)
    checked = 0
    for _ in range(2000):
        due = _random_date(rng)
        now = due + timedelta(days=rng.randint(1, 900))

        k = 1
        while _add_months(due, k) < now:
            k += 1
        expected = k * LATE_CHARGE_USD_PER_MONTH

        actual = _quarterly(due_on=due.isoformat()).late_charge_usd(now.isoformat())
        assert actual == expected, (due, now, expected, actual)
        checked += 1
    assert checked == 2000


def test_every_generated_instance_obeys_its_own_labelling_across_many_random_grants():
    """Sweep ``instances()`` itself over random grant dates, not just 10 January.

    Every instance this module ever emits must: have a unique key (nothing
    doubly billed), have a quarterly due_on exactly 21 days after its own
    period_end, and carry a period_end that falls inside the financial year
    its own ``period`` label names. 1,000 random grant dates, each looked at
    up to eight years out.
    """
    import random
    from datetime import date, timedelta

    rng = random.Random(20260813)
    for _ in range(1000):
        granted = _random_date(rng)
        today = granted + timedelta(days=rng.randint(0, 365 * 8))

        items = instances(granted.isoformat(), today.isoformat())
        keys = [i.key for i in items]
        assert len(keys) == len(set(keys)), (granted, today, "a period was billed twice")

        for item in items:
            period_end = date.fromisoformat(item.period_end)
            if "FY" in item.period:
                named_fy = int(item.period.split("FY")[1][:4])
                assert financial_year(period_end) == named_fy, (granted, today, item)
            else:
                # A one-time obligation: no period to mislabel, so its
                # invariant is that the deadline is its own anchor -- FINGate
                # is due the day it became owed, and a NISM clock ends four
                # months after it starts.
                due = date.fromisoformat(item.due_on)
                assert due >= period_end, (granted, today, item)
            if item.obligation is Obligation.QUARTERLY_REPORT:
                due = date.fromisoformat(item.due_on)
                assert due == period_end + timedelta(days=QUARTERLY_REPORT_DAYS), (
                    granted, today, item,
                )
