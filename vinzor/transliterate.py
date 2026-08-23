"""Spelling a name in Latin letters when it arrived in Devanagari or Arabic.

``romanise.py`` already closes one script gap with a model, and says in its
own docstring which scripts it leaves alone: yente's own normalisation
library, ``rigour``, auto-latinises six scripts on the way into a watchlist
match -- Latin, Cyrillic, Greek, Armenian, Georgian, Hangul -- and stops
there. Devanagari and Arabic are not among them. A fund's own investor book
is not so fortunate: an application form can arrive with an investor's name
written as ``प्रिया शर्मा`` or ``محمد``, and nothing between that field and
the watchlist match puts it into the alphabet the match actually runs in. A
name that never gets latinised is a name that was never really screened,
however clean the result looks.

**This is a table, not a model, and not a lookup of anyone's actual spelling.**
``romanise.py`` reaches for a model because knowing that "Джеремі" is "Jeremy"
is knowing the name, and a table cannot know a name. Devanagari and Arabic are
different: both scripts write most of a word's vowels down (Devanagari as
obligatory vowel signs, Arabic partially, through the letters ا, و and ي), so
a systematic, letter-by-letter reading gets close to a spelling a person would
recognise far more often than a script that omits its vowels entirely could.
Close is not the same as right, and nothing here claims to have looked anyone
up -- it has read the letters on the page, the way ``compare.py``'s own
``transliterate`` reads Cyrillic and Greek, table in, table out, the same
answer every time.

**What this produces is a candidate, and only a candidate.** Wired into
``ask.py`` as the ``transliterate_name`` tool, it hands back one Latin
spelling for a human to weigh -- it does not decide anything, it does not run
:mod:`screening` again, and it never writes a ``SCREENING_COMPLETED`` event.
The only thing that can follow from what this tool says is a person deciding
a re-screen is worth doing, and running one themselves through the ordinary
path. Extra spellings can only add a way for a future comparison to catch a
match it would otherwise miss; nothing here can make an existing match
disappear.

**Devanagari, and how far a table can take it.** Every consonant carries an
inherent "a" unless a vowel sign (a *matra*) replaces it or a virama (्)
removes it outright -- so ``राज`` reads letter by letter as र (ra) + ा (a,
replacing nothing new) + ज (ja), and a table that stopped there would hand
back "Raaja" for a name everyone spells "Raj". The one phonological step this
module *does* take is dropping that trailing inherent "a" when it is the
untouched default vowel of the very last consonant in a word -- exactly the
rule that turns ज at the end of राज into a bare "j" and leaves the same
consonant's "a" alone in the middle of a word or wherever an explicit vowel
sign put it there on purpose. ``कमल`` (bare final ल) becomes "Kamal";
``कमला`` (ल followed by an explicit ा) becomes "Kamala" -- the two spellings
this module is actually built to tell apart. Short and long vowels are not
distinguished -- both अ and आ come out "a", both इ and ई come out "i" -- which
matches how these names are conventionally spelled in Latin script far more
often than a vowel-length-preserving transliteration would.

**What Devanagari here will not do.** It does not delete a schwa anywhere
except that one final position. Real Hindi drops plenty of *medial* schwas
too (मेहता is said, and usually spelled, "Mehta", not the "Mehata" this
produces), governed by a syllable-weight rule that needs more than a table to
apply correctly -- so this module does not attempt it, and a name like that
comes back with an extra vowel a fluent reader would not write. It does not
distinguish the retroflex consonants (ट, ड, ण, ...) from their dental
counterparts (त, द, न, ...) -- both collapse to the same Latin letter, because
ASCII has no second "t" to give one of them. And it does not read anusvara
(ं) as anything but a plain "n", where a fluent speaker nasalises it to match
the consonant that follows -- सिंह, a name spelled "Singh" by everyone who
has ever met a person carrying it, comes back "Sinh".

**Arabic, and a much narrower promise.** Arabic is an abjad: short vowels are
diacritics (*harakat*) that a real name is, in the overwhelming majority of
cases, written *without*. This module reads exactly what is on the page. Where
harakat are present it uses them -- fatha, kasra and damma become a, i and u,
sukun marks the explicit absence of a vowel, and a shadda doubles the letter
it sits on, so a fully-marked ``مُحَمَّد`` comes back "Muhammad", letter and
mark for mark. Where they are absent, as almost every Arabic name in an
ordinary spreadsheet cell will be, there is nothing here to read a vowel from,
and this module does not guess one: ``محمد``, written the way it is written
everywhere outside a Quran or a schoolbook, comes back "Mhmd" -- the honest
consonant skeleton, not an invented name. Recovering "Muhammad" from that
skeleton needs a dictionary of known names or a model that has read enough of
them, which is precisely the vowel-reconstruction problem ``romanise.py``'s
own docstring names as the reason Arabic is not in its table either. The two
letters و and ي are read as the long vowels they most often are in a personal
name (نور reads "Nur", سامي reads "Sami") rather than as the consonants w and
y they occasionally are -- mostly at the start of a word, as in يوسف -- which
is a deliberate bet on the more common case, made and stated rather than left
for someone to discover. The pharyngeal ع has no Latin sound at all and is
approximated as the vowel colour it carries in a name (علي reads "Ali") rather
than dropped silently; the four emphatic consonants (ص ض ط ظ) collapse to
their plain counterparts for the same reason the retroflexes do on the
Devanagari side -- one Latin letter, two Arabic sounds, said so rather than
hidden.

**What this is not.** Not a general Sanskrit or Arabic transliterator, and
not trying to be one -- scoped, as asked, to what a personal name in either
script needs: the vowels, consonants, vowel signs and the handful of
conjuncts (क्ष, ज्ञ and the like fall out of the same virama rule that handles
every other consonant cluster) that actually turn up in one. It holds no
network call, no model, and no clock -- same input, same output, forever,
which is the property every table in this codebase is built to have.
"""

from __future__ import annotations

import unicodedata
from typing import Mapping

# -----------------------------------------------------------------------
# Devanagari
# -----------------------------------------------------------------------

#: Independent vowels -- used when a vowel opens a word or a syllable with no
#: consonant in front of it. Short and long forms of the same vowel share one
#: Latin letter (see the module docstring for why): अ and आ both read "a".
_DEVANAGARI_VOWELS: Mapping[str, str] = {
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}

#: Consonants, each carrying the inherent vowel it has unless a matra or a
#: virama says otherwise -- क is "ka" until something after it says it is not.
#: Dental and retroflex pairs (त/ट, द/ड, न/ण, थ/ठ, ध/ढ) are not
#: distinguished; nor are स, श and ष, which all read "sa"/"sha" as the
#: nearest they have.
_DEVANAGARI_CONSONANTS: Mapping[str, str] = {
    "क": "ka", "ख": "kha", "ग": "ga", "घ": "gha", "ङ": "nga",
    "च": "cha", "छ": "chha", "ज": "ja", "झ": "jha", "ञ": "nya",
    "ट": "ta", "ठ": "tha", "ड": "da", "ढ": "dha", "ण": "na",
    "त": "ta", "थ": "tha", "द": "da", "ध": "dha", "न": "na",
    "प": "pa", "फ": "pha", "ब": "ba", "भ": "bha", "म": "ma",
    "य": "ya", "र": "ra", "ल": "la", "व": "va",
    "श": "sha", "ष": "sha", "स": "sa", "ह": "ha",
    "ळ": "la",
}

#: A dot under a consonant (nukta) marks the Perso-Arabic sounds Hindi and
#: Urdu borrowed into their spelling -- फ़रहान, ज़ोया. Keyed by the *base*
#: consonant character rather than by its rendered text, because several
#: consonants render the same text (ट and त both read "ta") and only the
#: character that was actually written tells them apart.
_DEVANAGARI_NUKTA: Mapping[str, str] = {
    "क": "qa", "ख": "kha", "ग": "gha", "ज": "za",
    "ड": "ra", "ढ": "rha", "फ": "fa", "य": "ya",
}

#: The combining nukta mark itself (़, U+093C). Unicode does give four of
#: these letters a single precomposed codepoint each (क़ is also U+0958), but
#: the composition is on Unicode's own exclusion list -- NFC normalisation
#: takes it apart into base-plus-nukta rather than putting it together -- so
#: reading nukta as a mark that modifies the consonant before it, the same
#: way a matra or a virama does, is the only form that ever actually reaches
#: this function after ``devanagari()`` normalises its input.
_NUKTA = "़"

#: Vowel signs (matras): attach to the *previous* consonant and replace its
#: inherent vowel. Same short/long collapse as the independent vowels above.
_DEVANAGARI_MATRAS: Mapping[str, str] = {
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u",
    "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
}

#: Suppresses the previous consonant's inherent vowel entirely -- what turns
#: दो separate consonants into one cluster, and the mechanism every conjunct
#: in a name (क्ष, ज्ञ, ...) is built from. Nothing special-cases a conjunct;
#: this one rule, applied consonant by consonant, produces every one of them.
_VIRAMA = "्"

#: Nasalises the previous syllable. Read as a plain "n" here -- see the
#: module docstring on सिंह for the case where a fluent reader would not.
_ANUSVARA = "ं"

#: A trailing breathy "h" -- rare in a personal name, common in a Sanskrit
#: religious one (नमः reads "namah").
_VISARGA = "ः"

#: A lighter nasalisation than anusvara, mostly Hindi. Read the same as
#: anusvara: there is no second Latin letter to give it.
_CHANDRABINDU = "ँ"


def _devanagari_word(word: str) -> str:
    """One space-free run of text, Devanagari read wherever it appears.

    Builds a list of ``[text, vowel_is_explicit]`` pairs rather than a plain
    string, because the one phonological rule this module applies -- drop a
    word-final inherent vowel -- has to tell "ज ends this word and nothing
    touched its vowel" apart from "य ends this word and an explicit ा put an
    "a" there on purpose". Both look identical as bare text by the time a
    consonant has been rendered; only the flag remembers which one happened.
    """
    tokens: list = []  # each item: [text_so_far, vowel_is_explicit_or_none]
    last_consonant = ""  # the character behind tokens[-1], for nukta to key on

    for character in word:
        if character in _DEVANAGARI_CONSONANTS:
            tokens.append([_DEVANAGARI_CONSONANTS[character], False])
            last_consonant = character
            continue

        # A matra, a virama or a nukta only means something right after a
        # consonant whose inherent vowel is still sitting there untouched.
        # Anywhere else -- after another matra, at the start of a word --
        # treat it as stray rather than reach backward past what it cannot
        # apply to.
        touches_last = (
            tokens and tokens[-1][1] is False and tokens[-1][0].endswith("a")
        )
        if character == _NUKTA and touches_last and last_consonant in _DEVANAGARI_NUKTA:
            # Replaces the rendering, not the vowel slot: फ़रहान still needs
            # a matra or a virama to be free to act on what comes next, so
            # the inherent vowel stays open (``tokens[-1][1]`` unchanged).
            tokens[-1][0] = _DEVANAGARI_NUKTA[last_consonant]
            continue
        if character == _VIRAMA and touches_last:
            tokens[-1][0] = tokens[-1][0][:-1]
            tokens[-1][1] = None  # a true consonant cluster: no vowel here
            continue
        if character in _DEVANAGARI_MATRAS and touches_last:
            tokens[-1][0] = tokens[-1][0][:-1] + _DEVANAGARI_MATRAS[character]
            tokens[-1][1] = True  # an explicit vowel: never dropped
            continue
        if character in _DEVANAGARI_VOWELS:
            tokens.append([_DEVANAGARI_VOWELS[character], True])
            continue
        if character == _ANUSVARA or character == _CHANDRABINDU:
            tokens.append(["n", True])
            continue
        if character == _VISARGA:
            tokens.append(["h", True])
            continue
        # Not a character this table reads -- a digit, a danda, an already-
        # Latin letter. Passed through rather than dropped, so a name with a
        # stray character loses nothing silently.
        tokens.append([character, True])

    # The one phonological step this module takes: a bare consonant's own
    # inherent vowel, left untouched by anything, is silent when it is the
    # very last sound in the word. See the module docstring on कमल/कमला.
    if tokens and tokens[-1][1] is False:
        tokens[-1][0] = tokens[-1][0][:-1]

    return "".join(text for text, _explicit in tokens)


# -----------------------------------------------------------------------
# Arabic
# -----------------------------------------------------------------------

#: Letters, mapped straight to a Latin rendering -- there is no inherent
#: vowel to manage here as there is in Devanagari, so this table is a plain
#: substitution. و and ي read as the long vowels u and i, which is what they
#: most often are in a personal name (نور, سامي); see the module docstring
#: for the cases -- mostly a word-initial w or y -- where that reads wrong.
#: The four emphatic consonants (ص ض ط ظ) collapse onto their plain
#: counterparts, and ع, which has no Latin sound at all, is approximated as
#: the vowel colour it carries rather than dropped.
_ARABIC_LETTERS: Mapping[str, str] = {
    "ء": "",     # ء hamza alone: a glottal stop, dropped rather than guessed at
    "أ": "a",    # أ alef with hamza above
    "إ": "i",    # إ alef with hamza below
    "آ": "a",    # آ alef madda
    "ؤ": "u",    # ؤ waw with hamza
    "ئ": "i",    # ئ ya with hamza
    "ا": "a",    # ا alef
    "ب": "b", "ت": "t", "ث": "th",     # ب ت ث
    "ج": "j", "ح": "h", "خ": "kh",     # ج ح خ
    "د": "d", "ذ": "dh",                    # د ذ
    "ر": "r", "ز": "z",                     # ر ز
    "س": "s", "ش": "sh",                    # س ش
    "ص": "s", "ض": "d", "ط": "t", "ظ": "z",  # ص ض ط ظ
    "ع": "a",    # ع ayn -- see the module docstring
    "غ": "gh",   # غ ghayn
    "ف": "f", "ق": "q", "ك": "k",      # ف ق ك
    "ل": "l", "م": "m", "ن": "n",      # ل م ن
    "ه": "h",    # ه ha
    "و": "u",    # و waw, read as the long vowel -- see the docstring
    "ي": "i",    # ي ya, read as the long vowel -- see the docstring
    "ة": "a",    # ة ta marbuta -- said as -a in an unbroken name
    "ى": "a",    # ى alef maksura -- a word-final long a
    "ـ": "",     # ـ tatweel: a stretch mark, no sound of its own
}

#: Short-vowel diacritics (harakat). Present on a name only occasionally --
#: formally vowelled text, some religious names -- but read in full when
#: they are there, which is the one case this module can be fully confident
#: in rather than merely plausible. Sukun marks the explicit absence of a
#: vowel; the two are not the same thing and are not conflated.
_ARABIC_HARAKAT: Mapping[str, str] = {
    "َ": "a",   # fatha
    "ِ": "i",   # kasra
    "ُ": "u",   # damma
    "ْ": "",    # sukun: explicitly no vowel here
    "ً": "an",  # fathatan
    "ٍ": "in",  # kasratan
    "ٌ": "un",  # dammatan
}

#: Shadda -- doubles the letter it sits on. Not a letter of its own, and not
#: read through either table above: see ``_arabic_word`` for why it needs to
#: track the letter itself rather than the words immediately behind it.
_SHADDA = "ّ"


def _arabic_word(word: str) -> str:
    """One space-free run of text, Arabic read wherever it appears.

    Simpler than the Devanagari reading because Arabic letters carry no
    inherent vowel to manage: this is concatenation against two tables and a
    doubling rule for shadda -- with one wrinkle shadda alone needs.

    A shadda and the vowel mark riding the same letter do not arrive in a
    fixed typed order -- a name typed with the vowel mark first and one typed
    with the shadda first are both seen in the wild -- but Unicode's own
    canonical ordering does not leave it to chance: every combining mark
    carries a class, fatha's (30) sorts before shadda's (33), and
    ``unicodedata.normalize("NFC", ...)``
    -- which ``arabic()`` always runs first -- reorders both into "letter,
    vowel, shadda" regardless of which order they were typed in. Doubling
    whatever token sits immediately before the shadda, the obvious reading,
    doubles the *vowel* once one is present: مُحَمَّد, which is Muhammad, came
    back "Muhamaad", the second م's "a" repeated rather than the م itself.
    So this tracks *which slot in the output held the last letter*, vowel
    marks included, and re-inserts a copy of that letter there -- ahead of
    any vowel mark already appended after it -- which is what gemination
    actually is: the consonant held twice as long, the vowel said once.
    """
    out: list = []
    last_letter_at = -1  # position in `out` of the most recent letter (not mark)

    for character in word:
        if character == _SHADDA:
            if last_letter_at >= 0:
                out.insert(last_letter_at + 1, out[last_letter_at])
            continue
        mark = _ARABIC_HARAKAT.get(character)
        if mark is not None:
            out.append(mark)
            continue
        letter = _ARABIC_LETTERS.get(character)
        if letter is not None:
            out.append(letter)
            last_letter_at = len(out) - 1
            continue
        # Not Arabic script this table reads -- kept rather than dropped.
        out.append(character)
    return "".join(out)


# -----------------------------------------------------------------------
# What a reader of this module actually calls
# -----------------------------------------------------------------------


def _capitalised(word: str) -> str:
    """A rendered word with its first letter capitalised, wherever it is."""
    for index, character in enumerate(word):
        if character.isalpha():
            return word[:index] + character.upper() + word[index + 1:]
    return word


_DEVANAGARI_BLOCK = range(0x0900, 0x0980)
#: The core Arabic block. Presentation-form ligatures (FB50-FEFF, a legacy
#: of pre-Unicode encodings) are not covered -- a personal name typed today
#: does not need them, and a table that read them would be reading a form no
#: modern keyboard produces.
_ARABIC_BLOCK = range(0x0600, 0x0700)


def _is_devanagari(character: str) -> bool:
    return ord(character) in _DEVANAGARI_BLOCK


def _is_arabic(character: str) -> bool:
    return ord(character) in _ARABIC_BLOCK


def script_of(text: str) -> str:
    """Which script(s) ``text`` is written in, of the two this module reads.

    Returns ``"devanagari"``, ``"arabic"``, ``"mixed"`` when both appear (a
    spreadsheet cell holding two names side by side, say), or ``""`` when
    neither does -- which covers a name already in Latin letters as much as
    one in a script this module was never built for.
    """
    text = text or ""
    has_devanagari = any(_is_devanagari(c) for c in text)
    has_arabic = any(_is_arabic(c) for c in text)
    if has_devanagari and has_arabic:
        return "mixed"
    if has_devanagari:
        return "devanagari"
    if has_arabic:
        return "arabic"
    return ""


def devanagari(text: str) -> str:
    """A Latin candidate spelling of a Devanagari name.

    Anything that is not Devanagari is passed through unchanged, so a name
    already partly in Latin script -- a spreadsheet holding "Priya शर्मा" --
    keeps the half that needed nothing done to it.
    """
    text = unicodedata.normalize("NFC", text or "")
    return " ".join(_capitalised(_devanagari_word(w)) for w in text.split())


def arabic(text: str) -> str:
    """A Latin candidate spelling of an Arabic name. The Devanagari twin."""
    text = unicodedata.normalize("NFC", text or "")
    return " ".join(_capitalised(_arabic_word(w)) for w in text.split())


def romanize(text: str) -> str:
    """The best candidate spelling this module can offer, whichever script.

    Runs both readers in sequence rather than choosing one: each leaves
    anything outside its own script untouched, so a Devanagari name passes
    through the Arabic reader unchanged and an Arabic name passes through
    the Devanagari reader unchanged, and a name already in Latin letters
    comes back exactly as it went in. One function a caller does not have to
    inspect the text to choose between.
    """
    return arabic(devanagari(text or ""))
