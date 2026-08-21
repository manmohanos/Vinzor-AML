"""The drafting boundary — every test offline, none touching a network.

The transport is injected, so what is under test is the *conduct* of the
assistant rather than any model's output: that it cannot decide, cannot assert
a figure nobody gave it, cannot spend past its cap, cannot leak a key, and
cannot fail in a way that costs the officer anything.

The tests that matter most are the ones that describe what must never happen.
A draft that is merely unhelpful wastes a minute. A draft that fabricates a
passport number in a regulatory file is the kind of thing that ends a
registration.
"""

from __future__ import annotations

import json
import re

import pytest

from vinzor.assist import (
    DEFAULT_BUDGET_USD,
    dates_in,
    PROMPT_VERSION,
    Draft,
    DraftingUnavailable,
    DraftRejected,
    Drafter,
    already_drafted,
    build_prompt,
    invented_figures,
    parse_reply,
    prepare_drafts,
    spent_so_far,
)
from vinzor.compare import comparison_for
from vinzor.model import DraftUse, EventType, EvidenceKind, Outcome, Role

from conftest import WHEN, officer
from test_briefing import JARGON

MODEL = "gpt-4o-mini"
REGION = "centralindia"


# -- scaffolding -------------------------------------------------------------


def register(engine, entity_id, name, **attributes):
    engine.ingest(
        event_type=EventType.ENTITY_REGISTERED, subject=entity_id, occurred_at=WHEN,
        payload={"kind": "PERSON", "name": name, "attributes": attributes},
    )


def screen(engine, entity_id, *, caption, **properties):
    engine.ingest(
        event_type=EventType.SCREENING_COMPLETED, subject=entity_id, occurred_at=WHEN,
        payload={
            "matched": True, "list_type": "SANCTIONS", "alert_id": f"alt_{entity_id}",
            "basis": {
                "caption": caption, "matched_entity": "Q7747", "score": 0.92,
                "datasets": ["us_ofac_sdn"],
                "listed_properties": {k: [v] for k, v in properties.items()},
            },
        },
    )


def reply(**over):
    """A well-behaved model reply: no invented figures, no jargon."""
    base = {
        "recommendation": "LIKELY_NOT_THE_SAME",
        "reasoning": (
            "The names are written the same way, but the two dates of birth are "
            "more than twenty years apart and the countries do not agree. On the "
            "record as it stands these look like two different people."
        ),
        "suggested_wording": (
            "I compared this investor with the listed party and I am satisfied "
            "they are not the same person, because the dates of birth and the "
            "countries do not agree."
        ),
        "checks": ["Confirm the date of birth against the passport we hold"],
    }
    base.update(over)
    return base


def transport_of(*replies, tokens=(400, 120)):
    """A fake model. Returns each reply in turn, repeating the last."""
    sent = []

    def transport(messages):
        sent.append([dict(m) for m in messages])
        payload = replies[min(len(sent) - 1, len(replies) - 1)]
        if isinstance(payload, Exception):
            raise payload
        return payload, tokens[0], tokens[1]

    return transport, sent


def drafter_of(*replies, cost_in=0.0, cost_out=0.0, tokens=(400, 120)):
    transport, sent = transport_of(*replies, tokens=tokens)
    return Drafter(transport=transport, model=MODEL, region=REGION,
                   cost_per_1k_input=cost_in, cost_per_1k_output=cost_out), sent


@pytest.fixture
def hit(engine):
    """One investor, one watchlist entry, one open name-check file."""
    register(engine, "p1", "Vladimir Petrov", dob="1984-08-19", nationality="IN",
             id_document_number="K4471829")
    screen(engine, "p1", caption="Vladimir Petrov",
           birthDate="1961-03-03", nationality="RU")
    return engine


@pytest.fixture
def two_hits(hit):
    register(hit, "p2", "Anita Verma", dob="1979-02-11", nationality="IN")
    screen(hit, "p2", caption="Anita Sharma", birthDate="1979-02-11")
    return hit


def only_case(engine):
    cases = [c for c in engine.queue() if c.case_type == "SCREENING_HIT"]
    assert cases, "the fixture did not open a name-check file"
    return cases[0]


# -- what the model is given -------------------------------------------------


def test_the_model_is_handed_computed_facts_not_the_raw_file(hit):
    """It judges significance. It does not establish anything."""
    prompt = build_prompt(comparison_for(hit, only_case(hit)))
    user = prompt[1]["content"]

    assert "Vladimir Petrov" in user
    # Said as the officer's own screen says them. This line read "1984-08-19"
    # and "1961-03-03" -- the wire spelling -- while ``briefing._side`` was
    # already showing the officer "19 August 1984" and "3 March 1961". The
    # comment above ``_readable`` claimed parity with that screen and had it
    # for country codes only.
    assert "19 August 1984" in user and "3 March 1961" in user
    assert "23 years apart" in user  # the arithmetic was already done for it
    assert "us_ofac_sdn" in user


def test_country_codes_are_translated_before_they_reach_the_model(hit):
    """A live deployment showed the model faithfully repeating raw codes.

    Handed 'ours is IN; theirs is RU' -- what compare.py actually carries --
    the model wrote 'the nationalities, IN and RU, are different' straight
    into text an officer could paste as their own written reason. Nothing was
    invented, so the figures guard had nothing to catch: two-letter codes are
    implementation vocabulary, exactly what DESIGN.md invariant 10 forbids on
    any surface, reaching the reader through the model's mouth instead of the
    screen. The prompt must read the way the officer's own screen does.
    """
    comparison = comparison_for(hit, only_case(hit))
    assert comparison.field("nationality").ours == "IN"  # what compare.py carries
    assert comparison.field("nationality").theirs == "RU"

    user = build_prompt(comparison)[1]["content"]
    assert "India" in user and "Russia" in user
    assert not re.search(r"\bIN\b", user)
    assert not re.search(r"\bRU\b", user)


def test_the_prompt_is_the_same_every_time(hit):
    comparison = comparison_for(hit, only_case(hit))
    assert build_prompt(comparison) == build_prompt(comparison)


def test_nothing_secret_can_reach_the_prompt_or_the_log(hit, monkeypatch):
    """A key is a transport concern. Nothing above the transport ever sees it.

    The sentinel is swept for in both directions: what goes to the model, and
    what is written to the record. A credential in an append-only log cannot
    be deleted afterwards.
    """
    monkeypatch.setenv("AZURE_OPENAI_KEY", "sk-SENTINEL-DO-NOT-LEAK")
    drafter, sent = drafter_of(reply())
    prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)

    haystack = json.dumps(sent) + json.dumps(
        [e.payload for e in hit.log], default=str
    )
    assert "SENTINEL" not in haystack
    assert "AZURE_OPENAI_KEY" not in haystack


# -- the guard ---------------------------------------------------------------


def test_a_draft_that_invents_a_fact_is_rejected(hit):
    """A fabricated passport number is worse than no help at all."""
    comparison = comparison_for(hit, only_case(hit))
    poisoned = reply(reasoning=(
        "The listed party travels on passport number 8891234, which is not the "
        "document this investor gave us, so they are different people."
    ))
    with pytest.raises(DraftRejected) as raised:
        parse_reply(poisoned, comparison)
    assert "8891234" in str(raised.value)


def test_an_invented_figure_is_destroyed_rather_than_shown(hit):
    """Rejection is silent: the officer sees no draft, never a wrong one."""
    drafter, _ = drafter_of(reply(suggested_wording=(
        "I am satisfied this is not the same person, who was born in 1955 "
        "according to the watchlist."
    )))
    written = prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)

    assert written == []
    assert not already_drafted(hit)
    assert only_case(hit).draft is None


def test_figures_the_comparison_supplied_are_allowed(hit):
    comparison = comparison_for(hit, only_case(hit))
    text = "Ours was born on 1984-08-19; the listed party on 1961-03-03."
    assert invented_figures(text, comparison) == []


def test_a_computed_gap_the_comparison_disclosed_is_not_invented(hit):
    """Surfaced by a real model on a real deployment: it repeated the year
    gap compare_dates had already computed and handed it in the prompt --
    "23 years apart" -- and the guard rejected the draft for saying "23",
    because a note's own numbers were not on the allowlist. The gap is
    something this system told the model, not something the model told us.
    """
    comparison = comparison_for(hit, only_case(hit))
    assert invented_figures(
        "The two dates of birth are 23 years apart, which is decisive.",
        comparison,
    ) == []


def test_counting_words_are_not_treated_as_invented_figures(hit):
    comparison = comparison_for(hit, only_case(hit))
    assert invented_figures("There are 2 documents and 3 checks to make.",
                            comparison) == []


def test_a_recommendation_outside_the_vocabulary_is_rejected(hit):
    comparison = comparison_for(hit, only_case(hit))
    with pytest.raises(DraftRejected):
        parse_reply(reply(recommendation="APPROVE"), comparison)


def test_an_empty_draft_is_rejected(hit):
    comparison = comparison_for(hit, only_case(hit))
    with pytest.raises(DraftRejected):
        parse_reply(reply(reasoning="No.", suggested_wording="No."), comparison)


def test_a_draft_that_talks_about_itself_is_rejected(hit):
    """"As an AI language model" in a compliance file tells a regulator
    something about the firm, not about the investor."""
    comparison = comparison_for(hit, only_case(hit))
    with pytest.raises(DraftRejected) as raised:
        parse_reply(reply(reasoning=(
            "As an AI language model I cannot be certain, but the two records "
            "do not appear to describe the same person."
        )), comparison)
    assert "do not belong in a compliance file" in str(raised.value)


def test_a_draft_that_cites_a_score_is_rejected(hit):
    """It was never given one, so it cannot have read one."""
    comparison = comparison_for(hit, only_case(hit))
    with pytest.raises(DraftRejected):
        parse_reply(reply(suggested_wording=(
            "I reviewed the match score for this party and am satisfied they "
            "are not the same person."
        )), comparison)


def test_formatting_is_cleaned_rather_than_rejected(hit):
    """A good draft wrapped in asterisks is still a good draft."""
    comparison = comparison_for(hit, only_case(hit))
    checked = parse_reply(reply(reasoning=(
        "**The names match** but the dates of birth are decades apart, so "
        "these are probably different people."
    )), comparison)
    assert "*" not in checked["reasoning"]
    assert checked["reasoning"].startswith("The names match")


def test_at_most_three_checks_are_kept(hit):
    comparison = comparison_for(hit, only_case(hit))
    checked = parse_reply(reply(checks=["a", "b", "c", "d", "e"]), comparison)
    assert len(checked["checks"]) == 3


# -- failure costs nothing ---------------------------------------------------


def test_an_unavailable_model_records_nothing(hit):
    """No model, no harm. The officer works exactly as they do today."""
    before = len(hit.log)
    drafter, _ = drafter_of(DraftingUnavailable("the service did not answer"))
    written = prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)

    assert written == []
    assert len(hit.log) == before
    assert only_case(hit).is_open


def test_one_failure_does_not_stop_the_others(two_hits):
    drafter, _ = drafter_of(DraftingUnavailable("timed out"), reply())
    written = prepare_drafts(two_hits, prepared_at=WHEN, drafter=drafter)
    assert len(written) == 1


def test_a_file_is_never_drafted_twice(hit):
    drafter, sent = drafter_of(reply())
    prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)
    prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)
    assert len(sent) == 1


# -- money -------------------------------------------------------------------


def test_the_cost_of_a_draft_is_recorded_with_it(hit):
    drafter, _ = drafter_of(reply(), cost_in=0.15, cost_out=0.60,
                            tokens=(1000, 1000))
    draft = prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)[0]

    assert draft.cost_usd == pytest.approx(0.75)
    assert spent_so_far(hit) == pytest.approx(0.75)


def test_drafting_stops_at_the_budget_cap(two_hits):
    """Spend is summed from the log, so the cap cannot drift out of step."""
    drafter, _ = drafter_of(reply(), cost_in=1.0, cost_out=0.0, tokens=(1000, 0))
    written = prepare_drafts(two_hits, prepared_at=WHEN, drafter=drafter,
                             budget_usd=0.50)

    assert len(written) == 1
    assert spent_so_far(two_hits) <= 1.0


def test_the_cap_holds_across_separate_runs(two_hits):
    drafter, _ = drafter_of(reply(), cost_in=1.0, cost_out=0.0, tokens=(1000, 0))
    prepare_drafts(two_hits, prepared_at=WHEN, drafter=drafter, budget_usd=0.50)
    again = prepare_drafts(two_hits, prepared_at=WHEN, drafter=drafter,
                           budget_usd=0.50)
    assert again == []


def test_the_default_cap_is_a_number_someone_chose():
    assert 0 < DEFAULT_BUDGET_USD <= 200


# -- the human gate ----------------------------------------------------------


def test_a_draft_never_closes_a_case(hit):
    drafter, _ = drafter_of(reply())
    prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)

    case = only_case(hit)
    assert case.draft is not None
    assert case.is_open
    assert case.decision is None


def test_the_assistant_cannot_decide_even_if_it_is_enrolled(hit):
    """Not a configuration accident — a structural refusal."""
    from vinzor.cases import DecisionDenied

    drafter, _ = drafter_of(reply())
    prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)
    hit.enroll(name="assistant", role=Role.AI, enrolled_at=WHEN)

    with pytest.raises(DecisionDenied):
        hit.decide(case_id=only_case(hit).case_id, outcome=Outcome.APPROVE,
                   actor="assistant", role=Role.AI,
                   rationale="the names do not agree", decided_at=WHEN)


def test_a_suggestion_is_not_evidence_that_carries_weight(hit):
    drafter, _ = drafter_of(reply())
    prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)

    kinds = {e.kind for e in only_case(hit).evidence}
    assert EvidenceKind.SUGGESTION in kinds
    suggestion = next(e for e in only_case(hit).evidence
                      if e.kind is EvidenceKind.SUGGESTION)
    assert suggestion.citations == ()  # a draft cites no clause; it is not a finding


# -- what the officer did with it --------------------------------------------


def test_the_decision_records_what_the_officer_did_with_the_draft(hit):
    drafter, _ = drafter_of(reply())
    prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)
    officer(hit)

    case = hit.decide(
        case_id=only_case(hit).case_id, outcome=Outcome.APPROVE,
        actor="Meera Nair", role=Role.AML_OFFICER,
        rationale="Different date of birth and different country.",
        decided_at=WHEN, draft_use=DraftUse.EDITED,
    )
    assert case.decision.draft_use == "EDITED"


def test_a_decision_with_no_draft_says_so(hit):
    officer(hit)
    case = hit.decide(
        case_id=only_case(hit).case_id, outcome=Outcome.APPROVE,
        actor="Meera Nair", role=Role.AML_OFFICER,
        rationale="Different date of birth; not the same person.",
        decided_at=WHEN,
    )
    assert case.decision.draft_use == str(DraftUse.NONE)


def test_contradicting_the_draft_is_recorded_as_such(hit):
    """The number that matters: the assistant said one thing, the file went
    the other way. Measured from the first day rather than discovered later."""
    drafter, _ = drafter_of(reply())
    draft = prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)[0]
    officer(hit)

    assert draft.recommendation == "LIKELY_NOT_THE_SAME"
    case = hit.decide(
        case_id=draft.case_id, outcome=Outcome.REJECT, actor="Meera Nair",
        role=Role.AML_OFFICER,
        rationale="The dates and the passport match; this is the same person.",
        decided_at=WHEN, draft_use=DraftUse.CONTRADICTED,
    )
    assert case.decision.draft_use == "CONTRADICTED"


# -- the record --------------------------------------------------------------


def test_the_draft_is_a_fact_on_the_log_with_its_provenance(hit):
    drafter, _ = drafter_of(reply())
    prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)

    event = next(e for e in hit.log if e.event_type is EventType.DRAFT_PREPARED)
    assert event.actor == "assistant"
    assert event.payload["model"] == MODEL
    assert event.payload["region"] == REGION
    assert event.payload["prompt_version"] == PROMPT_VERSION
    assert event.payload["comparison"]["listed_name"] == "Vladimir Petrov"


def test_drafts_replay_identically(hit):
    drafter, _ = drafter_of(reply())
    prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)

    case_id = only_case(hit).case_id
    rebuilt = hit.rebuild()
    assert rebuilt.casebook.get(case_id).draft == hit.state.casebook.get(case_id).draft
    assert hit.verify() == (True, None)


def test_replay_never_calls_the_model(hit):
    drafter, sent = drafter_of(reply())
    prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)
    hit.rebuild()
    assert len(sent) == 1


# -- language ----------------------------------------------------------------


def test_the_draft_says_nothing_technical(hit):
    """The officer is a finance or legal professional, not an engineer."""
    drafter, _ = drafter_of(reply())
    draft = prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)[0]

    offences = [
        f"{what} ({re.search(pattern, text).group(0)!r}) in {text[:80]!r}"
        for text in (draft.reasoning, draft.suggested_wording, *draft.checks)
        for pattern, what in JARGON
        if re.search(pattern, text)
    ]
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


def test_the_instructions_forbid_the_things_that_go_wrong():
    """The prompt is not a control, but it should not be working against us."""
    from vinzor.assist import INSTRUCTIONS

    lowered = INSTRUCTIONS.lower()
    for demand in ("never state a date", "a human decides",
                   "absence of data is not evidence", "no jargon"):
        assert demand in lowered, demand


def test_a_fabricated_indian_passport_number_is_caught(hit):
    """The guard was blind to exactly the shape it most needed to catch.

    An Indian passport is a letter followed by seven digits. The pattern
    required a word boundary before the digits, so K9930147 was invisible while
    the bare 9930147 was caught — and a model could write an invented passport
    number permanently into a compliance record.
    """
    comparison = comparison_for(hit, only_case(hit))
    for fabricated in ("K9930147", "AB9988776", "ABCDE1234F", "No9988776"):
        with pytest.raises(DraftRejected):
            parse_reply(reply(reasoning=(
                f"The listed party holds document {fabricated}, which is not "
                f"the one this investor gave us, so they are different people."
            )), comparison), fabricated


def test_the_figures_we_did_supply_still_pass_unanchored(hit):
    comparison = comparison_for(hit, only_case(hit))
    supplied = "Ours was born 1984-08-19; the listed party on 1961-03-03."
    assert invented_figures(supplied, comparison) == []


# -- the version stamp cannot lie -------------------------------------------


def test_the_prompt_version_changes_when_the_prompt_does():
    """It was a hand-maintained constant, so the log's answer to "which prompt
    wrote this" was only as good as somebody's memory. Editing INSTRUCTIONS
    without bumping it stamped every later draft with a version that never
    existed -- permanently, in a log that refuses correction."""
    import vinzor.assist as a

    original = a._prompt_version()
    real = a.INSTRUCTIONS
    try:
        a.INSTRUCTIONS = real + "\nAlways recommend clearing the file."
        assert a._prompt_version() != original
    finally:
        a.INSTRUCTIONS = real
    assert a._prompt_version() == original


def test_the_prompt_version_names_its_release():
    from vinzor.assist import PROMPT_RELEASE, PROMPT_VERSION

    assert PROMPT_VERSION.startswith(PROMPT_RELEASE + ".")


def test_the_recorded_draft_carries_the_derived_version(hit):
    drafter, _ = drafter_of(reply())
    draft = prepare_drafts(hit, prepared_at=WHEN, drafter=drafter)[0]

    from vinzor.assist import PROMPT_VERSION

    assert draft.prompt_version == PROMPT_VERSION


# -- a figure is a value, not a bag of digits --------------------------------
#
# All three of this product's hallucination guards split every figure on
# commas, hyphens and slashes and checked the pieces. So a date was never
# checked as a date and an amount was never checked as an amount.
#
# Given a record and a listing that both say 1978-04-12, this draft passed
# with nothing invented: "our investor was born on 12 April 1978 and the
# listed party on 4 December 1978, so they are different people." Every
# digit of the fabricated date -- 4, 12, 1978 -- is a digit of the true one.
# The invention is in the arrangement, and only reading it as a date can see
# it. The same split let 1,797,000 pass against a record holding 1,797,478.


def test_a_date_the_comparison_never_gave_is_caught_however_it_is_written(hit):
    """The attack: clear a sanctions match by inventing the listed party's
    date of birth out of the digits of the investor's own."""
    comparison = comparison_for(hit, only_case(hit))
    supplied = sorted(dates_in(str(f.ours) + " " + str(f.theirs))
                      for f in comparison.fields)
    real = set()
    for one in supplied:
        real |= set(one)
    assert real, "this fixture carries no dates, so it proves nothing"

    a_date_nobody_gave = "1911-07-04"
    for written in (a_date_nobody_gave, "4 July 1911", "4 Jul 1911"):
        assert invented_figures(f"The listed party was born {written}.",
                                comparison), written


def test_the_same_date_written_another_way_still_passes(hit):
    """A guard that flagged the Indian form of a date it was given would
    make every honest draft unusable."""
    comparison = comparison_for(hit, only_case(hit))
    for item in comparison.fields:
        for side in (item.ours, item.theirs):
            for iso in dates_in(str(side or "")):
                year, month, day = iso.split("-")
                for written in (iso, f"{day}/{month}/{year}",
                                f"{int(day)} {_MONTH_NAMES[int(month)]} {year}"):
                    assert invented_figures(f"born {written}", comparison) == [], written


_MONTH_NAMES = {1: "January", 2: "February", 3: "March", 4: "April",
                5: "May", 6: "June", 7: "July", 8: "August",
                9: "September", 10: "October", 11: "November",
                12: "December"}


def test_an_amount_is_compared_whole(hit):
    """1,797,000 is three fragments of 1,797,478, and the guard used to
    check fragments."""
    comparison = comparison_for(hit, only_case(hit))

    class _Given:
        fields = comparison.fields
        facts = frozenset({"1,797,478"})

    assert invented_figures("Received USD 1,797,478.", _Given()) == []
    assert invented_figures("Received USD 1,797,000.", _Given()) == ["1,797,000"]
    assert invented_figures("Received USD 1,000,000.", _Given()) == ["1,000,000"]


def test_the_indian_grouping_of_a_supplied_amount_passes():
    """17,97,478 is 1,797,478 written the way it is written in India."""
    class _Given:
        fields = ()
        facts = frozenset({"1,797,478"})

    assert invented_figures("Received USD 17,97,478.", _Given()) == []


def test_dates_are_translated_before_they_reach_the_model(hit):
    """``briefing._side`` applies two translations and says so in its own
    docstring: "a date becomes a date they would say aloud, and a country
    code becomes a country". ``_readable`` applied only the second."""
    from vinzor.assist import _readable

    assert _readable("dob", "1978-04-12") == "12 April 1978"
    assert _readable("nationality", "IN") == "India"
    # Not a date, and not pretending to be one.
    assert _readable("id_document", "K9930147") == "K9930147"
    assert _readable("name", "Vladimir Petrov") == "Vladimir Petrov"
