"""What the firm can show for itself.

A queue of two hundred files says nothing about whether the oldest is a day
old or a year old, and that difference is the one an inspector asks about
first. These tests hold the report to the two properties that make it worth
handing to a board: every figure is read off the log rather than kept
beside it, and nothing on the page is a number without the words that make
it a fact.
"""

from __future__ import annotations

import re

import pytest

from vinzor.briefing import band_by_age, days_between
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType, Outcome, Role
from vinzor.reporting import period_report

from conftest import commits, officer, person, register, screened
from test_briefing import JARGON, _strings

TODAY = "2026-08-17"


@pytest.fixture
def engine() -> Vinzor:
    return Vinzor(EventLog())


@pytest.fixture
def busy(engine):
    """A workspace with a little of everything, dated across two months."""
    officer(engine, "Meera Nair", Role.AML_OFFICER)
    officer(engine, "Aarav Sharma", Role.COMPLIANCE)
    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Kavya Singh")
    register(engine, "c1", EntityKind.COMPANY, "Orion Zenith Enterprises")
    commits(engine, "c1")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    screened(engine, "p2", "PEP", alert_id="alt_2")
    return engine


def sections_of(report):
    return {section.heading: section for section in report.sections}


# -- the shape of it ---------------------------------------------------------


def test_the_report_covers_a_named_period_and_says_so(busy):
    report = period_report(busy, TODAY, since="2026-08-01",
                           workspace="Acme GIFT Fund Managers Ltd")
    assert "1 August 2026" in report.covering
    assert "17 August 2026" in report.covering
    assert report.workspace == "Acme GIFT Fund Managers Ltd"
    assert "permanent record" in report.assurance


def test_the_period_defaults_to_the_month_it_ends_in(busy):
    report = period_report(busy, TODAY)
    assert "1 August 2026" in report.covering


def test_every_section_leads_with_a_sentence(busy):
    report = period_report(busy, TODAY, since="2026-08-01")
    assert report.sections
    for section in report.sections:
        assert section.heading
        assert section.lead.endswith("."), section.lead
        assert len(section.lead.split()) > 3, section.lead


def test_the_report_says_nothing_technical(busy):
    """The widest surface a board or an inspector reads. Every count, label
    and closing line is walked for identifiers the way every other screen
    is."""
    officer(busy, "Devika Rao", Role.SENIOR_MGMT)
    case = busy.queue()[0]
    busy.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                actor="Meera Nair", role=Role.AML_OFFICER,
                rationale="Different date of birth; not the same person.",
                decided_at=TODAY)

    offences = []
    for report in (period_report(busy, TODAY, since="2026-08-01"),
                   period_report(Vinzor(EventLog()), TODAY)):
        for path, text in _strings(report, "report"):
            for pattern, what in JARGON:
                found = re.search(pattern, text)
                if found:
                    offences.append(f"{path}: {what} ({found.group(0)!r})")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


def test_an_empty_workspace_reports_emptily_rather_than_breaking(engine):
    report = period_report(engine, TODAY)
    assert report.sections
    assert any("No" in line or "no " in line for line in report.summary)


# -- what it counts ----------------------------------------------------------


def test_what_came_in_is_counted_from_the_log(busy):
    report = period_report(busy, TODAY, since="2026-08-01")
    arrivals = sections_of(report)["What came in"]
    counts = {row.what: row.count for row in arrivals.rows}
    assert counts["Parties"] == "3"
    assert counts["Watchlist checks"] == "2"


def test_a_period_that_predates_everything_counts_nothing(busy):
    report = period_report(busy, "2026-01-31", since="2026-01-01")
    arrivals = sections_of(report)["What came in"]
    assert all(row.count == "0" for row in arrivals.rows)
    assert "Nothing was recorded" in arrivals.lead


def test_decisions_are_counted_by_outcome_and_by_person(busy):
    # The second file is a politically exposed person, and clause
    # 5.5(b)(iii) reserves clearing one to senior management -- so it is
    # senior management who settles it here.
    officer(busy, "Devika Rao", Role.SENIOR_MGMT)
    for case, actor, role in ((busy.queue()[0], "Meera Nair",
                               Role.AML_OFFICER),
                              (busy.queue()[1], "Devika Rao",
                               Role.SENIOR_MGMT)):
        busy.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                    actor=actor, role=role,
                    rationale="Different date of birth; a false positive.",
                    decided_at=TODAY)

    report = period_report(busy, TODAY, since="2026-08-01")
    decisions = sections_of(report)["What people decided"]
    rows = {row.what: row.count for row in decisions.rows}
    assert rows["Cleared"] == "2"
    assert rows["Meera Nair"] == "1"
    assert rows["Devika Rao"] == "1"


def test_a_file_passed_up_is_reported_as_still_waiting(busy):
    case = busy.queue()[0]
    busy.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                actor="Meera Nair", role=Role.AML_OFFICER,
                rationale="The record cannot resolve this either way.",
                decided_at=TODAY)

    decisions = sections_of(
        period_report(busy, TODAY, since="2026-08-01"))["What people decided"]
    assert "waiting for a second officer" in decisions.tail
    assert "Nobody who passed a file up can settle it" in decisions.tail


# -- how long things have been waiting ---------------------------------------


def test_open_files_are_banded_by_how_long_they_have_waited(busy):
    ageing = sections_of(
        period_report(busy, TODAY, since="2026-08-01"))[
            "How long files have been waiting"]
    bands = {row.what: row.count for row in ageing.rows}
    assert "Opened today" in bands
    assert "More than three months" in bands
    assert sum(int(count) for count in bands.values()) == len(busy.queue())


def test_the_oldest_open_file_is_named_with_its_age(engine):
    person(engine, "p1", "Rohan Desai")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when="2026-01-05")
    ageing = sections_of(period_report(engine, TODAY))[
        "How long files have been waiting"]
    assert "5 January 2026" in ageing.tail
    assert "days ago" in ageing.tail
    assert "Rohan Desai" in ageing.tail


def test_a_band_nobody_should_be_looking_at_is_marked(engine):
    person(engine, "p1", "Rohan Desai")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when="2026-01-05")
    ageing = sections_of(period_report(engine, TODAY))[
        "How long files have been waiting"]
    old = next(r for r in ageing.rows
               if r.what.startswith("More than three months"))
    assert old.count == "1"
    assert old.tone == "stop"
    # And the band just below it stays empty rather than double-counting.
    assert next(r for r in ageing.rows
                if r.what.startswith("One to three")).count == "0"


def test_the_bands_agree_between_the_report_and_the_dashboard(engine):
    """One table of bands, read by both, so a screen and a report can never
    disagree about the same file."""
    person(engine, "p1", "Rohan Desai")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when="2026-01-05")
    banded = band_by_age(engine.queue(), TODAY)
    report_rows = sections_of(period_report(engine, TODAY))[
        "How long files have been waiting"].rows
    assert [label for label, _, _ in banded] == [r.what for r in report_rows]
    assert [str(count) for _, count, _ in banded] == \
        [r.count for r in report_rows]


def test_days_between_reads_dates_and_refuses_anything_else():
    assert days_between("2026-08-01", "2026-08-17") == 16
    assert days_between("not a date", "2026-08-17") is None
    assert days_between("2026-08-17", "") is None


# -- who has never been checked ----------------------------------------------


def test_a_party_nobody_ever_checked_is_named(busy):
    coverage = sections_of(
        period_report(busy, TODAY, since="2026-08-01"))["Watchlist coverage"]
    rows = {row.what: row.count for row in coverage.rows}
    assert rows["Parties on the record"] == "3"
    assert rows["Checked against the watchlists at least once"] == "2"
    assert rows["Never checked"] == "1"
    assert "Orion Zenith Enterprises" in coverage.tail
    assert "never run" in coverage.tail


def test_full_coverage_is_stated_rather_than_left_blank(engine):
    person(engine, "p1", "Rohan Desai")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", matched=False)
    coverage = sections_of(period_report(engine, TODAY))["Watchlist coverage"]
    assert next(r for r in coverage.rows
                if r.what == "Never checked").count == "0"
    assert "Every party on the record has been checked" in coverage.tail


# -- the record behind it ----------------------------------------------------


def test_the_report_states_the_chain_it_was_read_from(busy):
    record = sections_of(period_report(busy, TODAY))[
        "The record behind this report"]
    rows = {row.what: row.count for row in record.rows}
    assert rows["Records in the permanent log"] == f"{len(busy.log):,}"
    assert rows["The chain"] == "Verifies"


def test_the_same_period_reports_the_same_figures_twice(busy):
    """The property that makes it a record rather than a rendering: nothing
    here reads a clock or a cache, so June's report is still June's report
    when it is produced again in December."""
    first = period_report(busy, TODAY, since="2026-08-01")
    again = period_report(busy, TODAY, since="2026-08-01")
    assert first == again

    rebuilt = Vinzor(busy.log)
    assert period_report(rebuilt, TODAY, since="2026-08-01") == first


# -- whether the book could be handed over -----------------------------------


def test_the_report_says_whether_the_book_could_be_handed_over(engine):
    """From 1 September 2026 the book has to go to a registration agency.
    A board reading a quarterly report should learn that before October."""
    from vinzor.model import EntityKind

    register(engine, "p1", EntityKind.PERSON, "Asha Mehta")
    register(engine, "p2", EntityKind.PERSON, "Rohan Desai")

    section = sections_of(period_report(engine, TODAY))[
        "Whether the book could be handed over"]
    rows = {row.what: row.count for row in section.rows}
    assert rows["Parties on the record"] == "2"
    assert rows["Short of something the guidelines require"] == "2"
    assert "clause 5.4.2" in section.tail
    assert "does not promise a file will be accepted" in section.tail


def test_the_shortfall_is_explained_as_a_missing_column(engine):
    """A firm told "240 problems" reads it as a month of work. Told "one
    column is absent", they fix it in an afternoon."""
    from vinzor.model import EntityKind

    for index in range(4):
        register(engine, f"p{index}", EntityKind.PERSON, f"Person {index}",
                 nationality="SG", dob="1980-01-01", jurisdiction="SG",
                 phone="+65 6555 0100", id_document_number="E123456X")

    section = sections_of(period_report(engine, TODAY))[
        "Whether the book could be handed over"]
    assert "one column absent from an export" in section.tail
    assert "4 parties" in section.tail


def test_the_handover_section_is_not_a_period_figure(engine):
    """Everything else on the report covers a period; this is the state of
    the book today, and saying so stops a reader misreading it."""
    from vinzor.model import EntityKind

    register(engine, "p1", EntityKind.PERSON, "Asha Mehta")
    section = sections_of(period_report(engine, TODAY, since="2020-01-01"))[
        "Whether the book could be handed over"]
    assert "as the record stands today" in section.lead.lower()


def test_an_empty_book_leaves_the_section_out(engine):
    """A section reporting nothing about nobody is noise on a board paper."""
    assert "Whether the book could be handed over" not in sections_of(
        period_report(engine, TODAY))
