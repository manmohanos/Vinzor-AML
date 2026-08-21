"""The reason gate, measured against reasons instead of imagined against them.

The control exists to stop paper closures. Measured on 12 reasons a screening
officer would really type and 13 one-line closures, it was catching the wrong
side::

    genuine refused : 5 of 12   stock accepted : 10 of 13

Two separate faults, one line of code. ``re.findall(r"[a-z']+", ...)`` is an
ASCII-only character class, so **every reason written in an Indian script was
refused outright** -- the product could not be used in a language it was built
for, and the officer was told "this reason says nothing an inspector could
read" about a sentence that said plenty. And ignoring digits refused "DOB 1971
vs 1985", which is the commonest true reason on a name match and is item one
on OFAC's own checklist, quoted in ``SCREENING_REASONS``.

Meanwhile "ok ok ok" and "n/a n/a n/a" cleared a three-word floor, because
repeating a non-reason made it three words long.

What a gate like this actually produces when it is wrong is officers
rephrasing true reasons until the box lets them past.
"""

from __future__ import annotations

import pytest

from vinzor.cases import LONGEST_REASON, thin_reason
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType, Outcome, Role

WHEN = "2026-08-20"

#: Reasons a screening officer would really type, in the languages this
#: product is used in.
GENUINE = [
    "Different date of birth on the passport we hold.",
    "DOB 1971 vs 1985",
    "1997 vs 1962",
    "Name matches but the listed party is Russian; ours is Indian.",
    "Passport number differs from the designation.",
    "Confirmed with the client's bank; different person entirely.",
    "जन्म तिथि मेल "
    "नहीं खाती",
    "જન્મ તારીખ "
    "અલગ છે",
    "Фамилия совп"
    "адает, дата "
    "рождения нет",
    "Nationalité différente selon le passeport.",
    "Same name, different father's name on the PAN card.",
    "Screened again against the fresh list; no longer designated.",
]

#: What people type when they want the box to go away.
STOCK = [
    "ok", "ok ok ok", "reviewed", "no issues found", "fine by me",
    "this is fine", "closed as agreed", "n/a n/a n/a", "asdf asdf asdf",
]


def test_no_genuine_reason_is_refused():
    refused = [text for text in GENUINE if thin_reason(text)]
    assert refused == [], "genuine reasons refused: " + " | ".join(refused)


def test_a_reason_in_an_indian_script_is_a_reason():
    """It was not a calibration problem. Devanagari, Gujarati and Cyrillic
    text of any length was refused, because none of it is ASCII."""
    hindi = ("जन्म तिथि "
             "मेल नहीं खा"
             "ती")
    assert thin_reason(hindi) is False


def test_a_date_comparison_is_a_reason():
    """"Different date of birth" is item one on OFAC's own checklist. Written
    the way an officer actually writes it, it was refused."""
    assert thin_reason("DOB 1971 vs 1985") is False
    assert thin_reason("1997 vs 1962") is False


def test_the_stock_closures_are_still_refused():
    through = [text for text in STOCK if not thin_reason(text)]
    assert through == [], "stock closures accepted: " + " | ".join(through)


def test_repeating_a_non_reason_does_not_make_it_a_reason():
    """A three-word floor counted "ok ok ok" as three words."""
    assert thin_reason("ok ok ok") is True
    assert thin_reason("n/a n/a n/a") is True
    assert thin_reason("fine, fine, fine") is True


def test_two_words_is_still_too_few():
    """The floor did not move; only what counts as a word did."""
    assert thin_reason("different person") is True


def test_the_gate_is_honest_about_what_it_does_not_catch():
    """Kept as a measurement rather than a claim. These four name an action
    or a conclusion without a basis, and refusing them would cost more
    genuine reasons than it saves paper ones. The gate refuses the
    click-through; it does not grade prose, and this test says so out loud
    rather than letting a reader assume otherwise."""
    still_through = ["checked with team", "reviewed it again",
                     "not the same", "spoke to the client"]
    assert [t for t in still_through if not thin_reason(t)] == still_through


# -- how long a reason may be ------------------------------------------------


def a_book():
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera", role=Role.AML_OFFICER, enrolled_at=WHEN)
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"kind": EntityKind.PERSON.value,
                           "name": "Vladimir Listed", "attributes": {}})
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject="p1",
                  occurred_at=WHEN, actor="system",
                  payload={"matched": True, "list_type": "SANCTIONS",
                           "list_types": ["SANCTIONS"], "rule": "match",
                           "alert_id": "os:x", "basis": {}})
    return engine, engine.queue()[0]


def test_a_reason_has_a_stated_maximum_length():
    """It had none. A 100,011-character rationale went onto a permanent event
    unchanged, and the only thing bounding it over HTTP was a constant about
    request bodies -- a hidden limit, and one about something else."""
    engine, case = a_book()
    with pytest.raises(ValueError) as refusal:
        engine.decide(case_id=case.case_id, outcome=Outcome.REJECT,
                      actor="Meera", role=Role.AML_OFFICER, decided_at=WHEN,
                      rationale="Different birth date. " * 5_000)
    assert str(LONGEST_REASON) in str(refusal.value).replace(",", "")
    assert "Put the detail in the file" in str(refusal.value)


def test_a_full_page_of_typing_still_clears_it():
    """A limit that a careful officer meets is a limit in the wrong place."""
    engine, case = a_book()
    settled = engine.decide(
        case_id=case.case_id, outcome=Outcome.REJECT, actor="Meera",
        role=Role.AML_OFFICER, decided_at=WHEN,
        rationale="Different date of birth on the passport we hold. " * 40)
    assert settled.status.value == "REJECTED"
