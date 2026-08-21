"""What a Principal Officer reads — and what must never reach them.

The first test in this file is the important one. It walks every string the
system can put in front of a person and fails if a single piece of
implementation vocabulary has leaked into it. That is a build-breaking error,
not a cosmetic one: the reader is a compliance professional, not an engineer,
and a screen they cannot read is a control they cannot operate.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Mapping

import pytest

from vinzor import briefing
from vinzor.briefing import CHOICES, PLAIN_RULES, brief, item_for, report
from vinzor.citations import CLAUSES
from vinzor.model import Outcome
from vinzor.quality import Quality

from conftest import (commits, company, owns, paid, person, register,
                      screened, trust_of)

#: Vocabulary that exists only because of how the software is built.
JARGON = [
    (r"case_[0-9a-f]{6,}", "an internal case id"),
    (r"\bPOL_[A-Z]", "a policy id"),
    (r"\b(?:cmp|per|trs|fnd|pay|alt|ccm|bac|edg|san|adm|cas)_\d{3,}", "an entity id"),
    (r"[A-Z][A-Z0-9]{2,}_[A-Z]", "a SCREAMING_CASE constant"),
    (r"\b[0-9a-f]{32,}\b", "a hash"),
    (r"\bseq\b", "a sequence number"),
    (r"[{}\[\]]", "raw JSON punctuation"),
    (r"\bNone\b", "an unfilled Python value"),
    (r"\b(?:payload|projection|enum|dataclass|dedupe|traversal|boolean)\b",
     "an implementation word"),
]


def _strings(value, path="briefing"):
    """Every user-facing string in a nested structure of dataclasses."""
    if dataclasses.is_dataclass(value):
        for f in dataclasses.fields(value):
            # The only field deliberately not shown: it is how a button posts
            # a decision back, never something a person reads.
            # These fields are addresses, not prose: how a button posts a
            # decision, where a link points, and which party or file a row
            # leads to. None is ever read aloud.
            if f.name in {"case_id", "link", "ref", "entity_id", "subject"}:
                continue
            yield from _strings(getattr(value, f.name), f"{path}.{f.name}")
    elif isinstance(value, Mapping):
        # This branch did not exist, and its absence was the whole of the
        # hole: ``briefing.UI`` is a plain dict of 124 strings, injected into
        # every JSON response and rendered on every screen -- the single
        # largest body of prose in the product -- and the walker returned
        # nothing at all for it. A sweep that cannot reach the text it is
        # sweeping reads as a passing guard forever.
        for key, item in value.items():
            yield from _strings(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _strings(v, f"{path}[{i}]")
    elif isinstance(value, str):
        yield path, value


@pytest.fixture
def busy(engine):
    """One of everything, so the sweep has real text to walk."""
    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Anita Verma")
    company(engine, "c1", "Orion Zenith Enterprises")
    company(engine, "c2", "Meridian Trading")
    company(engine, "c3", "Apex Global Partners")
    company(engine, "c4", "Harbour Point Capital")
    trust_of(engine, "t1", "The Desai Family Trust")

    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    screened(engine, "p2", "PEP", alert_id="alt_2")
    screened(engine, "c4", "ADVERSE_MEDIA", alert_id="alt_3")

    owns(engine, "c1", "c2", 40)
    owns(engine, "c2", "c3", 50)
    owns(engine, "c3", "c1", 30)  # a loop
    commits(engine, "c1")
    commits(engine, "t1")
    commits(engine, "c4")

    # Six payment findings until 21 August 2026, one per rule. Two rules
    # remain, so this arranges the two of them: a declared sanctioned payer,
    # and a payment from a party other than the investor.
    paid(engine, "p1", anomaly="SANCTIONED_PAYER", payment_id="pay_1",
         currency="USD", expected_currency="USD", amount=2_500_000.0,
         called_amount=2_000_000.0)
    paid(engine, "p1", payment_id="pay_3", payer="somebody_else",
         currency="USD", expected_currency="USD", amount=2_500_000.0,
         called_amount=2_000_000.0)
    return engine


@pytest.fixture
def drafted(engine):
    """A name check that has a prepared suggestion on it.

    The suggestion is model output, so it goes through the same sweep as
    everything else. Its wording is not ours, which is exactly why it is
    swept rather than trusted.
    """
    from test_assist import drafter_of, register, reply, screen
    from vinzor.assist import prepare_drafts

    register(engine, "p9", "Vladimir Petrov", dob="1984-08-19", nationality="IN")
    screen(engine, "p9", caption="Vladimir Petrov", birthDate="1961-03-03",
           nationality="RU")
    drafter, _ = drafter_of(reply())
    prepare_drafts(engine, prepared_at="2026-08-12", drafter=drafter)
    return engine


# -- the guard -------------------------------------------------------------


def test_no_implementation_vocabulary_reaches_the_reader(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    offences = []
    for path, text in _strings(briefing):
        for pattern, what in JARGON:
            match = re.search(pattern, text)
            if match:
                offences.append(f"{path}: {what} ({match.group(0)!r}) in {text[:90]!r}")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


#: Named holes in a message, filled by the caller before a reader sees one.
#: ``server.py`` does ``MESSAGES["no_party"].format(query=query)``. Stated as
#: an exemption rather than left to the JSON-punctuation rule to trip over,
#: so that a real brace in a real sentence is still caught.
_A_HOLE = re.compile(r"\{[a-z_][a-z0-9_]*\}")


def _swept(blob, name):
    """Every string in a dictionary, with its placeholders filled in."""
    for path, text in _strings(blob, name):
        yield path, _A_HOLE.sub("something", text)


def test_no_implementation_vocabulary_reaches_the_reader_through_the_screens():
    """``UI`` is 124 strings injected into every JSON response and rendered on
    every screen -- the largest body of prose in the product -- and for a
    while the walker could not see a single one of them, because it descended
    dataclasses, lists and tuples and ``UI`` is a plain dictionary. It was
    hiding a live offence: pressing "Check the watchlists now" on a workspace
    with no watchlist replaced the screen with "Set VINZOR_SCREENING_URL to
    your watchlist index" -- an instruction to whoever installed the software,
    printed to somebody who cannot act on it, and the first thing every new
    user saw."""
    offences = []
    for name, blob in (("screens", briefing.UI), ("messages", briefing.MESSAGES)):
        for path, text in _swept(blob, name):
            for pattern, what in JARGON:
                match = re.search(pattern, text)
                if match:
                    offences.append(
                        f"{path}: {what} ({match.group(0)!r}) in {text[:90]!r}")
    assert not offences, ("jargon reached the reader:\n  "
                           + ("\n  ".join(offences)))


def test_the_walker_can_actually_see_into_a_dictionary():
    """The guard that was passing on nothing. Without this the test above is
    an assertion over an empty list."""
    assert len(list(_strings(briefing.UI, "screens"))) >= len(briefing.UI)
    assert len(list(_strings(briefing.MESSAGES, "messages"))) == len(briefing.MESSAGES)


def test_a_hole_in_a_message_is_a_plain_name_not_a_structure():
    """The exemption above is only safe while every brace really is a hole
    somebody fills."""
    leftover = [(key, text) for key, text in briefing.MESSAGES.items()
                if "{" in _A_HOLE.sub("", str(text))]
    assert leftover == []


def test_the_dictionary_sweep_would_actually_catch_something():
    poisoned = dict(briefing.UI, greeting="Case POL_UBO_CYCLE on cmp_0001")
    assert any(re.search(pattern, text)
               for _, text in _swept(poisoned, "screens")
               for pattern, _ in JARGON)


def test_the_sweep_would_actually_catch_something(busy):
    """A guard nobody has seen fail is a guard nobody should trust."""
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    poisoned = dataclasses.replace(briefing, greeting="Case POL_UBO_CYCLE on cmp_0001")
    offences = [
        1
        for _, text in _strings(poisoned)
        for pattern, _ in JARGON
        if re.search(pattern, text)
    ]
    assert offences


def test_the_sweep_also_runs_against_the_real_dataset():
    """The handmade fixture cannot anticipate every shape the data takes.

    It did not, in fact: unattributed payments have no registered entity, and
    an early version printed the internal record id where a name belongs. Only
    the real corpus surfaced it.
    """
    from vinzor.seed import DEFAULT_DATASET, seed

    if not DEFAULT_DATASET.exists():
        pytest.skip("synthetic dataset not present")

    briefing = brief(seed(), person="Meera Nair", today="2026-08-12")
    offences = []
    for path, text in _strings(briefing):
        for pattern, what in JARGON:
            match = re.search(pattern, text)
            if match:
                offences.append(f"{path}: {what} ({match.group(0)!r}) in {text[:90]!r}")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


def test_an_unattributable_payment_is_described_not_numbered(engine):
    """A file whose subject is a payment record, not a party, must be named
    in words rather than with the record id.

    This used to take its example off the seeded dataset, which had 29
    payments with no sender recorded. The rule that opened files on those was
    removed on 21 August 2026, so the dataset has no such file any more and
    the example is built here instead. The situation is still reachable and
    still ordinary: a bank statement names a remitter but no beneficiary, the
    row is filed against an unregistered id, and the third-party rule sees a
    sender that is not the subject.
    """
    from vinzor.briefing import UNKNOWN_SENDER
    from vinzor.model import EventType

    engine.ingest(
        event_type=EventType.PAYMENT_RECEIVED, subject="unk_pay_9",
        occurred_at="2026-08-02",
        payload={"payment_id": "pay_9", "payment_ref": "TX-9",
                 "amount": 40_000.0, "called_amount": 40_000.0,
                 "currency": "USD", "expected_currency": "USD",
                 "payer": "somebody_else"})

    briefing = brief(engine, person="Meera Nair", today="2026-08-12")
    unknown = [i for g in briefing.groups for i in g.items if i.who == UNKNOWN_SENDER]
    assert unknown, "the sender was not described"
    assert not any("unk_pay_9" in i.who for g in briefing.groups
                   for i in g.items), "the record id reached the reader"


# -- every item answers the six questions ----------------------------------


def test_each_item_says_who_what_why_and_what_to_do(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    assert briefing.items
    for item in briefing.items:
        assert item.who, f"{item.reference} does not say who it is about"
        assert item.headline, f"{item.reference} does not say what is wrong"
        assert item.because, f"{item.reference} does not explain why"
        assert item.to_close_this, f"{item.reference} does not say what to do"
        assert item.rules, f"{item.reference} does not say which rule applies"
        assert item.choices, f"{item.reference} offers no decision"
        assert item.recorded_as, f"{item.reference} does not say how it is recorded"


def test_an_item_is_referred_to_by_something_a_person_can_say_aloud(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    references = [i.reference for i in briefing.items]
    assert "Name check 1" in references
    assert len(set(references)) == len(references)


def test_urgency_is_expressed_as_when_not_as_a_grade(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    urgencies = {i.urgency for i in briefing.items}
    assert any("today" in u or "stop" in u.lower() for u in urgencies)
    assert not any(u in {"HIGH", "CRITICAL", "MEDIUM", "LOW"} for u in urgencies)


def test_entities_are_named_never_numbered(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    assert any(i.who == "Orion Zenith Enterprises" for i in briefing.items)


# -- the rule, in both voices ----------------------------------------------


def test_each_rule_is_given_in_plain_words_and_in_the_regulator_s(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    for item in briefing.items:
        for rule in item.rules:
            assert rule.says and rule.quote and rule.clause
            assert rule.says != rule.quote
            assert rule.link.startswith("https://")
            # ...and the reader sees a sentence, not the address.
            assert rule.link_text.startswith("Read clause")


def test_an_unconfirmed_rule_says_so_to_the_reader(busy):
    """The reader is told when we have not had a professional check the wording."""
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    rules = [r for i in briefing.items for r in i.rules]
    assert rules
    for rule in rules:
        assert rule.checked_by_a_person is False
        assert rule.caution and "compliance professional" in rule.caution


def test_every_registered_clause_has_a_plain_english_reading():
    """A clause the product can cite but cannot explain is not usable."""
    missing = sorted(set(CLAUSES) - set(PLAIN_RULES))
    assert not missing, f"no plain-language reading for: {missing}"


# -- decisions -------------------------------------------------------------


def test_the_choices_say_what_will_happen_not_just_what_they_are():
    assert [c.outcome for c in CHOICES] == [
        Outcome.APPROVE,
        Outcome.ESCALATE,
        Outcome.REJECT,
    ]
    for choice in CHOICES:
        assert len(choice.means) > 40
        assert choice.label.lower() == choice.label or choice.label[0].isupper()


def test_the_reader_is_told_the_record_is_permanent(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    assert "cannot be edited or deleted" in briefing.items[0].recorded_as
    assert "recorded permanently" in briefing.assurance


# -- the shape of the morning ----------------------------------------------


def test_the_briefing_leads_with_what_must_stop(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    assert "stop" in briefing.headlines[0].lower()


def test_the_briefing_says_what_needs_nothing(busy):
    """Telling someone what they can ignore is half the value."""
    from vinzor.model import Outcome, Role

    busy.enroll(name="Meera Nair", role=Role.AML_OFFICER, enrolled_at="2026-08-12")
    case = busy.queue()[0]
    busy.decide(case_id=case.case_id, outcome=Outcome.APPROVE, actor="Meera Nair",
                role=Role.AML_OFFICER, rationale="Different date of birth; a false positive.",
                decided_at="2026-08-12")
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    assert briefing.nothing_needed == (
        "1 file has already been settled and needs nothing further from you."
    )


def test_before_anything_is_settled_it_says_so_plainly(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    assert "Nothing has been settled yet" in briefing.nothing_needed


def test_dates_are_written_the_way_a_person_writes_them(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    assert "12 August 2026" in briefing.greeting


def test_like_work_is_grouped_so_the_reason_is_given_once(busy):
    """Four payments held for one reason are one piece of work, not four."""
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    assert briefing.groups
    for group in briefing.groups:
        assert group.title and group.because and group.to_close_this
        assert group.items
        assert group.total >= len(group.items)


def test_group_titles_read_as_english_at_one_and_at_many():
    """A count of one must not produce "1 structure own each other"."""
    from vinzor.briefing import GROUP_TITLE, _group_title

    for policy in GROUP_TITLE:
        for n in (1, 40):
            rendered = _group_title(policy, n)
            assert "{" not in rendered, f"{policy} left a placeholder: {rendered}"

    assert _group_title("POL_UBO_CYCLE", 1) == "1 structure contains circular ownership"
    assert _group_title("POL_UBO_CYCLE", 3) == "3 structures contain circular ownership"
    assert _group_title("POL_SANCTIONS_HIT", 1) == "1 party may be on a sanctions list"
    assert _group_title("POL_SANCTIONS_HIT", 8) == "8 parties may be on a sanctions list"
    assert _group_title("POL_PAY_THIRD_PARTY", 1) == (
        "1 payment came from someone other than the investor"
    )
    assert _group_title("POL_PAY_THIRD_PARTY", 38) == (
        "38 payments came from someone other than the investor"
    )
    assert _group_title("POL_UBO_NOT_DECLARED", 1) == (
        "1 investor has told us nothing about who owns them"
    )
    assert _group_title("POL_OFFICE_VACANT", 1) == "1 required post is unfilled"
    assert _group_title("POL_OFFICE_VACANT", 3) == "3 required posts are unfilled"
    assert _group_title("POL_ACTIVITY_OUTSIDE_LICENCE", 2) == (
        "2 activities may be outside what your licence permits"
    )


def test_a_group_counts_itself_in_its_own_title(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    titles = [g.title for g in briefing.groups]
    assert any(t.startswith("1 ") for t in titles)
    # and it must read as English at one, not "1 partys"
    assert not any("partys" in t or "querys" in t or "investors " in t and t.startswith("1 ")
                   for t in titles)


def test_a_long_group_says_how_many_it_is_holding_back(busy):
    """It used to promise the rest were "shown when you open this", which was
    true nowhere. It now states what is on screen and offers to fetch the rest.
    """
    briefing = brief(busy, person="Meera Nair", today="2026-08-12", per_group=1)
    hidden = [g for g in briefing.groups if g.total > 1]
    assert hidden
    for group in hidden:
        assert group.more == f"Showing 1 of {group.total}."
        assert group.show_all == f"Show all {group.total}"
        assert "shown when you open" not in group.more


def test_the_most_urgent_group_is_first(busy):
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    assert "stop" in briefing.groups[0].urgency.lower()


# -- the comparison and the suggestion ---------------------------------------


def test_the_sweep_covers_the_suggestion_too(drafted):
    """The wording in a suggestion is not ours. That is why it is swept."""
    briefing = brief(drafted, person="Meera Nair", today="2026-08-12")
    item = next(i for i in briefing.items if i.suggestion)
    offences = []
    for path, text in _strings(item.suggestion, "suggestion"):
        for pattern, what in JARGON:
            match = re.search(pattern, text)
            if match:
                offences.append(f"{path}: {what} ({match.group(0)!r})")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


def test_the_comparison_is_shown_as_dates_a_person_reads(drafted):
    briefing = brief(drafted, person="Meera Nair", today="2026-08-12")
    item = next(i for i in briefing.items if i.side_by_side)
    birth = next(l for l in item.side_by_side if l.what == "Date of birth")

    assert birth.ours == "19 August 1984"
    assert birth.theirs == "3 March 1961"
    assert birth.says == "23 years apart."
    assert birth.tone == "differs"


def test_a_detail_nobody_holds_says_so_rather_than_sitting_empty(drafted):
    briefing = brief(drafted, person="Meera Nair", today="2026-08-12")
    item = next(i for i in briefing.items if i.side_by_side)
    document = next(l for l in item.side_by_side if l.what == "Identity document")

    assert document.ours == "Not on file"
    assert document.theirs == "Not on the list entry"
    assert document.tone == "unknown"


def test_the_columns_are_labelled_in_plain_words(drafted):
    briefing = brief(drafted, person="Meera Nair", today="2026-08-12")
    item = next(i for i in briefing.items if i.side_by_side)
    assert (item.ours_label, item.theirs_label) == ("What we hold",
                                                    "What the list says")


def test_the_suggestion_warns_before_it_concludes(drafted):
    """The caveat is read first because it is written first."""
    from vinzor.briefing import Suggestion
    import dataclasses as dc

    names = [f.name for f in dc.fields(Suggestion)]
    assert names.index("caveat") < names.index("verdict")

    briefing = brief(drafted, person="Meera Nair", today="2026-08-12")
    suggestion = next(i.suggestion for i in briefing.items if i.suggestion)
    assert "not a decision" in suggestion.caveat
    assert "can be wrong" in suggestion.caveat


def test_the_two_ways_out_are_offered_equally(drafted):
    briefing = brief(drafted, person="Meera Nair", today="2026-08-12")
    suggestion = next(i.suggestion for i in briefing.items if i.suggestion)
    assert suggestion.use_label == "Use this wording"
    assert suggestion.own_label == "Write my own"


def test_the_recommendation_is_translated_out_of_its_code(drafted):
    briefing = brief(drafted, person="Meera Nair", today="2026-08-12")
    suggestion = next(i.suggestion for i in briefing.items if i.suggestion)
    assert suggestion.verdict == (
        "On the details we hold, these look like two different parties."
    )
    assert "LIKELY" not in suggestion.verdict


def test_a_file_with_no_suggestion_reads_exactly_as_it_did_before(busy):
    """The ordinary case: no model, no budget, or a draft that was destroyed."""
    briefing = brief(busy, person="Meera Nair", today="2026-08-12")
    assert all(i.suggestion is None for i in briefing.items)
    assert all(i.side_by_side == () for i in briefing.items)
    assert all(i.headline for i in briefing.items)


def test_an_unrecognised_recommendation_shows_nothing_at_all(drafted):
    """Better a missing panel than an untranslated one."""
    from vinzor.briefing import suggestion_for
    import dataclasses as dc

    case = next(c for c in drafted.queue() if c.draft)
    poisoned = dc.replace(case, draft={**case.draft, "recommendation": "MAYBE"})
    assert suggestion_for(poisoned) is None


def test_a_country_code_is_shown_as_a_country(drafted):
    """It read "SG" against "cn" once. That is a puzzle, not a comparison."""
    briefing = brief(drafted, person="Meera Nair", today="2026-08-12")
    item = next(i for i in briefing.items if i.side_by_side)
    row = next(l for l in item.side_by_side if l.what == "Nationality")
    assert (row.ours, row.theirs) == ("India", "Russia")


def test_a_country_code_nobody_recognises_is_shown_as_written():
    from vinzor.countries import name_of

    assert name_of("sg") == "Singapore"
    assert name_of("ZZ") == "ZZ"
    assert name_of("") == ""
    assert name_of("Singapore") == "Singapore"


# -- the circular-ownership sentence ----------------------------------------
# Two shapes of cycle reach the writer: graph.resolve_ubo closes the loop by
# repeating the first company at the end, policies.ownership_cycle does not.
# Slicing the last element off unconditionally dropped a real company, and on
# a two-company loop it named nobody but the subject.


def _loop(engine, pairs, names):
    from vinzor.model import EventType

    for entity_id, name in names.items():
        engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=entity_id,
                      occurred_at="2026-01-01",
                      payload={"kind": "COMPANY", "name": name})
    for owner, owned in pairs:
        engine.ingest(event_type=EventType.OWNERSHIP_DECLARED, subject=owned,
                      occurred_at="2026-01-02",
                      payload={"owner": owner, "owned": owned,
                               "relation": "OWNS", "percentage": 100.0})
    return engine


def _circle_sentence(engine):
    briefing = brief(engine, person="Meera Nair", today="2026-03-02")
    for item in briefing.items:
        for line in item.because:
            if "runs in a circle" in line:
                return line
    return ""


def test_a_two_company_loop_names_both_companies(engine):
    """It named only the subject: "the ownership of Alpha runs in a circle:
    Alpha — and that last one owns the first". Nobody could act on that."""
    _loop(engine, [("a", "b"), ("b", "a")],
          {"a": "Alpha Holdings", "b": "Beta Trading"})
    sentence = _circle_sentence(engine)

    assert sentence, "no circular-ownership sentence was produced"
    assert "Alpha Holdings" in sentence
    assert "Beta Trading" in sentence


def test_a_three_company_loop_names_all_three(engine):
    _loop(engine, [("a", "b"), ("b", "c"), ("c", "a")],
          {"a": "Orion Zenith", "b": "Pinnacle Harbor", "c": "Dynamic Trading"})
    sentence = _circle_sentence(engine)

    for name in ("Orion Zenith", "Pinnacle Harbor", "Dynamic Trading"):
        assert name in sentence, f"{name} is in the loop but not in the sentence"


def test_the_chain_closes_on_itself_so_the_circle_is_visible(engine):
    """It stopped short and then said "that last company owns the first one
    again" — describing the first company as though it were a different one."""
    _loop(engine, [("a", "b"), ("b", "c"), ("c", "a")],
          {"a": "Orion Zenith", "b": "Pinnacle Harbor", "c": "Dynamic Trading"})
    sentence = _circle_sentence(engine)

    assert sentence.endswith("Orion Zenith again.")
    assert "that last company" not in sentence
    # Named once at the start of the chain and once closing it, and nowhere
    # else: three companies, four links.
    assert sentence.count("Orion Zenith") == 3  # the lead-in, plus both ends
    assert sentence.count("Pinnacle Harbor") == 1


def test_an_amount_is_shown_as_it_stands_on_the_record():
    """Rounding could print an overpayment as two identical figures — "called
    2,000,000, received 2,000,000" — which reads as no discrepancy at all."""
    from vinzor.briefing import _money

    assert _money(2_500_000.75, "USD") == "USD 2,500,000.75"
    assert _money(2_500_000.0, "USD") == "USD 2,500,000"
    assert _money(0.5, "INR") == "INR 0.5"
    assert _money(None, "USD") == "an unstated amount"


# -- a group's shared text must be true of every item in it -----------------


def test_a_groups_shared_text_does_not_borrow_one_partys_detail(engine):
    """app.js renders only group.because/group.to_close_this for the whole
    group -- never an item's own headline or because -- so copying the
    group's shared text verbatim from its first item made that item's own
    detail stand in for every other item. Two sanctions matches on two
    different people, grouped under the same policy, must not leave either
    person's name in the text both items are explained by, even though each
    item's own "because" is still allowed -- and expected -- to name them.
    """
    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Anita Verma")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    screened(engine, "p2", "SANCTIONS", alert_id="alt_2")

    briefing = brief(engine, person="Meera Nair", today="2026-08-12")
    group = next(g for g in briefing.groups if "sanctions list" in g.title)
    assert len(group.items) == 2

    shared = " ".join(group.because) + " ".join(group.to_close_this)
    assert "Rohan Desai" not in shared, shared
    assert "Anita Verma" not in shared, shared

    # each item's own explanation still names the party it is actually about
    assert any("Rohan Desai" in " ".join(i.because) for i in group.items)
    assert any("Anita Verma" in " ".join(i.because) for i in group.items)


# -- the assistant's own report reads as English at n=1 ----------------------


def _quality(**overrides) -> Quality:
    base = dict(
        prepared=0, waiting=0, decided=0, accepted=0, edited=0, rejected=0,
        contradicted=0, spend_usd=0.0, budget_usd=50.0, input_tokens=0,
        output_tokens=0, models=(), regions=(), prompt_versions=(),
    )
    base.update(overrides)
    return Quality(**base)


def test_one_prepared_suggestion_not_yet_decided_reads_as_singular():
    """It used to read "1 suggestion has been prepared and none of them
    decided yet" -- "none of them" describing a single suggestion. At one
    suggestion it must read as "it", not "none of them"."""
    standing = report(_quality(prepared=1, decided=0)).standing
    assert standing == (
        "1 suggestion has been prepared and it has not been decided yet, "
        "so there is nothing to judge it by."
    )
    assert "none of them" not in standing


def test_one_decided_file_that_agreed_reads_as_the_one_file_not_all_1():
    """It used to read "On all 1 decided file, your officer's decision
    agreed..." -- "all 1" is not how a person counts to one."""
    standing = report(_quality(prepared=1, decided=1, contradicted=0)).standing
    assert standing == (
        "On the one decided file, your officer's decision agreed with what "
        "was suggested. No suggestion has been overruled."
    )
    assert "all 1" not in standing


def test_one_contradicted_file_is_read_back_as_singular():
    """The third branch hard-coded "Read those files" regardless of count,
    so a single contradicted file was still called "those files"."""
    standing = report(_quality(prepared=1, decided=1, contradicted=1)).standing
    assert standing == (
        "On 1 of 1 decided file, your officer decided the opposite of what "
        "was suggested. Read that file: either the suggestion was wrong, or "
        "the officer was, and you need to know which."
    )
    assert "those files" not in standing


def test_one_contradicted_file_among_several_decided_is_still_singular():
    """A fix that reads the plural off "decided" instead of "contradicted"
    passes the case above by coincidence -- decided and contradicted were
    both 1. With five decided and only one contradicted, "Read" must still
    be singular: it is the contradicted files being read, not the whole
    decided pool."""
    standing = report(_quality(prepared=5, decided=5, contradicted=1)).standing
    assert "Read that file:" in standing
    assert "Read those files:" not in standing


def test_several_contradicted_files_among_more_decided_reads_as_plural():
    standing = report(_quality(prepared=5, decided=5, contradicted=2)).standing
    assert "Read those files:" in standing
    assert "Read that file:" not in standing


# -- a watchlist this register cannot name ----------------------------------
# The policy that opens these Cases landed before any words were written for
# them, so they inherited the adverse-media writer's fallback: an officer
# reviewing a debarment-register match was told "press or public reporting
# was flagged during checks", which is not what happened.


def _unclassified(engine, count=1):
    from vinzor.model import EventType

    for i in range(count):
        engine.ingest(
            event_type=EventType.ENTITY_REGISTERED, subject=f"w{i}",
            occurred_at="2026-08-13",
            payload={"kind": "PERSON", "name": f"Investor {i}", "attributes": {}},
        )
        engine.ingest(
            event_type=EventType.SCREENING_COMPLETED, subject=f"w{i}",
            occurred_at="2026-08-13",
            payload={"matched": True, "list_type": "WATCHLIST", "alert_id": f"a{i}",
                     "basis": {"caption": f"Investor {i}", "matched_entity": f"Q{i}",
                               "score": 0.9, "datasets": ["debarment"],
                               "listed_properties": {}}},
        )
    return brief(engine, person="Meera Nair", today="2026-08-13").groups[0]


def test_an_unclassified_watchlist_match_is_not_called_adverse_media(engine):
    group = _unclassified(engine)
    said = " ".join(group.because) + " " + " ".join(group.to_close_this)

    assert "reporting" not in said, said
    assert "article" not in said, said
    assert "does not yet have a specific rule" in said


def test_an_unclassified_watchlist_match_says_what_is_not_known(engine):
    """It must not name the list as something it might not be."""
    group = _unclassified(engine)

    assert "not able to tell you what kind of list" in " ".join(group.because)
    assert "establish what the list is" in " ".join(group.to_close_this)


def test_the_unclassified_watchlist_title_agrees_at_one_and_at_many(engine):
    assert _unclassified(engine).title == (
        "1 party matched a watchlist we do not yet classify"
    )


def test_a_policy_with_no_title_of_its_own_still_reads_as_english():
    """The fallback was "1 item need your review" for any rule this file has
    not been taught to name -- the first sentence a reader would see."""
    from vinzor.briefing import _group_title

    assert _group_title("POL_NOT_NAMED_HERE", 1) == "1 item needs your review"
    assert _group_title("POL_NOT_NAMED_HERE", 4) == "4 items need your review"


# -- the queue must be reachable --------------------------------------------
# brief() rendered six items per group and then said "and 32 more of the same,
# shown when you open this". Opening the group showed the same six: the promise
# was kept nowhere in the codebase. On the seeded workspace that left 120 of 195
# open files unreachable while the screen told the officer otherwise -- the most
# damaging sentence on a screen whose whole claim is that it cannot drift from
# the regulator's file.


def _many(engine, count=9):
    for i in range(count):
        person(engine, f"m{i}", f"Investor {i}")
        screened(engine, f"m{i}", "SANCTIONS", alert_id=f"m_alt_{i}")
    return engine


def test_a_capped_group_says_how_much_it_is_showing(engine):
    _many(engine, 9)
    briefing = brief(engine, person="Meera Nair", today="2026-08-12", per_group=2)
    capped = [g for g in briefing.groups if g.total > 2]
    assert capped, "the fixture should produce at least one group over the cap"
    for group in capped:
        assert group.more == f"Showing {len(group.items)} of {group.total}."
        assert group.show_all == f"Show all {group.total}"


def test_asking_for_a_group_in_full_returns_every_file_in_it(engine):
    _many(engine, 9)
    briefing = brief(engine, person="Meera Nair", today="2026-08-12", per_group=3)
    group = max(briefing.groups, key=lambda g: g.total)
    assert len(group.items) == 3 and group.total == 9

    expanded = brief(engine, person="Meera Nair", today="2026-08-12",
                     per_group=3, expand=group.ref)
    opened = next(g for g in expanded.groups if g.ref == group.ref)
    assert len(opened.items) == opened.total == 9


def test_the_showing_line_disappears_exactly_when_it_stops_being_true(engine):
    _many(engine, 9)
    expanded = brief(engine, person="Meera Nair", today="2026-08-12",
                     per_group=3, expand="POL_SANCTIONS_HIT")
    opened = next(g for g in expanded.groups if g.ref == "POL_SANCTIONS_HIT")
    assert opened.more == ""
    assert opened.show_all == ""


def test_expanding_one_group_does_not_expand_the_others(engine):
    """A queue of two hundred files must not arrive as one page because the
    officer opened one group of eight."""
    _many(engine, 9)
    # Five payment files, so there is a second group for the assertion below
    # to find unexpanded. These were overpayments until 21 August 2026; a
    # third-party payer is what opens a file now.
    for pid in [f"pay_{i}" for i in range(5)]:
        paid(engine, "m0", payment_id=pid, payer="somebody_else",
             currency="USD", expected_currency="USD",
             amount=2_000.0, called_amount=1_000.0)

    expanded = brief(engine, person="Meera Nair", today="2026-08-12",
                     per_group=2, expand="POL_SANCTIONS_HIT")
    for group in expanded.groups:
        if group.ref == "POL_SANCTIONS_HIT":
            assert len(group.items) == group.total
        else:
            assert len(group.items) <= 2, f"{group.ref} was expanded too"


def test_an_unknown_group_reference_widens_nothing(engine):
    """The value arrives from a query string. An unrecognised one must match
    no bucket rather than open every one."""
    _many(engine, 9)
    briefing = brief(engine, person="Meera Nair", today="2026-08-12",
                     per_group=3, expand="../../etc/passwd")
    for group in briefing.groups:
        assert len(group.items) <= 3


# -- one file, in full -------------------------------------------------------


def _drafted_case(engine):
    from test_assist import drafter_of, register, reply, screen
    from vinzor.assist import prepare_drafts

    register(engine, "cf1", "Vladimir Petrov", dob="1984-08-19", nationality="IN")
    screen(engine, "cf1", caption="Vladimir Petrov", birthDate="1961-03-03",
           nationality="RU")
    drafter, _ = drafter_of(reply())
    prepare_drafts(engine, prepared_at="2026-08-12", drafter=drafter)
    return next(c for c in engine.queue() if c.draft)


def test_the_case_page_says_nothing_technical(engine):
    """A new surface is a new way for implementation vocabulary to escape, and
    this one renders Evidence -- whose summaries are internal record text like
    "SANCTIONS match for X" and "A suggestion was prepared: LIKELY_NOT_THE_SAME".
    """
    from vinzor.briefing import case_file

    case = _drafted_case(engine)
    page = case_file(engine, case.case_id)

    offences = []
    for path, text in _strings(page, "case_file"):
        for pattern, what in JARGON:
            match = re.search(pattern, text)
            if match:
                offences.append(f"{path}: {what} ({match.group(0)!r}) in {text[:80]!r}")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


def test_the_case_page_carries_the_whole_file(engine):
    from vinzor.briefing import case_file

    case = _drafted_case(engine)
    page = case_file(engine, case.case_id)

    assert page.who == "Vladimir Petrov"
    assert page.headline
    assert page.because and page.to_close_this
    assert page.rules, "a file must always be able to say which rule applies"
    assert page.side_by_side, "a name check should show the computed comparison"
    assert page.suggestion is not None
    assert page.timeline, "the chronology is the point of this page"
    assert page.choices, "an open file offers a decision"
    assert page.settled == ""


def test_the_timeline_is_in_the_order_things_happened(engine):
    from vinzor.briefing import case_file

    case = _drafted_case(engine)
    page = case_file(engine, case.case_id)

    kinds = [m.tone for m in page.timeline]
    assert kinds[0] == "rule", "a file opens because a rule fired"
    assert "suggestion" in kinds
    assert len(page.timeline) == len(case.evidence)


def test_a_settled_file_says_who_settled_it_and_why(engine):
    from conftest import officer
    from vinzor.briefing import case_file
    from vinzor.model import Outcome, Role

    case = _drafted_case(engine)
    officer(engine, "Meera Nair", Role.AML_OFFICER)
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  rationale="Dates of birth 23 years apart.", decided_at="2026-08-13")

    page = case_file(engine, case.case_id)
    assert "Meera Nair settled this" in page.settled
    assert "23 years apart" in page.settled
    assert page.choices == (), "a settled file offers no further decision"
    assert any(m.tone == "decision" for m in page.timeline)


def test_an_unknown_file_is_refused_rather_than_invented(engine):
    from vinzor.briefing import case_file
    from vinzor.cases import UnknownCase

    with pytest.raises(UnknownCase):
        case_file(engine, "case_does_not_exist")


# -- where you stand with the regulator --------------------------------------


def _licensed(engine):
    from vinzor.model import EventType

    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="fme",
                  occurred_at="2025-01-10",
                  payload={"kind": "COMPANY", "name": "Acme FME"})
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="fme",
                  occurred_at="2025-01-10",
                  payload={"category": "REGISTERED_NON_RETAIL",
                           "number": "IFSCA/FME/II/2024-25/084"})
    return engine


def test_the_regulatory_page_says_nothing_technical(engine):
    """It renders enum values from four modules. The first cut leaked
    "Ground.SCOPE" and "Level.FULL" straight onto the page, because
    enforcement.py's enums did not use the project's StrEnum base and str()
    on them returns the qualified name.
    """
    from vinzor.briefing import regulatory

    _licensed(engine)
    page = regulatory(engine, today="2026-08-14")

    offences = []
    for path, text in _strings(page, "regulatory"):
        for pattern, what in JARGON:
            match = re.search(pattern, text)
            if match:
                offences.append(f"{path}: {what} ({match.group(0)!r}) in {text[:80]!r}")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


def test_the_regulatory_page_reports_the_registration_and_its_gaps(engine):
    from vinzor.briefing import regulatory

    _licensed(engine)
    page = regulatory(engine, today="2026-08-14")

    assert "Registered (non-retail)" in page.licence_summary
    assert "IFSCA/FME/II/2024-25/084" in page.licence_summary
    assert page.unlicensed == ""
    assert page.posts, "a licence requires posts; they must be listed"
    assert all(p.holder == "Nobody holds this post" for p in page.posts)
    assert all(p.tone == "stop" for p in page.posts)


def test_an_entity_with_no_licence_is_told_so_rather_than_shown_blanks(engine):
    from vinzor.briefing import regulatory

    page = regulatory(engine, today="2026-08-14")
    assert page.unlicensed
    assert page.licence_summary == ""
    assert page.owed == () and page.owed_summary == ""


def test_the_register_never_overstates_what_a_person_has_checked(engine):
    """Every clause is machine-extracted today. The page must say so."""
    from vinzor.briefing import regulatory

    _licensed(engine)
    page = regulatory(engine, today="2026-08-14")

    assert page.clauses
    assert all(c.checked == "Not yet checked by a person" for c in page.clauses)
    assert page.register_caveat, "an unverified register must carry its caveat"
    assert "0 confirmed by a person" in page.register_summary


def test_the_page_is_silent_about_amendments_only_when_there_are_none(engine):
    """It used to warn that a circular of 3 August 2026 was not incorporated.
    The register now cites the master that already contains it, so the warning
    is gone -- and must come back the moment anything is outstanding.
    """
    from vinzor.briefing import regulatory

    _licensed(engine)
    assert regulatory(engine, today="2026-08-14").amendment == ""

    from vinzor import citations

    outstanding = ({"doc_id": "IFSCA-AML-2022", "circular_date": "2026-09-01",
                    "summary": "A later circular nobody has folded in.",
                    "affects": ("5.9",), "incorporated": False},)
    original = citations.KNOWN_PENDING_AMENDMENTS
    citations.KNOWN_PENDING_AMENDMENTS = outstanding
    try:
        page = regulatory(engine, today="2026-09-14")
        assert "has not been incorporated here yet" in page.amendment
        assert "A later circular nobody has folded in." in page.amendment
    finally:
        citations.KNOWN_PENDING_AMENDMENTS = original


def test_the_scorecard_never_counts_partial_coverage_as_full(engine):
    from vinzor.briefing import regulatory

    _licensed(engine)
    page = regulatory(engine, today="2026-08-14")

    covers = {g.ground: g.coverage for g in page.grounds}
    # Answering the regulator moved from "Not covered" to "Partly" when
    # letters became something the product tracks. Partly, not covered:
    # somebody still has to put the letter in, and a firm that has stopped
    # opening its post is not a firm this reaches.
    assert covers["Answering the regulator"] == "Partly covered"
    assert covers["People and premises"] == "Partly covered"
    assert covers["Activities beyond the licence"] == "Covered"
    # The point of the test: partial coverage must never render as full.
    # Nothing reads "Not covered" any more -- every ground now has
    # something built against it -- which makes this guard more important
    # rather than less, because a page of "partly" is one careless change
    # away from a page of green ticks.
    # The guard is that a partial capability never renders as a full one.
    # Nothing reads "Not covered" any more, since every ground has
    # something built against it -- which makes this more important rather
    # than less, because a page of "partly" is one careless change away
    # from a page of green ticks.
    assert covers["Capital and net worth"] == "Partly covered"
    assert covers["What was disclosed"] == "Partly covered"
    assert covers["Filings and returns"] == "Partly covered"
    assert set(covers.values()) <= {"Covered", "Partly covered",
                                    "Not covered"}


# -- everything about one party ---------------------------------------------


def test_the_party_page_says_nothing_technical(busy):
    """The widest sweep in the file: this page renders raw attribute keys,
    ISO codes, 0/1 flags, four enums and every event type there is.
    """
    from vinzor.briefing import party

    offences = []
    for entity_id in ("p1", "c1", "t1", "c4"):
        page = party(busy, entity_id)
        for path, text in _strings(page, f"party[{entity_id}]"):
            for pattern, what in JARGON:
                match = re.search(pattern, text)
                if match:
                    offences.append(
                        f"{path}: {what} ({match.group(0)!r}) in {text[:80]!r}")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


def test_the_party_sweep_runs_against_the_real_dataset():
    """The fixture registers plain entities. The corpus has shell companies,
    passports, ISO codes and flags -- the fields most likely to leak.
    """
    from vinzor.briefing import party
    from vinzor.seed import DEFAULT_DATASET, seed

    if not DEFAULT_DATASET.exists():
        pytest.skip("synthetic dataset not present")

    engine = seed()
    subjects = sorted({c.subject for c in engine.state.casebook.cases.values()})
    offences = []
    for entity_id in subjects[:40]:
        for path, text in _strings(party(engine, entity_id), "party"):
            for pattern, what in JARGON:
                match = re.search(pattern, text)
                if match:
                    offences.append(
                        f"{entity_id} {path}: {what} ({match.group(0)!r}) "
                        f"in {text[:80]!r}")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


def test_a_party_page_gathers_what_was_scattered_across_files(busy):
    from vinzor.briefing import party

    page = party(busy, "p1")
    assert page.name == "Rohan Desai"
    assert page.kind == "Person"
    assert page.open_files, "this party has open files; none were listed"
    assert page.timeline, "this party has recorded events; the page shows none"
    assert page.movements, "this party has payments; none were listed"


def test_the_chronology_runs_oldest_first_not_in_recorded_order(busy):
    """An ownership link declared in 2018 is recorded after a registration
    dated today. Printing recorded order puts 2026 above 2018 and reads as a
    defect, so a party's chronology sorts by when things happened.
    """
    from vinzor.briefing import party

    page = party(busy, "c1")
    order = [m.when for m in page.timeline]
    assert order == sorted(order, key=_as_date), f"out of order: {order}"


def _as_date(shown: str):
    from vinzor.briefing import MONTHS

    day, month, year = shown.split(" ")
    return (int(year), MONTHS.index(month), int(day))


def test_totals_are_never_added_across_currencies(engine):
    """A single figure would need a rate this system does not hold. An officer
    might repeat that number to a regulator.
    """
    from vinzor.briefing import party

    person(engine, "p1", "Rohan Desai")
    paid(engine, "p1", payment_id="pay_1", currency="USD",
         expected_currency="USD", amount=1000.0, called_amount=1000.0)
    paid(engine, "p1", payment_id="pay_2", currency="JPY",
         expected_currency="JPY", amount=2000.0, called_amount=2000.0)

    summary = party(engine, "p1").money_summary
    assert "JPY 2,000" in summary and "USD 1,000" in summary
    assert "3,000" not in summary, f"currencies were added together: {summary}"


def test_a_shell_company_is_flagged_not_merely_recorded(engine):
    from vinzor.briefing import party

    from vinzor.model import EntityKind

    register(engine, "c1", EntityKind.COMPANY, "Orion Zenith Enterprises",
             is_shell="1", jurisdiction="KY")
    traits = {t.label: t for t in party(engine, "c1").traits}

    assert traits["Registered in"].value == "Cayman Islands", "ISO code not translated"
    assert traits["Shell company"].tone == "today", "a shell company reads as ordinary"
    assert "1" != traits["Shell company"].value


def test_the_page_never_claims_a_detail_was_verified(engine):
    from vinzor.briefing import party

    from vinzor.model import EntityKind

    register(engine, "p1", EntityKind.PERSON, "Rohan Desai", nationality="SG")
    page = party(engine, "p1")
    assert page.traits_caveat, "declared details are shown with no caveat"
    assert "checked against an independent source" in page.traits_caveat


def test_ownership_is_shown_in_both_directions(engine):
    from vinzor.briefing import party

    company(engine, "c1", "Orion Zenith Enterprises")
    company(engine, "c2", "Meridian Trading")
    company(engine, "c3", "Apex Global Partners")
    owns(engine, "c2", "c1", 30)   # c2 holds c1
    owns(engine, "c1", "c3", 40)   # c1 holds c3

    ties = {t.direction: t for t in party(engine, "c1").ties}
    assert ties["Held by"].who == "Meridian Trading"
    assert ties["Holds"].who == "Apex Global Partners"
    assert ties["Held by"].share == "30%" and ties["Holds"].share == "40%"


def test_a_party_nobody_has_registered_says_so_rather_than_showing_blanks(engine):
    from vinzor.briefing import party

    page = party(engine, "per_nobody")
    assert page.unknown, "an unknown party renders as an empty page"
    assert page.traits == () and page.ties == () and page.movements == ()


def test_files_on_one_party_can_be_told_apart(busy):
    """Six payment queries all labelled "Payment query" are six identical
    rows. The reference has to number them.
    """
    from vinzor.briefing import party

    page = party(busy, "p1")
    references = [f.reference for f in page.open_files]
    assert len(references) == len(set(references)), f"duplicates: {references}"


def test_a_file_knows_which_party_it_is_about(busy):
    """Without this the case page cannot offer a way through to the party."""
    from vinzor.briefing import case_file

    case = next(c for c in busy.state.casebook.cases.values() if c.subject == "p1")
    assert case_file(busy, case.case_id).subject == "p1"


def test_a_case_with_no_party_behind_it_is_never_titled_with_a_record_id(engine):
    """A file opened against a payment record has a payment id for a subject
    and no entity will ever be registered for it. The queue calls that sender
    "An unidentified sender"; this page must agree with the queue the reader
    clicked through from, and must never print the id -- which tells them
    nothing and looks like a name.

    Built here rather than read off the seeded dataset. The dataset's 29
    unattributable files came from the rule that fired on a payment with no
    sender recorded, and that rule was removed on 21 August 2026. The
    situation itself has not gone: an imported statement that names a
    remitter but no beneficiary still files the row against an unregistered
    id, and the third-party rule still opens on it.
    """
    from vinzor.briefing import UNKNOWN_SENDER, party
    from vinzor.model import EventType

    engine.ingest(
        event_type=EventType.PAYMENT_RECEIVED, subject="unk_pay_9",
        occurred_at="2026-08-02",
        payload={"payment_id": "pay_9", "payment_ref": "TX-9",
                 "amount": 40_000.0, "called_amount": 40_000.0,
                 "currency": "USD", "expected_currency": "USD",
                 "payer": "somebody_else"})

    orphans = [
        case.subject for case in engine.state.casebook.cases.values()
        if case.subject not in engine.state.graph.entities
    ]
    assert orphans == ["unk_pay_9"]

    page = party(engine, orphans[0])
    assert page.name == UNKNOWN_SENDER
    assert orphans[0] not in page.name and orphans[0] not in page.heading
    assert page.unknown, "an unregistered subject is shown with no explanation"
    assert page.open_files or page.settled_files, "its files were dropped"


def test_no_user_facing_sentence_uses_a_double_hyphen_for_a_dash():
    """The source writes "--" in comments by convention. A reader is shown
    the string, not the convention, and "Yes -- no operations" reached a
    screen once already.
    """
    import re as _re
    from pathlib import Path

    source = Path(briefing.__file__).read_text(encoding="utf-8")
    # Quoted strings only, and only where a dash sits between words.
    offenders = _re.findall(r'"[^"\n]*\b[a-z] -- [a-z][^"\n]*"', source)
    assert not offenders, "double hyphens in text a person reads:\n  " + \
        "\n  ".join(offenders)


# -- who has been checked against the watchlists ----------------------------


def _committed(engine, entity_id, name):
    from vinzor.model import EventType

    person(engine, entity_id, name)
    engine.ingest(event_type=EventType.COMMITMENT_MADE, subject=entity_id,
                  occurred_at="2026-01-05",
                  payload={"investor": entity_id, "fund": "fnd_1",
                           "amount": 1_000_000.0, "currency": "USD",
                           "commitment_id": "ccm_" + entity_id})


def _checked(engine, entity_id, when, matched=False):
    from vinzor.model import EventType

    payload = {"matched": matched}
    if matched:
        payload.update({"list_type": "SANCTIONS", "rule": "test",
                        "alert_id": "alt_" + entity_id})
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject=entity_id,
                  occurred_at=when, actor="system", payload=payload)


def test_the_screening_page_says_nothing_technical(engine):
    from vinzor.briefing import screening

    _committed(engine, "p1", "Rohan Desai")
    _committed(engine, "p2", "Anita Verma")
    _checked(engine, "p1", "2026-06-01")
    _checked(engine, "p2", "2026-06-02", matched=True)

    offences = []
    for path, text in _strings(screening(engine, "2026-08-14"), "screening"):
        for pattern, what in JARGON:
            match = re.search(pattern, text)
            if match:
                offences.append(f"{path}: {what} ({match.group(0)!r}) in {text[:80]!r}")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)


def test_a_clean_check_is_visible_somewhere_at_last(engine):
    """The whole reason this page exists. A match opens a Case and reaches the
    officer; a clean result opens nothing, so until now it appeared on no
    screen at all -- yet it is the only evidence the check was performed.
    """
    from vinzor.briefing import NOTHING_FOUND, screening

    _committed(engine, "p1", "Rohan Desai")
    _checked(engine, "p1", "2026-06-01")

    page = screening(engine, "2026-08-14")
    clean = [c for c in page.checked if c.result == NOTHING_FOUND]
    assert clean, "a clean check is still invisible"
    assert clean[0].who == "Rohan Desai"
    assert clean[0].when == "1 June 2026", "the date of the check is the proof"


def test_a_customer_nobody_checked_is_named_not_merely_counted(engine):
    from vinzor.briefing import NO_CHECK, screening

    _committed(engine, "p1", "Rohan Desai")
    _committed(engine, "p2", "Anita Verma")
    _checked(engine, "p1", "2026-06-01")

    page = screening(engine, "2026-08-14")
    assert [c.who for c in page.unchecked] == ["Anita Verma"]
    assert page.unchecked[0].result == NO_CHECK
    assert page.unchecked[0].tone == "stop"
    assert "1 has no record of a check" in page.coverage_summary


def test_the_page_never_invents_a_re_screening_deadline(engine):
    """Clause 5.9 requires screening to be ongoing and says nothing about how
    often. Calling a party "overdue" would be inventing an obligation the
    regulator has not imposed, which is the one thing this system must never
    do to a compliance officer.
    """
    from vinzor.briefing import screening

    _committed(engine, "p1", "Rohan Desai")
    _checked(engine, "p1", "2019-01-01")   # ancient, by any firm's policy

    page = screening(engine, "2026-08-14")
    words = " ".join(t for _, t in _strings(page, "screening")).lower()
    for invented in ("overdue", "out of date", "expired", "stale",
                     "must be re-screened", "due for"):
        assert invented not in words, f"invented an obligation: {invented!r}"
    assert "does not say how often" in page.rule_caveat
    assert page.checked[0].tone != "stop", "an old check was judged, not reported"


def test_checks_are_ordered_by_when_they_happened_not_by_how_they_read(engine):
    """"10 June 2026" sorts before "13 August 2026" as text. Ordering the
    shown date rather than the recorded one looks convincing and is wrong.
    """
    from vinzor.briefing import screening

    for entity_id, name, when in (
        ("p1", "First Checked", "2026-04-07"),
        ("p2", "Second Checked", "2026-06-10"),
        ("p3", "Third Checked", "2026-08-13"),
    ):
        _committed(engine, entity_id, name)
        _checked(engine, entity_id, when)

    order = [c.who for c in screening(engine, "2026-08-14").checked]
    assert order == ["First Checked", "Second Checked", "Third Checked"], order


def test_re_screening_reports_the_latest_standing_not_every_row(engine):
    from vinzor.briefing import NOTHING_FOUND, screening

    _committed(engine, "p1", "Rohan Desai")
    _checked(engine, "p1", "2026-01-01")
    _checked(engine, "p1", "2026-07-01")

    page = screening(engine, "2026-08-14")
    assert len(page.checked) == 1, "one party, one row"
    assert page.checked[0].when == "1 July 2026", "not the most recent check"
    assert page.checked[0].result == NOTHING_FOUND


def test_a_party_who_never_committed_is_not_counted_as_a_customer(engine):
    """Clause 5.9 names customers. Counting intermediate holding companies
    would overstate the gap and understate how much of it is a customer.
    """
    from vinzor.briefing import screening

    _committed(engine, "p1", "Rohan Desai")
    company(engine, "c9", "A Holding Company In A Chain")

    page = screening(engine, "2026-08-14")
    named = [c.who for c in page.unchecked + page.checked]
    assert "A Holding Company In A Chain" not in named
    assert page.scope_note, "the narrowed denominator is not explained"


def test_full_coverage_reads_as_an_achievement_not_a_silence(engine):
    from vinzor.briefing import screening

    _committed(engine, "p1", "Rohan Desai")
    _checked(engine, "p1", "2026-06-01")

    page = screening(engine, "2026-08-14")
    assert page.unchecked == ()
    assert page.coverage_tone == "settled"
    assert "All 1 party" in page.coverage_summary


def test_parties_sharing_a_name_are_told_apart_by_what_is_on_record(engine):
    """Two different people really are called Priya Hussain, and five distinct
    trusts really are called Sovereign Succession Trust. Identical rows are
    truthful and unusable: the failure mode is acting on the wrong party.
    """
    from vinzor.briefing import qualified_name, shared_names
    from vinzor.model import EntityKind

    register(engine, "p1", EntityKind.PERSON, "Priya Hussain", dob="1972-11-06")
    register(engine, "p2", EntityKind.PERSON, "Priya Hussain", dob="2012-07-10")
    register(engine, "t1", EntityKind.TRUST, "Crest Settlor Trust",
             jurisdiction="GG")
    register(engine, "t2", EntityKind.TRUST, "Crest Settlor Trust",
             jurisdiction="AE")
    register(engine, "c1", EntityKind.COMPANY, "A Name Nobody Else Has")

    graph = engine.state.graph
    shared = shared_names(graph)
    named = {i: qualified_name(graph, i, shared) for i in ("p1", "p2", "t1", "t2", "c1")}

    assert named["p1"] == "Priya Hussain (born 6 November 1972)"
    assert named["p2"] == "Priya Hussain (born 10 July 2012)"
    assert named["t1"] == "Crest Settlor Trust (Guernsey)"
    assert named["t2"] == "Crest Settlor Trust (United Arab Emirates)"
    assert len(set(named.values())) == 5, "two rows are still identical"

    # A name nobody shares is never decorated: a qualifier on a unique name is
    # noise, and noise on every row is how a reader stops reading them.
    assert named["c1"] == "A Name Nobody Else Has"


def test_nothing_is_invented_to_break_a_tie(engine):
    """A party with nothing distinguishing on file stays ambiguous, because
    that is the true answer. Inventing a qualifier would be worse than the
    ambiguity it hides.
    """
    from vinzor.briefing import qualified_name, shared_names
    from vinzor.model import EntityKind

    register(engine, "t1", EntityKind.TRUST, "A Trust")
    register(engine, "t2", EntityKind.TRUST, "A Trust")

    graph = engine.state.graph
    shared = shared_names(graph)
    assert qualified_name(graph, "t1", shared) == "A Trust"
    assert qualified_name(graph, "t2", shared) == "A Trust"


def test_every_clause_can_be_looked_up_in_the_source(engine):
    """A citation a reader cannot turn to is one they must take on trust.
    Seventeen of the twenty-one carried no page number until the extracts were
    checked against the published PDFs.
    """
    from vinzor.citations import CLAUSES

    missing = [cid for cid, c in CLAUSES.items() if c.page is None]
    assert not missing, f"no page number to look up: {missing}"


def test_a_machine_check_is_never_reported_as_a_person_checking(engine):
    """The two claims are different and the page must not blur them. A string
    comparison proves the words were copied faithfully. It proves nothing
    about whether the right clause was chosen, or what it means.
    """
    from vinzor.briefing import regulatory
    from vinzor.citations import CLAUSES
    from vinzor.model import EventType

    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="fme",
                  occurred_at="2025-01-10",
                  payload={"kind": "COMPANY", "name": "Acme FME"})
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="fme",
                  occurred_at="2025-01-10",
                  payload={"category": "REGISTERED_NON_RETAIL",
                           "number": "IFSCA/FME/II/2024-25/084"})

    assert all(c.source_checked for c in CLAUSES.values()), "no source check recorded"
    assert not any(c.verified for c in CLAUSES.values()), \
        "a machine set verified=True; only a qualified person may"

    page = regulatory(engine, today="2026-08-14")
    assert "0 confirmed by a person" in page.register_summary
    assert page.source_check, "the source check is not shown at all"
    assert "does not show that the right clause was picked" in page.source_check
    assert page.register_caveat, "the caveat was dropped once a machine checked"
    assert all(c.checked == "Not yet checked by a person" for c in page.clauses)
    assert all(c.where.startswith("Page ") for c in page.clauses)


# -- the first line of the screen --------------------------------------------


@pytest.mark.parametrize("hour,words", [
    (0, "Good morning"), (6, "Good morning"), (11, "Good morning"),
    (12, "Good afternoon"), (15, "Good afternoon"), (16, "Good afternoon"),
    (17, "Good evening"), (21, "Good evening"), (23, "Good evening"),
])
def test_the_greeting_follows_the_clock(busy, hour, words):
    """It said "Good morning" at every hour of the day. A small lie, on the
    first line of a screen whose whole argument is that it does not tell them.
    """
    greeting = brief(busy, person="Meera Nair", today="2026-08-12",
                     hour=hour).greeting
    assert greeting.startswith(words + ", Meera Nair.")


def test_the_hour_comes_from_the_boundary_like_the_date(busy):
    """The core reads no clock of its own; both travel in from the caller."""
    import inspect

    from vinzor.briefing import brief as build

    parameters = inspect.signature(build).parameters
    assert parameters["hour"].default is None
    assert parameters["today"].default is None


def test_the_greeting_still_names_the_day(busy):
    for hour in (9, 14, 20):
        assert "12 August 2026" in brief(busy, person="Meera Nair",
                                         today="2026-08-12", hour=hour).greeting


# -- how often an officer decided against the assistant ----------------------
#
# The quality page built its numerator by tallying CASE_DECIDED *events* and
# its denominator from a set of *case ids*, then divided one by the other. A
# file can carry two decisions: escalate, then settle -- which is the
# ordinary AML path, one of the three buttons on every file, and forced for
# every politically exposed person. So the page read "Decided against the
# suggestion: 2 of 1", and a reader with any arithmetic stopped believing
# the rest of it.
#
# An escalation is also not a verdict on the draft. ``cases.py`` says in as
# many words that it is "a handover, not an answer", and the file stays open.


def _one_drafted_file(engine):
    from vinzor.model import EntityKind, EventType, Role

    engine.enroll(name="Meera", role=Role.AML_OFFICER, enrolled_at="2026-08-20")
    engine.enroll(name="Rohan", role=Role.SENIOR_MGMT, enrolled_at="2026-08-20")
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="p1",
                  occurred_at="2026-08-20", actor="system",
                  payload={"kind": EntityKind.PERSON.value, "name": "A Party",
                           "attributes": {}})
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject="p1",
                  occurred_at="2026-08-20", actor="system",
                  payload={"matched": True, "list_type": "SANCTIONS",
                           "list_types": ["SANCTIONS"], "rule": "m",
                           "alert_id": "a", "basis": {}})
    case = engine.queue()[0]
    engine.ingest(event_type=EventType.DRAFT_PREPARED, subject="p1",
                  occurred_at="2026-08-20", actor="system",
                  payload={"case_id": case.case_id,
                           "recommendation": "LIKELY_THE_SAME",
                           "reasoning": "x", "suggested_wording": "y",
                           "cost_usd": 0.01, "input_tokens": 10,
                           "output_tokens": 10, "model": "m",
                           "region": "southindia", "prompt_version": "v"})
    return case


def test_a_file_escalated_then_settled_counts_once(engine):
    from vinzor.model import DraftUse, Outcome, Role
    from vinzor.quality import measure

    case = _one_drafted_file(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera", role=Role.AML_OFFICER, decided_at="2026-08-20",
                  rationale="Passing this up; I cannot clear a sanctions match.",
                  draft_use=DraftUse.REJECTED)
    engine.decide(case_id=case.case_id, outcome=Outcome.REJECT, actor="Rohan",
                  role=Role.SENIOR_MGMT, decided_at="2026-08-20",
                  rationale="Name, birth year and passport all match the "
                            "designation.",
                  draft_use=DraftUse.REJECTED)

    seen = measure(engine)
    assert seen.decided == 1
    assert seen.rejected == 1
    assert seen.accepted + seen.edited + seen.rejected <= seen.decided


def test_a_handover_on_its_own_is_not_a_verdict_on_the_draft(engine):
    """The file is still open and nobody has answered the question the
    assistant was asked. Counting it as disagreement invents an opinion."""
    from vinzor.model import DraftUse, Outcome, Role
    from vinzor.quality import measure

    case = _one_drafted_file(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE,
                  actor="Meera", role=Role.AML_OFFICER, decided_at="2026-08-20",
                  rationale="Passing this up; I cannot clear a sanctions match.",
                  draft_use=DraftUse.REJECTED)

    seen = measure(engine)
    assert seen.decided == 0
    assert seen.rejected == 0
    assert seen.waiting == 1


def test_an_ordinary_settled_file_still_counts(engine):
    from vinzor.model import DraftUse, Outcome, Role
    from vinzor.quality import measure

    case = _one_drafted_file(engine)
    engine.decide(case_id=case.case_id, outcome=Outcome.REJECT, actor="Meera",
                  role=Role.AML_OFFICER, decided_at="2026-08-20",
                  rationale="Name, birth year and passport all match the "
                            "designation.",
                  draft_use=DraftUse.ACCEPTED)

    seen = measure(engine)
    assert seen.decided == 1
    assert seen.accepted == 1
