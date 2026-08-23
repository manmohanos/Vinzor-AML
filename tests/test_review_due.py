"""A review that fell due, and the officer who has to hear about it.

The arithmetic behind this existed long before the sweep did. ``next_review``
worked, ``due_for_review`` worked, and both were called by their own tests and
by nothing else -- so a customer whose refresh date passed a year ago was
correctly computed as overdue and silently never mentioned anywhere. These
tests are mostly about the second half of that sentence.
"""

from __future__ import annotations

import pytest

from vinzor.model import EventType, Role

from conftest import officer, person


def rate(engine, entity_id, category, on, actor="Meera Nair"):
    if actor not in engine.actors():
        officer(engine, actor, Role.AML_OFFICER)
    engine.assess_risk(entity_id=entity_id, category=category, actor=actor,
                       role=Role.AML_OFFICER,
                       reason="Recorded for the purposes of this test.",
                       assessed_at=on)


def reviews(engine):
    return [e for e in engine.log
            if e.event_type is EventType.REVIEW_OVERDUE]


# -- it reaches somebody -----------------------------------------------------


def test_a_lapsed_review_becomes_a_file_on_the_sweep(engine):
    """The whole point. Every other assertion here is about not doing this
    twice, or not doing it wrongly -- this is the one about doing it."""
    person(engine, "p1", "Rohan Desai")
    rate(engine, "p1", "HIGH", "2024-01-10")

    opened = engine.observe_deadlines("2026-08-23")
    assert reviews(engine), "the sweep never noticed the review was owed"
    assert opened, "it was recorded but no file was opened"

    case = next(c for c in opened if c.subject == "p1")
    said = " ".join(piece.summary for piece in case.evidence)
    assert "2025-01-10" in said, "the file does not say when it fell due"
    assert "high risk" in said


def test_it_is_reported_once_not_every_time_a_page_loads(engine):
    """The log records that lateness was observed, not that it is still true
    whenever somebody looks."""
    person(engine, "p1", "Rohan Desai")
    rate(engine, "p1", "HIGH", "2024-01-10")

    engine.observe_deadlines("2026-08-23")
    first = len(reviews(engine))
    engine.observe_deadlines("2026-08-24")
    engine.observe_deadlines("2026-08-25")
    assert len(reviews(engine)) == first == 1


def test_refreshing_the_diligence_starts_the_clock_again(engine):
    """A review done is a review done: the next date moves, and the customer
    stops being overdue. When that later date passes it is a *new* lapse and
    is reported again -- which is why the due date is part of the key."""
    person(engine, "p1", "Rohan Desai")
    rate(engine, "p1", "HIGH", "2024-01-10")
    engine.observe_deadlines("2026-08-23")
    assert len(reviews(engine)) == 1

    rate(engine, "p1", "HIGH", "2026-08-23")           # the review happens
    engine.observe_deadlines("2026-09-01")
    assert len(reviews(engine)) == 1, "reported again after it was done"

    engine.observe_deadlines("2027-09-01")             # a year on, lapsed anew
    assert len(reviews(engine)) == 2
    assert reviews(engine)[-1].payload["due_on"] == "2027-08-23"


# -- what it must not report -------------------------------------------------


def test_a_review_not_yet_due_is_not_reported(engine):
    person(engine, "p1", "Rohan Desai")
    rate(engine, "p1", "LOW", "2026-01-10")
    engine.observe_deadlines("2026-08-23")
    assert not reviews(engine)


def test_an_uncategorised_customer_is_not_given_a_default_date(engine):
    """Clause 5.11 keys the interval to a category, so without one there is
    no date to be past. The thing that needs doing is the assessment, not the
    refresh, and inventing an interval here would report the wrong failure."""
    person(engine, "p1", "Rohan Desai")
    engine.observe_deadlines("2026-08-23")
    assert not reviews(engine)


def test_a_lapsed_review_is_reported_where_no_licence_is_recorded(engine):
    """Clause 5.11 measures from the day the diligence was last refreshed,
    which has nothing to do with when this firm's licence was granted.

    The filings sweep returns early when no licence date is on record, and
    this once made an unanswered regulator's notice invisible for a reason
    that had nothing to do with it. A customer review must not sit behind
    that same guard.
    """
    person(engine, "p1", "Rohan Desai")
    rate(engine, "p1", "HIGH", "2024-01-10")
    assert not engine.state.licence.granted_on

    engine.observe_deadlines("2026-08-23")
    assert reviews(engine), "hidden behind a guard about a different thing"


# -- how serious it is -------------------------------------------------------


def test_a_high_risk_lapse_outranks_a_low_risk_one(engine):
    """Clause 5.11 gives high-risk customers the shortest interval precisely
    because they need the most scrutiny, so a high-risk review lapsing is the
    more serious failure on the day it lapses."""
    from vinzor.model import Severity

    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Anita Rao")
    rate(engine, "p1", "HIGH", "2024-01-10")
    rate(engine, "p2", "MEDIUM", "2018-01-10")

    opened = {c.subject: c for c in engine.observe_deadlines("2026-08-23")}
    assert opened["p1"].severity is Severity.HIGH
    assert opened["p2"].severity is Severity.MEDIUM, (
        "a longer delay outranked the category, which is not what 5.11 says")


def test_the_file_says_which_rule_put_it_there(engine):
    person(engine, "p1", "Rohan Desai")
    rate(engine, "p1", "HIGH", "2024-01-10")
    case = next(c for c in engine.observe_deadlines("2026-08-23")
                if c.subject == "p1")
    assert any("5.11" in str(cited)
               for piece in case.evidence for cited in piece.citations)


def test_it_is_named_in_words_an_officer_reads(engine):
    """A finding shown as POL_REVIEW_OVERDUE is a finding nobody acts on."""
    from vinzor.briefing import GROUP_ACTIONS, GROUP_BECAUSE, GROUP_TITLE

    assert "POL_REVIEW_OVERDUE" in GROUP_TITLE
    assert "POL_REVIEW_OVERDUE" in GROUP_BECAUSE
    assert "POL_REVIEW_OVERDUE" in GROUP_ACTIONS
    assert "_" not in GROUP_TITLE["POL_REVIEW_OVERDUE"]


# -- the book, on the page ---------------------------------------------------


def test_a_book_nobody_has_categorised_does_not_read_as_a_clean_one(engine):
    """The whole reason this figure is on the page.

    A customer with no risk category has no review interval, so they cannot
    be overdue for one. That means a book nobody has categorised shows
    nothing overdue while being in the worst position it can be in -- this
    system's oldest mistake, on its most important page. The caveat is not
    decoration; it is the thing that makes the number above it honest.
    """
    from vinzor.briefing import regulatory

    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Anita Rao")

    page = regulatory(engine, "2026-08-23")
    assert "0 of 2" in page.customers_summary
    assert page.customers_caveat, (
        "two uncategorised customers and the page said nothing")
    assert "5.11" in page.customers_caveat


def test_the_caveat_goes_away_once_everyone_is_categorised(engine):
    """A caveat that is always on screen is a caveat nobody reads."""
    from vinzor.briefing import regulatory

    person(engine, "p1", "Rohan Desai")
    rate(engine, "p1", "LOW", "2026-01-10")

    page = regulatory(engine, "2026-08-23")
    assert not page.customers_caveat
    assert "1 of 1" in page.customers_summary
    assert "Not one of them is overdue" in page.customers_summary


def test_the_page_counts_a_lapsed_review(engine):
    from vinzor.briefing import regulatory

    person(engine, "p1", "Rohan Desai")
    rate(engine, "p1", "HIGH", "2024-01-10")

    page = regulatory(engine, "2026-08-23")
    assert "1 is overdue for review" in page.customers_summary


def test_an_empty_book_says_so_rather_than_reporting_nothing_overdue(engine):
    """Nought of nought carrying a category is not a compliance position."""
    from vinzor.briefing import regulatory

    page = regulatory(engine, "2026-08-23")
    assert "No customers are on the book yet." == page.customers_summary
    assert not page.customers_caveat
