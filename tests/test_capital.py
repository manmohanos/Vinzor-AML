"""The last two enforcement grounds: the money, and what was said about it.

Capital cost Darwin Platform Aircraft Leasing its registration -- minimum
capital never infused. Disclosure cost Prowess Insurance Brokers its
authorisation, and not for misstating a number: it "recorded reinsurance
income as risk management fees". What went on the record was not what
happened.

The tests that matter here are the restraint ones. The capital figures this
product ships with came from law-firm summaries rather than the
regulations, and every screen that uses them has to say so. And the
tempting disclosure rule -- that a reported figure must equal something
computed from the book -- is simply false, so most of what follows checks
that ordinary differences stay quiet.
"""

from __future__ import annotations

import pytest

from vinzor.capital import (NOT_CONFIRMED, PUBLISHED_EXTRA_FOR_THIRD_PARTY_USD,
                            PUBLISHED_MINIMUM_USD, in_words, required,
                            shortfall)
from vinzor.disclosure import Book, compare, nothing_behind_it
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.licence import Activity, Category
from vinzor.model import EntityKind, EventType, Role, Severity

WHEN = "2025-01-10"
TODAY = "2026-08-19"


@pytest.fixture
def engine() -> Vinzor:
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera Nair", role=Role.AML_OFFICER, enrolled_at=WHEN)
    engine.enroll(name="Priya Rao", role=Role.VIEWER, enrolled_at=WHEN)
    return engine


def licensed(engine, category=Category.REGISTERED_NON_RETAIL, activities=()):
    engine.ingest(
        event_type=EventType.LICENCE_GRANTED, subject="lic",
        occurred_at=WHEN, actor="system",
        payload={"category": category.value, "number": "lic"})
    # What the firm does is recorded as it does it, not declared on the
    # grant. The extra capital requirement keys off the activity, which is
    # a proxy for the authorisation and errs toward what is really
    # happening.
    for activity in activities:
        engine.ingest(
            event_type=EventType.ACTIVITY_UNDERTAKEN, subject="lic",
            occurred_at=WHEN, actor="system",
            payload={"activity": activity.value})


def files(engine, kind: str) -> list:
    return [case for case in engine.state.casebook.cases.values()
            if case.case_type == kind]


# -- how much is required ----------------------------------------------------


def test_the_minimum_follows_the_licence_category(engine):
    licensed(engine, Category.AUTHORISED)
    minimum, _confirmed, _why = required(engine.state.licence,
                                         engine.state.capital)
    assert minimum == PUBLISHED_MINIMUM_USD[Category.AUTHORISED]


def test_a_retail_licence_requires_more_than_an_authorised_one(engine):
    assert (PUBLISHED_MINIMUM_USD[Category.REGISTERED_RETAIL]
            > PUBLISHED_MINIMUM_USD[Category.REGISTERED_NON_RETAIL]
            > PUBLISHED_MINIMUM_USD[Category.AUTHORISED])


def test_managing_other_peoples_money_adds_to_it(engine):
    licensed(engine, Category.REGISTERED_NON_RETAIL,
             (Activity.PORTFOLIO_MANAGEMENT_SERVICES,))
    minimum, _confirmed, why = required(engine.state.licence,
                                        engine.state.capital)
    assert minimum == (PUBLISHED_MINIMUM_USD[Category.REGISTERED_NON_RETAIL]
                       + PUBLISHED_EXTRA_FOR_THIRD_PARTY_USD)
    assert "not the firm's own" in why


def test_the_extra_follows_what_the_firm_actually_does(engine):
    """A proxy, and worth knowing as one. The requirement as reported
    attaches to seeking the authorisation; what this system can observe is
    the activity, which errs toward what is really happening."""
    licensed(engine, Category.AUTHORISED)
    before, _c, _w = required(engine.state.licence, engine.state.capital)
    engine.ingest(
        event_type=EventType.ACTIVITY_UNDERTAKEN, subject="lic",
        occurred_at=WHEN, actor="system",
        payload={"activity": Activity.PORTFOLIO_MANAGEMENT_SERVICES.value})
    after, _c, _w = required(engine.state.licence, engine.state.capital)
    assert after == before + PUBLISHED_EXTRA_FOR_THIRD_PARTY_USD


def test_a_family_fund_does_not_add_to_it(engine):
    """A family investment fund manages the family's own money, which is
    the distinction the extra requirement turns on."""
    licensed(engine, Category.AUTHORISED, (Activity.FAMILY_INVESTMENT_FUND,))
    minimum, _confirmed, _why = required(engine.state.licence,
                                         engine.state.capital)
    assert minimum == PUBLISHED_MINIMUM_USD[Category.AUTHORISED]


def test_no_licence_category_means_no_minimum_is_asserted(engine):
    minimum, _confirmed, why = required(engine.state.licence,
                                        engine.state.capital)
    assert minimum is None
    assert "depends on it" in why


# -- the figures are not verified, and say so --------------------------------


def test_an_unconfirmed_minimum_is_marked_unconfirmed(engine):
    licensed(engine)
    _minimum, confirmed, _why = required(engine.state.licence,
                                         engine.state.capital)
    assert confirmed is False


def test_the_caveat_says_what_can_still_be_wrong(engine):
    """It used to say the figure was unchecked against the regulations,
    which was true while no copy of them was kept. It is checked now, so
    the caveat has to name the thing that can still be wrong: this is the
    floor for one activity, not the total a firm must hold."""
    assert "Second Schedule" in NOT_CONFIRMED
    assert "Treat it as a floor" in NOT_CONFIRMED
    assert "unchecked" not in NOT_CONFIRMED.lower()


def test_the_figures_are_the_ones_in_the_second_schedule():
    """The whole point of fetching the Regulations. These three came from
    two law-firm summaries for a week; they are now the schedule's own."""
    from vinzor.citations import CLAUSES

    schedule = CLAUSES["Second Schedule"].extract
    assert "Authorised FME USD 75,000" in schedule
    assert "Registered FME (Non-retail) USD 5,00,000" in schedule
    assert "Registered FME (Retail) USD 1,000,000" in schedule
    assert PUBLISHED_MINIMUM_USD[Category.AUTHORISED] == 75_000
    assert PUBLISHED_MINIMUM_USD[Category.REGISTERED_NON_RETAIL] == 500_000
    assert PUBLISHED_MINIMUM_USD[Category.REGISTERED_RETAIL] == 1_000_000
    assert "USD 500,000" in CLAUSES["107F"].extract
    assert PUBLISHED_EXTRA_FOR_THIRD_PARTY_USD == 500_000


def test_a_capital_finding_cites_the_schedule_that_sets_the_amount(engine):
    """It used to cite 3(4) alone -- which category to register under --
    so a firm told it was short was shown everything except the figure."""
    from vinzor.citations import CLAUSES

    licensed(engine)
    engine.report_net_worth(amount_usd=10_000, as_at="2026-06-30",
                            actor="Meera Nair", note="June accounts.")
    case = files(engine, "CAPITAL")[0]
    cited = {c["clause"] for c in case.evidence[0].citations}
    assert {"3(4)", "8(1)", "Second Schedule"} <= cited
    assert all(CLAUSES[one].doc_id == "IFSCA-FMR-2025" for one in cited)


def test_a_confirmed_minimum_beats_the_published_one(engine):
    """Nobody's reading of a regulation beats the firm's own reading of
    its own licence, and the firm is the one the Authority will ask."""
    licensed(engine)
    engine.confirm_minimum(
        minimum_usd=750_000, actor="Meera Nair", role=Role.AML_OFFICER,
        confirmed_on=TODAY,
        note="Read from Regulation 8 of the notified 2025 regulations.")
    minimum, confirmed, why = required(engine.state.licence,
                                       engine.state.capital)
    assert minimum == 750_000
    assert confirmed is True
    assert "Meera Nair" in why


def test_confirming_a_minimum_needs_a_source(engine):
    licensed(engine)
    with pytest.raises(ValueError, match="where the figure came from"):
        engine.confirm_minimum(minimum_usd=750_000, actor="Meera Nair",
                               role=Role.AML_OFFICER, confirmed_on=TODAY,
                               note="  ")


def test_a_viewer_cannot_confirm_a_minimum(engine):
    from vinzor.cases import DecisionDenied

    licensed(engine)
    with pytest.raises(DecisionDenied):
        engine.confirm_minimum(minimum_usd=750_000, actor="Priya Rao",
                               role=Role.VIEWER, confirmed_on=TODAY,
                               note="Read it in the regulations myself.")


# -- being short ------------------------------------------------------------


def test_a_shortfall_opens_a_file_that_stops_everything(engine):
    licensed(engine)
    engine.report_net_worth(amount_usd=310_000, as_at="2026-06-30",
                            actor="Meera Nair", note="June accounts.")
    opened = files(engine, "CAPITAL")
    assert len(opened) == 1
    assert opened[0].severity is Severity.CRITICAL


def test_meeting_the_minimum_opens_nothing(engine):
    licensed(engine)
    engine.report_net_worth(amount_usd=620_000, as_at="2026-06-30",
                            actor="Meera Nair", note="June accounts.")
    assert not files(engine, "CAPITAL")


def test_nothing_is_said_before_a_figure_is_reported(engine):
    """Not knowing is a different condition from being short, and
    reporting a firm as short on no evidence is how it learns to ignore
    the screen."""
    licensed(engine)
    assert shortfall(engine.state.licence, engine.state.capital) is None
    assert "Nobody has recorded" in in_words(engine.state.licence,
                                            engine.state.capital)


def test_the_latest_figure_is_the_one_that_counts(engine):
    licensed(engine)
    engine.report_net_worth(amount_usd=310_000, as_at="2026-03-31",
                            actor="Meera Nair", note="March accounts.")
    engine.report_net_worth(amount_usd=640_000, as_at="2026-06-30",
                            actor="Meera Nair", note="After the raise.")
    assert shortfall(engine.state.licence, engine.state.capital) is None


def test_a_figure_reported_out_of_order_does_not_win(engine):
    """Recording March after June must not make March the position."""
    licensed(engine)
    engine.report_net_worth(amount_usd=640_000, as_at="2026-06-30",
                            actor="Meera Nair", note="After the raise.")
    engine.report_net_worth(amount_usd=310_000, as_at="2026-03-31",
                            actor="Meera Nair", note="Late entry for March.")
    assert engine.state.capital.latest.as_at == "2026-06-30"


def test_the_file_carries_the_caveat_while_the_figure_is_unconfirmed(engine):
    from vinzor.briefing import case_file

    licensed(engine)
    engine.report_net_worth(amount_usd=310_000, as_at="2026-06-30",
                            actor="Meera Nair", note="June accounts.")
    said = " ".join(case_file(engine, files(engine, "CAPITAL")[0].case_id,
                              TODAY).because)
    assert "Second Schedule to the Fund Management Regulations" in said
    assert "Treat it as a floor" in said


def test_a_negative_net_worth_is_refused_as_the_wrong_question(engine):
    licensed(engine)
    with pytest.raises(ValueError, match="going-concern"):
        engine.report_net_worth(amount_usd=-1, as_at=TODAY,
                                actor="Meera Nair", note="x")


def test_the_position_survives_a_rebuild(engine):
    licensed(engine)
    engine.report_net_worth(amount_usd=310_000, as_at="2026-06-30",
                            actor="Meera Nair", note="June accounts.")
    assert engine.rebuild().capital.latest == engine.state.capital.latest


# -- what was reported, beside what the book holds ---------------------------


def book_with(engine, commitments=((20e6, "Fund I"), (35e6, "Fund I"))):
    for index, (amount, fund) in enumerate(commitments):
        engine.ingest(
            event_type=EventType.ENTITY_REGISTERED, subject=f"p{index}",
            occurred_at="2026-01-05",
            payload={"kind": EntityKind.PERSON.value, "name": f"Investor {index}",
                     "attributes": {}})
        engine.ingest(
            event_type=EventType.COMMITMENT_MADE, subject=f"p{index}",
            occurred_at="2026-01-05",
            payload={"amount": amount, "currency": "USD", "fund": fund})


def test_an_ordinary_difference_is_shown_and_not_raised(engine):
    """Assets under management are properly not the sum of commitments.
    A rule that fired on the difference would fire every quarter of every
    firm's life and be switched off by March."""
    book_with(engine)
    rows = compare(engine.state.book, {"aum_usd": 48_000_000})
    assert rows[0].apart
    assert not nothing_behind_it(rows)


def test_a_figure_the_book_holds_nothing_for_is_raised(engine):
    book_with(engine)
    rows = compare(engine.state.book, {"capital_received_usd": 44_000_000})
    assert nothing_behind_it(rows)


def test_a_return_with_a_figure_from_nowhere_opens_a_file(engine):
    book_with(engine)
    engine.ingest(
        event_type=EventType.FILING_SUBMITTED, subject="lic",
        occurred_at="2026-07-18", actor="Meera Nair",
        payload={"obligation": "QUARTERLY_REPORT", "period": "2026-Q1",
                 "submitted_on": "2026-07-18",
                 "reported": {"capital_received_usd": 44_000_000}})
    assert len(files(engine, "DISCLOSURE")) == 1


def test_a_return_that_agrees_with_the_book_opens_nothing(engine):
    book_with(engine)
    engine.ingest(
        event_type=EventType.FILING_SUBMITTED, subject="lic",
        occurred_at="2026-07-18", actor="Meera Nair",
        payload={"obligation": "QUARTERLY_REPORT", "period": "2026-Q1",
                 "submitted_on": "2026-07-18",
                 "reported": {"aum_usd": 48_000_000, "investors": 2}})
    assert not files(engine, "DISCLOSURE")


def test_a_return_carrying_no_figures_opens_nothing(engine):
    """Every filing already on every workspace carries none, and this must
    not turn all of them into findings."""
    book_with(engine)
    engine.ingest(
        event_type=EventType.FILING_SUBMITTED, subject="lic",
        occurred_at="2026-07-18", actor="Meera Nair",
        payload={"obligation": "QUARTERLY_REPORT", "period": "2026-Q1",
                 "submitted_on": "2026-07-18"})
    assert not files(engine, "DISCLOSURE")


def test_a_disclosure_file_does_not_read_as_an_overdue_filing(engine):
    """It shared the filing writer at first, so a return that *was*
    submitted rendered as one that was overdue -- the opposite of what
    happened."""
    from vinzor.briefing import case_file

    book_with(engine)
    engine.ingest(
        event_type=EventType.FILING_SUBMITTED, subject="lic",
        occurred_at="2026-07-18", actor="Meera Nair",
        payload={"obligation": "QUARTERLY_REPORT", "period": "2026-Q1",
                 "submitted_on": "2026-07-18",
                 "reported": {"capital_received_usd": 44_000_000}})
    page = case_file(engine, files(engine, "DISCLOSURE")[0].case_id, TODAY)
    assert "overdue" not in page.headline.lower()
    assert "cannot show" in page.headline


def test_the_file_says_an_ordinary_gap_is_not_what_this_is(engine):
    from vinzor.briefing import case_file

    book_with(engine)
    engine.ingest(
        event_type=EventType.FILING_SUBMITTED, subject="lic",
        occurred_at="2026-07-18", actor="Meera Nair",
        payload={"obligation": "QUARTERLY_REPORT", "period": "2026-Q1",
                 "submitted_on": "2026-07-18",
                 "reported": {"capital_received_usd": 44_000_000}})
    said = " ".join(case_file(engine, files(engine, "DISCLOSURE")[0].case_id,
                              TODAY).because)
    assert "called in tranches" in said
    assert "nothing behind the figure" in said


# -- the book underneath -----------------------------------------------------


def test_only_dollars_are_added_up(engine):
    """Converting would need a rate this system does not hold, and a total
    that quietly assumes one is a number an officer might repeat."""
    engine.ingest(
        event_type=EventType.COMMITMENT_MADE, subject="p1",
        occurred_at="2026-01-05",
        payload={"amount": 100.0, "currency": "INR", "fund": "Fund I"})
    assert engine.state.book.commitments_usd == 0.0


def test_the_book_counts_each_investor_once(engine):
    for index in range(3):
        engine.ingest(
            event_type=EventType.COMMITMENT_MADE, subject="p1",
            occurred_at="2026-01-05",
            payload={"amount": 1e6, "currency": "USD", "fund": "Fund I"})
    assert engine.state.book.as_figures()["investors"] == 1


def test_the_book_survives_a_rebuild(engine):
    book_with(engine)
    assert engine.rebuild().book.as_figures() == engine.state.book.as_figures()


# -- how it reads ------------------------------------------------------------


def test_nothing_new_speaks_jargon(engine):
    import re

    from vinzor.briefing import brief
    from test_briefing import JARGON, _strings

    licensed(engine)
    book_with(engine)
    engine.report_net_worth(amount_usd=310_000, as_at="2026-06-30",
                            actor="Meera Nair", note="June accounts.")
    engine.ingest(
        event_type=EventType.FILING_SUBMITTED, subject="lic",
        occurred_at="2026-07-18", actor="Meera Nair",
        payload={"obligation": "QUARTERLY_REPORT", "period": "2026-Q1",
                 "submitted_on": "2026-07-18",
                 "reported": {"capital_received_usd": 44_000_000}})

    offences = []
    briefing = brief(engine, person="Meera Nair", today=TODAY)
    for path, text in _strings(briefing, "briefing"):
        for pattern, what in JARGON:
            found = re.search(pattern, text)
            if found:
                offences.append(f"{path}: {what} ({found.group(0)!r})")
    assert not offences, ("jargon reached the reader:\n  "
                          + "\n  ".join(offences))
