"""The one document a firm hands to somebody outside it.

Everything else in the product is a screen for a person who already works
there. This is the artefact that leaves the building -- to an inspector, an
auditor, a correspondent bank -- so the tests here are about two things a
screen never has to worry about: that it is complete, and that it says who
is allowed to read it.
"""

from __future__ import annotations

import re

import pytest

from vinzor.dossier import CONFIDENTIAL, dossier
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, Outcome, Role

from conftest import (WHEN, company, owns, paid, person, register, screened,
                      trust_of)
from test_briefing import JARGON, _strings

TODAY = "2026-08-19"

#: Who each name is, so a test can settle a file without restating it.
ROLES = {"Meera Nair": Role.AML_OFFICER, "Rohan Kapoor": Role.SENIOR_MGMT}


def decide(engine, case_id, outcome, actor, rationale, when=TODAY):
    return engine.decide(case_id=case_id, outcome=Outcome[outcome],
                         actor=actor, role=ROLES[actor], rationale=rationale,
                         decided_at=when)


@pytest.fixture
def engine() -> Vinzor:
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera Nair", role=Role.AML_OFFICER, enrolled_at=WHEN)
    engine.enroll(name="Rohan Kapoor", role=Role.SENIOR_MGMT, enrolled_at=WHEN)
    return engine


def headings(doc) -> list:
    return [part.heading for part in doc.parts]


def part(doc, heading):
    return next(p for p in doc.parts if p.heading == heading)


def text_of(doc) -> str:
    return " ".join(value for _path, value in _strings(doc, "dossier"))


# -- refusing rather than inventing ------------------------------------------


def test_a_party_that_does_not_exist_is_refused_by_name(engine):
    doc = dossier(engine, "per_9999", TODAY)
    assert doc.refusal
    assert not doc.parts
    assert "look the party up by name" in doc.refusal.lower()


def test_a_refusal_carries_no_confidentiality_banner(engine):
    """There is nothing confidential about a document with nothing in it,
    and a warning on an empty page teaches a reader to ignore warnings."""
    doc = dossier(engine, "per_9999", TODAY)
    assert doc.confidential == ""


# -- who may read it ---------------------------------------------------------


def test_every_real_record_says_who_may_read_it(engine):
    person(engine, "p1", "Anand Bhat")
    doc = dossier(engine, "p1", TODAY)
    assert doc.confidential == CONFIDENTIAL


def test_the_warning_names_the_clause_and_the_reason(engine):
    """Clause 4.1(d) is not about secrecy for its own sake. It exists so a
    customer under examination is not tipped off, and a warning that does
    not say so gets treated as boilerplate."""
    assert "4.1(d)" in CONFIDENTIAL
    assert "tipped off" in CONFIDENTIAL
    assert "never be given to the party it is about" in CONFIDENTIAL


def test_there_is_no_redacted_version_and_it_says_why(engine):
    """The dangerous version of this feature is a second, shorter export
    that looks safe to hand over. It would not be: the existence of the
    document is itself the disclosure."""
    assert "no shortened version" in CONFIDENTIAL


# -- completeness ------------------------------------------------------------


def test_a_bare_party_still_produces_every_part_that_matters(engine):
    person(engine, "p1", "Anand Bhat")
    doc = dossier(engine, "p1", TODAY)
    assert "Who this party is" in headings(doc)
    assert "How risky this party has been judged" in headings(doc)
    assert "What this party has been checked against" in headings(doc)
    assert "The record behind this document" in headings(doc)


def test_never_being_checked_is_stated_not_left_blank(engine):
    """A blank where a screening result belongs reads as a clean result.
    The distinction is the whole point of the section."""
    person(engine, "p1", "Anand Bhat")
    checked = part(dossier(engine, "p1", TODAY),
                   "What this party has been checked against")
    assert "never been checked" in checked.lead
    assert "not a party that came back clean" in checked.tail


def test_never_being_categorised_is_not_reported_as_low_risk(engine):
    person(engine, "p1", "Anand Bhat")
    judged = part(dossier(engine, "p1", TODAY),
                  "How risky this party has been judged")
    assert "Nobody has categorised" in judged.lead
    assert "not a low score" in judged.tail


def test_the_gaps_are_listed_before_the_contents(engine):
    """An inspector reads what is missing first, and a document that lists
    only what is present invites the reader to assume the rest was done."""
    person(engine, "p1", "Anand Bhat")
    doc = dossier(engine, "p1", TODAY)
    assert "What this file is still missing" in headings(doc)
    missing = part(doc, "What this file is still missing")
    assert missing.facts
    assert all(fact.value == "Not on file" for fact in missing.facts)
    assert "5.4.2" in missing.lead


def test_a_gap_is_not_reported_as_a_finding_against_the_customer(engine):
    person(engine, "p1", "Anand Bhat")
    missing = part(dossier(engine, "p1", TODAY),
                   "What this file is still missing")
    assert "work the firm has not finished" in missing.tail


# -- the decisions, in the decider's own words -------------------------------


def test_a_decision_is_quoted_not_summarised(engine):
    person(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    case = next(iter(engine.state.casebook.cases.values()))
    decide(engine, case.case_id, "APPROVE", "Meera Nair",
           "Different date of birth on the passport we hold.")

    decided = part(dossier(engine, "p1", TODAY), "What people decided")
    assert any("Different date of birth on the passport we hold."
               == entry.why for entry in decided.entries)


def test_a_decision_names_who_made_it(engine):
    person(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    case = next(iter(engine.state.casebook.cases.values()))
    decide(engine, case.case_id, "APPROVE", "Meera Nair", "Not the same man.")

    decided = part(dossier(engine, "p1", TODAY), "What people decided")
    assert any(entry.who == "Meera Nair" for entry in decided.entries)


def test_a_handover_appears_as_well_as_the_decision_that_settled_it(engine):
    """A file passed up and then cleared is two people's work, and a
    document showing only the second name hides the four-eyes control that
    is the reason the first one exists."""
    person(engine, "p1", "Dev Kumar")
    screened(engine, "p1", "PEP", alert_id="alt_1")
    case = next(iter(engine.state.casebook.cases.values()))
    decide(engine, case.case_id, "ESCALATE", "Meera Nair",
           "Public office match needs a senior decision.")
    decide(engine, case.case_id, "APPROVE", "Rohan Kapoor",
           "Approved as a politically exposed customer, enhanced monitoring.")

    decided = part(dossier(engine, "p1", TODAY), "What people decided")
    who = [entry.who for entry in decided.entries]
    assert "Meera Nair" in who and "Rohan Kapoor" in who


def test_decisions_are_in_the_order_they_were_made(engine):
    """Dates are written the way a person reads them, and ordering on that
    text would put April before November because A comes before N."""
    person(engine, "p1", "Dev Kumar")
    screened(engine, "p1", "PEP", alert_id="alt_1")
    case = next(iter(engine.state.casebook.cases.values()))
    decide(engine, case.case_id, "ESCALATE", "Meera Nair",
           "Public office match needs a senior decision.", when="2026-04-29")
    decide(engine, case.case_id, "APPROVE", "Rohan Kapoor",
           "Approved as politically exposed, with enhanced monitoring.",
           when="2026-11-01")

    decided = part(dossier(engine, "p1", TODAY), "What people decided")
    assert [entry.when for entry in decided.entries] ==         ["29 April 2026", "1 November 2026"]


def test_the_document_says_a_decision_cannot_be_edited(engine):
    person(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    case = next(iter(engine.state.casebook.cases.values()))
    decide(engine, case.case_id, "APPROVE", "Meera Nair", "Not the same man.")

    decided = part(dossier(engine, "p1", TODAY), "What people decided")
    assert "can be edited or removed" in decided.tail


# -- findings ----------------------------------------------------------------


def test_a_finding_is_rendered_the_way_the_queue_renders_it(engine):
    """The recorded summary names parties by reference and rules by
    identifier. It has never reached a screen and must not reach a
    document."""
    person(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")

    found = part(dossier(engine, "p1", TODAY), "What the rules found")
    assert found.entries
    assert any("Anand Bhat" in entry.what for entry in found.entries)
    assert not any("p1" == entry.what for entry in found.entries)


def test_a_finding_cites_the_clause_it_answers_to(engine):
    person(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    found = part(dossier(engine, "p1", TODAY), "What the rules found")
    assert any(entry.clause for entry in found.entries)


def test_the_count_of_findings_counts_files_not_lines(engine):
    """Each file contributes a headline and several explaining lines, and
    counting the lines would report three findings where there is one."""
    person(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    found = part(dossier(engine, "p1", TODAY), "What the rules found")
    assert "1 file" in found.lead


# -- ownership ---------------------------------------------------------------


def test_a_trust_with_nobody_declared_says_who_is_missing(engine):
    """The section has no declared holdings to show, and returning nothing
    would drop the most important sentence on the page."""
    trust_of(engine, "t1", "The Bhat Family Trust")
    control = part(dossier(engine, "t1", TODAY),
                   "Who owns or controls this party")
    assert any("Nobody has been named as" in entry.what
               for entry in control.entries)


def test_an_owner_below_the_threshold_is_named_not_dropped(engine):
    """Somebody sitting just under the threshold is the most useful line on
    the page for a reader judging whether a structure was arranged to sit
    under it."""
    company(engine, "c1", "Orion Holdings")
    person(engine, "p1", "Anand Bhat")
    owns(engine, "p1", "c1", 5.0)

    control = part(dossier(engine, "c1", TODAY),
                   "Who owns or controls this party")
    assert any("Below the" in entry.who for entry in control.entries)


def test_the_threshold_and_its_clause_are_stated(engine):
    company(engine, "c1", "Orion Holdings")
    person(engine, "p1", "Anand Bhat")
    owns(engine, "p1", "c1", 60.0)

    control = part(dossier(engine, "c1", TODAY),
                   "Who owns or controls this party")
    assert "10%" in control.tail
    assert "1.3.3" in control.tail
    assert "not the same threshold for every kind" in control.tail


def test_a_party_with_no_ownership_at_all_omits_the_section(engine):
    person(engine, "p1", "Anand Bhat")
    assert "Who owns or controls this party" not in headings(
        dossier(engine, "p1", TODAY))


# -- the seal ----------------------------------------------------------------


def test_the_document_seals_the_records_it_was_built_from(engine):
    person(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    seal = part(dossier(engine, "p1", TODAY), "The record behind this document")
    values = {fact.label: fact.value for fact in seal.facts}
    assert values["The chain"] == "Verifies"
    assert int(values["Records this document was built from"].replace(",", ""))


def test_the_seal_distinguishes_this_party_from_the_whole_log(engine):
    person(engine, "p1", "Anand Bhat")
    person(engine, "p2", "Nadia Rahman")
    seal = part(dossier(engine, "p1", TODAY), "The record behind this document")
    values = {fact.label: fact.value for fact in seal.facts}
    assert values["Records this document was built from"] != \
        values["Records in the whole log"]


# -- reproducibility ---------------------------------------------------------


def test_the_same_log_and_date_give_the_same_document(engine):
    """The property that makes it worth handing to anybody: an inspector
    asking in December what the file looked like in August gets the August
    document, not a fresh reading of today's rules."""
    person(engine, "p1", "Anand Bhat")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    assert dossier(engine, "p1", TODAY) == dossier(engine, "p1", TODAY)


def test_nothing_is_read_from_a_clock(engine):
    person(engine, "p1", "Anand Bhat")
    early = dossier(engine, "p1", "2026-08-19")
    later = dossier(engine, "p1", "2027-08-19")
    assert early.printed != later.printed


# -- how it reads ------------------------------------------------------------


def test_the_whole_document_speaks_no_jargon(engine):
    """The sweep that guards every screen guards the one artefact that
    leaves the building.

    It was sweeping a party with almost no attributes on it, and the leak was
    in the fall-through for attributes nobody had named. On the live book 120
    of 218 parties carry an identity document type and 29 of those hold
    NATIONAL_ID, which is what the record page showed them. So the party this
    sweeps now carries what a real one carries.
    """
    register(engine, "p1", EntityKind.PERSON, "Anand Bhat",
             id_document_type="NATIONAL_ID", dob="2005-12-17",
             nationality="AE", id_document_number="K9930147")
    company(engine, "c1", "Orion Holdings")
    trust_of(engine, "t1", "The Bhat Family Trust")
    owns(engine, "p1", "c1", 60.0)
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    screened(engine, "c1", "PEP", alert_id="alt_2")
    paid(engine, "p1", payment_id="pay_1", payer="c1")
    case = next(iter(engine.state.casebook.cases.values()))
    decide(engine, case.case_id, "APPROVE", "Meera Nair",
           "Different date of birth on the passport we hold.")

    offences = []
    for who in ("p1", "c1", "t1"):
        doc = dossier(engine, who, TODAY, workspace="live.db")
        for path, text in _strings(doc, f"dossier[{who}]"):
            for pattern, what in JARGON:
                found = re.search(pattern, text)
                if found:
                    offences.append(f"{path}: {what} ({found.group(0)!r})")
    assert not offences, ("jargon reached the reader:\n  "
                          + "\n  ".join(offences))


def test_a_recorded_yes_or_no_is_not_shown_as_a_number(engine):
    """Attributes arrive as 0 and 1 as often as true and false. Neither is
    a word anybody says."""
    register(engine, "t1", EntityKind.TRUST, "The Bhat Family Trust",
             is_discretionary=1, has_protector=0)
    who = part(dossier(engine, "t1", TODAY), "Who this party is")
    values = {fact.label: fact.value for fact in who.facts}
    assert values.get("A discretionary trust") == "Yes"
    assert values.get("Has a protector") == "No"


def test_a_country_is_named_not_coded(engine):
    register(engine, "p1", EntityKind.PERSON, "Anand Bhat", nationality="AE")
    who = part(dossier(engine, "p1", TODAY), "Who this party is")
    values = {fact.label: fact.value for fact in who.facts}
    assert "United Arab Emirates" in values.values()


def test_an_unrecognised_column_is_spelled_out_rather_than_dropped(engine):
    """An import can carry anything. Leaving an unnamed field out of a
    document that claims to hold everything is the worse failure."""
    register(engine, "p1", EntityKind.PERSON, "Anand Bhat",
             employer_name="Harbour Point Capital")
    who = part(dossier(engine, "p1", TODAY), "Who this party is")
    values = {fact.label: fact.value for fact in who.facts}
    assert values.get("Employer name") == "Harbour Point Capital"


def test_an_identity_document_is_named_in_words_on_the_record_page():
    """29 parties on the live book were shown NATIONAL_ID on the page the
    product calls the document you would hand an inspector."""
    from vinzor.dossier import _label_for, _said

    assert _said("id_document_type", "NATIONAL_ID") == "National identity card"
    assert _said("id_document_type", "PASSPORT") == "Passport"
    assert _label_for("id_document_type") == "Kind of identity document"


def test_a_kind_of_document_nobody_anticipated_is_still_readable():
    """An import carries whatever the firm's spreadsheet carries. Dropping an
    unnamed one is the worse of the two failures; showing it raw is the
    defect this closes."""
    from vinzor.dossier import _said

    assert _said("id_document_type", "AADHAAR_CARD") == "Aadhaar card"


def test_a_date_of_birth_reads_like_every_other_date_on_the_page():
    """It sat as 2005-12-17 next to "First went on the record = 7 August
    2026" -- two spellings of a date on one document."""
    from vinzor.dossier import _said

    assert _said("dob", "2005-12-17") == "17 December 2005"
    assert _said("id_document_expiry", "2031-04-02") == "2 April 2031"


def test_a_number_that_looks_like_a_date_is_left_alone():
    """Named keys, not sniffed shapes: a passport number is not a date
    however much it resembles one."""
    from vinzor.dossier import _said

    assert _said("id_document_number", "K9930147") == "K9930147"
    assert _said("registration_number", "2019-08-14") == "2019-08-14"


# -- the paragraph at the top ------------------------------------------------
#
# It was regenerated on every page view and every print, and recorded
# nowhere. Three consecutive views of an identical, unchanged record -- at
# temperature 0, top_p 1, seed 7 -- produced three materially different
# paragraphs, and one printed the raw address, email, date of birth and
# identifying number that the other two summarised. Nothing was written
# either way: not the paragraph, and not the `withheld` sentence when a guard
# fired -- while every withheld answer at the ask boundary *is* recorded, on
# the stated ground that a guard which fires silently is a guard nobody can
# audit.


def a_transport(said="Two files are open on this party."):
    calls = []

    def talk(messages):
        calls.append(messages)
        return {"summary": said}, 100, 20

    talk.calls = calls
    talk.model = "model-router"
    talk.region = "southindia"
    return talk


def test_the_opening_is_written_once_and_read_thereafter(engine):
    from vinzor.model import EventType

    register(engine, "p1", EntityKind.PERSON, "Anand Bhat")
    talk = a_transport()

    first = dossier(engine, "p1", TODAY, transport=talk)
    second = dossier(engine, "p1", TODAY, transport=talk)

    assert first.opening == second.opening
    assert len(talk.calls) == 1, "the model was asked again for a page view"
    written = [e for e in engine.log
               if e.event_type is EventType.RECORD_OPENING_WRITTEN]
    assert len(written) == 1
    assert written[0].subject == "p1"


def test_what_the_record_says_about_who_wrote_it(engine):
    from vinzor.model import EventType
    from vinzor.narrative import PROMPT_VERSION

    register(engine, "p1", EntityKind.PERSON, "Anand Bhat")
    dossier(engine, "p1", TODAY, transport=a_transport())
    payload = [e for e in engine.log
               if e.event_type is EventType.RECORD_OPENING_WRITTEN][0].payload

    assert payload["model"] == "model-router"
    assert payload["region"] == "southindia"
    assert payload["prompt_version"] == PROMPT_VERSION


def test_a_withheld_opening_is_recorded_too(engine):
    """A guard that fires silently is a guard nobody can audit -- the reason
    the ask boundary records its own refusals."""
    from vinzor.model import EventType

    register(engine, "p1", EntityKind.PERSON, "Anand Bhat")
    invented = a_transport("This party received USD 9,912,004 last year.")
    page = dossier(engine, "p1", TODAY, transport=invented)

    assert page.opening == ""
    assert "thrown away" in page.opening_withheld
    payload = [e for e in engine.log
               if e.event_type is EventType.RECORD_OPENING_WRITTEN][0].payload
    assert payload["summary"] == ""
    assert "thrown away" in payload["withheld"]


def test_a_reader_who_only_wants_to_look_writes_nothing(engine):
    register(engine, "p1", EntityKind.PERSON, "Anand Bhat")
    before = len(engine.log)
    page = dossier(engine, "p1", TODAY, transport=a_transport(), record=False)
    assert page.opening
    assert len(engine.log) == before


def test_the_rulepack_never_runs_over_a_written_opening(engine):
    """It is model output on a permanent record, like a prepared draft."""
    from vinzor.engine import MODEL_AUTHORED
    from vinzor.model import EventType

    assert EventType.RECORD_OPENING_WRITTEN in MODEL_AUTHORED


def test_a_page_with_no_assistant_still_reads_as_a_page(engine):
    register(engine, "p1", EntityKind.PERSON, "Anand Bhat")
    page = dossier(engine, "p1", TODAY)
    assert page.opening == ""
    assert page.parts
