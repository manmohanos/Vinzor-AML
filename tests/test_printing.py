"""Writing the record out as the PDF somebody actually sends.

The useful property here is that this repository already contains a PDF
*reader*, written for the clause register. So these tests do not check that
bytes were produced -- they read the document back and check what it says,
which is the only version of this test worth having.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vinzor.dossier import dossier
from vinzor.pdfwrite import BOLD, REGULAR, Document, measure, wrap
from vinzor.pdftext import pages
from vinzor.printing import filename_for, render

from conftest import commits, company, officer, paid, person, screened


@pytest.fixture
def workspace(engine):
    officer(engine)
    person(engine, "p1", "Rohan Desai")
    company(engine, "c1", "Orion Zenith Enterprises")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    commits(engine, "c1")
    paid(engine, "p1", anomaly="OVERPAYMENT", payment_id="pay_1")
    return engine


def read_back(data: bytes, tmp_path) -> str:
    out = tmp_path / "read.pdf"
    out.write_bytes(data)
    return "\n".join(page.text for page in pages(str(out)))


# -- it is a real PDF ---------------------------------------------------------


def test_the_file_is_a_pdf_our_own_reader_can_open(workspace, tmp_path):
    """Not a magic-number check. The document is read back with the reader
    written for the clause register, which is the only proof that a PDF
    viewer would have got the same thing."""
    paper = dossier(workspace, "p1", "2026-08-22", record=False)
    data = render(paper)
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    text = read_back(data, tmp_path)
    assert "Rohan Desai" in text


def test_the_firm_and_the_product_are_both_on_it(workspace, tmp_path):
    paper = dossier(workspace, "p1", "2026-08-22", workspace="Acme GIFT",
                    record=False)
    text = read_back(render(paper), tmp_path)
    assert "Vinzor" in text
    assert "Acme GIFT" in text


def test_the_warning_about_who_may_read_it_is_on_the_first_page(
        workspace, tmp_path):
    """Clause 4.1(d) forbids tipping off a customer under examination, and
    this document names what was suspected. The warning cannot be somewhere
    a reader might not reach."""
    paper = dossier(workspace, "p1", "2026-08-22", record=False)
    out = tmp_path / "one.pdf"
    out.write_bytes(render(paper))
    first = pages(str(out))[0].text
    assert "never be given to the party" in first


def test_every_page_is_numbered_and_says_how_many_there_are(
        workspace, tmp_path):
    """A compliance document that arrives two pages short should be
    detectable by the person holding it."""
    paper = dossier(workspace, "c1", "2026-08-22", record=False)
    out = tmp_path / "many.pdf"
    out.write_bytes(render(paper))
    read = pages(str(out))
    assert len(read) >= 1
    for index, page in enumerate(read, start=1):
        assert "Page %d of %d" % (index, len(read)) in page.text


def test_a_party_that_is_not_on_the_record_says_only_that(workspace, tmp_path):
    paper = dossier(workspace, "nobody_at_all", "2026-08-22", record=False)
    text = read_back(render(paper), tmp_path)
    assert "Vinzor" in text


def test_printing_writes_nothing_to_the_log(workspace):
    """Asking for a printable copy is not an event. A download that wrote to
    an append-only ledger would put a row in it every time somebody pressed
    a button twice."""
    before = len(workspace.log)
    render(dossier(workspace, "p1", "2026-08-22", record=False))
    assert len(workspace.log) == before


# -- the layout ---------------------------------------------------------------


def test_a_long_document_runs_onto_more_than_one_page(tmp_path):
    pdf = Document(title="long")
    for n in range(120):
        pdf.paragraph(f"Line {n}. " + "words " * 12)
    out = tmp_path / "long.pdf"
    out.write_bytes(pdf.bytes())
    assert len(pages(str(out))) > 1


def test_text_wraps_at_the_measured_width_not_a_character_count():
    """Wrapping by counting characters overflows on capitals and wastes a
    third of the page on lowercase."""
    narrow = wrap("WWWWWWWWWW", REGULAR, 10, 60)
    wide = wrap("iiiiiiiiii", REGULAR, 10, 60)
    assert len(narrow) > len(wide)
    for line in wrap("the quick brown fox jumps over the lazy dog",
                     REGULAR, 10, 100):
        assert measure(line, REGULAR, 10) <= 100


def test_a_word_too_long_for_the_page_is_cut_rather_than_lost():
    lines = wrap("x" * 400, REGULAR, 10, 80)
    assert len(lines) > 1
    for line in lines:
        assert measure(line, REGULAR, 10) <= 80


def test_bold_is_measured_as_bold():
    assert measure("Compliance", BOLD, 10) > measure("Compliance", REGULAR, 10)


def test_a_heading_never_ends_a_page_alone(tmp_path):
    """A heading stranded at the foot of a page with its section overleaf
    reads as a document that was cut in half."""
    pdf = Document()
    pdf.y = 90          # almost nothing left on this page
    before = len(pdf.pages)
    pdf.heading("What was found")
    assert len(pdf.pages) > before


# -- characters the base fonts cannot draw ------------------------------------


def test_a_name_outside_latin_is_marked_rather_than_silently_dropped(tmp_path):
    """The base-14 fonts cover Latin-1 and no more. A name that has lost a
    character to a substitution is visibly wrong; one that has silently lost
    three is a different name that looks correct."""
    pdf = Document()
    pdf.paragraph("Name: गोपाल")
    out = tmp_path / "devanagari.pdf"
    out.write_bytes(pdf.bytes())
    text = "\n".join(p.text for p in pages(str(out)))
    assert "Name:" in text
    assert "?" in text


def test_typographic_punctuation_is_folded_rather_than_questioned():
    """briefing.py writes real em dashes and curly quotes, and a compliance
    document peppered with question marks where its punctuation was would
    look broken."""
    from vinzor.pdfwrite import _latin

    assert _latin("a — b") == "a - b"
    assert _latin("‘quoted’") == "'quoted'"
    assert _latin("“quoted”") == '"quoted"'
    assert "?" not in _latin("one… two – three")


# -- the name it lands under --------------------------------------------------


def test_the_download_is_named_as_a_pdf(workspace):
    paper = dossier(workspace, "p1", "2026-08-22", record=False)
    assert filename_for(paper, "2026-08-22").endswith(".pdf")


def test_the_server_does_not_call_every_download_a_spreadsheet():
    """``_filename`` wrote ``.xlsx`` into itself, because for a while a
    workbook was the only thing this server handed out. The first PDF route
    to use it would have sent a correct PDF under a name telling the
    operating system to open it in a spreadsheet."""
    from vinzor.server import _filename

    assert _filename("a record", "pdf").endswith(".pdf")
    assert _filename("the book").endswith(".xlsx")
    assert "/" not in _filename('a "quoted"/slashed name', "pdf")
