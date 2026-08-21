"""Comparing an investor against a watchlist entry — the facts, not the judgement.

This module answers *what is the same and what differs*. It never answers
*is it the same party*: that is judgement, and it belongs to the officer, with
a model's help (see ``assist.py``).

The split matters more than it looks. Sanctions screening runs above a 95%
false-positive rate, so an officer's day is mostly assembling this same
comparison over and over. It is also exactly the kind of work a language model
gets *nearly* right — and a hallucinated date of birth in a compliance file is
not a nearly-right, it is a fabricated regulatory record. So the facts are
computed here, deterministically, and the model is handed them rather than the
raw file.

Everything here is pure: no clock, no network, no model. Same inputs, same
comparison, forever.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping, Optional, Sequence

from .model import StrEnum

#: A birthday two years apart is usually a transcription error; twenty is not.
#: Below this, the difference is reported as "close"; at or above it, "differs".
CLOSE_YEARS = 3

#: The years a date of birth can plausibly fall in. Outside this it is not
#: a date of birth at all, it is a typing accident -- watchlists carry
#: 1708, 2104 and 2465 among real entries. Reading one of those as
#: "five hundred years apart, therefore a different person" turns a
#: corrupt field into evidence, which is the opposite of what it is.
PLAUSIBLE_BIRTH_YEARS = (1850, 2035)


class Verdict(StrEnum):
    IDENTICAL = "IDENTICAL"
    #: Same in substance, different in form: word order, spelling, accents.
    EQUIVALENT = "EQUIVALENT"
    #: Shares some but not all of its parts.
    PARTIAL = "PARTIAL"
    DIFFERENT = "DIFFERENT"
    #: One side is missing the field. Not evidence either way, and the most
    #: common outcome in real screening — watchlists are sparse.
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FieldComparison:
    """One field, both sides, and what can be said about the difference."""

    field: str
    ours: str
    theirs: str
    verdict: Verdict
    note: str = ""
    #: How much of the shorter name the two sides share, 0 to 1. Only a name
    #: carries it. It never closes a match -- every overlap still reaches a
    #: person -- but it lets an officer work the strong ones first.
    #:
    #: Measured on 8,000 pairs judged by OpenSanctions analysts: demanding more
    #: than half the name would cut false positives fourfold and close 264
    #: pairs the analysts judged to be the same person. In anti-money
    #: laundering a missed party is not a smaller version of a wasted hour, so
    #: nothing is closed. It is ordered instead.
    strength: float = 1.0

    @property
    def decisive(self) -> bool:
        """A difference worth an officer's attention on its own.

        Named "decisive" when this was written, on the assumption that a
        contradicting date, nationality or document argued the parties were
        different. Measured against 10,000 pairs OpenSanctions analysts had
        judged, that assumption is wrong in every one of the three: used as
        a veto, birth dates cost 0.2 points of recall, nationality 1.0, and
        identity documents 2.0, each for at most a tenth of a point of
        precision. Same-party records disagree about all three routinely,
        because different sources record different things about one person.

        So this marks a question, not a conclusion, and the product treats
        it as one -- it orders a file up a reader's page and closes
        nothing. The name is kept because it is what the field is called
        wherever it already appears; what it claims has been corrected.
        """
        return self.verdict is Verdict.DIFFERENT and self.field in {
            "date of birth", "nationality", "identity document"
        }

    @property
    def corroborating(self) -> bool:
        """An agreement that is close to proof on its own.

        The other half of the same measurement, and the more useful half.
        A matching identity document number was the single strongest
        signal in the corpus: 97.1% precision, higher than any name-based
        reading, though it appears on only 11.8% of true matches. Admitting
        it alongside a name agreement -- rather than requiring both -- took
        the strict reading from 87.1% to 88.0% F1, the only change measured
        that improved matching at all.

        A shared date of birth or nationality is not here. Millions of
        people share either.
        """
        return (self.verdict is Verdict.IDENTICAL
                and self.field == "identity document")


@dataclass(frozen=True)
class Comparison:
    """Everything factual about a possible match."""

    subject: str
    our_name: str
    listed_name: str
    listed_id: str
    listed_on: tuple[str, ...]
    match_score: float
    fields: tuple[FieldComparison, ...]

    def field(self, name: str) -> Optional[FieldComparison]:
        return next((f for f in self.fields if f.field == name), None)

    @property
    def decisive_differences(self) -> tuple[FieldComparison, ...]:
        return tuple(f for f in self.fields if f.decisive)

    @property
    def corroborations(self) -> tuple[FieldComparison, ...]:
        return tuple(f for f in self.fields if f.corroborating)

    @property
    def corroboration(self) -> str:
        """What agrees here that is worth more than the rest, in words.

        Measured on 10,000 pairs OpenSanctions analysts had judged, a
        matching identity document number carried 97.1% precision --
        higher than any reading of the names, and higher than every
        contradiction in the comparison is worth as evidence against.
        It appears on about one true match in eight.

        On the page it was one line among four, toned the same as a
        matching country. An officer scanning four lines had no way to see
        that one of them was worth more than the other three together, so
        the comparison now says so itself.

        This states a fact and settles nothing. The file stays open, the
        officer still decides, and a matching number is not proof: numbers
        are mistyped and reused. It is the strongest thing this comparison
        can offer, which is not the same as being enough.
        """
        found = self.corroborations
        if not found:
            return ""
        what = _join_words([f.field for f in found])
        return (
            f"The {what} agrees on both records. Of everything compared "
            f"here that is the strongest single agreement -- on the pairs "
            f"this was measured against it was right far more often than "
            f"a matching name. It is not proof: numbers get mistyped and "
            f"reused."
        )

    @property
    def comparable(self) -> tuple[FieldComparison, ...]:
        """Fields where both sides had something to compare."""
        return tuple(f for f in self.fields if f.verdict is not Verdict.UNKNOWN)

    @property
    def facts(self) -> frozenset[str]:
        """Every value that legitimately appears in this comparison.

        This is the allowlist the hallucination guard checks a draft against:
        any date or number a model writes that is not in here was invented.

        Notes count as legitimate too, not just the raw ``ours``/``theirs``
        values. ``compare_dates`` computes "23 years apart" and hands that
        sentence to the model as part of the comparison -- the note is what
        this system told the model, not what the model told us. A live
        deployment surfaced exactly this: a model faithfully repeating a
        computed gap ("32 years apart") back in its own reasoning was
        destroyed as an invented figure, because the number existed only in
        a note nobody had added to the allowlist. Trusting a note the same as
        any other field closes that gap without weakening what the guard is
        actually for -- stopping a figure nobody gave the model, not one this
        system computed and disclosed itself.
        """
        seen: set[str] = set()
        for item in self.fields:
            for side in (item.ours, item.theirs, item.note):
                seen.update(_tokens(side))
        seen.update(_tokens(self.our_name))
        seen.update(_tokens(self.listed_name))
        for name in self.listed_on:
            seen.update(_tokens(name))
        return frozenset(seen)

    def as_dict(self) -> dict[str, Any]:
        """The form recorded on the event and handed to the model."""
        return {
            "subject": self.subject,
            "our_name": self.our_name,
            "listed_name": self.listed_name,
            "listed_id": self.listed_id,
            "listed_on": list(self.listed_on),
            "match_score": self.match_score,
            "fields": [
                {"field": f.field, "ours": f.ours, "theirs": f.theirs,
                 "verdict": f.verdict.value, "note": f.note}
                for f in self.fields
            ],
            # Recorded rather than recomputed on read, like every other
            # judgement here: what the officer was told at the time has to
            # survive a later change to what counts as corroboration.
            "corroboration": self.corroboration,
        }


# ---------------------------------------------------------------------------
# Normalising
# ---------------------------------------------------------------------------


#: Cyrillic to Latin, in the shape sanctions lists actually use. Measured
#: against 8,000 pairs judged by OpenSanctions analysts, 320 of our 335
#: dangerous misses -- pairs judged to be the same person that we closed as
#: different -- crossed scripts. A Ukrainian name and its Latin spelling share
#: no characters at all, so every token comparison returned "nothing in
#: common", which is true and useless.
#:
#: Russian, Ukrainian and Belarusian dominate the lists this is aimed at.
#: Arabic and the CJK scripts are not handled here: transliterating them needs
#: vowel reconstruction or a dictionary, not a table, and a table that pretends
#: otherwise would fail quietly.
_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e",
    "ё": "e", "є": "ye", "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "yi",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ў": "w", "ф": "f", "х": "kh",
    "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y",
    "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

_GREEK = {
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
}

#: Spellings that differ only by how somebody chose to romanise a sound. Both
#: sides are reduced to the same skeleton before comparing, so "Alexei" and
#: "Aleksey" stop being two people. Applied after transliteration so a name
#: that arrived in Cyrillic and one that arrived in Latin meet in the middle.
_SOUNDS = (
    ("shch", "sh"), ("kh", "h"), ("ck", "k"), ("ph", "f"), ("th", "t"),
    ("zh", "j"), ("ts", "c"), ("cz", "c"), ("sch", "sh"), ("x", "ks"),
    ("ee", "i"), ("oo", "u"), ("ou", "u"), ("ie", "i"), ("ei", "i"),
    ("ai", "a"), ("ay", "a"), ("ey", "i"), ("y", "i"), ("w", "v"),
    ("q", "k"), ("ë", "e"),
)


def transliterate(text: str) -> str:
    """Latin letters for a name written in another alphabet.

    Left alone if it is already Latin, so nothing that works today changes.
    """
    out = []
    for character in text:
        lowered = character.lower()
        replacement = _CYRILLIC.get(lowered)
        if replacement is None:
            replacement = _GREEK.get(lowered)
        out.append(character if replacement is None else replacement)
    return "".join(out)


#: Below this many letters, folding spellings together stops distinguishing
#: people. "Li" and "Lei" are different Chinese given names and the rule that
#: makes Aleksey meet Alexei collapses them into one man -- caught by a test
#: that had been passing since long before any of this was written.
_TOO_SHORT_TO_FOLD = 4


def _sounds_like(part: str) -> str:
    """One spelling for a sound, whichever spelling arrived.

    Not a general phonetic algorithm -- Soundex and its relatives collapse far
    too much and would match strangers. This only folds the specific pairs that
    romanisation disagrees about, and only where there is enough name to be
    confident the difference is spelling rather than identity.
    """
    if len(part) < _TOO_SHORT_TO_FOLD:
        return part
    reduced = part
    for written, canonical in _SOUNDS:
        reduced = reduced.replace(written, canonical)
    # A doubled letter is a spelling choice, never a different name.
    squeezed = []
    for letter in reduced:
        if not squeezed or squeezed[-1] != letter:
            squeezed.append(letter)
    return "".join(squeezed)


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))


def _name_parts(name: str) -> tuple[str, ...]:
    """Lowercase word parts, accents removed, punctuation dropped.

    Deliberately ignores order: "Wei Zhang" and "Zhang Wei" are the same parts,
    which is the point — many naming conventions put the family name first, and
    a screening system that treats them as different names is useless in Asia.
    """
    # Apostrophes vanish rather than split: O'Brien is one name, and turning
    # it into "o" + "brien" would stop it matching "OBrien". Hyphens and the
    # rest become spaces, because double-barrelled names are two parts.
    text = re.sub(r"['‘’ʼ]", "",
                  _strip_accents(transliterate(name)).lower())
    cleaned = re.sub(r"[^\w\s]", " ", text)
    return tuple(sorted(p for p in cleaned.split() if p))


def _names(parts: Sequence[str]) -> str:
    """Name parts, capitalised and joined as English rather than as a list."""
    shown = [p.capitalize() for p in parts]
    if len(shown) <= 1:
        return "".join(shown)
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def _join_words(parts) -> str:
    parts = list(parts)
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _plural(count: int, singular: str) -> str:
    return singular if count == 1 else singular + "s"


def _years(count: int) -> str:
    return f"{count} {_plural(count, 'year')}"


def _tokens(text: str) -> set[str]:
    """Comparable tokens: words and digit-runs, lowercased."""
    if not text:
        return set()
    return {t.lower() for t in re.findall(r"[A-Za-z]{2,}|\d+", _strip_accents(text))}


def _parse_date(value: str) -> tuple[Optional[date], str]:
    """Parse a date *and say how precise it is*.

    Watchlists very often carry a year alone. Turning "1961" into 1 January 1961
    and then comparing it as a full date is how a system manufactures evidence:
    the month and the day were never on the record, and every later step -- the
    "11 years apart" note, the model's prose, the officer's decision -- treats
    the invention as fact. So the precision travels with the date, and nothing
    compares a day nobody supplied.
    """
    value = (value or "").strip()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(value, pattern).date(), "day"
        except ValueError:
            continue
    if re.fullmatch(r"\d{4}", value):
        return date(int(value), 1, 1), "year"
    if re.fullmatch(r"\d{4}[-/]\d{1,2}", value):
        year, month = re.split(r"[-/]", value)
        try:
            return date(int(year), int(month), 1), "month"
        except ValueError:
            return None, "none"
    return None, "none"


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------


#: How alike two name parts must be to be treated as the same part. Below
#: this they are different names; above it they are one name spelled twice.
#:
#: Chosen by measurement on 8,000 pairs judged by OpenSanctions analysts.
#: Exact matching alone agreed with 98.7% of their "same person" judgements;
#: at 0.80 that rises to 99.3% *and* the share of correctly-rejected pairs
#: rises with it, from 9.8% to 15.5%. Better in both directions at once, which
#: is rare enough to be worth stating: the pairs it newly matches are ones the
#: old rule was rejecting for the wrong reason.
NEARLY_THE_SAME = 0.80

#: How much of the shorter name must match before two records are treated as
#: possibly one party. A single shared forename out of three parts is two
#: strangers who share a forename.
#:
#: This closes matches, which everywhere else in this file is the thing not to
#: do. It is only defensible here because the fuzzy comparison above recovers
#: more true pairs than the threshold turns away -- 99.3% against 98.7% -- so
#: the rule as a whole misses fewer parties than the one it replaces.
ENOUGH_OF_THE_NAME = 0.34


def _overlap(ours: set, theirs: set) -> set:
    """Parts the two names share, allowing for how they were spelled.

    "Журавльова Тетяна Володимирівна" and "Zhuravleva Tatyana Vladimirovna" are
    one woman recorded in Ukrainian and in Russian. Transliteration gets them
    into the same alphabet; only this gets zhuravlova and zhuravleva, tetyana
    and tatyana, into the same name.
    """
    shared = set()
    for part in ours:
        if part in theirs:
            shared.add(part)
            continue
        for other in theirs:
            # Length guard first: it is cheap, and it stops "li" being
            # rewritten into "lei" by a ratio that short strings reach easily.
            if abs(len(part) - len(other)) > 3 or min(len(part), len(other)) < 4:
                continue
            if SequenceMatcher(None, part, other).ratio() >= NEARLY_THE_SAME:
                shared.add(part)
                break
    return shared


def compare_names(ours: str, theirs: str) -> FieldComparison:
    # Whitespace is not a name. "   " against "John" used to reach the token
    # comparison, share nothing, and come back DIFFERENT -- asserting that two
    # people are not the same when one of them was never recorded.
    if not (ours or "").strip() or not (theirs or "").strip():
        return FieldComparison("name", ours, theirs, Verdict.UNKNOWN,
                               "one side has no name recorded")
    if ours.strip() == theirs.strip():
        return FieldComparison("name", ours, theirs, Verdict.IDENTICAL,
                               "written exactly the same way")

    ours_parts, theirs_parts = _name_parts(ours), _name_parts(theirs)
    if ours_parts == theirs_parts:
        return FieldComparison("name", ours, theirs, Verdict.EQUIVALENT,
                               "the same words in a different order or spelling")

    # Second look, with romanisation choices folded away: a list writing
    # Aleksey and a passport writing Alexei are one man, and no amount of
    # exact token matching will ever say so.
    ours_sounds = {_sounds_like(p) for p in ours_parts}
    theirs_sounds = {_sounds_like(p) for p in theirs_parts}
    if ours_sounds == theirs_sounds:
        return FieldComparison("name", ours, theirs, Verdict.EQUIVALENT,
                               "the same name, spelled differently")

    shared = _overlap(set(ours_parts), set(theirs_parts))
    if not shared:
        # Fall back to the folded forms before concluding these are strangers.
        folded = ours_sounds & theirs_sounds
        if folded:
            strength = len(folded) / min(len(ours_sounds), len(theirs_sounds))
            return FieldComparison(
                "name", ours, theirs, Verdict.PARTIAL,
                f"the names share {_names(sorted(folded))} once spelling "
                f"differences are set aside. "
                + ("Most of the name matches" if strength > 0.5
                   else "Only part of the name matches"),
                strength=strength)
    if shared:
        # Written as a sentence about names, not as set arithmetic. The reader
        # is deciding whether two people are one person; "differs on lei, li"
        # makes them do the reconstruction themselves.
        ours_only = sorted(set(ours_parts) - shared)
        theirs_only = sorted(set(theirs_parts) - shared)
        strength = len(shared) / min(len(set(ours_parts)), len(set(theirs_parts)))
        if strength < ENOUGH_OF_THE_NAME:
            return FieldComparison(
                "name", ours, theirs, Verdict.DIFFERENT,
                f"the names share only {_names(sorted(shared))}, which is too "
                f"little of either to be the same party",
                strength=strength)
        note = f"both names include {_names(sorted(shared))}"
        if ours_only:
            note += f"; ours also has {_names(ours_only)}"
        if theirs_only:
            note += f"; the list entry also has {_names(theirs_only)}"
        # Said in words as well as recorded as a number, because the officer
        # reading this is deciding, and "one part of three" is the whole point.
        note += (". Most of the name matches"
                 if strength > 0.5 else
                 ". Only part of the name matches")
        return FieldComparison("name", ours, theirs, Verdict.PARTIAL, note,
                               strength=strength)
    return FieldComparison("name", ours, theirs, Verdict.DIFFERENT,
                           "no part of the names is shared")


#: Which verdict wins when a watchlist entry carries several values for one
#: field. A match anywhere beats a difference everywhere -- the whole point of
#: an entry holding three passport numbers is that the party travels on any of
#: them. UNKNOWN ranks last: having something to compare and finding it
#: different is a real answer, and must not be displaced by a blank beside it.
_RANK = {
    Verdict.IDENTICAL: 0,
    Verdict.EQUIVALENT: 1,
    Verdict.PARTIAL: 2,
    Verdict.DIFFERENT: 3,
    Verdict.UNKNOWN: 4,
}


def _best(ours: str, theirs: Sequence[str], compare_one) -> FieldComparison:
    """Compare ours against every listed value and keep the closest match.

    A listed party may hold several passports, nationalities or dates of birth.
    ``screening.py`` records them all and ``Hit`` says so in its own docstring.
    Comparing only the first is how a screening system exonerates a real match:
    the sanctioned party carrying our investor's *second* passport is reported
    as a different document, and the file is cleared.
    """
    values = [str(v) for v in theirs if str(v).strip()]
    if not values:
        return compare_one(ours, "")
    results = [compare_one(ours, v) for v in values]
    winner = min(results, key=lambda r: _RANK[r.verdict])
    if len(values) == 1:
        return winner
    # More than one value was on the entry, so the note has to say which of them
    # the verdict is about. An officer reading "different document numbers"
    # against a party holding three passports is misled by omission.
    count = len(values)
    if winner.verdict in (Verdict.IDENTICAL, Verdict.EQUIVALENT, Verdict.PARTIAL):
        note = f"{winner.note} - this is one of {count} recorded on the list entry"
    else:
        note = f"{winner.note} - none of the {count} recorded on the list entry match"
    return FieldComparison(winner.field, winner.ours, "; ".join(values),
                           winner.verdict, note)


def compare_dates(ours: str, theirs: Any) -> FieldComparison:
    """Compare a date of birth against every date the list entry carries."""
    listed = _all(theirs)
    if len(listed) == 1:
        return _one_date(ours, listed[0])
    return _best(ours, listed, _one_date)


def _one_date(ours: str, theirs: str) -> FieldComparison:
    """One date against one date, respecting how precise each side is."""
    if not ours or not theirs:
        return FieldComparison("date of birth", ours, theirs, Verdict.UNKNOWN,
                               "one side has no date of birth recorded")
    left, left_precision = _parse_date(ours)
    right, right_precision = _parse_date(theirs)
    if left is None or right is None:
        return FieldComparison("date of birth", ours, theirs, Verdict.UNKNOWN,
                               "a date could not be read")

    # A year nobody could have been born in is a broken field, not a
    # difference. Measured on 10,000 analyst-judged pairs: four of the
    # twenty-five same-party pairs our date comparison contradicted were
    # this -- one side carrying 1708, 2104 or 2465.
    low, high = PLAUSIBLE_BIRTH_YEARS
    for value, side in ((left, ours), (right, theirs)):
        if not low <= value.year <= high:
            return FieldComparison(
                "date of birth", ours, theirs, Verdict.UNKNOWN,
                f"{side} is not a date anybody could be born on, so the two "
                f"cannot be compared",
            )

    # Compare only as finely as the vaguer side allows. "1961" against
    # "1961-03-03" agrees on everything anybody actually wrote down.
    if "year" in (left_precision, right_precision):
        if left.year == right.year:
            return FieldComparison(
                "date of birth", ours, theirs, Verdict.PARTIAL,
                "the same year - the list entry records only a year, so the day "
                "and month cannot be compared",
            )
        years = abs(left.year - right.year)
        return FieldComparison(
            "date of birth", ours, theirs,
            Verdict.PARTIAL if years < CLOSE_YEARS else Verdict.DIFFERENT,
            f"{_years(years)} apart, comparing years only - the list entry "
            f"records no day or month",
        )
    if "month" in (left_precision, right_precision):
        if (left.year, left.month) == (right.year, right.month):
            return FieldComparison(
                "date of birth", ours, theirs, Verdict.PARTIAL,
                "the same month - the list entry records no day, so the day "
                "cannot be compared",
            )

    if left == right:
        return FieldComparison("date of birth", ours, theirs, Verdict.IDENTICAL,
                               "the same date")
    years = abs(left.year - right.year)
    if left.day == right.month and left.month == right.day and years == 0:
        return FieldComparison("date of birth", ours, theirs, Verdict.EQUIVALENT,
                               "the same date with day and month transposed")
    if years < CLOSE_YEARS:
        days = abs((left - right).days)
        return FieldComparison(
            "date of birth", ours, theirs, Verdict.PARTIAL,
            f"{days} {_plural(days, 'day')} apart - close enough to be a "
            f"recording error",
        )
    # The same day and month with a different year is the commonest way a
    # date of birth is mistyped, and the analysts agree: nine of the
    # twenty-five same-party pairs this comparison contradicted on 10,000
    # judged pairs had exactly this shape -- 1950-11-20 against
    # 1955-11-20, 1954-10-16 against 1964-10-16. Two people sharing a
    # birthday to the day and differing only in year is possible; treating
    # it as proof of difference cost more true matches than it saved.
    if (left.day, left.month) == (right.day, right.month):
        return FieldComparison(
            "date of birth", ours, theirs, Verdict.PARTIAL,
            f"the same day and month, {_years(years)} apart - the pattern a "
            f"mistyped year leaves",
        )
    return FieldComparison("date of birth", ours, theirs, Verdict.DIFFERENT,
                           f"{_years(years)} apart")


def compare_exact(field_name: str, ours: str, theirs: Any,
                  note_same: str, note_differ: str) -> FieldComparison:
    """Compare one value of ours against every value the list entry carries."""
    def one(o: str, t: str) -> FieldComparison:
        return _one_exact(field_name, o, t, note_same, note_differ)

    listed = _all(theirs)
    if len(listed) == 1:
        return one(ours, listed[0])
    return _best(ours, listed, one)


def _one_exact(field_name: str, ours: str, theirs: str,
               note_same: str, note_differ: str) -> FieldComparison:
    if not ours or not theirs:
        return FieldComparison(field_name, ours, theirs, Verdict.UNKNOWN,
                               f"one side has no {field_name} recorded")
    if ours.strip().upper() == theirs.strip().upper():
        return FieldComparison(field_name, ours, theirs, Verdict.IDENTICAL, note_same)
    return FieldComparison(field_name, ours, theirs, Verdict.DIFFERENT, note_differ)


def _all(values: Any) -> list[str]:
    if isinstance(values, (list, tuple)):
        return [str(v) for v in values]
    return [str(values)] if values else []


def compare(
    *,
    subject: str,
    our_name: str,
    our_attributes: Mapping[str, Any],
    listed: Mapping[str, Any],
) -> Comparison:
    """Compare one of our entities against one watchlist entry.

    ``listed`` is the ``basis`` block recorded on a screening event: caption,
    score, datasets and the identifying properties carried off the watchlist.
    """
    properties: Mapping[str, Any] = listed.get("listed_properties") or {}
    listed_name = str(listed.get("caption") or "")

    fields = [compare_names(our_name, listed_name)]

    fields.append(compare_dates(
        str(our_attributes.get("dob") or ""),
        _all(properties.get("birthDate")),
    ))

    # ``or`` between two property lists is a short circuit, not a union: an entry
    # carrying both a nationality and a country would have had the country
    # discarded. Both answer the same question, so both are compared.
    fields.append(compare_exact(
        "nationality",
        str(our_attributes.get("nationality") or ""),
        _all(properties.get("nationality")) + _all(properties.get("country")),
        "the same country", "different countries",
    ))

    fields.append(compare_exact(
        "identity document",
        str(our_attributes.get("id_document_number") or ""),
        _all(properties.get("passportNumber")) + _all(properties.get("idNumber")),
        "the same document number", "different document numbers",
    ))

    # An alias match is worth surfacing even though it is not a field of ours:
    # "the listed party is also known by our investor's name" changes the read.
    #
    # Matched the same way the primary name field is -- shared parts, not an
    # exact set -- rather than requiring every word of the alias to equal
    # every word of our investor's name. That exact-only check reported
    # "Fatima N." against "Fatima Noor" as no match at all: the same silent
    # discarding of a real partial signal that _best() exists to stop for
    # dates, nationality and document number (see its own docstring). Capped
    # at PARTIAL rather than IDENTICAL/EQUIVALENT regardless of how close the
    # words are: an alias is evidence worth surfacing, not a field of ours
    # being compared like for like.
    # Blank entries are dropped before anything is compared or shown. A
    # watchlist entry carrying an empty alias is ordinary provider data, and
    # both halves of leaving one in were wrong on the officer's screen: the
    # joined list rendered a stray separator, and ``compare_names`` answers
    # UNKNOWN against an empty string -- which "not DIFFERENT" then read as a
    # match, printing "the listed party is also recorded as " with no name
    # after it. Only a real, positive match counts as one, named explicitly
    # rather than by what it is not.
    aliases = [a for a in _all(properties.get("alias")) if a.strip()]
    if aliases:
        best = min((compare_names(our_name, a) for a in aliases),
                  key=lambda r: _RANK[r.verdict])
        matched = best.verdict in (Verdict.IDENTICAL, Verdict.EQUIVALENT,
                                   Verdict.PARTIAL)
        fields.append(FieldComparison(
            "known aliases", our_name, "; ".join(aliases),
            Verdict.PARTIAL if matched else Verdict.DIFFERENT,
            f"the listed party is also recorded as {best.theirs}" if matched
            else "none of the listed aliases match",
        ))

    return Comparison(
        subject=subject,
        our_name=our_name,
        listed_name=listed_name,
        listed_id=str(listed.get("matched_entity") or ""),
        listed_on=tuple(listed.get("datasets") or ()),
        match_score=float(listed.get("score") or 0.0),
        fields=tuple(fields),
    )


def comparison_for(engine, case) -> Optional[Comparison]:
    """Build the comparison for a screening-hit Case, or ``None``.

    Returns ``None`` when the Case is not a screening hit, or when the
    watchlist entry carried nothing to compare beyond a name.
    """
    if case.case_type != "SCREENING_HIT":
        return None
    # The watchlist details live on the screening *event*, not on the finding
    # -- a finding records what a rule concluded, not a copy of its input.
    # Every piece of evidence points back at its event, which is what
    # source_seq is for.
    seqs = {e.source_seq for e in case.evidence}
    basis = next(
        (event.payload.get("basis") for event in engine.log
         if event.seq in seqs and event.payload.get("basis")),
        None,
    )
    if not basis:
        return None
    entity = engine.state.graph.entities.get(case.subject)
    if entity is None:
        return None
    return compare(
        subject=case.subject,
        our_name=entity.name,
        our_attributes=entity.attributes,
        listed=basis,
    )
