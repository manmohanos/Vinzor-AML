"""Reading Devanagari and Arabic letters into Latin ones, and nothing else.

Every expected spelling below was checked two ways before it went in this
file: by hand, tracing the table against the word, and then by actually
running the code and comparing -- because the first pass through this file
got two of them wrong by hand-arithmetic alone (string concatenation is
easier to get wrong on paper than it looks). Trust the second way.
"""

from __future__ import annotations

import pytest

from vinzor.transliterate import arabic, devanagari, romanize, script_of


# -- Devanagari ---------------------------------------------------------


@pytest.mark.parametrize("written, expected", [
    ("राम", "Ram"),                        # bare final consonant: schwa dropped
    ("सीता", "Sita"),
    ("प्रिया शर्मा", "Priya Sharma"),        # a virama-built cluster (प्र), two words
    ("अनिल कुमार", "Anil Kumar"),
    ("राजेश गुप्ता", "Rajesh Gupta"),
    ("विजय", "Vijay"),                      # medial schwa kept, final one dropped
    ("संजय", "Sanjay"),                     # anusvara
    ("भारत", "Bharat"),
    ("मोक्ष", "Moksh"),                     # a conjunct (क्ष) built from the virama rule
    ("गांधी", "Gandhi"),                    # a matra and an anusvara on one consonant
    ("ज़ोया", "Zoya"),                      # a nukta consonant
])
def test_a_devanagari_name_reads_as_its_known_spelling(written, expected):
    assert devanagari(written) == expected


def test_the_final_schwa_is_the_one_thing_that_tells_two_names_apart():
    """कमल and कमला differ only in whether ल carries an explicit vowel sign.
    Telling a bare consonant's own untouched vowel from one an explicit
    matra put there is the one phonological step this module takes, and the
    reason the internal representation is more than a plain string -- see
    ``_devanagari_word``'s own docstring."""
    assert devanagari("कमल") == "Kamal"
    assert devanagari("कमला") == "Kamala"


def test_devanagari_does_not_distinguish_vowel_length():
    """अ and आ, इ and ई: both pairs read as the same Latin letter, which
    matches how these names are conventionally spelled far more often than
    marking the difference would."""
    assert devanagari("अ") == devanagari("आ") == "A"
    assert devanagari("इ") == devanagari("ई") == "I"


def test_medial_schwa_deletion_is_a_documented_gap_not_attempted():
    """Real Hindi drops the middle vowel in मेहता too (it is said, and
    usually spelled, "Mehta"), but that needs a syllable-weight rule this
    module does not have -- only the *final* vowel is ever dropped, and the
    module's own docstring says so rather than silently getting this one
    wrong. This test exists so a future change that starts silently
    guessing at medial vowels has to walk past an assertion that says what
    the honest, narrower answer is."""
    assert devanagari("मेहता") == "Mehata"


def test_a_name_already_partly_latin_keeps_the_latin_part():
    assert devanagari("Priya शर्मा") == "Priya Sharma"


def test_devanagari_on_empty_or_latin_text_is_a_no_op():
    assert devanagari("") == ""
    assert devanagari("John Smith") == "John Smith"


# -- Arabic ---------------------------------------------------------------


@pytest.mark.parametrize("written, expected", [
    ("علي", "Ali"),
    ("نور", "Nur"),
    ("سعيد", "Said"),
    ("سارة", "Sara"),
    ("نادية", "Nadia"),
    ("دينا", "Dina"),
    ("لينا", "Lina"),
    ("أمينة", "Amina"),
    ("سامي", "Sami"),
    ("رامي", "Rami"),
    ("فاطمة", "Fatma"),
])
def test_an_arabic_name_reads_as_its_known_spelling(written, expected):
    assert arabic(written) == expected


def test_fully_vowelled_arabic_reads_exactly():
    """The one case this module can be fully confident in rather than
    merely plausible: every diacritic is on the page, so nothing has to be
    guessed. مُحَمَّد -- fatha, then a shadda doubling the second م -- is
    Muhammad, letter and mark for mark."""
    assert arabic("مُحَمَّد") == "Muhammad"


def test_shadda_doubles_the_consonant_whichever_order_the_marks_were_typed():
    """A shadda and the vowel riding the same letter can be typed in either
    order; Unicode's own canonical ordering (fatha's combining class sorts
    before shadda's) settles it to one order before this module ever sees
    it. Doubling whichever token happens to sit last -- the obvious
    approach -- doubles the vowel once one is present instead of the
    consonant, which is what this test would have caught."""
    fatha_then_shadda = "م" + "َ" + "ّ"
    shadda_then_fatha = "م" + "ّ" + "َ"
    assert arabic(fatha_then_shadda) == "Mma"
    assert arabic(shadda_then_fatha) == "Mma"


def test_sukun_marks_an_explicit_absence_of_a_vowel():
    assert arabic("مَنْ") == "Man"


def test_undiacritized_arabic_reads_as_an_honest_consonant_skeleton():
    """Almost every Arabic name in an ordinary spreadsheet cell is written
    without harakat, and this module does not invent the missing vowels --
    محمد, spelled the way it is spelled everywhere outside a Quran or a
    schoolbook, comes back a skeleton, not a guess at "Muhammad"."""
    assert arabic("محمد") == "Mhmd"


def test_a_name_already_partly_latin_keeps_the_latin_part_arabic():
    assert arabic("Sami رامي") == "Sami Rami"


def test_arabic_on_empty_or_latin_text_is_a_no_op():
    assert arabic("") == ""
    assert arabic("John Smith") == "John Smith"


# -- script detection and the combined entry point -------------------------


def test_script_of_tells_the_two_scripts_apart():
    assert script_of("राम") == "devanagari"
    assert script_of("علي") == "arabic"
    assert script_of("राम علي") == "mixed"
    assert script_of("John Smith") == ""
    assert script_of("") == ""


def test_romanize_reads_whichever_script_is_actually_there():
    """One entry point a caller does not have to inspect the text before
    using: it runs both readers, and each one leaves what is not its own
    script alone."""
    assert romanize("राम") == "Ram"
    assert romanize("علي") == "Ali"
    assert romanize("John Smith") == "John Smith"
    assert romanize("Priya शर्मा") == "Priya Sharma"
