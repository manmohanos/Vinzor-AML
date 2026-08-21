"""Asking a model how a name is spelled in Latin letters, and nothing else.

Twenty-nine pairs an OpenSanctions analyst judged to be the same person are
still closed as different, and the table cannot reach them. "Штудгальтер
Джеремі Ерік Каміль" is a Latin name written in Ukrainian: a table returns
"shtudgalter dzheremi erik kamil", which is a faithful letter-for-letter
rendering and not what anybody wrote on the passport, "Jeremy Eric Camille
Studhalter".

Knowing that Джеремі is Jeremy is not transliteration. It is knowing the name.
That is what a language model has and a lookup table does not, so this asks
one -- for the spelling, and for nothing else.

**What it is allowed to do.** Return additional Latin spellings of a name.
That is the whole contract. It is never asked whether two parties are the same
person, never shown the other side of a comparison, and never given a decision
to make. The comparison that follows is the same deterministic code as before,
reading one more candidate spelling.

**Why that is safe.** Extra spellings can only add ways for two records to
match. A verdict is the best across every spelling, so an answer from the
model can move a pair from DIFFERENT towards a match and can never move one
the other way. The failure mode of a wrong answer is a pair that reaches a
human who then dismisses it -- never a sanctioned party quietly cleared.

**What is checked before any of it is used.** A reply must be Latin letters,
must carry about as many parts as the name it came from, must not be longer
than a name plausibly is, and must not contain digits or punctuation a name
does not have. A model that invents a person, returns prose, or hands back the
question is discarded and the table's answer stands. Nothing here can fail
open: with no model configured, or a model that errors, the behaviour is
exactly what it was before this file existed.

**What it costs.** One call per distinct name that is not already Latin, and
the answer is cached for the life of the process. A firm whose book is mostly
Latin names may make none at all.

**Whether it is worth switching on: measured, and mostly not.** This is off by
default, and the numbers are the reason rather than caution.

On the comparison, it recovered 4 of the 29 pairs still being closed -- 99.3%
to 99.4% -- from nine calls taking about four seconds each. The romanisations
themselves are good: "Штудгальтер Джеремі Ерік Каміль" comes back as
"Studhalter Jeremy Eric Camille", which is exactly right and exactly what the
table cannot do.

On the search it buys almost nothing, for a reason worth knowing before
anybody builds on this: OpenSanctions already carries a Latin alias beside the
Cyrillic one. Screening 61 listed people recorded in another script, a Latin
spelling of the name found 60 of them. The problem this was built for is
already solved upstream, by people who solved it properly.

So the deterministic work did 306 of the 335, and a model does a little of the
rest. It stays here, tested and ready, because a firm whose book is mostly
Arabic or Chinese would find a different answer -- neither script is in the
table at all -- and because the measurement should be repeatable rather than
remembered. It is not wired into screening, and turning it on should follow a
measurement on that firm's own book, not this paragraph.
"""

from __future__ import annotations

import json
import re
from typing import Callable, Mapping, Optional, Sequence

from .compare import transliterate

#: The model is asked for spellings, in a shape that leaves no room to answer
#: a different question. No entity is named, no comparison is implied, and the
#: words "match", "same person" and "sanctions" do not appear -- the last one
#: removed after a test objected: naming the domain tells the model what the
#: answer is for, and it does not need to know to spell a name.
INSTRUCTIONS = """You romanise personal names. You are given one name, \
possibly written in a non-Latin script. Reply with a JSON object:

  {"spellings": ["...", "..."]}

Give up to three ways this same name is commonly written in the Latin \
alphabet, most likely first. Where a part of the name is a Latin name that has \
been written in another script, give the Latin name it came from -- \
"Джеремі" is "Jeremy", not "Dzheremi". Where a name is Slavic, give the \
spellings an official document would use.

Give only spellings of the name you were given. Add no titles, no notes, no \
other people, and no explanation. If you cannot romanise it, reply \
{"spellings": []}."""

#: A name, once romanised. Anything outside this is not a name and is refused.
_LATIN_NAME = re.compile(r"^[A-Za-z][A-Za-z '\-\.]{0,79}$")

#: How many spellings are read from a reply, however many it offers.
MOST_SPELLINGS = 3


def already_latin(name: str) -> bool:
    """Whether the name arrived in Latin letters in the first place.

    Asks of the name as written, not of the table's output: the table turns
    Cyrillic into Latin by construction, so testing what it produced answered
    "yes, always" and the model was never once called.
    """
    return all(ord(c) < 0x250 for c in (name or ""))


def acceptable(original: str, offered: str) -> bool:
    """Whether an offered spelling is a spelling of the name that was asked.

    Deliberately crude. This is not judging whether the romanisation is good;
    it is refusing replies that are not romanisations at all -- prose, a
    different person, an apology, the question repeated back.
    """
    candidate = (offered or "").strip()
    if not _LATIN_NAME.match(candidate):
        return False
    parts_in = len([p for p in (original or "").split() if p])
    parts_out = len(candidate.split())
    if not parts_in or abs(parts_out - parts_in) > 1:
        return False
    # A romanisation of a name is about as long as the name. Twice its length
    # means something was added to it.
    return len(candidate) <= max(24, len(original) * 2)


def spellings(name: str, ask: Optional[Callable] = None,
              cache: Optional[dict] = None) -> tuple:
    """Latin spellings of ``name``: the table's, then the model's if asked.

    The table's answer is always first and always present, so a caller reading
    only the first entry behaves exactly as it did before.
    """
    table = transliterate(name or "").strip()
    found = [table] if table else []

    if ask is None or already_latin(name):
        return tuple(found)

    if cache is not None and name in cache:
        return tuple(found + [s for s in cache[name] if s not in found])

    extra: list = []
    try:
        reply = ask([
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": name},
        ])
        offered = (reply or {}).get("spellings")
        if isinstance(offered, Sequence) and not isinstance(offered, str):
            for candidate in list(offered)[:MOST_SPELLINGS]:
                if isinstance(candidate, str) and acceptable(name, candidate):
                    cleaned = candidate.strip()
                    if cleaned not in found and cleaned not in extra:
                        extra.append(cleaned)
    except Exception:
        # A model that is unreachable, slow, or answering in a shape this does
        # not recognise leaves the table's answer standing. Screening does not
        # stop because a convenience is unavailable.
        extra = []

    if cache is not None:
        cache[name] = extra
    return tuple(found + extra)
