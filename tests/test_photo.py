"""Reading a document that is a photograph.

The reader that parses a PDF is deterministic and this one is not, so most of
what follows tests the seam: that a model's answer is filtered by the same
rules the parser obeys, that it is marked as a model's answer wherever it
goes, and above all that a reader which did not run is never reported as a
document that showed nothing.

Every test runs offline against a scripted reader. The transport is injected.
"""

from __future__ import annotations

import json

import pytest

from vinzor.extraction import Proposal, read as parse
from vinzor.photo import (INSTRUCTION, MAX_IMAGE_BYTES, PhotographUnreadable,
                          read, shape_of)

JPEG = b"\xff\xd8\xff" + b"pretend this is a passport photograph" * 4
PNG = b"\x89PNG\r\n\x1a\n" + b"pretend this is an aadhaar photograph" * 4


def scripted(answer):
    """A reader that says exactly this."""
    def look(data, fmt, instruction):
        look.asked = {"bytes": len(data), "format": fmt,
                      "instruction": instruction}
        if isinstance(answer, Exception):
            raise answer
        return answer
    look.asked = None
    return look


def by_field(reading):
    return {p.field: p.value for p in reading.proposals}


PASSPORT = json.dumps({"fields": [
    {"field": "name", "value": "KRAUSE FREYA", "seen_as": "Name KRAUSE"},
    {"field": "dob", "value": "1982-03-24", "seen_as": "Date of birth 24.03.1982"},
    {"field": "nationality", "value": "DEUTSCH", "seen_as": "Nationality DEUTSCH"},
    {"field": "id_document_number", "value": "FX01ADA5A",
     "seen_as": "Passport No FX01ADA5A"},
]})


# -- the thing that must never happen ----------------------------------------


def test_a_reader_that_could_not_be_reached_is_never_a_clean_read():
    """The defect this product has found four times, in a fifth place.

    A reader that failed, reported as a document that showed nothing, is
    indistinguishable on screen from a passport with nothing on it -- and
    the officer moves on.
    """
    reading = read(JPEG, kind="passport",
                   eyes=scripted(OSError("the network is down")))
    assert not reading.proposals
    assert reading.unreadable
    assert "not been read" in reading.unreadable


def test_an_answer_in_a_shape_we_cannot_read_is_a_refusal_not_an_empty_one():
    reading = read(JPEG, kind="passport", eyes=scripted("I'm sorry, I can't."))
    assert not reading.proposals
    assert reading.unreadable


def test_a_reader_that_found_nothing_says_so_in_different_words():
    """Distinct from the above, deliberately: this one ran."""
    reading = read(JPEG, kind="passport",
                   eyes=scripted(json.dumps({"fields": []})))
    assert not reading.proposals
    assert "Nothing this system recognises" in reading.unreadable


# -- what it does ------------------------------------------------------------


def test_a_photographed_passport_gives_up_its_details():
    got = by_field(read(JPEG, kind="passport", eyes=scripted(PASSPORT)))
    assert got["name"] == "KRAUSE FREYA"
    assert got["dob"] == "1982-03-24"
    assert got["id_document_number"] == "FX01ADA5A"


def test_a_fenced_answer_is_still_an_answer():
    """Providers wrap JSON in markdown about half the time."""
    got = by_field(read(JPEG, kind="passport",
                        eyes=scripted("```json\n" + PASSPORT + "\n```")))
    assert got["name"] == "KRAUSE FREYA"


def test_the_picture_is_named_by_its_bytes_not_by_the_caller():
    eyes = scripted(PASSPORT)
    read(PNG, kind="aadhaar", eyes=eyes)
    assert eyes.asked["format"] == "png"
    assert shape_of(JPEG) == "jpeg"
    assert shape_of(b"neither of those") == ""


# -- every proposal says a model read it -------------------------------------


def test_every_proposal_says_which_reader_produced_it():
    """An officer confirming a date of birth is entitled to know whether it
    was parsed off a page or looked at by a model."""
    reading = read(JPEG, kind="passport", eyes=scripted(PASSPORT))
    for proposal in reading.proposals:
        assert proposal.read_by == Proposal.BY_MODEL

    from pathlib import Path
    pack = Path(__file__).resolve().parent.parent / "examples" / "pack"
    parsed = parse(pack / "passport-bhat.pdf", kind="passport")
    for proposal in parsed.proposals:
        assert proposal.read_by == Proposal.BY_PARSER


# -- the model does not get to widen what a document proves ------------------


def test_a_document_may_not_evidence_what_its_kind_cannot():
    """A utility bill that prints a nationality does not get to prove one,
    however clearly the photograph shows it. documents.KINDS decides, and
    the model is not trusted to have obeyed the instruction it was given."""
    said = json.dumps({"fields": [
        {"field": "address", "value": "51247 Koln, Heidestrasse 19",
         "seen_as": "51247 KOLN HEIDESTRASSE 19"},
        {"field": "nationality", "value": "DEUTSCH", "seen_as": "DEUTSCH"},
        {"field": "dob", "value": "1982-03-24", "seen_as": "24.03.1982"},
    ]})
    got = by_field(read(JPEG, kind="utility_bill", eyes=scripted(said)))
    assert "address" in got
    assert "nationality" not in got
    assert "dob" not in got


def test_an_identifier_with_no_digit_in_it_is_still_not_an_identifier():
    said = json.dumps({"fields": [
        {"field": "pan", "value": "Card", "seen_as": "Permanent Account Number Card"},
    ]})
    assert not read(JPEG, kind="pan_card", eyes=scripted(said)).proposals


def test_a_placeholder_date_is_not_a_date():
    """Sumsub's own Aadhaar sample prints 00/00/0000. A reader that turned
    that into a real looking date would put it on a compliance file."""
    said = json.dumps({"fields": [
        {"field": "name", "value": "George Smith", "seen_as": "George Smith"},
        {"field": "dob", "value": "00/00/0000", "seen_as": "DOB : 00/00/0000"},
    ]})
    got = by_field(read(PNG, kind="aadhaar", eyes=scripted(said)))
    assert got["name"] == "George Smith"
    assert "dob" not in got


def test_a_null_value_is_not_a_value():
    said = json.dumps({"fields": [
        {"field": "name", "value": None, "seen_as": "unreadable"},
        {"field": "dob", "value": "1982-03-24", "seen_as": "24.03.1982"},
    ]})
    got = by_field(read(JPEG, kind="passport", eyes=scripted(said)))
    assert "name" not in got
    assert got["dob"] == "1982-03-24"


# -- what it refuses before it asks ------------------------------------------


def test_something_that_is_not_a_picture_is_refused_without_asking():
    eyes = scripted(PASSPORT)
    reading = read(b"%PDF-1.4 this is a pdf", kind="passport", eyes=eyes)
    assert reading.unreadable
    assert eyes.asked is None, "nothing should have been sent"


def test_an_enormous_image_is_refused_without_asking():
    eyes = scripted(PASSPORT)
    huge = b"\xff\xd8\xff" + b"\0" * (MAX_IMAGE_BYTES + 1)
    reading = read(huge, kind="passport", eyes=eyes)
    assert reading.unreadable
    assert eyes.asked is None


def test_a_kind_this_system_does_not_know_evidences_nothing():
    eyes = scripted(PASSPORT)
    assert read(JPEG, kind="not_a_kind", eyes=eyes).unreadable
    assert eyes.asked is None


# -- the instruction ---------------------------------------------------------


def test_the_reader_is_asked_to_transcribe_and_not_to_judge():
    """The one thing a model must not be invited to do here. A reader that
    volunteered "this passport looks genuine" would be establishing
    something, and nothing in this module may establish anything."""
    assert "not judging" in INSTRUCTION
    for judging in ("genuine", "valid", "expired", "acceptable"):
        assert judging in INSTRUCTION, (
            "the instruction has to name what it is refusing to do")


def test_nothing_is_written_to_any_record():
    import inspect

    from vinzor import photo

    source = inspect.getsource(photo)
    for writing in ("ingest(", "engine.", "file_document"):
        assert writing not in source, f"{writing} would make this establish a fact"


# -- the parser is still preferred where there is one ------------------------


def test_a_readable_pdf_never_reaches_the_model():
    """Where a document can be parsed it is parsed, because that answer is
    reproducible and a model's is not. The model is for when the alternative
    is nothing at all."""
    from pathlib import Path

    pack = Path(__file__).resolve().parent.parent / "examples" / "pack"
    eyes = scripted(PASSPORT)
    reading = parse(pack / "passport-bhat.pdf", kind="passport", eyes=eyes)
    assert eyes.asked is None, "a parsable document went to the model anyway"
    assert by_field(reading)["name"] == "ANAND BHAT"


def test_a_picture_reaches_the_model_through_the_ordinary_reader():
    eyes = scripted(PASSPORT)
    reading = parse(JPEG, kind="passport", eyes=eyes)
    assert eyes.asked is not None
    assert by_field(reading)["name"] == "KRAUSE FREYA"


def test_with_no_model_a_picture_still_says_what_it_is():
    """No reader configured is not an error. It is the sentence that was
    always there."""
    reading = parse(JPEG, kind="passport")
    assert not reading.proposals
    assert reading.unreadable
