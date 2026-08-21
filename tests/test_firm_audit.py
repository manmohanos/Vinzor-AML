"""The firm's own file: capital, what was reported, and what was filed.

Five things this block says about itself, each measured rather than read.

**"Raised on the report, the only moment the answer can change with it."**
Not true, and the answer is a comparison with two halves. Three ordinary
orderings moved the other half with nothing reaching a queue: a net worth
recorded before the licence (the order a fresh workspace fills up in) left a
USD 190,000 shortfall unfiled; a third-party activity recorded afterwards --
the very mechanism this module chose -- left USD 400,000; an officer
confirming a higher minimum, the same. The regulatory page said the firm was
short in all three cases; nothing that reaches a queue did.

**A confirmed minimum outlived the licence it was confirmed for.** A firm
that upgraded from Authorised to Registered (Retail) kept its USD 75,000
floor, held USD 100,000, and read as compliant -- USD 900,000 below the
Second Schedule figure, with the word *confirmed* attached.

**"Nothing at all behind it" was measured against a projection that counted
investors only from commitments.** Built through the real intake -- a
registrar's list with no commitment column, which the importer explicitly
supports -- 87 parties and 87 payments produced an investor count of nought,
and a return claiming 87, every figure of it true, produced this module's
gravest accusation.

**The side-by-side row dropped every non-dollar payment** and then called the
difference "more than arrived". On the shipped demo that is 83 of 805
payments, in six currencies, none of them mentioned anywhere on the row.

**And nothing in the product could record that a return was filed.**
``FILING_SUBMITTED`` existed in the model and in six files; no command, no
route and no import produced one, while ``FILING_OVERDUE`` was swept for on
every briefing load. A firm licensed in April 2023 and opened here in August
2026 collected **19 permanent overdue records in one call** -- USD 24,700 of
computed late charges -- with no way to say it had filed any of them.
"""

from __future__ import annotations

import pytest

from vinzor.capital import required
from vinzor.disclosure import compare
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType, Role

WHEN = "2026-06-01"


def a_firm(category="REGISTERED_NON_RETAIL", granted=WHEN):
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera Nair", role=Role.AML_OFFICER, enrolled_at=WHEN)
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="FME-1",
                  occurred_at=granted, actor="system",
                  payload={"number": "FME-1", "category": category,
                           "activities": []})
    return engine


def capital_files(engine):
    return [c for c in engine.state.casebook.cases.values()
            if c.case_type == "CAPITAL"]


# -- when a shortfall reaches a queue ----------------------------------------


def test_a_shortfall_is_filed_when_the_licence_arrives_after_the_net_worth():
    """The order a fresh workspace actually fills up in."""
    engine = Vinzor(EventLog())
    engine.report_net_worth(amount_usd=310_000, as_at="2026-06-30",
                            actor="system")
    assert capital_files(engine) == []
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="FME-1",
                  occurred_at="2026-07-01", actor="system",
                  payload={"number": "FME-1",
                           "category": "REGISTERED_NON_RETAIL",
                           "activities": []})
    assert len(capital_files(engine)) == 1


def test_a_shortfall_is_filed_when_an_activity_raises_the_minimum():
    """The mechanism this module chose for itself: read the minimum from
    what the firm has actually been recorded as doing."""
    engine = a_firm()
    engine.report_net_worth(amount_usd=600_000, as_at="2026-06-30",
                            actor="system")
    assert capital_files(engine) == []

    engine.ingest(event_type=EventType.ACTIVITY_UNDERTAKEN, subject="FME-1",
                  occurred_at="2026-07-01", actor="system",
                  payload={"activity": "PORTFOLIO_MANAGEMENT_SERVICES"})
    assert len(capital_files(engine)) == 1


def test_a_shortfall_is_filed_when_an_officer_confirms_a_higher_minimum():
    engine = a_firm()
    engine.report_net_worth(amount_usd=600_000, as_at="2026-06-30",
                            actor="system")
    engine.confirm_minimum(minimum_usd=1_000_000, actor="Meera Nair",
                           role=Role.AML_OFFICER, confirmed_on="2026-07-01",
                           note="Second Schedule read with 107F")
    assert len(capital_files(engine)) == 1


def test_a_firm_that_is_not_short_still_opens_nothing():
    engine = a_firm()
    engine.report_net_worth(amount_usd=5_000_000, as_at="2026-06-30",
                            actor="system")
    assert capital_files(engine) == []


def test_a_minimum_that_moves_raises_the_question_once_more_not_every_time():
    """The minimum is in the dedupe key, so a firm that takes on a
    third-party activity gets a second file about the higher figure -- once.
    Every later fact that does not move either half attaches to the file that
    already exists rather than opening another."""
    engine = a_firm()
    engine.report_net_worth(amount_usd=310_000, as_at="2026-06-30",
                            actor="system")
    assert len(capital_files(engine)) == 1

    engine.ingest(event_type=EventType.ACTIVITY_UNDERTAKEN, subject="FME-1",
                  occurred_at="2026-07-01", actor="system",
                  payload={"activity": "RESTRICTED_SCHEME"})
    assert len(capital_files(engine)) == 2

    engine.ingest(event_type=EventType.ACTIVITY_UNDERTAKEN, subject="FME-1",
                  occurred_at="2026-07-02", actor="system",
                  payload={"activity": "PORTFOLIO_MANAGEMENT_SERVICES"})
    assert len(capital_files(engine)) == 2


# -- a confirmed minimum belongs to a licence --------------------------------


def _upgraded():
    engine = a_firm(category="AUTHORISED", granted="2024-02-01")
    engine.confirm_minimum(minimum_usd=75_000, actor="Meera Nair",
                           role=Role.AML_OFFICER, confirmed_on="2024-02-05",
                           note="Second Schedule, Authorised FME")
    return engine


def test_a_confirmation_stands_for_the_licence_it_was_made_against():
    engine = _upgraded()
    amount, confirmed, why = required(engine.state.licence,
                                      engine.state.capital)
    assert (amount, confirmed) == (75_000.0, True)
    assert "Meera Nair" in why


def test_it_stops_standing_when_the_firm_changes_category():
    """USD 900,000 below the published floor, shown as compliant, with the
    word "confirmed" on it."""
    engine = _upgraded()
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="FME-1",
                  occurred_at="2026-04-01", actor="system",
                  payload={"number": "FME-1", "category": "REGISTERED_RETAIL",
                           "activities": []})
    amount, confirmed, why = required(engine.state.licence,
                                      engine.state.capital)

    assert amount == 1_000_000.0
    assert confirmed is False
    assert "for a licence of a different category" in why
    assert "confirms again" in why


def test_the_confirmation_itself_is_never_thrown_away():
    """It is on the log, it stays on the screen, and the sentence says who
    made it and when. It simply stops being confirmation of a question
    nobody asked it."""
    engine = _upgraded()
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="FME-1",
                  occurred_at="2026-04-01", actor="system",
                  payload={"number": "FME-1", "category": "REGISTERED_RETAIL",
                           "activities": []})
    _amount, _confirmed, why = required(engine.state.licence,
                                        engine.state.capital)
    assert "Meera Nair confirmed USD 75,000 on 2024-02-05" in why


def test_a_confirmation_above_the_published_figure_still_stands():
    """A firm that confirmed a *higher* minimum has not become less careful
    by upgrading, and overriding them upward would be the product second-
    guessing the firm about its own licence."""
    engine = a_firm(category="AUTHORISED", granted="2024-02-01")
    engine.confirm_minimum(minimum_usd=2_000_000, actor="Meera Nair",
                           role=Role.AML_OFFICER, confirmed_on="2024-02-05",
                           note="our own board floor, above the Schedule")
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="FME-1",
                  occurred_at="2026-04-01", actor="system",
                  payload={"number": "FME-1", "category": "REGISTERED_RETAIL",
                           "activities": []})
    amount, confirmed, _why = required(engine.state.licence,
                                       engine.state.capital)
    assert (amount, confirmed) == (2_000_000.0, True)


# -- what the records show ---------------------------------------------------


def a_registrar_book(currency="USD", how_many=8):
    """Parties and payments, no commitments -- which is what a registrar's
    investor list actually looks like, and which the intake supports."""
    engine = Vinzor(EventLog())
    for index in range(how_many):
        engine.ingest(event_type=EventType.ENTITY_REGISTERED,
                      subject=f"per_{index:04}", occurred_at=WHEN,
                      actor="importer",
                      payload={"kind": EntityKind.PERSON.value,
                               "name": f"An Investor {index}",
                               "attributes": {}})
        engine.ingest(event_type=EventType.PAYMENT_RECEIVED,
                      subject=f"fnd_0001", occurred_at=WHEN, actor="importer",
                      payload={"amount": 100_000.0, "currency": currency,
                               "payer": f"per_{index:04}",
                               "payment_ref": f"pay{index}"})
    return engine


def test_investors_are_counted_from_who_actually_paid_not_only_commitments():
    engine = a_registrar_book()
    rows = compare(engine.state.book, {"investors": 8})
    assert rows[0].records_show == "8"
    assert rows[0].unsupported is False


def test_a_true_return_on_a_registrar_book_is_not_accused_of_having_nothing_behind_it():
    engine = a_registrar_book()
    rows = compare(engine.state.book,
                   {"investors": 8, "capital_received_usd": 800_000})
    assert [row.what for row in rows if row.unsupported] == []


def test_payments_in_another_currency_are_named_rather_than_dropped():
    """A bare "USD 0" asserts that nothing arrived. 83 of 805 payments on the
    shipped demo are in six other currencies."""
    engine = a_registrar_book(currency="INR")
    rows = compare(engine.state.book, {"capital_received_usd": 800_000})
    row = rows[0]

    assert "8 more payments in INR" in row.records_show
    assert "not converted here" in row.records_show
    assert row.unsupported is False


def test_the_difference_is_not_called_more_than_arrived_when_money_was_left_out():
    engine = a_registrar_book(currency="AED")
    row = compare(engine.state.book, {"capital_received_usd": 800_000})[0]
    assert "more than arrived" not in row.apart


def test_a_dollars_only_book_still_reads_exactly_as_before():
    engine = a_registrar_book()
    row = compare(engine.state.book, {"capital_received_usd": 900_000})[0]
    assert row.records_show == "USD 800,000"
    assert "more than arrived" in row.apart


# -- a figure that is not a figure -------------------------------------------


def test_a_reported_figure_sent_as_text_is_read_as_the_number_it_is():
    """It was accepted and then failed every isinstance check downstream,
    opening a HIGH case whose own permanent record read "reported: nothing
    recorded" -- a case that exists because a figure was filed, stating that
    no figure was filed."""
    engine = a_firm()
    engine.record_filing(obligation="QUARTERLY_REPORT", period="Q1",
                         submitted_on="2026-07-18", actor="Meera Nair",
                         reported={"capital_received_usd": "44000000"})
    filed = [e for e in engine.log
             if e.event_type is EventType.FILING_SUBMITTED][0]
    assert filed.payload["reported"] == {"capital_received_usd": 44_000_000.0}


def test_a_count_that_is_not_a_number_is_refused_with_a_sentence():
    """It raised a raw ValueError out of a policy and out of ingest."""
    engine = a_firm()
    with pytest.raises(ValueError) as refusal:
        engine.record_filing(obligation="QUARTERLY_REPORT", period="Q1",
                             submitted_on="2026-07-18", actor="Meera Nair",
                             reported={"investors": "twelve"})
    assert "has to be a number" in str(refusal.value)


def test_a_figure_of_a_shape_that_used_to_crash_a_page_render_cannot_be_stored():
    """``compare`` runs on every render of the regulatory page, so a value
    like this recorded by an actor whose findings are gated off would have
    taken the page down permanently."""
    engine = a_firm()
    for value in ([1, 2, 3], {"a": 1}, True, None):
        with pytest.raises((ValueError, TypeError)):
            engine.record_filing(obligation="QUARTERLY_REPORT", period="Q1",
                                 submitted_on="2026-07-18", actor="Meera Nair",
                                 reported={"investors": value})


def test_a_figure_nobody_reports_on_is_named_rather_than_silently_dropped():
    """``{"aum": 48_000_000}`` -- one letter short of ``aum_usd`` -- produced
    no rows and no complaint at all."""
    engine = a_firm()
    with pytest.raises(ValueError) as refusal:
        engine.record_filing(obligation="QUARTERLY_REPORT", period="Q1",
                             submitted_on="2026-07-18", actor="Meera Nair",
                             reported={"aum": 48_000_000})
    assert "there is nothing on a return called 'aum'" in str(refusal.value)


def test_a_bad_figure_never_reaches_the_page_render_defensively_either():
    """Belt as well as braces: the boundary refuses it, and ``compare``
    cannot raise on one that somehow got past."""
    engine = a_firm()
    rows = compare(engine.state.book, {"investors": "twelve"})
    assert rows[0].apart == ""


# -- recording that something was filed --------------------------------------


def test_a_return_can_be_recorded_as_filed():
    engine = a_firm()
    engine.record_filing(obligation="QUARTERLY_REPORT",
                         period="Q1 FY2026-27", submitted_on="2026-07-18",
                         actor="Meera Nair")
    assert engine.state.calendar.submitted == {
        "QUARTERLY_REPORT|Q1 FY2026-27": "2026-07-18"}


def test_an_obligation_nobody_tracks_is_refused_by_name():
    engine = a_firm()
    with pytest.raises(ValueError) as refusal:
        engine.record_filing(obligation="MONTHLY_RETURN", period="July",
                             submitted_on="2026-07-18", actor="Meera Nair")
    assert "QUARTERLY_REPORT" in str(refusal.value)


def test_a_filing_needs_the_period_it_covers():
    engine = a_firm()
    with pytest.raises(ValueError):
        engine.record_filing(obligation="QUARTERLY_REPORT", period="  ",
                             submitted_on="2026-07-18", actor="Meera Nair")


def test_the_date_it_went_in_is_read_as_a_date():
    engine = a_firm()
    with pytest.raises(ValueError) as refusal:
        engine.record_filing(obligation="QUARTERLY_REPORT", period="Q1",
                             submitted_on="18-07-2026", actor="Meera Nair")
    assert "submitted_on" in str(refusal.value)


def test_the_same_period_cannot_be_filed_twice():
    """A correction is a new record, not a second copy of this one."""
    engine = a_firm()
    engine.record_filing(obligation="QUARTERLY_REPORT", period="Q1",
                         submitted_on="2026-07-18", actor="Meera Nair")
    with pytest.raises(ValueError) as refusal:
        engine.record_filing(obligation="QUARTERLY_REPORT", period="Q1",
                             submitted_on="2026-07-19", actor="Meera Nair")
    assert "already recorded as filed" in str(refusal.value)


def test_a_filed_return_stops_the_sweep_calling_it_overdue():
    """The whole point. Lateness was swept for and filing was not
    recordable, so every quarter since the licence grant stayed permanently
    overdue with no way to answer it."""
    from vinzor.calendar import Status, outstanding

    from vinzor.calendar import instances

    engine = a_firm(granted="2026-01-01")
    engine.observe_deadlines("2026-08-20")
    late = [row for row in outstanding("2026-01-01", "2026-08-20",
                                       engine.state.calendar.submitted)
            if row.status("2026-08-20") is Status.OVERDUE]
    assert late, "the sweep found nothing overdue to answer"

    first = late[0]
    engine.record_filing(obligation=str(first.obligation),
                         period=first.period, submitted_on="2026-08-20",
                         actor="Meera Nair")
    still = [row for row in instances("2026-01-01", "2026-08-20",
                                      engine.state.calendar.submitted)
             if row.period == first.period
             and row.obligation == first.obligation]
    assert [row.status("2026-08-20") for row in still] == [Status.SUBMITTED]
    assert still[0].submitted_on == "2026-08-20"
