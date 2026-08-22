"""The papers behind the facts, and the difference that makes.

Every attribute on every party in this workspace arrived in a spreadsheet.
Clause 5.4.2 asks a firm to *hold* identification data; clause 5.4.5 asks it
to verify identity "using the relevant information or data obtained from
reliable, independent sources". A column is the first and not the second,
and until a document could be filed the two looked identical on every
screen.

Half these tests are about that distinction being visible. The rest are
about the door: a file that is not what it claims to be, and a document
said to evidence more than its kind can.
"""

from __future__ import annotations

import pytest

from vinzor.documents import (Cabinet, KINDS, Papers, can_support, fingerprint,
                              refuse, shape_of)
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType, Role
from vinzor.readiness import measure

WHEN = "2026-08-05"
TODAY = "2026-08-19"

#: A real PDF header, because the door checks the first bytes and a test
#: that used b"pretend" would be testing a different door.
PDF = b"%PDF-1.7\n" + b"a scanned page " * 40
OTHER_PDF = b"%PDF-1.7\n" + b"a different scanned page " * 40


@pytest.fixture
def engine() -> Vinzor:
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera Nair", role=Role.AML_OFFICER, enrolled_at=WHEN)
    return engine


def party(engine, entity_id: str, name: str,
          kind: EntityKind = EntityKind.PERSON, **attributes) -> None:
    engine.ingest(
        event_type=EventType.ENTITY_REGISTERED, subject=entity_id,
        occurred_at=WHEN,
        payload={"kind": kind.value, "name": name, "attributes": attributes})


def a_person(engine, entity_id="p1", name="Anand Bhat"):
    party(engine, entity_id, name, dob="1980-02-02", nationality="IN",
          pan="ABCDE1234F", address="12 Marine Drive, Mumbai",
          email="a@example.com", country_of_residence="IN")


def file_it(engine, entity_id="p1", kind="passport", data=PDF,
            supports=("name", "dob", "nationality"), **rest):
    return engine.file_document(
        entity_id=entity_id, kind=kind, filename=f"{kind}.pdf", data=data,
        supports=list(supports), actor="Meera Nair", filed_on=WHEN, **rest)


def standing(engine, entity_id="p1", today=TODAY):
    return measure(engine, only=(entity_id,), today=today).parties[0]


# -- held is not the same as evidenced ---------------------------------------


def test_a_party_can_be_complete_and_evidence_nothing(engine):
    """The distinction the whole module exists for. Every field clause
    5.4.2 asks for is on this record and not one of them has a document
    behind it."""
    a_person(engine)
    where = standing(engine)
    assert where.ready is True
    assert where.evidenced is False
    assert where.unsupported


def test_filing_a_document_moves_what_it_evidences(engine):
    a_person(engine)
    before = {gap.what for gap in standing(engine).unsupported}
    file_it(engine, supports=("name", "dob", "nationality"))
    after = {gap.what for gap in standing(engine).unsupported}
    assert "a date of birth" in before
    assert "a date of birth" not in after


def test_a_document_must_evidence_a_field_the_party_actually_holds(engine):
    """A passport says it evidences a passport number. Where the party's
    identifying number is a tax number instead, the passport has evidenced
    nothing about what is on this record."""
    a_person(engine)                       # holds a PAN, not a passport number
    file_it(engine, supports=("name", "dob", "nationality",
                              "id_document_number"))
    assert any(gap.what == "an identifying number"
               for gap in standing(engine).unsupported)


def test_the_right_document_settles_it(engine):
    a_person(engine)
    file_it(engine, kind="pan_card", supports=("name", "pan", "dob"))
    assert not any(gap.what == "an identifying number"
                   for gap in standing(engine).unsupported)


def test_nothing_is_reported_unsupported_without_a_date(engine):
    """Whether a passport has run out cannot be answered without one, and
    guessing would be worse than declining."""
    a_person(engine)
    assert measure(engine, only=("p1",)).parties[0].unsupported == ()


# -- expiry ------------------------------------------------------------------


def test_an_expired_document_stops_supporting_what_it_supported(engine):
    a_person(engine)
    file_it(engine, supports=("name", "dob", "nationality"),
            expires_on="2031-04-30")
    assert not any(gap.what == "a nationality"
                   for gap in standing(engine).unsupported)
    assert any(gap.what == "a nationality"
               for gap in standing(engine, today="2032-01-01").unsupported)


def test_an_expired_document_stays_on_the_record(engine):
    """It verified something once and no longer does. Taking it off would
    lose the fact that it ever existed, which is a different claim."""
    a_person(engine)
    file_it(engine, expires_on="2031-04-30")
    lapsed = engine.state.papers.lapsed("p1", "2032-01-01")
    assert len(lapsed) == 1
    assert lapsed[0].called == "Passport"


def test_one_document_lapsing_does_not_take_the_others_with_it(engine):
    a_person(engine)
    file_it(engine, supports=("name", "dob", "nationality"),
            expires_on="2031-04-30")
    file_it(engine, kind="pan_card", data=OTHER_PDF,
            supports=("name", "pan", "dob"))
    later = {gap.what for gap in standing(engine, today="2032-01-01").unsupported}
    assert "a nationality" in later
    assert "a date of birth" not in later


# -- the same file, two parties ----------------------------------------------


def test_the_same_file_against_two_parties_opens_a_file(engine):
    """Free, because the fingerprint was already there to notice a
    re-upload. The same scan cannot be evidence of two people."""
    a_person(engine)
    a_person(engine, "p2", "Nadia Rahman")
    file_it(engine)
    file_it(engine, entity_id="p2")
    found = [case for case in engine.state.casebook.cases.values()
             if case.case_type == "DOCUMENT"]
    assert len(found) == 1


def test_the_same_file_against_the_same_party_twice_is_not_a_finding(engine):
    """Somebody uploading the same passport again is a re-upload, not two
    identities."""
    a_person(engine)
    file_it(engine)
    file_it(engine)
    assert not [case for case in engine.state.casebook.cases.values()
                if case.case_type == "DOCUMENT"]


def test_different_files_for_different_parties_are_quiet(engine):
    a_person(engine)
    a_person(engine, "p2", "Nadia Rahman")
    file_it(engine)
    file_it(engine, entity_id="p2", data=OTHER_PDF)
    assert not [case for case in engine.state.casebook.cases.values()
                if case.case_type == "DOCUMENT"]


def test_the_finding_names_the_other_party(engine):
    from vinzor.briefing import case_file

    a_person(engine)
    a_person(engine, "p2", "Nadia Rahman")
    file_it(engine)
    file_it(engine, entity_id="p2")
    case = next(case for case in engine.state.casebook.cases.values()
                if case.case_type == "DOCUMENT")
    said = " ".join(case_file(engine, case.case_id, TODAY).because)
    assert "Anand Bhat" in said
    assert "byte for byte" in said


def test_the_finding_does_not_assume_which_record_is_wrong(engine):
    from vinzor.briefing import case_file

    a_person(engine)
    a_person(engine, "p2", "Nadia Rahman")
    file_it(engine)
    file_it(engine, entity_id="p2")
    case = next(case for case in engine.state.casebook.cases.values()
                if case.case_type == "DOCUMENT")
    said = " ".join(case_file(engine, case.case_id, TODAY).because)
    assert "Nothing has been assumed either way" in said


# -- the door ----------------------------------------------------------------


def test_a_file_that_is_not_a_document_is_refused(engine):
    a_person(engine)
    with pytest.raises(ValueError, match="does not begin like a document"):
        file_it(engine, data=b"just some text somebody pasted")


def test_an_empty_file_is_refused(engine):
    a_person(engine)
    with pytest.raises(ValueError, match="empty"):
        file_it(engine, data=b"")


def test_a_document_cannot_be_promoted_beyond_its_kind(engine):
    """A utility bill may be said to evidence an address. It may not be
    made into proof of a nationality because somebody was in a hurry."""
    a_person(engine)
    with pytest.raises(ValueError, match="cannot evidence"):
        file_it(engine, kind="utility_bill", supports=("nationality",))


def test_a_document_may_be_said_to_support_less_than_it_could(engine):
    a_person(engine)
    file_it(engine, kind="passport", supports=("name",))
    assert engine.state.papers.held_for("p1")[0].supports == ("name",)


def test_an_unknown_kind_is_refused_and_lists_the_ones_it_knows(engine):
    a_person(engine)
    with pytest.raises(ValueError, match="no document kind called"):
        file_it(engine, kind="birth_chart")


def test_an_unreadable_expiry_is_refused_rather_than_guessed(engine):
    a_person(engine)
    with pytest.raises(ValueError, match="not a date"):
        file_it(engine, expires_on="next spring")


def test_a_document_for_a_party_nobody_registered_is_refused(engine):
    with pytest.raises(KeyError):
        file_it(engine, entity_id="nobody")


def test_a_file_larger_than_the_limit_is_refused(engine):
    from vinzor.documents import MOST_BYTES

    a_person(engine)
    with pytest.raises(ValueError, match="limit is"):
        file_it(engine, data=b"%PDF-1.7\n" + b"x" * (MOST_BYTES + 1))


# -- what goes where ---------------------------------------------------------


def test_the_bytes_never_reach_the_log(engine):
    """A log carrying twenty-megabyte scans stops being something anybody
    can replay. The fingerprint is enough to prove the file has not
    changed and enough to notice it filed twice."""
    a_person(engine)
    file_it(engine)
    written = b"".join(str(event.payload).encode() for event in engine.log)
    assert b"a scanned page" not in written
    assert fingerprint(PDF) in str([event.payload for event in engine.log])


def test_the_cabinet_keeps_one_copy_however_many_parties_cite_it(engine):
    cabinet = Cabinet()
    a_person(engine)
    a_person(engine, "p2", "Nadia Rahman")
    file_it(engine, cabinet=cabinet)
    file_it(engine, entity_id="p2", cabinet=cabinet)
    held = cabinet._conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    assert held == 1
    assert cabinet.fetch(fingerprint(PDF)) == PDF


def test_the_document_survives_a_rebuild(engine):
    a_person(engine)
    file_it(engine)
    assert engine.rebuild().papers.held_for("p1") == \
        engine.state.papers.held_for("p1")


# -- how it reads ------------------------------------------------------------


def test_a_party_with_no_documents_says_so_plainly(engine):
    from vinzor.briefing import party as party_page

    a_person(engine)
    page = party_page(engine, "p1", today=TODAY)
    assert "No document has been filed" in page.papers_none
    assert "typed in" in page.papers_none


def test_the_party_page_says_what_is_held_but_not_evidenced(engine):
    from vinzor.briefing import party as party_page

    a_person(engine)
    file_it(engine, kind="pan_card", supports=("name", "pan", "dob"))
    page = party_page(engine, "p1", today=TODAY)
    assert "held but not evidenced" in page.papers_note
    assert "5.4.5" in page.papers_note


def test_a_requirement_is_never_named_twice(engine):
    """Clause 5.4.2 asks for a full name under (a) and again under (b), for
    different kinds of customer. Reading both lists said it twice."""
    from vinzor.briefing import party as party_page

    a_person(engine)
    file_it(engine, kind="pan_card", supports=("name", "pan", "dob"))
    supports = party_page(engine, "p1", today=TODAY).papers[0].supports
    assert supports.count("a full name") == 1


def test_nothing_new_speaks_jargon(engine):
    import re

    from vinzor.briefing import brief
    from test_briefing import JARGON, _strings

    a_person(engine)
    a_person(engine, "p2", "Nadia Rahman")
    file_it(engine, expires_on="2031-04-30")
    file_it(engine, entity_id="p2")

    offences = []
    briefing = brief(engine, person="Meera Nair", today=TODAY)
    for path, text in _strings(briefing, "briefing"):
        for pattern, what in JARGON:
            found = re.search(pattern, text)
            if found:
                offences.append(f"{path}: {what} ({found.group(0)!r})")
    assert not offences, ("jargon reached the reader:\n  "
                          + "\n  ".join(offences))


def test_every_kind_names_itself_in_words(engine):
    """A kind whose label is its key would put an implementation word on a
    compliance screen."""
    for key, (called, _supports) in KINDS.items():
        assert called and called != key
        assert called[0].isupper()


# -- the documents an international centre actually receives ------------------


class _Paper:
    """A document on file, as ``outstanding`` reads one."""

    def __init__(self, kind, evidences=()):
        self.kind = kind
        self.evidences = tuple(evidences)


def test_a_voter_card_can_satisfy_the_identity_requirement():
    """PML Rules 9(4)(a) names the voter identity card alongside the passport
    and the driving licence, and it was not on the list at all -- so an
    investor whose identity document was their voter card had nowhere to file
    it and nothing that could ever close the requirement."""
    from vinzor.documents import KINDS
    from vinzor.model import EntityKind
    from vinzor.requirements import outstanding

    assert "voter_id" in KINDS

    held = outstanding(EntityKind.PERSON, (_Paper("voter_id"),))
    identity = [o for o in held if o.requirement.slug == "identity"]
    assert identity, "the requirement vanished rather than staying open"
    assert identity[0].held_but_unevidenced, (
        "a voter card was not recognised as something that could satisfy this")

    evidenced = outstanding(EntityKind.PERSON,
                            (_Paper("voter_id", ("name", "dob")),))
    assert not [o for o in evidenced if o.requirement.slug == "identity"]


def test_a_foreign_identity_card_is_read_but_is_not_an_official_document():
    """The distinction this product exists to keep.

    A German or Singaporean identity card can be filed and is read -- a name
    and a date of birth that disagree with the record are worth knowing
    however the paper is classified. It does not satisfy the identity
    requirement, because clause 1.3.30 and PML Rules 9(4)(a) name what counts
    as an officially valid document and it is not among them. Accepting one
    would be this system inventing a rule in the firm's favour.
    """
    from vinzor.documents import KINDS
    from vinzor.model import EntityKind
    from vinzor.requirements import outstanding

    assert "national_id" in KINDS
    assert "dob" in KINDS["national_id"][1], "it is still read"
    assert "nationality" in KINDS["national_id"][1]

    # Even fully evidenced, it does not close the identity requirement.
    held = outstanding(EntityKind.PERSON,
                       (_Paper("national_id", ("name", "dob", "nationality")),))
    identity = [o for o in held if o.requirement.slug == "identity"]
    assert identity, (
        "a foreign identity card was accepted as an officially valid document")
    assert not identity[0].held_but_unevidenced, (
        "it should not even read as partway there")


def test_the_list_has_somewhere_to_put_a_foreign_investors_papers():
    """This is an international financial centre. A list offering only
    Aadhaar, a permanent account number and an Indian driving licence has no
    home for the primary identity document of most of the investors GIFT
    City exists to serve."""
    from vinzor.documents import KINDS

    reads_identity = {k for k, (_label, fields) in KINDS.items()
                      if "dob" in fields and "name" in fields}
    assert {"passport", "national_id", "voter_id"} <= reads_identity
