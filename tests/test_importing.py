"""Reading a firm's own spreadsheet without inventing anything.

Most of these tests are about refusing. An importer that always succeeds is an
importer that guesses, and every guess it makes becomes a fact on a compliance
record that nobody asserted -- in a log with no undo.
"""

from __future__ import annotations

import pytest

from vinzor.importing import apply, read
from vinzor.model import EntityKind


def sheet(tmp_path, text, name="investors.csv"):
    path = tmp_path / name
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def test_a_plain_sheet_maps_without_being_told_anything(tmp_path):
    plan = read(sheet(tmp_path, """
Investor Name,Type,Nationality,Date of Birth,Commitment,Currency
Rajesh Iyer,Individual,Singapore,1974-03-02,2500000,USD
"""))
    assert not plan.refusals
    assert plan.mapped["name"] == "Investor Name"
    assert plan.mapped["kind"] == "Type"
    row = plan.usable[0]
    assert row.kind is EntityKind.PERSON
    assert row.attributes["nationality"] == "SG", "country name not resolved"
    assert row.commitment == {"amount": 2_500_000.0, "currency": "USD",
                              "fund": "the fund"}


def test_a_column_nobody_recognises_is_reported_not_absorbed(tmp_path):
    plan = read(sheet(tmp_path, """
Name,Type,Relationship Manager,Internal Notes
Rajesh Iyer,Individual,Priya,called twice
"""))
    assert plan.ignored == ["Relationship Manager", "Internal Notes"]
    assert plan.usable[0].attributes == {}


def test_two_columns_claiming_one_field_refuse_the_whole_sheet(tmp_path):
    """A sheet with both "Nationality" and "Citizenship" is a question for the
    firm, not something to resolve by picking the leftmost.
    """
    plan = read(sheet(tmp_path, """
Name,Type,Nationality,Citizenship
Rajesh Iyer,Individual,SG,IN
"""))
    assert plan.refusals
    assert "could all be nationality" in plan.refusals[0]
    assert plan.rows == [], "rows were read from a sheet that was refused"


def test_an_ambiguous_date_is_refused_rather_than_assumed(tmp_path):
    """03/04/1980 is 3 April in Mumbai and 4 March in New York. Date of birth
    is a field screening compares: guessing turns a match into a miss.
    """
    plan = read(sheet(tmp_path, """
Name,Type,Date of Birth
Aditi Menon,Individual,03/04/1980
Rajesh Iyer,Individual,25/12/1974
Sam Wu,Individual,1974-03-02
"""))
    assert [r.name for r in plan.usable] == ["Rajesh Iyer", "Sam Wu"]
    assert "could be two different dates" in plan.rejected[0].problems[0]
    # 25/12 can only be day-first, so it is not ambiguous and is kept.
    assert plan.usable[0].attributes["dob"] == "1974-12-25"


def test_a_sheet_with_no_name_column_is_refused(tmp_path):
    plan = read(sheet(tmp_path, """
Reference,Type,Nationality
LP-001,Individual,SG
"""))
    assert any("no column holds a party's name" in r.lower()
               for r in plan.refusals)


def test_a_sheet_with_no_type_column_asks_rather_than_assuming_person(tmp_path):
    body = """
Name,Nationality
Rajesh Iyer,SG
"""
    assert read(sheet(tmp_path, body)).refusals

    told = read(sheet(tmp_path, body), default_kind="person")
    assert not told.refusals
    assert told.usable[0].kind is EntityKind.PERSON


def test_rows_that_cannot_be_read_are_left_out_and_named(tmp_path):
    plan = read(sheet(tmp_path, """
Name,Type
Rajesh Iyer,Individual
,Individual
Ravi Kumar,Spaceship
"""))
    assert [r.name for r in plan.usable] == ["Rajesh Iyer"]
    assert plan.rejected[0].problems == ["this row names no party"]
    assert "not a kind of party this recognises" in plan.rejected[1].problems[0]


def test_importing_the_same_sheet_twice_does_not_duplicate_anyone(tmp_path, engine):
    path = sheet(tmp_path, """
Name,Type,Nationality,Date of Birth
Rajesh Iyer,Individual,SG,1974-03-02
""")
    first = apply(engine, read(path), on="2026-08-14")
    second = apply(engine, read(path), on="2026-08-15")

    assert first["registered"] == 1
    assert second["registered"] == 0 and second["already_known"] == 1
    assert len(engine.state.graph.entities) == 1


def test_two_people_with_the_same_name_are_two_parties(tmp_path, engine):
    """Identity comes from the row's content, so a shared name does not merge
    two different investors into one."""
    apply(engine, read(sheet(tmp_path, """
Name,Type,Date of Birth
Priya Hussain,Individual,1972-11-06
Priya Hussain,Individual,2012-07-10
""")), on="2026-08-14")
    assert len(engine.state.graph.entities) == 2


def test_a_refused_sheet_cannot_be_written_by_mistake(tmp_path, engine):
    plan = read(sheet(tmp_path, """
Name,Type,Nationality,Citizenship
Rajesh Iyer,Individual,SG,IN
"""))
    with pytest.raises(ValueError, match="refused"):
        apply(engine, plan, on="2026-08-14")
    assert len(engine.log) == 0


def test_an_import_lands_as_ordinary_events(tmp_path, engine):
    """There is no import-shaped side door into the log."""
    apply(engine, read(sheet(tmp_path, """
Name,Type,Commitment,Currency
Sunrise Holdings Pte Ltd,Company,1000000,SGD
""")), on="2026-08-14")

    kinds = [str(e.event_type) for e in engine.log]
    assert kinds[:2] == ["ENTITY_REGISTERED", "COMMITMENT_MADE"]
    assert all(e.actor == "import" for e in engine.log
               if str(e.event_type) != "CASE_OPENED")

    # And the rules ran on the way in, which is the point of using the
    # ordinary path: a company that commits money with no declared ownership
    # is a beneficial-ownership question, whether it arrived by spreadsheet or
    # any other way.
    assert kinds[2:] == ["CASE_OPENED"]
    assert engine.queue()[0].case_type == "UBO_REVIEW"

    intact, why = engine.verify()
    assert intact, why


def test_a_firms_own_book_is_never_mixed_with_the_demo_data(tmp_path):
    """Invented parties are indistinguishable from real ones on every screen,
    and an append-only log offers no way to take them out again.
    """
    from vinzor.server import open_workspace

    engine = open_workspace(tmp_path / "live.db", demo=False)
    assert len(engine.state.graph.entities) == 0
    apply(engine, read(sheet(tmp_path, """
Name,Type
Rajesh Iyer,Individual
""")), on="2026-08-14")
    assert [e.name for e in engine.state.graph.entities.values()] == ["Rajesh Iyer"]


# -- sheets as they actually arrive ------------------------------------------


def test_a_header_below_a_title_and_a_blank_row_is_still_found(tmp_path):
    """Exports open with a title, a CONFIDENTIAL line and a spacer. Anchoring
    on row 1 fails on the first real file anyone sends.
    """
    plan = read(sheet(tmp_path, """
Investor Book as at 31 March 2026
Prepared by Operations. CONFIDENTIAL.

Name,Type,Nationality
Rajesh Iyer,Individual,SG
"""))
    assert not plan.refusals
    assert [r.name for r in plan.usable] == ["Rajesh Iyer"]
    assert any("header is on row 4" in n for n in plan.notes)


def test_a_semicolon_export_reads_and_says_so(tmp_path):
    plan = read(sheet(tmp_path, """
Name;Type;Nationality
Rajesh Iyer;Individual;SG
"""))
    assert [r.name for r in plan.usable] == ["Rajesh Iyer"]
    assert plan.usable[0].attributes["nationality"] == "SG"
    assert any("semicolon" in n for n in plan.notes)


def test_a_sheet_excel_wrote_in_the_windows_codepage_is_read(tmp_path):
    """Excel on an Indian or European Windows writes cp1252, and one rupee
    sign is enough to make strict utf-8 decoding refuse the whole file.
    """
    path = tmp_path / "cp1252.csv"
    path.write_bytes("Name,Type,Commitment\nRené Dupont,Individual,€1,000\n"
                     .encode("cp1252"))
    plan = read(path)
    assert plan.usable[0].name == "René Dupont"
    assert plan.usable[0].commitment["currency"] == "EUR"


@pytest.mark.parametrize("written,expected,currency", [
    ("USD 2,500,000", 2_500_000, "USD"),
    ("\u20b91,00,00,000", 10_000_000, "INR"),     # Indian lakh grouping
    ("Rs. 75,00,000", 7_500_000, "INR"),
    ("50 lakh", 5_000_000, ""),
    ("2.5 crore", 25_000_000, ""),
    ("2.5mn", 2_500_000, ""),
    ("750k", 750_000, ""),
    ("1,000,000", 1_000_000, ""),
])
def test_amounts_are_read_the_way_they_are_written(written, expected, currency):
    """A sheet from a Mumbai fund says "2.5 crore" far more often than it says
    25000000, and Indian grouping is not Western grouping.
    """
    from vinzor.importing import _amount

    amount, found, problem = _amount(written)
    assert problem == "", problem
    assert amount == expected
    assert found == currency


@pytest.mark.parametrize("written", ["(1,000)", "-5000", "0", "nil", "abc"])
def test_an_amount_that_is_not_a_commitment_is_refused(written):
    from vinzor.importing import _amount

    amount, _, problem = _amount(written)
    assert amount is None
    if written.lower() != "nil":
        assert problem, f"{written!r} was accepted silently"


def test_a_commitment_with_no_currency_anywhere_is_refused(tmp_path):
    """Recording an amount with a guessed currency would misstate what a firm
    is exposed to by roughly eighty-five times, in the rupee case."""
    plan = read(sheet(tmp_path, """
Name,Type,Commitment
Rajesh Iyer,Individual,2500000
"""))
    assert plan.usable == []
    assert "no currency" in plan.rejected[0].problems[0]


def test_a_currency_column_beats_one_written_in_the_cell(tmp_path):
    plan = read(sheet(tmp_path, """
Name,Type,Commitment,Currency
Rajesh Iyer,Individual,$2500000,SGD
"""))
    assert plan.usable[0].commitment["currency"] == "SGD"


@pytest.mark.parametrize("marker", ["N/A", "n.a.", "NIL", "-", "unknown", "TBD"])
def test_a_cell_meaning_nothing_is_not_recorded_as_something(tmp_path, marker):
    """"N/A" stored as a date of birth is worse than no date of birth: it is a
    value, and screening will compare it."""
    plan = read(sheet(tmp_path, f"""
Name,Type,Date of Birth,Nationality
Rajesh Iyer,Individual,{marker},{marker}
"""))
    assert plan.usable[0].attributes == {}


def test_an_invisible_space_does_not_split_one_investor_into_two(tmp_path):
    """Copy-and-paste out of a PDF brings U+00A0 with it. It looks identical
    and hashes differently, so the same person imports twice."""
    plan = read(sheet(tmp_path, "Name,Type\n  Rajesh\u00a0Iyer ,Individual\n"))
    assert plan.usable[0].name == "Rajesh Iyer"


def test_blank_spacer_rows_and_unnamed_columns_are_not_reported_as_problems(tmp_path):
    plan = read(sheet(tmp_path, """
Name,Type,,
Rajesh Iyer,Individual,,

Meera Rao,Individual,,
"""))
    assert [r.name for r in plan.usable] == ["Rajesh Iyer", "Meera Rao"]
    assert plan.ignored == [], "an unnamed spacer column was reported as ignored"


def test_two_columns_with_the_same_name_do_not_silently_overwrite(tmp_path):
    """Excel allows it. A dict comprehension would keep only the last."""
    plan = read(sheet(tmp_path, """
Name,Type,Notes,Notes
Rajesh Iyer,Individual,first,second
"""))
    assert not plan.refusals
    assert plan.ignored == ["Notes", "Notes (2)"]
