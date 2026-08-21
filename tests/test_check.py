"""The check, narrated as it happened.

The demonstration systems this competes with show a reasoning timeline whose
entries all carry the same timestamp, because the narration is written after
the fact and replayed. These tests hold ours to the opposite standard: every
step must correspond to something that actually happened, the near-misses must
be shown rather than hidden, and the check must end with a handoff to a person
rather than a decision.
"""

from __future__ import annotations

import re

import pytest

from vinzor.check import Investigation, list_name, run_check
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.screening import WatchlistClient

from conftest import person, register
from test_briefing import JARGON, _strings
from test_screening import sanction_result, service


def client_of(*results):
    transport, calls = service(*results)
    return WatchlistClient(url="https://yente.local", transport=transport), calls


def checked(engine, *results, drafter=None):
    client, _ = client_of(*results)
    return run_check(engine, "p1", client=client, today="2026-08-16",
                     drafter=drafter)


# -- what it says ------------------------------------------------------------


def test_the_check_says_nothing_technical(engine):
    """The widest new surface since the party page: it renders queries,
    scores, dataset codes, thresholds and provenance, every one a chance for
    an identifier to reach the reader."""
    from vinzor.model import EntityKind

    register(engine, "p1", EntityKind.PERSON, "Rohan Desai",
             nationality="SG", dob="1974-03-02")
    offences = []
    for investigation in (checked(engine), checked(engine, sanction_result())):
        for path, text in _strings(investigation, "check"):
            for pattern, what in JARGON:
                found = re.search(pattern, text)
                if found:
                    offences.append(f"{path}: {what} ({found.group(0)!r})")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


def test_a_clean_check_narrates_the_question_and_the_silence(engine):
    person(engine, "p1", "Rohan Desai")
    investigation = checked(engine)

    kinds = [step.kind for step in investigation.steps]
    assert kinds == ["record", "asked", "returned", "logged"]
    assert investigation.outcome == "clean"
    assert investigation.verdict == "Nothing found."
    assert "only evidence the check was ever performed" in \
        investigation.explanation[0]
    assert investigation.files == ()

    asked = investigation.steps[1]
    assert any(f.label == "The name asked about" and "Rohan Desai" in f.value
               for f in asked.facts)
    assert asked.took, "the elapsed time is real and must be shown"


def test_a_match_ends_with_a_handoff_never_a_decision(engine):
    """The one property that separates this from the products it resembles."""
    person(engine, "p1", "Vladimir Listed")
    investigation = checked(engine, sanction_result())

    assert investigation.outcome == "match"
    assert investigation.files, "a match must hand over the file it opened"
    assert "yours" in investigation.explanation[0]
    assert "cannot settle" in investigation.explanation[0]
    # And nothing in the structure carries a way to decide.
    assert not any("approve" in (s.title + " ".join(s.body)).lower()
                   for s in investigation.steps)


def test_near_misses_are_shown_not_hidden(engine):
    """Refusing to show the names that did not qualify would make every clean
    result look effortless, and an officer reading "nothing found" deserves to
    see what "nothing" consisted of."""
    person(engine, "p1", "Rohan Desai")
    near = {"id": "Q1", "caption": "Rohan Desa", "score": 0.42,
            "properties": {"topics": ["sanction"]}, "datasets": ["us_ofac_sdn"]}
    investigation = checked(engine, near)

    returned = next(s for s in investigation.steps if s.kind == "returned")
    assert len(returned.candidates) == 1
    assert returned.candidates[0].name == "Rohan Desa"
    assert returned.candidates[0].standing == "not close enough to matter"
    assert "none was close enough" in returned.body[0]
    assert investigation.outcome == "clean"


def test_a_match_shows_the_two_records_side_by_side(engine):
    from vinzor.model import EntityKind

    register(engine, "p1", EntityKind.PERSON, "Vladimir Listed",
             nationality="IN", dob="1984-08-19")
    investigation = checked(engine, sanction_result())

    compared = next(s for s in investigation.steps if s.kind == "compared")
    assert compared.side_by_side, "a match with nothing to compare shows nothing"
    assert compared.ours_label and compared.theirs_label


def test_the_list_a_match_appears_on_is_named_for_a_person(engine):
    person(engine, "p1", "Vladimir Listed")
    investigation = checked(engine, sanction_result())
    returned = next(s for s in investigation.steps if s.kind == "returned")
    assert "the US Treasury sanctions list" in returned.body[0]
    assert "us_ofac_sdn" not in " ".join(returned.body)


def test_an_unknown_list_code_is_spelled_out_not_leaked():
    assert list_name("xx_new_list") == "the xx new list list"
    assert list_name("us_ofac_sdn") == "the US Treasury sanctions list"


def test_the_record_step_reports_the_chain(engine):
    person(engine, "p1", "Rohan Desai")
    investigation = checked(engine)
    logged = next(s for s in investigation.steps if s.kind == "logged")
    assert "The chain verifies." in logged.body
    assert "Not one can be edited or removed" in logged.body[0]


def test_an_unreachable_service_is_a_refusal_with_nothing_written(engine):
    person(engine, "p1", "Rohan Desai")

    def down(url, body, headers):
        raise OSError("connection refused")

    before = len(engine.log)
    investigation = run_check(
        engine, "p1", today="2026-08-16",
        client=WatchlistClient(url="https://yente.local", transport=down))

    assert investigation.outcome == "not performed"
    assert "Nothing was written" in investigation.explanation[0]
    assert len(engine.log) == before


def test_the_assistant_step_appears_only_when_a_draft_was_prepared(engine):
    from vinzor.model import EntityKind

    from test_assist import drafter_of, reply

    register(engine, "p1", EntityKind.PERSON, "Vladimir Listed",
             nationality="IN", dob="1984-08-19")
    drafter, _ = drafter_of(reply())
    investigation = checked(engine, sanction_result(), drafter=drafter)

    assistant = next((s for s in investigation.steps if s.kind == "assistant"),
                     None)
    assert assistant is not None
    assert assistant.suggestion is not None
    assert assistant.suggestion.caveat, "a suggestion without its caveat"
    assert assistant.took, "drafting time is real and must be shown"

    # And without a drafter, the step simply is not there.
    engine2 = Vinzor(EventLog())
    register(engine2, "p1", EntityKind.PERSON, "Vladimir Listed")
    plain = checked(engine2, sanction_result())
    assert not any(s.kind == "assistant" for s in plain.steps)


def test_a_party_nobody_registered_is_a_loud_error(engine):
    client, _ = client_of()
    with pytest.raises(KeyError):
        run_check(engine, "per_nobody", client=client, today="2026-08-16")
