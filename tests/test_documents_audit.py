"""What the documents block claims, tested by attacking it.

This block exists to answer one question: how does the firm know. Every
attribute on every party arrived in a spreadsheet column, and clause 5.4.5
does not ask for the data, it asks that identity be verified from reliable
independent sources. So a document is filed, a person says what it
evidences, and a fact with paper behind it stops looking like a fact
somebody typed.

Its central promise is one sentence in its own docstring: *a document may
be said to support less than it could, never more*. **There was a door
straight through it.**

``KINDS`` gives every document an allowlist of what it can evidence, and
the check enforced it -- except that it read ``if overreach and kind !=
"other"``. An unclassified file could therefore be filed as evidence of a
name, a date of birth, a nationality and a permanent account number at
once. Measured on a party holding the seven items clause 5.4.2 asks of a
person, one such file left **five of the seven reading as backed by a
document** and two as unsupported. The party was never reported as fully
evidenced -- that is worth saying plainly, because it is less than it first
appeared -- but a screen whose whole job is to separate "we hold it" from
"we can produce paper for it" said the wrong thing about five facts out of
seven. It was also the easiest path in the product, because "Other
document" is exactly what somebody picks when they cannot find their
document in the list.

**And the expiry cascade could be turned off by a keystroke.** The door
accepts ``2026-1-1`` -- which is how a person writes 1 January -- and
expiry was a text comparison, in which ``"2026-1-1" > "2026-08-20"``. A
passport seven months out of date read as current and went on evidencing a
nationality. Because the log cannot be rewritten, records carrying such a
date exist for good, so the fix had to be in the reading and not only at
the door.

What held: the fingerprint does catch the same scan filed against two
investors, and the cascade is otherwise exactly as described -- a lapsed
passport stops supporting a nationality while the tax card keeps supporting
the name.
"""

from __future__ import annotations

import pytest

from vinzor import readiness
from vinzor.documents import EVIDENCEABLE, KINDS, Paper, refuse
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType

A_PDF = b"%PDF-1.4 the bytes of a scan"


@pytest.fixture
def book() -> Vinzor:
    engine = Vinzor(EventLog())
    for eid, name in (("p1", "Ravi Shah"), ("p2", "Anita Verma")):
        engine.ingest(
            event_type=EventType.ENTITY_REGISTERED, subject=eid,
            occurred_at="2026-08-20", actor="t",
            payload={"kind": EntityKind.PERSON.value, "name": name,
                     "attributes": {"dob": "1980-01-01", "nationality": "IN",
                                    "jurisdiction": "IN", "address": "1 Road",
                                    "phone": "+91", "pan": "ABCDE1234F"}})
    return engine


def file_it(engine, who, digest, kind, supports, expires=""):
    engine.ingest(
        event_type=EventType.DOCUMENT_FILED, subject=who,
        occurred_at="2026-08-20", actor="Meera Nair",
        payload={"digest": digest, "kind": kind, "filename": "scan.pdf",
                 "size": len(A_PDF), "shape": "pdf",
                 "supports": list(supports), "expires_on": expires,
                 "note": ""})


# -- the door through the central promise ------------------------------------


def test_an_unclassified_document_cannot_evidence_anything():
    """The attack that succeeded. "Other document" skipped the allowlist
    entirely, which made it the one kind that could evidence whatever it
    was told to."""
    why = refuse("other", A_PDF, ("name", "dob", "nationality", "pan"))
    assert why
    assert "unclassified document cannot evidence" in why


def test_an_unclassified_document_can_still_be_kept(book):
    """The fix must not stop a firm filing a paper it holds. Keeping a
    document and standing behind a fact are different acts, and only the
    second is refused."""
    assert refuse("other", A_PDF, ()) == ""


def test_the_refusal_says_what_to_do_instead():
    """A refusal without a remedy teaches somebody to work around it."""
    why = refuse("other", A_PDF, ("nationality",))
    assert "Say what kind of document this is" in why
    assert "can still be filed" in why


def test_one_unclassified_file_does_not_evidence_seven_facts(book):
    """What the door actually bought. ``ready`` answers clause 5.4.2 -- does
    the firm hold the data -- and documents have nothing to do with it;
    ``evidenced`` answers 5.4.5, and that is the one this moved. Before the
    fix, five of this party's seven required items read as backed by a
    document, on the strength of one unclassified file."""
    file_it(book, "p1", "a" * 64, "other",
            ("name", "dob", "nationality", "pan", "address"))
    # A date is needed: whether a document has lapsed cannot be answered
    # without one, so ``measure`` reports nothing as unsupported without it.
    standing = readiness.measure(book, only=("p1",),
                                 today="2026-08-20").parties[0]

    # Seven items are held and none is evidenced: the one file backs
    # nothing. Before the fix this read as two unsupported, meaning five
    # were shown as standing on paper.
    assert len(standing.unsupported) == 7
    assert not standing.evidenced
    # ``ready`` answers a different clause -- whether the firm *holds* the
    # data -- and does not move. Asserting it here would be testing 5.4.2
    # and calling the result 5.4.5, which is the mistake that made this
    # defect look larger than it is.
    assert standing.ready
    # And the claim itself is still on the record, unhonoured rather than
    # erased -- an inspector may want to see that it was made.
    filed = book.state.papers.held_for("p1")[0]
    assert filed.supports == ("name", "dob", "nationality", "pan", "address")
    assert filed.evidences == ()


def test_a_named_kind_still_evidences_what_it_can():
    """Removing an exemption that should not have existed must not make
    the ordinary case harder."""
    assert refuse("passport", A_PDF, ("name", "dob", "nationality")) == ""
    assert refuse("utility_bill", A_PDF, ("name", "address")) == ""


def test_a_named_kind_still_cannot_reach_past_its_list():
    why = refuse("utility_bill", A_PDF, ("name", "nationality"))
    assert "cannot evidence nationality" in why


def test_a_document_cannot_evidence_something_the_record_does_not_hold():
    """Not a permission question. ``anything_at_all`` is a typing mistake
    or an invented field, and either way nothing will ever read it."""
    why = refuse("passport", A_PDF, ("anything_at_all",))
    assert "Nothing on this record is called anything_at_all" in why
    assert "anything_at_all" not in EVIDENCEABLE
    assert EVIDENCEABLE == {key for _name, keys in KINDS.values()
                            for key in keys}


# -- the expiry cascade, and the keystroke that switched it off --------------


def a_passport(expires: str) -> Paper:
    return Paper(digest="d", kind="passport", filename="f", size=1,
                 shape="pdf", subject="p1", filed_on="2025-01-01",
                 filed_by="t", supports=("nationality",),
                 expires_on=expires, note="")


@pytest.mark.parametrize("expires,gone", [
    ("2026-01-01", True),
    # The same date as a person writes it. As text this sorts *after*
    # "2026-08-20", so the document read as current for another seven
    # months and went on evidencing a nationality.
    ("2026-1-1", True),
    ("2026-9-9", False),
    # Valid through the day it names, which is how a passport works.
    ("2026-08-20", False),
    ("2026-08-21", False),
])
def test_expiry_is_read_as_a_date_and_not_as_text(expires, gone):
    assert a_passport(expires).expired("2026-08-20") is gone


def test_a_date_nobody_can_read_expires_nothing():
    """An unreadable expiry is not evidence that a document has lapsed.
    Treating it as one would quietly withdraw support from a document that
    may be perfectly current."""
    assert a_passport("not a date").expired("2026-08-20") is False
    assert a_passport("").expired("2026-08-20") is False


def test_a_document_with_no_expiry_never_lapses():
    assert a_passport("").expired("2099-01-01") is False


# -- and what held ------------------------------------------------------------


def test_the_same_scan_against_two_investors_opens_a_file(book):
    """Free, because the fingerprint was already there to notice a
    re-upload. The same passport image cannot evidence two people."""
    file_it(book, "p1", "b" * 64, "passport", ("name", "nationality"))
    file_it(book, "p2", "b" * 64, "passport", ("name", "nationality"))

    assert book.state.papers.parties_sharing("b" * 64) == {"p1", "p2"}
    assert "POL_ONE_DOCUMENT_TWO_PARTIES" in {
        str(e.payload.get("policy_id")) for e in book.log
        if e.event_type is EventType.CASE_OPENED}


def test_a_lapsed_document_stops_supporting_only_what_it_supported(book):
    """The cascade, exactly as the block describes it: the passport stops
    standing behind a nationality while the tax card goes on standing
    behind the name."""
    file_it(book, "p1", "c" * 64, "passport", ("name", "nationality"),
            expires="2026-01-01")
    file_it(book, "p1", "d" * 64, "pan_card", ("name", "pan"))

    before = book.state.papers.supporting("p1", "2025-12-31")
    after = book.state.papers.supporting("p1", "2026-08-20")

    assert set(before) == {"name", "nationality", "pan"}
    assert set(after) == {"name", "pan"}


def test_a_lapsed_document_stays_on_the_record(book):
    """It verified something once and no longer does. If the file simply
    disappeared, both readings of that would be wrong in the same
    direction."""
    file_it(book, "p1", "e" * 64, "passport", ("name", "nationality"),
            expires="2026-01-01")
    lapsed = book.state.papers.lapsed("p1", "2026-08-20")
    assert len(lapsed) == 1
    assert lapsed[0].called == "Passport"
    assert lapsed[0].supports == ("name", "nationality")
