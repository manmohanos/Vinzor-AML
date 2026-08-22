"""Reading a document, and proposing nothing more.

The division under test is the same one drawn around the model: this reads
and suggests, a person confirms. A field promoted straight onto the record
would mean the firm had copied a document rather than verified one, and
clause 5.4.5 asks for the second.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vinzor.extraction import LABELS, Proposal, fields_in, read

PACK = Path(__file__).resolve().parent.parent / "examples" / "pack"


def by_field(reading):
    return {p.field: p.value for p in reading.proposals}


def test_a_passport_gives_up_its_details():
    got = by_field(read(PACK / "passport-bhat.pdf", kind="passport"))
    assert got["name"] == "ANAND BHAT"
    assert got["dob"] == "1981-03-14", "a date is normalised to how the record keeps one"
    assert got["nationality"] == "INDIAN"
    assert got["id_document_number"] == "Z9999999"


def test_a_surname_on_its_own_is_not_a_name():
    """A passport prints the two halves separately. Taking the first and
    stopping gives a party called "BHAT" -- a surname, and the name every
    later check would then screen."""
    got = by_field(read(PACK / "passport-bhat.pdf", kind="passport"))
    assert got["name"] == "ANAND BHAT"
    assert got["name"] != "BHAT"


def test_an_identifier_with_no_digit_in_it_is_not_an_identifier():
    """The title of a PAN card is "Permanent Account Number Card", which
    prefix-matches the label and leaves a permanent account number of
    "Card". That would have gone onto a compliance record."""
    got = by_field(read(PACK / "pan-bhat.pdf", kind="pan_card"))
    assert got["pan"] == "ZZZPB0000Z"


def test_a_document_may_not_evidence_what_its_kind_cannot():
    """A utility bill that happens to print a nationality does not get to
    prove one. documents.KINDS decides what a kind of paper supports, and a
    reader is not the place to argue with it."""
    got = by_field(read(PACK / "utility-bhat.pdf", kind="utility_bill"))
    assert "address" in got
    assert "nationality" not in got
    assert "dob" not in got


def test_a_company_certificate_reads_as_a_company():
    got = by_field(read(PACK / "incorporation-orion.pdf", kind="incorporation"))
    assert got["cin"] == "U00000MH2019PTC000000"
    assert got["date_of_incorporation"] == "2019-04-09"
    assert "ORION" in got["name"]


# -- the part that matters ----------------------------------------------------


def test_a_document_that_disagrees_with_the_record_says_so():
    """The finding worth having. The spreadsheet says one date of birth and
    the passport says another; one of them is wrong and a person decides
    which. Nothing here decides."""
    reading = read(PACK / "passport-bhat.pdf", kind="passport",
                   holds={"name": "Anand Bhat", "dob": "1979-01-01"})
    disagreed = {p.field for p in reading.disagreements}
    assert "dob" in disagreed
    agreed = {p.field for p in reading.proposals if p.agrees}
    assert "name" in agreed, "agreement is corroboration and worth showing too"


def test_every_proposal_carries_the_line_it_was_read_from():
    """The whole reason to trust one. An officer can see where a value came
    off the page without opening the file."""
    reading = read(PACK / "passport-bhat.pdf", kind="passport")
    for proposal in reading.proposals:
        assert proposal.seen_as
        # Every word of the value has to appear in the line it was read
        # from. A name assembled from two lines names both of them: a
        # proposal whose "seen as" does not contain its own value is one an
        # officer cannot check, which is the only thing making these
        # trustworthy at all. Dates are exempt -- they are normalised to the
        # shape the record keeps, and the page said 14/03/1981.
        if proposal.field in ("dob", "date_of_incorporation", "expires"):
            continue
        for word in proposal.value.split():
            assert word in proposal.seen_as, (
                f"{proposal.field}={proposal.value!r} claims to have been "
                f"read from {proposal.seen_as!r}")


def test_nothing_is_written_to_any_record():
    """It returns proposals. There is no engine here to write to, and that
    is the design rather than an oversight."""
    import inspect

    from vinzor import extraction

    source = inspect.getsource(extraction)
    for writing in ("ingest(", "engine.", "file_document"):
        assert writing not in source, f"{writing} would make this establish a fact"


# -- what it will not do ------------------------------------------------------


def test_an_image_with_no_text_says_so_rather_than_guessing():
    reading = read(b"%PDF-1.4 nothing readable here at all", kind="passport")
    assert reading.unreadable
    assert not reading.proposals


def test_something_that_is_not_a_document_is_refused_in_words():
    reading = read(b"this is not a pdf", kind="passport")
    assert reading.unreadable
    assert not reading.proposals


def test_reading_the_same_document_twice_gives_the_same_answer():
    """Deterministic, which is why there is no model in here. A field that
    changed between two readings could not go on a compliance file."""
    first = read(PACK / "passport-bhat.pdf", kind="passport")
    second = read(PACK / "passport-bhat.pdf", kind="passport")
    assert by_field(first) == by_field(second)


def test_the_words_it_looks_for_are_a_table_anyone_can_read():
    """A firm has to be able to say what its software searched for."""
    fields = {field for field, _words in LABELS}
    assert {"name", "dob", "pan", "address"} <= fields
    for _field, words in LABELS:
        assert all(word == word.lower() for word in words)


# -- a document that is no longer valid ---------------------------------------


def test_a_passport_that_has_expired_says_so():
    """Clause 1.3.30 asks for an officially valid document, and one that ran
    out five years before it was handed over is not one.

    The product read the rest of the page and said nothing about the expiry,
    so an expired passport satisfied a document requirement exactly as a
    current one did.
    """
    library = Path(__file__).resolve().parent.parent / "examples" / "library"
    reading = read(library / "03-expired-document" / "passport-iyer-EXPIRED.pdf",
                   kind="passport", today="2026-08-22")
    assert reading.expired
    assert "2021-02-11" in reading.expired
    assert "1.3.30" in reading.expired


def test_a_current_passport_says_nothing_about_expiry():
    reading = read(PACK / "passport-bhat.pdf", kind="passport",
                   today="2026-08-22")
    assert not reading.expired
    assert by_field(reading)["expires"] == "2032-07-22"


def test_an_expired_document_is_still_filed_and_still_read():
    """A finding, not a refusal. What a firm holds is a fact about the firm,
    and refusing to record it would be losing the evidence that they were
    given an out-of-date passport."""
    library = Path(__file__).resolve().parent.parent / "examples" / "library"
    reading = read(library / "03-expired-document" / "passport-iyer-EXPIRED.pdf",
                   kind="passport", today="2026-08-22")
    got = by_field(reading)
    assert got["name"] == "RAKESH IYER"
    assert got["dob"] == "1975-06-02"


def test_expiry_is_never_judged_without_being_told_the_day():
    """No module under vinzor/ may read a clock. With no date supplied there
    is no opinion to give, rather than a wrong one."""
    library = Path(__file__).resolve().parent.parent / "examples" / "library"
    reading = read(library / "03-expired-document" / "passport-iyer-EXPIRED.pdf",
                   kind="passport")
    assert not reading.expired


def test_a_utility_bill_may_not_evidence_an_expiry():
    """``expires`` is on the three kinds that print one. A bill is not one."""
    from vinzor.documents import KINDS

    assert "expires" in KINDS["passport"][1]
    assert "expires" in KINDS["driving_licence"][1]
    assert "expires" not in KINDS["utility_bill"][1]
    assert "expires" not in KINDS["pan_card"][1]
