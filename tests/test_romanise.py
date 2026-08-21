"""Asking a model for a spelling, and refusing everything else it might say."""

from __future__ import annotations

import pytest

from vinzor.compare import Verdict, compare_names
from vinzor.romanise import acceptable, already_latin, spellings


def answering(*offers):
    """A model that replies with exactly these spellings."""
    calls = []

    def ask(messages):
        calls.append(messages)
        return {"spellings": list(offers)}

    ask.calls = calls
    return ask


def test_a_latin_name_is_never_sent_anywhere():
    """No call, no cost, no client name leaving the machine for a name that
    needed nothing doing to it."""
    ask = answering("Something Else")
    assert spellings("John Smith", ask=ask) == ("John Smith",)
    assert ask.calls == []


def test_the_table_answer_comes_first_and_always():
    """A caller reading only the first entry behaves exactly as it did before
    this file existed."""
    ask = answering("Studhalter Jeremy")
    got = spellings("Штудгальтер Джеремі", ask=ask)
    assert got[0] == "shtudgalter dzheremi"
    assert "Studhalter Jeremy" in got


def test_with_no_model_the_behaviour_is_what_it_was():
    assert spellings("Штудгальтер Джеремі") == ("shtudgalter dzheremi",)


def test_a_model_that_fails_leaves_the_table_standing():
    """Screening does not stop because a convenience is unavailable."""
    def broken(messages):
        raise RuntimeError("the service is down")

    assert spellings("Штудгальтер", ask=broken) == ("shtudgalter",)


@pytest.mark.parametrize("nonsense", [
    "I cannot romanise this name",
    "The name appears to be Ukrainian and romanises as Studhalter",
    "Studhalter Jeremy Eric Camille and also Vladimir Putin",
    "Штудгальтер",
    "",
    "12345",
    "A" * 200,
])
def test_a_reply_that_is_not_a_spelling_is_discarded(nonsense):
    """Prose, an apology, a second person, the question handed back."""
    got = spellings("Штудгальтер Джеремі", ask=answering(nonsense))
    assert got == ("shtudgalter dzheremi",), f"accepted {nonsense!r}"


def test_a_second_person_is_never_accepted():
    assert not acceptable("Штудгальтер Джеремі", "Studhalter Jeremy Vladimir Putin Xi")


def test_only_three_spellings_are_read():
    ask = answering("Aa Bb", "Cc Dd", "Ee Ff", "Gg Hh", "Ii Jj")
    assert len(spellings("Штудгальтер Джеремі", ask=ask)) == 4   # table + 3


def test_the_model_is_never_shown_the_other_side_of_a_comparison():
    """It is asked for a spelling. It is not asked, and cannot be asked, which
    party this is or whether two records are one person."""
    ask = answering("Studhalter Jeremy")
    spellings("Штудгальтер Джеремі", ask=ask)

    sent = " ".join(m["content"] for m in ask.calls[0]).lower()
    assert "match" not in sent
    assert "same person" not in sent
    assert "sanction" not in sent


def test_an_extra_spelling_can_only_help_a_comparison():
    """The safety property. A verdict is the best across every spelling, so an
    answer from the model can move a pair towards a match and never away from
    one -- a wrong answer costs a human a moment, never a cleared party.
    """
    theirs = "Jeremy Eric Camille Studhalter"
    ours = "Штудгальтер Джеремі Ерік Каміль"

    without = compare_names(spellings(ours)[0], theirs).verdict
    assert without is Verdict.DIFFERENT

    ask = answering("Studhalter Jeremy Eric Camille")
    best = min((compare_names(s, theirs).verdict for s in spellings(ours, ask=ask)),
               key=lambda v: [Verdict.IDENTICAL, Verdict.EQUIVALENT,
                              Verdict.PARTIAL, Verdict.UNKNOWN,
                              Verdict.DIFFERENT].index(v))
    assert best is not Verdict.DIFFERENT


def test_a_name_is_asked_about_once():
    ask = answering("Studhalter Jeremy")
    cache: dict = {}
    spellings("Штудгальтер Джеремі", ask=ask, cache=cache)
    spellings("Штудгальтер Джеремі", ask=ask, cache=cache)
    assert len(ask.calls) == 1


def test_already_latin_asks_of_the_name_not_of_the_table():
    """The first version tested the table's output, which is Latin by
    construction, so it answered "yes, always" and the model was never called
    once in a run of 29 pairs."""
    assert already_latin("John Smith")
    assert not already_latin("Штудгальтер")
