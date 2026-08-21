"""Every quoted clause, checked against the regulator's own PDF.

The register in ``citations.py`` quoted twenty-one clauses. They were read
against IFSCA's published documents once, by hand, on 14 August 2026, and
twelve of the twenty-one had a real problem. All twelve were corrected --
and then nothing at all stopped them drifting again, because an extract is
a string in a Python file and a string in a Python file can be changed by
anybody who thinks they are tidying a quotation.

Running the same check by machine found five more the hand check had
passed. Three were punctuation: a semicolon printed as a full stop, which
turns half a clause into what looks like a whole sentence; a space inserted
into a Home Affairs file number; a semicolon inserted into the list of
things an employee may know or suspect. The fourth was not punctuation --
clause 3(4)'s three licence categories were quoted as a semicolon list that
appears nowhere in the Regulations, which set them out as a lettered list
running over a page break. The fifth was not a quotation at all: the file
recorded that most Fund Management headings were its own descriptions
rather than IFSCA's words, and every one of them turned out to be printed
in the document.

None of the five changes what a rule requires. All five meant the file was
saying something about the source that was not so, while telling a
compliance officer it had been checked.

That is the case for this file. A person reading two dozen long clauses for
punctuation is doing a job people are bad at and machines are good at.

**What this proves and does not.** It proves the words in the register are
the words in the document, on the page the register names. It proves
nothing about whether the right clause was chosen for the rule that cites
it, or whether it means what this system takes it to mean. Those need a
qualified person, and until one signs a clause off ``verified`` stays False
and every Case citing it says so.
"""

from __future__ import annotations

import hashlib

import pytest

from vinzor import pdftext
from vinzor.citations import (CLAUSES, DOCUMENTS, SOURCES, checkable, held,
                              uncheckable)


@pytest.fixture(scope="module")
def books():
    """Both documents as text, read once for the whole module."""
    out = {}
    for doc_id, source in SOURCES.items():
        if not source.path.exists():
            pytest.skip(f"no copy of {source.filename}")
        out[doc_id] = pdftext.pages(source.path)
    return out


def where_it_stops(extract: str, book) -> str:
    """Why a clause was not found, in enough detail to fix it.

    A bare "not found" on a four-hundred-character quotation sends whoever
    reads it back to the PDF to do the comparison by eye, which is the work
    this file exists to remove.
    """
    whole = pdftext.flatten(pdftext.as_amended(" ".join(p.text for p in book)))
    said = []
    for part in pdftext.as_amended(extract).split(pdftext.ELISION):
        part = pdftext.flatten(part)
        if not part:
            continue
        if part in whole:
            said.append(f"    in the document: {part[:60]}...")
            continue
        low, high = 0, len(part)
        while low < high:
            middle = (low + high + 1) // 2
            if part[:middle] in whole:
                low = middle
            else:
                high = middle - 1
        at = whole.find(part[max(0, low - 50):low])
        said.append(
            f"    matches for {low} of {len(part)} characters, then parts:\n"
            f"      register: ...{part[max(0, low - 50):low + 50]}\n"
            f"      document: ...{whole[at:at + 100] if at >= 0 else '(lost)'}")
    return "\n".join(said)


# -- the copies being read are the copies that were checked -------------------


@pytest.mark.parametrize("doc_id", sorted(SOURCES))
def test_the_document_is_the_edition_the_register_was_built_against(doc_id):
    """IFSCA republishes a consolidated master at the same address every
    time a circular lands, and the page numbers move. Without this the
    register would go on citing page 5 of a document whose page 5 changed,
    and every test below would keep passing against the new one."""
    source = SOURCES[doc_id]
    if not source.path.exists():
        pytest.skip(f"no copy of {source.filename} is kept")
    seen = hashlib.sha256(source.path.read_bytes()).hexdigest()
    assert seen == source.digest, (
        f"\n{source.filename} is not the copy this register was checked "
        f"against.\nIf IFSCA has published a new consolidation, the clause "
        f"pages in citations.py have almost certainly moved and must be "
        f"rechecked before the new digest is recorded here.")


@pytest.mark.parametrize("doc_id", sorted(SOURCES))
def test_the_whole_document_can_be_read(doc_id, books):
    """A page that yields no letters is a page a clause could hide on."""
    book = books[doc_id]
    assert len(book) == SOURCES[doc_id].pages
    blank = [page.number for page in book if not page.readable]
    assert not blank, f"pages that could not be read: {blank}"
    assert sum(page.guessed_at for page in book) == 0


def test_the_body_text_of_a_clause_page_is_actually_there(books):
    """The regression that started this. IFSCA sets its body text in subset
    Aptos, encoded Identity-H, so every letter is a two-byte glyph number;
    an extractor that reads only the plain strings returns page 5 as
    ``1.3.2 1.3.3 (a) (i) 4`` -- the numbering, and not one word under it.
    A clause check run against that reports the correct wording of the
    beneficial-ownership definition as missing from the document that
    states it."""
    page = books["IFSCA-AML-2022"][4]
    assert page.number == 5
    assert "Beneficial" in page.text
    assert "controlling ownership interest" in page.text.lower()
    assert len(page.text.split()) > 250


# -- the clauses themselves ---------------------------------------------------


@pytest.mark.parametrize("clause_id", sorted(CLAUSES))
def test_the_clause_says_what_the_document_says(clause_id, books):
    clause = CLAUSES[clause_id]
    book = books[clause.doc_id]
    found = pdftext.find(clause.extract, book)
    if found is None:
        pytest.fail(
            f"\nclause {clause_id} is quoted in the register but this "
            f"sentence is not in {held(clause.doc_id).filename}:\n"
            f"{where_it_stops(clause.extract, book)}")
    assert found == clause.page, (
        f"\nclause {clause_id} says page {clause.page}; the sentence is on "
        f"page {found}. If IFSCA has repaginated, every page in this "
        f"register needs rechecking, not just this one.")


def test_every_clause_in_the_register_was_checked(books):
    """The parametrised test above proves each clause it runs on. This
    proves it runs on all of them -- a filter that quietly stopped matching
    would otherwise leave the suite green and the register unchecked."""
    assert len(CLAUSES) == 29
    assert len(checkable()) == 29
    assert all(pdftext.find(c.extract, books[c.doc_id]) == c.page
               for c in CLAUSES.values())


@pytest.mark.parametrize("clause_id", sorted(CLAUSES))
def test_a_heading_is_the_regulator_s_own_words_or_is_declared_not_to_be(
        clause_id, books):
    """A heading presented as the regulator's when it is this file's is the
    same defect as an extract presented as verbatim when it is not, and
    harder to spot, because a heading is short enough to look obviously
    right. This file used to record that most Fund Management headings were
    editorial descriptions. Checking them found the opposite: every one is
    IFSCA's own, printed above the regulation."""
    from vinzor.citations import EDITORIAL_HEADINGS

    clause = CLAUSES[clause_id]
    at = pdftext.find(clause.heading, books[clause.doc_id])
    if clause_id in EDITORIAL_HEADINGS:
        assert at is None, (
            f"{clause_id}'s heading is declared this register's own wording, "
            f"but the document prints it on page {at}. Take it out of "
            f"EDITORIAL_HEADINGS -- it is the regulator's.")
    else:
        assert at is not None, (
            f"{clause_id}'s heading is presented as the document's own "
            f"words and does not appear in it. Either correct it or declare "
            f"it in EDITORIAL_HEADINGS.")


def test_a_shared_heading_belongs_to_the_parent_regulation(books):
    """Sub-regulations 7(1) to 7(5) and 8(1) carry the heading printed above
    the regulation they sit under, not one of their own. That is the
    document's structure and not a copying mistake, so they are checked as
    the regulator's words rather than declared editorial."""
    book = books["IFSCA-FMR-2025"]
    shared = {CLAUSES[c].heading for c in ("7(1)", "7(2)", "7(3)", "7(4)", "7(5)")}
    assert len(shared) == 1
    assert pdftext.find(shared.pop(), book) == 7
    assert pdftext.find(CLAUSES["8(1)"].heading, book) == 10


def test_the_permitted_activities_are_the_ones_the_regulation_lists(books):
    """``licence.py`` decides what each registration category may do, and
    every screen about scope rests on it. It was written from Regulation
    3(4) without a copy of Regulation 3(4) nearby. Each activity is tied
    here to the phrase in the document that creates it, so the model cannot
    drift from the rule quietly."""
    from vinzor.licence import PERMITTED, Activity, Category

    book = books["IFSCA-FMR-2025"]
    creates = {
        Activity.VENTURE_CAPITAL_SCHEME:
            "early-stage ventures through Venture Capital Scheme",
        Activity.FAMILY_INVESTMENT_FUND:
            "set up by a Single Family to manage its Family Investment Fund",
        Activity.RESTRICTED_SCHEME:
            "through one or more restricted schemes",
        Activity.PORTFOLIO_MANAGEMENT_SERVICES:
            "undertake Portfolio Management Services (including for "
            "multi-family office)",
        Activity.INVESTMENT_TRUST_PRIVATE_PLACEMENT:
            "investment manager for private placement of Investment Trusts "
            "(REITs and InvITs)",
        Activity.RETAIL_SCHEME:
            "permitted asset classes through retail schemes",
        Activity.INVESTMENT_TRUST_PUBLIC_OFFER:
            "investment manager for public offer of Investment Trusts "
            "(REITs and InvITs)",
        Activity.EXCHANGE_TRADED_FUND:
            "launch Exchange Traded Funds (ETFs)",
    }
    assert set(creates) == set(Activity), "an activity with no source phrase"
    for activity, phrase in creates.items():
        assert pdftext.find(phrase, book) is not None, activity

    # The categories build on each other, which the document says outright:
    # (b)(iii) admits everything an Authorised FME may do, and (c)(iii)
    # everything (a) and (b) may.
    assert (PERMITTED[Category.AUTHORISED]
            < PERMITTED[Category.REGISTERED_NON_RETAIL]
            < PERMITTED[Category.REGISTERED_RETAIL])
    assert PERMITTED[Category.REGISTERED_RETAIL] == set(Activity)
    assert pdftext.find(
        "such FMEs shall also be able to undertake all activities as "
        "permitted to Authorised FMEs and Registered FMEs (Non-retail).",
        book) == 6


# -- the check is able to fail ------------------------------------------------


def test_a_sentence_the_document_does_not_contain_is_not_found(books):
    """Without this the suite would pass just as happily if ``find`` always
    said yes, which for a test whose whole job is catching a wrong
    quotation is the only failure that matters."""
    assert pdftext.find("The Authority shall reimburse all fees paid.",
                        books["IFSCA-AML-2022"]) is None


def test_the_superseded_threshold_is_not_accepted(books):
    """Twenty-five per cent was the beneficial-ownership threshold before
    the 2023 amendment, and quoting it would be the single most damaging
    drift available in this register. It must not match."""
    was = CLAUSES["1.3.3(a)"].extract.replace("ten per cent", "twenty-five per cent")
    assert pdftext.find(was, books["IFSCA-AML-2022"]) is None


def test_a_near_miss_in_punctuation_is_not_accepted(books):
    """Three of the four defects the hand check missed were punctuation. A
    matcher relaxed enough to forgive them would have found nothing."""
    loose = CLAUSES["10.1"].extract.replace("suspecting that", "suspecting; that")
    assert pdftext.find(loose, books["IFSCA-AML-2022"]) is None


def test_the_semicolon_list_that_was_never_in_the_regulations_is_not_accepted(books):
    """What clause 3(4) used to quote. The Regulations set the three licence
    categories out as a lettered list with numbered sub-clauses; the
    register had compressed them into ``Authorised FME; Registered FME
    (Non-Retail); Registered FME (Retail)``, which reads like a quotation
    and is not one."""
    invented = ("The applicant shall seek registration under any of the "
                "following three categories: Authorised FME; Registered FME "
                "(Non-Retail); Registered FME (Retail).")
    assert pdftext.find(invented, books["IFSCA-FMR-2025"]) is None


def test_two_sentences_a_chapter_apart_do_not_satisfy_one_extract(books):
    """A clause may run over a page break, which is why ``find`` looks past
    the end of a page at all. Without a limit on how far it looks, an
    extract could be satisfied by two unrelated sentences forty pages
    apart, and the elision mark would hide that it had been."""
    book = books["IFSCA-FMR-2025"]
    near = CLAUSES["7(1)"].extract[:60]
    far = CLAUSES["137"].extract[:60]
    assert pdftext.find(near, book) == 7
    assert pdftext.find(far, book) == 79
    assert pdftext.find(f"{near} {pdftext.ELISION} {far}", book) is None


# -- what is not checked, said out loud ---------------------------------------


def test_no_clause_rests_on_a_document_nobody_kept():
    """This was not always true. For a week the register quoted nine
    clauses of the Fund Management Regulations with no copy of that
    document anywhere near it, so the rules on who a fund manager must
    appoint and what it must tell the Authority rested on one person having
    read them once, in August, and nothing rechecking it."""
    assert uncheckable() == ()
    assert set(SOURCES) == set(DOCUMENTS)


def test_every_clause_carries_the_date_of_the_check_it_had():
    from vinzor.citations import SOURCE_CHECKED_ON

    assert all(c.source_checked == SOURCE_CHECKED_ON for c in CLAUSES.values())


def test_the_printed_report_does_not_claim_more_than_was_done():
    """The line a compliance officer reads. It may say the wording was
    matched; it may not say the rule was confirmed, which is a qualified
    person's job and has not happened."""
    from vinzor.briefing import SOURCE_CHECK_LINE

    said = SOURCE_CHECK_LINE.format(checked="20 August 2026",
                                    clauses=len(CLAUSES),
                                    documents=len(SOURCES))
    assert "29" in said and "20 August 2026" in said
    assert "does not show that the right clause was picked" in said
    assert len(said) < 500, "a caveat nobody finishes reading is not a caveat"


# -- how the two documents' conventions are read ------------------------------


def test_an_amended_word_is_read_as_the_word_in_force():
    """IFSCA does not reprint an amended sentence. It leaves the original,
    marks it with a footnote number and sets the replacement in brackets,
    so page 5 of the Guidelines reads ``more than 5[ten] per cent.`` The
    rule in force is ten per cent."""
    assert pdftext.as_amended("more than \n5\n[ten] per cent.") == \
        "more than \nten per cent."


def test_an_amendment_whose_bracket_is_never_closed_loses_only_its_marker():
    """Page 5 has one. Inventing a closing bracket would be deciding where
    an amendment ends, which is the regulator's to say and not this
    file's."""
    assert pdftext.as_amended("partnership \n6\n[or who exercises control") == \
        "partnership \nor who exercises control"


def test_an_ordinary_bracket_is_left_alone():
    """The fold is narrow on purpose: only a bracket introduced by a
    footnote number is apparatus. Everything else is the text."""
    assert pdftext.as_amended("sub-section (1) [see below]") == \
        "sub-section (1) [see below]"


def test_a_hyphen_at_a_line_end_is_read_every_way_it_could_be_meant():
    """It may be the typesetter's -- "compli-" over "ance" is *compliance*
    -- or the author's -- "sub-" over "regulation" is *sub-regulation*. The
    page does not say which, and both are in IFSCA's text."""
    assert pdftext.flatten("compli-\nance") == "compli- ance"
    assert pdftext.mended("compli-\nance") == "compliance"
    assert pdftext.mended("sub-\nregulation", keep_hyphen=True) == "sub-regulation"


def test_a_word_the_author_hyphenated_survives_a_line_break(books):
    """Clause 7(5) quotes ``sub-regulation``, and page 8 breaks the line
    inside it. Neither reading the page as printed nor mending it into
    ``subregulation`` finds the clause; the third reading does."""
    assert pdftext.find(CLAUSES["7(5)"].extract, books["IFSCA-FMR-2025"]) == 8


def test_a_clause_that_runs_over_a_page_break_cites_where_it_begins(books):
    """Clause 3(4) lists three licence categories. The first is on page 5
    and the other two are on page 6, and a citation names the page a reader
    turns to, which is the first."""
    book = books["IFSCA-FMR-2025"]
    assert pdftext.find(CLAUSES["3(4)"].extract, book) == 5
    assert "Registered FME (Non-Retail)" not in book[4].text
    assert "Registered FME (Non-Retail)" in book[5].text


def test_an_extract_may_leave_the_middle_out_but_not_reorder_it(books):
    """``...`` is this register's mark for words left out, and four clauses
    use it. The parts on either side must still appear in the order the
    register puts them."""
    clause = CLAUSES["1.3.3(a)"]
    book = books["IFSCA-AML-2022"]
    assert pdftext.ELISION in clause.extract
    assert pdftext.find(clause.extract, book) == 5
    front, back = clause.extract.split(pdftext.ELISION, 1)
    assert pdftext.find(f"{back} {pdftext.ELISION} {front}", book) is None
