"""The deterministic half of assisted review.

No model, no network. These are the facts a draft is allowed to rest on, so
they must be right, and they must be the same every time.
"""

from __future__ import annotations

import pytest

from vinzor.compare import (
    CLOSE_YEARS,
    Comparison,
    Verdict,
    compare,
    compare_dates,
    compare_exact,
    compare_names,
    comparison_for,
)


def listed(**kwargs):
    base = {"caption": "Vladimir Petrov", "matched_entity": "Q7747",
            "score": 0.92, "datasets": ["us_ofac_sdn"], "listed_properties": {}}
    props = kwargs.pop("properties", None)
    base.update(kwargs)
    if props is not None:
        base["listed_properties"] = props
    return base


# -- names -----------------------------------------------------------------


def test_the_same_name_written_the_same_way():
    assert compare_names("Vladimir Petrov", "Vladimir Petrov").verdict is Verdict.IDENTICAL


def test_word_order_does_not_make_a_different_person():
    """Family-name-first is a convention, not a difference. A screening system
    that misses this is useless across most of Asia."""
    result = compare_names("Wei Zhang", "Zhang Wei")
    assert result.verdict is Verdict.EQUIVALENT
    assert "different order" in result.note


def test_accents_and_punctuation_are_not_differences():
    assert compare_names("José O'Brien-Smith", "Jose OBrien Smith").verdict is (
        Verdict.EQUIVALENT
    )


def test_a_shared_surname_is_partial_not_a_match():
    result = compare_names("Anita Verma", "Rohan Verma")
    assert result.verdict is Verdict.PARTIAL
    assert result.note == (
        "both names include Verma; ours also has Anita; "
        "the list entry also has Rohan. Only part of the name matches"
    )
    # A surname alone out of two parts: half, and said so in words as well as
    # recorded as a number. Still a match -- nothing here closes a question.
    assert result.strength == 0.5


def test_how_much_of_the_name_matches_is_recorded_but_closes_nothing():
    """On 8,000 pairs judged by OpenSanctions analysts, demanding more than
    half the name would have cut false positives fourfold and closed 264 pairs
    the analysts judged to be the same person. A missed party is not a smaller
    version of a wasted hour, so the number orders the work instead.
    """
    weak = compare_names("Anita Verma", "Rohan Verma")
    strong = compare_names("Vladimir Petrov Ivanovich", "Vladimir Petrov Sergeyevich")

    assert weak.strength < strong.strength
    assert weak.verdict is strong.verdict is Verdict.PARTIAL
    assert "Only part" in weak.note and "Most of the name" in strong.note


def test_the_note_reads_as_a_sentence_about_names_not_as_set_arithmetic():
    """It said "shares zhang; differs on lei, li" once, and made the officer
    reconstruct the comparison themselves."""
    result = compare_names("Zhang Li", "Lei ZHANG")
    assert "differs on" not in result.note
    assert result.note.startswith("both names include Zhang")


def test_unrelated_names_are_different():
    assert compare_names("Anita Verma", "Karl Schmidt").verdict is Verdict.DIFFERENT


def test_a_missing_name_is_unknown_not_different():
    """Absence of data is not evidence of difference. Watchlists are sparse."""
    assert compare_names("Anita Verma", "").verdict is Verdict.UNKNOWN


# -- dates -----------------------------------------------------------------


def test_the_same_date_of_birth():
    assert compare_dates("1984-08-19", "1984-08-19").verdict is Verdict.IDENTICAL


def test_a_year_apart_reads_as_a_recording_error():
    result = compare_dates("1984-08-19", "1985-08-19")
    assert result.verdict is Verdict.PARTIAL
    assert "recording error" in result.note
    assert CLOSE_YEARS == 3


def test_decades_apart_is_a_real_difference():
    result = compare_dates("1984-08-19", "1961-03-03")
    assert result.verdict is Verdict.DIFFERENT
    assert "23 years apart" in result.note
    assert result.decisive


def test_a_transposed_day_and_month_is_the_same_date():
    result = compare_dates("1984-08-05", "1984-05-08")
    assert result.verdict is Verdict.EQUIVALENT
    assert "transposed" in result.note


def test_a_year_only_watchlist_date_still_compares():
    """Sanctions lists frequently carry a birth year and nothing more."""
    assert compare_dates("1984-08-19", "1984").verdict is Verdict.PARTIAL


def test_an_unreadable_date_is_unknown_not_a_crash():
    assert compare_dates("1984-08-19", "circa 1960").verdict is Verdict.UNKNOWN


# -- the whole comparison --------------------------------------------------


def test_a_convincing_false_positive():
    """Same name, wrong person — the 95% case an officer sees all day."""
    result = compare(
        subject="p1", our_name="Vladimir Petrov",
        our_attributes={"dob": "1984-08-19", "nationality": "IN",
                        "id_document_number": "K4471829"},
        listed=listed(properties={"birthDate": ["1961-03-03"],
                                  "nationality": ["ru"],
                                  "passportNumber": ["7712345"]}),
    )
    assert result.field("name").verdict is Verdict.IDENTICAL
    assert {f.field for f in result.decisive_differences} == {
        "date of birth", "nationality", "identity document"
    }


def test_a_real_match_has_nothing_decisive_against_it():
    result = compare(
        subject="p1", our_name="Vladimir Petrov",
        our_attributes={"dob": "1961-03-03", "nationality": "RU",
                        "id_document_number": "7712345"},
        listed=listed(properties={"birthDate": ["1961-03-03"],
                                  "nationality": ["RU"],
                                  "passportNumber": ["7712345"]}),
    )
    assert result.decisive_differences == ()
    assert all(f.verdict is Verdict.IDENTICAL for f in result.comparable)


def test_a_watchlist_entry_with_only_a_name_compares_only_the_name():
    result = compare(
        subject="p1", our_name="Vladimir Petrov",
        our_attributes={"dob": "1984-08-19", "nationality": "IN"},
        listed=listed(properties={}),
    )
    assert [f.field for f in result.comparable] == ["name"]
    assert result.decisive_differences == ()


def test_an_alias_matching_our_investor_is_surfaced():
    """'The listed party also goes by your investor's name' changes the read."""
    result = compare(
        subject="p1", our_name="Vladimir Petrov",
        our_attributes={},
        listed=listed(caption="V. A. Petrov",
                      properties={"alias": ["Vladimir Petrov", "Volodya P"]}),
    )
    aliases = result.field("known aliases")
    assert aliases.verdict is Verdict.PARTIAL
    assert "also recorded as" in aliases.note


def test_a_shortened_alias_still_counts_as_a_match():
    """Requiring every word to match exactly reported "Fatima N." against
    "Fatima Noor" as no match at all -- discarding a real partial signal."""
    result = compare(
        subject="p1", our_name="Fatima Noor", our_attributes={},
        listed=listed(properties={"alias": ["Fatima N."]}),
    )
    assert result.field("known aliases").verdict is Verdict.PARTIAL


def test_a_blank_alias_is_never_reported_as_a_match():
    """An empty alias made compare_names answer UNKNOWN, and "not DIFFERENT"
    read that as a match -- printing "the listed party is also recorded as "
    with no name after it, on the officer's screen and in the model's prompt.
    """
    result = compare(
        subject="p1", our_name="Fatima Noor", our_attributes={},
        listed=listed(properties={"alias": [""]}),
    )
    assert result.field("known aliases") is None


def test_a_blank_alias_beside_a_real_one_leaves_no_stray_separator():
    """Joining the raw list rendered "; Volodya P" to the reader."""
    result = compare(
        subject="p1", our_name="Fatima Noor", our_attributes={},
        listed=listed(properties={"alias": ["", "Volodya P"]}),
    )
    aliases = result.field("known aliases")
    assert aliases.theirs == "Volodya P"
    assert aliases.verdict is Verdict.DIFFERENT


def test_an_alias_sharing_only_part_of_the_name_is_still_surfaced():
    """Requiring every word of the alias to equal every word of ours discarded
    a real partial signal: 'Fatima N.' abbreviates 'Noor' rather than dropping
    it, and an exact-set check reported that as no match at all -- the same
    shape of loss _best() exists to prevent for the other fields."""
    result = compare(
        subject="p1", our_name="Fatima Noor",
        our_attributes={},
        listed=listed(properties={"alias": ["Fatima N."]}),
    )
    aliases = result.field("known aliases")
    assert aliases.verdict is Verdict.PARTIAL
    assert "also recorded as Fatima N." in aliases.note


def test_an_alias_with_no_shared_words_is_reported_as_no_match():
    result = compare(
        subject="p1", our_name="Mohammed Al-Rashid",
        our_attributes={},
        listed=listed(properties={"alias": ["Roberto Diaz"]}),
    )
    aliases = result.field("known aliases")
    assert aliases.verdict is Verdict.DIFFERENT
    assert aliases.note == "none of the listed aliases match"


def test_the_comparison_is_deterministic():
    args = dict(
        subject="p1", our_name="Vladimir Petrov",
        our_attributes={"dob": "1984-08-19", "nationality": "IN"},
        listed=listed(properties={"birthDate": ["1961-03-03"]}),
    )
    assert compare(**args).as_dict() == compare(**args).as_dict()


# -- the allowlist the hallucination guard uses ----------------------------


def test_every_value_in_the_comparison_is_in_its_facts():
    result = compare(
        subject="p1", our_name="Vladimir Petrov",
        our_attributes={"dob": "1984-08-19", "nationality": "IN",
                        "id_document_number": "K4471829"},
        listed=listed(properties={"birthDate": ["1961-03-03"],
                                  "nationality": ["RU"],
                                  "passportNumber": ["7712345"]}),
    )
    facts = result.facts
    for expected in ("vladimir", "petrov", "1984", "1961", "7712345", "4471829"):
        assert expected in facts, expected


def test_facts_does_not_contain_things_nobody_mentioned():
    result = compare(
        subject="p1", our_name="Vladimir Petrov", our_attributes={"dob": "1984-08-19"},
        listed=listed(properties={"birthDate": ["1961-03-03"]}),
    )
    assert "1972" not in result.facts
    assert "hezbollah" not in result.facts


def test_a_computed_note_is_a_fact_the_model_may_repeat():
    """A live run against a real Azure deployment surfaced this: compare_dates
    computes "32 years apart" and hands that sentence to the model as part of
    the comparison. The model repeated "32" back in its own reasoning -- a
    faithful echo of something this system told it -- and the guard destroyed
    the draft as an invented figure, because the note that number came from
    was never added to the allowlist. The note is what we told the model, not
    what the model told us; it belongs in facts like any other field.
    """
    result = compare(
        subject="p1", our_name="Rohan Verma",
        our_attributes={"dob": "1990-04-12"},
        listed=listed(properties={"birthDate": ["1958-11-02"]}),
    )
    assert result.field("date of birth").note == "32 years apart"
    assert "32" in result.facts


# -- reading it off a real Case --------------------------------------------


def test_a_screening_case_yields_a_comparison(engine):
    from conftest import WHEN, person
    from vinzor.model import EventType

    engine.ingest(
        event_type=EventType.ENTITY_REGISTERED, subject="p1", occurred_at=WHEN,
        payload={"kind": "PERSON", "name": "Vladimir Petrov",
                 "attributes": {"dob": "1984-08-19", "nationality": "IN"}},
    )
    engine.ingest(
        event_type=EventType.SCREENING_COMPLETED, subject="p1", occurred_at=WHEN,
        payload={"matched": True, "list_type": "SANCTIONS", "alert_id": "a1",
                 "basis": listed(properties={"birthDate": ["1961-03-03"],
                                             "nationality": ["RU"]})},
    )
    case = engine.queue()[0]
    result = comparison_for(engine, case)

    assert result is not None
    assert result.our_name == "Vladimir Petrov"
    assert result.listed_name == "Vladimir Petrov"
    assert len(result.decisive_differences) == 2


def test_a_case_that_is_not_a_screening_hit_yields_nothing(engine):
    from conftest import company, commits

    company(engine, "c1", "Orion Zenith Enterprises")
    case = commits(engine, "c1").cases[0]
    assert comparison_for(engine, case) is None


# -- a list entry may carry more than one of anything -----------------------
# The bug these hold shut: comparing only the FIRST value. A sanctioned party
# travelling on our investor's second passport was reported as a different
# document, and the file would have been cleared.


def test_a_match_on_any_listed_passport_is_a_match():
    result = compare(
        subject="p1", our_name="Vladimir Petrov",
        our_attributes={"id_document_number": "K4471829"},
        listed=listed(properties={"passportNumber": ["RU7788991", "K4471829"]}),
    )
    document = result.field("identity document")
    assert document.verdict is Verdict.IDENTICAL
    assert "one of 2 recorded" in document.note


def test_a_match_on_any_listed_date_of_birth_is_a_match():
    result = compare(
        subject="p1", our_name="Vladimir Petrov",
        our_attributes={"dob": "1961-03-03"},
        listed=listed(properties={"birthDate": ["1950-01-01", "1961-03-03"]}),
    )
    assert result.field("date of birth").verdict is Verdict.IDENTICAL


def test_a_match_on_any_listed_nationality_is_a_match():
    result = compare(
        subject="p1", our_name="V P", our_attributes={"nationality": "IN"},
        listed=listed(properties={"nationality": ["RU"], "country": ["IN"]}),
    )
    assert result.field("nationality").verdict is Verdict.IDENTICAL


def test_when_nothing_matches_the_officer_is_told_how_many_were_checked():
    result = compare(
        subject="p1", our_name="V P",
        our_attributes={"id_document_number": "K4471829"},
        listed=listed(properties={"passportNumber": ["A1", "B2", "C3"]}),
    )
    document = result.field("identity document")
    assert document.verdict is Verdict.DIFFERENT
    assert "none of the 3 recorded" in document.note
    assert document.theirs == "A1; B2; C3"


def test_a_blank_beside_a_real_value_does_not_hide_the_difference():
    result = compare(
        subject="p1", our_name="V P", our_attributes={"nationality": "IN"},
        listed=listed(properties={"nationality": ["", "RU"]}),
    )
    assert result.field("nationality").verdict is Verdict.DIFFERENT


# -- a year is not a date ---------------------------------------------------
# The bug these hold shut: "1961" became 1 January 1961, and the invented day
# and month were then compared as though somebody had recorded them.


def test_a_year_only_entry_is_compared_as_a_year():
    result = compare_dates("1961-03-03", "1961")
    assert result.verdict is Verdict.PARTIAL
    assert "only a year" in result.note
    assert "1 January" not in result.note


def test_a_year_only_entry_that_differs_says_it_compared_years():
    result = compare_dates("1984-08-19", "1961")
    assert result.verdict is Verdict.DIFFERENT
    assert "comparing years only" in result.note


def test_a_year_only_entry_close_by_is_not_treated_as_decisive():
    assert compare_dates("1961-03-03", "1962").verdict is Verdict.PARTIAL


def test_a_month_precision_entry_is_compared_as_a_month():
    result = compare_dates("1961-03-03", "1961-03")
    assert result.verdict is Verdict.PARTIAL
    assert "no day" in result.note


def test_one_day_apart_reads_as_one_day():
    """It read "1 days apart" on the officer's screen."""
    assert "1 day apart" in compare_dates("1961-03-03", "1961-03-04").note
    assert "2 days apart" in compare_dates("1961-03-03", "1961-03-05").note


def test_one_year_apart_reads_as_one_year():
    """Only the year-comparison paths phrase the gap in years; under three
    years apart, a full date reports the exact number of days instead."""
    assert "1 year apart" in compare_dates("1961-03-03", "1962").note
    assert "23 years apart" in compare_dates("1984-08-19", "1961-03-03").note
    assert "365 days apart" in compare_dates("1961-03-03", "1962-03-03").note


# -- names that arrive in another alphabet -----------------------------------


def test_a_cyrillic_name_matches_its_latin_spelling():
    """320 of our 335 worst errors -- pairs judged the same that we closed as
    different -- crossed scripts. A Ukrainian name and its transliteration
    share no characters at all, so every token comparison honestly reported
    nothing in common.
    """
    result = compare_names("Владимир Путин", "Vladimir Putin")
    assert result.verdict is Verdict.EQUIVALENT

    # A patronymic romanised two ways. What matters is that it is not closed;
    # whether it lands on PARTIAL or EQUIVALENT is the comparison getting
    # better, and pinning the stronger answer would forbid that.
    across = compare_names("Костенко Ірина Анатоліївна",
                           "Kostenko Irina Anatolievna")
    assert across.verdict is not Verdict.DIFFERENT, "closed as a different person"


def test_a_greek_name_matches_its_latin_spelling():
    assert compare_names("Γιωργος Παπαδοπουλος",
                         "Giorgos Papadopoulos").verdict is not Verdict.DIFFERENT


def test_romanisation_choices_are_not_two_people():
    """A list writes Aleksey and a passport writes Alexei. Both are one man."""
    from vinzor.compare import _sounds_like

    assert _sounds_like("aleksey") == _sounds_like("alexei")
    assert _sounds_like("smith") == _sounds_like("smyth")
    # And it must still tell people apart: folding that matches everything
    # matches nothing useful.
    assert _sounds_like("john") != _sounds_like("jane")
    assert compare_names("Aleksey Ivanov", "Alexei Ivanov").verdict is         Verdict.EQUIVALENT


def test_transliteration_leaves_a_latin_name_exactly_as_it_was():
    """Nothing that worked before may change because of this."""
    from vinzor.compare import transliterate

    for name in ("John Smith", "Jean-Luc O'Brien", "Zhang Wei", "Anita Verma"):
        assert transliterate(name) == name


def test_two_strangers_stay_strangers_across_scripts():
    """Transliteration must not turn everybody into everybody."""
    assert compare_names("Владимир Путин", "Angela Merkel").verdict is Verdict.DIFFERENT
    assert compare_names("Костенко Ірина", "Tanaka Hiroshi").verdict is Verdict.DIFFERENT


def test_a_short_name_is_never_folded_into_another_one():
    """Li and Lei are different Chinese given names. The rule that lets
    Aleksey meet Alexei collapses them into one man, which a test written
    long before any of this caught on the first run.
    """
    result = compare_names("Zhang Li", "Lei ZHANG")
    assert result.verdict is Verdict.PARTIAL
    assert "Li" in result.note and "Lei" in result.note

    assert compare_names("Wei Chen", "Wai Chen").verdict is Verdict.PARTIAL


def test_a_name_nobody_recorded_is_not_a_different_person():
    """"   " against "John" reached the token comparison, shared nothing, and
    came back DIFFERENT -- asserting two people are not the same when one of
    them was never written down.
    """
    for blank in ("", "   ", "\t", None):
        assert compare_names(blank, "John Smith").verdict is Verdict.UNKNOWN
        assert compare_names("John Smith", blank).verdict is Verdict.UNKNOWN


def test_the_same_woman_in_ukrainian_and_in_russian():
    """Журавльова Тетяна Володимирівна and Zhuravleva Tatyana Vladimirovna are
    one person recorded in two languages. Transliteration gets them into the
    same alphabet; only near-matching gets zhuravlova and zhuravleva, tetyana
    and tatyana, into the same name.
    """
    result = compare_names("Журавльова Тетяна Володимирівна",
                           "Zhuravleva Tatyana Vladimirovna")
    assert result.verdict is not Verdict.DIFFERENT
    assert result.strength == 1.0


def test_a_forename_in_common_is_not_a_match():
    """Two strangers who share a forename were a possible match, because any
    single shared part was enough. One part of three is not enough of either
    name to put a person in front of it.
    """
    result = compare_names("Ivan Petrov Sergeyevich", "Ivan Volkov Mikhailovich")
    assert result.verdict is Verdict.DIFFERENT
    assert "too little of either" in result.note


def test_closing_on_too_little_still_misses_fewer_parties_than_before():
    """This is the only rule in the file that closes a match, and it is only
    defensible because the near-matching beside it recovers more true pairs
    than it turns away: measured against 8,000 analyst judgements, 99.3%
    against 98.7%. A surname out of two parts is still a match.
    """
    from vinzor.compare import ENOUGH_OF_THE_NAME

    assert compare_names("Anita Verma", "Rohan Verma").verdict is Verdict.PARTIAL
    assert 0.0 < ENOUGH_OF_THE_NAME < 0.5


def test_short_parts_are_never_near_matched():
    """A ratio that long strings have to earn, two-letter names reach by
    accident. Li and Lei stay two people."""
    assert compare_names("Zhang Li", "Lei ZHANG").verdict is Verdict.PARTIAL
    assert compare_names("Wei Chen", "Wai Chen").verdict is Verdict.PARTIAL


# -- what 10,000 analyst-judged pairs said about dates -----------------------


def test_the_same_day_and_month_in_a_different_year_is_a_mistyped_year():
    """The commonest way a date of birth is mistyped. Nine of the
    twenty-five same-party pairs our comparison contradicted on 10,000
    analyst-judged pairs had exactly this shape."""
    for ours, theirs in (("1950-11-20", "1955-11-20"),
                         ("1954-10-16", "1964-10-16"),
                         ("1960-12-05", "1980-12-05")):
        found = compare_dates(ours, theirs)
        assert found.verdict is Verdict.PARTIAL, (ours, theirs)
        assert "same day and month" in found.note
        assert not found.decisive


def test_a_year_nobody_could_be_born_in_is_a_broken_field():
    """Watchlists carry 1708, 2104 and 2465 among real entries. Reading one
    as "five hundred years apart, therefore a different person" turns a
    corrupt field into evidence."""
    for bad in ("2465", "2104", "1708"):
        found = compare_dates("1967-07-04", bad)
        assert found.verdict is Verdict.UNKNOWN, bad
        assert "not a date anybody could be born on" in found.note
        assert not found.decisive


def test_genuinely_different_dates_are_still_different():
    """Twelve of those twenty-five were genuinely different dates, where
    the analysts matched on evidence we do not hold. Calling those
    different is correct, and the fix must not swallow them."""
    for ours, theirs in (("1989-02-01", "1978-01-06"),
                         ("1983-08-11", "1952-04-19"),
                         ("1979-03-03", "1984-05-28")):
        found = compare_dates(ours, theirs)
        assert found.verdict is Verdict.DIFFERENT, (ours, theirs)
        assert found.decisive


def test_the_ordinary_readings_are_untouched():
    assert compare_dates("1974-03-02", "1974-03-02").verdict is Verdict.IDENTICAL
    assert compare_dates("1974-03-02", "1974-02-03").verdict is Verdict.EQUIVALENT
    assert compare_dates("1974-03-02", "1974").verdict is Verdict.PARTIAL
    assert compare_dates("1974-03-02", "").verdict is Verdict.UNKNOWN


# -- what agreement and contradiction are actually worth ---------------------


def test_a_matching_document_number_corroborates():
    """The strongest single signal in 10,000 analyst-judged pairs: 97.1%
    precision, higher than any name-based reading."""
    found = compare_exact("identity document", "X1234567", "X1234567",
                          "the same document number",
                          "different document numbers")
    assert found.corroborating
    assert not found.decisive


def test_a_shared_nationality_corroborates_nothing():
    """Millions of people share one."""
    found = compare_exact("nationality", "IN", "IN",
                          "the same country", "different countries")
    assert not found.corroborating


def test_a_shared_birth_date_corroborates_nothing():
    assert not compare_dates("1974-03-02", "1974-03-02").corroborating


def test_a_contradiction_is_a_question_not_a_conclusion():
    """Used as a veto, each of the three costs recall for almost no
    precision. They order a file up the page; they close nothing."""
    for found in (compare_dates("1989-02-01", "1978-01-06"),
                  compare_exact("nationality", "IN", "SG",
                                "the same country", "different countries"),
                  compare_exact("identity document", "X1", "Y2",
                                "same", "different")):
        assert found.decisive
        assert not found.corroborating


# -- what the comparison says about itself ----------------------------------


def _with(*fields):
    return Comparison(subject="p1", our_name="J Smith",
                      listed_name="John Smith", listed_id="Q1",
                      listed_on=("a list",), match_score=0.8, fields=fields)


def test_a_matching_document_is_stated_as_the_strongest_agreement():
    """It was one line among four, toned the same as a matching country.
    An officer scanning four lines had no way to see that one was worth
    more than the other three together."""
    said = _with(compare_names("J Smith", "John Smith"),
                 compare_exact("identity document", "X1", "X1",
                               "same", "different")).corroboration
    assert "identity document" in said
    assert "strongest single agreement" in said


def test_it_says_plainly_that_it_is_not_proof():
    """Numbers get mistyped and reused. A sentence that sounded like proof
    would close files this system exists to keep open."""
    said = _with(compare_names("J Smith", "John Smith"),
                 compare_exact("identity document", "X1", "X1",
                               "same", "different")).corroboration
    assert "not proof" in said


def test_a_matching_name_alone_corroborates_nothing():
    assert _with(compare_names("John Smith", "John Smith")).corroboration == ""


def test_a_shared_country_or_birthday_corroborates_nothing():
    """Millions of people share either, and saying otherwise would put a
    reassuring sentence on files that have not earned one."""
    assert _with(compare_exact("nationality", "IN", "IN",
                               "same", "different"),
                 compare_dates("1974-03-02", "1974-03-02")).corroboration == ""


def test_the_corroboration_is_recorded_not_recomputed():
    """What the officer was told at the time has to survive a later change
    to what counts as corroboration."""
    recorded = _with(compare_names("J Smith", "John Smith"),
                     compare_exact("identity document", "X1", "X1",
                                   "same", "different")).as_dict()
    assert "corroboration" in recorded
    assert "strongest single agreement" in recorded["corroboration"]


def test_a_contradicting_document_states_nothing_reassuring():
    said = _with(compare_names("J Smith", "John Smith"),
                 compare_exact("identity document", "X1", "Y2",
                               "same", "different")).corroboration
    assert said == ""
