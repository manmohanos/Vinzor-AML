"""The same party, entered twice, which splits everything held about them.

Perturbing shapes we detect found this, and it was the cheapest evasion on
the board. Three senders funding one investor opened a file. Enter that
investor twice -- a second folio, a second feeder vehicle, a maiden name --
and the same three payments landed on two records, neither reaching the
threshold, and nothing was said. Cost to whoever wanted that: one extra line
on a spreadsheet.

**That rule was removed on 21 August 2026 with eight others, and this module
was not.** The incident above is why it exists and is left standing as the
record of that, but it is now history rather than a live example: nothing in
the product counts how many senders have paid one investor. What a split
record still halves is everything held about a party -- screening results,
documents, payments, and the risk assessment built on top of them, including
the one payment count that survives, how often money arrived from somebody
other than the investor.

It is worse than an evasion, because it is mostly not one. Books arrive with
duplicates in them. A registrar exports a customer under two folios, an
investor subscribes through two vehicles, somebody marries and the surname
changes. Nobody intended to hide anything, and everything the product holds
about a party is split just the same.

**Reported, never merged.** The obvious response is to resolve the two
records into one, and it is the wrong one. Merging is a derivation, and a
wrong merge is unrecoverable in a log with no undo: two people's payment
histories, screening results and decisions become one person's, and no
later correction can unpick which fact belonged to whom. So this says
"these two look like the same party, and here is what follows if they are"
and leaves the judgement where it belongs.

**What makes a pair worth raising.** Measured, not assumed. Against the
455,219 judgements in the OpenSanctions pairs benchmark, a matching identity
document scored 97.1% precision on its own, while every field used to *rule
a match out* made matching worse. So identifiers are read as corroboration
and never as a veto: a shared permanent account number raises a pair by
itself, a resembling name raises one only when something else agrees, and a
date of birth that disagrees is recorded rather than used to dismiss.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .compare import (Verdict, _name_parts, _sounds_like, compare_dates,
                      compare_exact, compare_names)
from .model import EventType

#: Attributes that identify a party outright. Two records carrying the same
#: one are the same party, near enough that saying so is not a guess. Each
#: is issued by an authority to exactly one holder -- which is why a
#: coincidence here means a data error rather than two people.
IDENTIFIERS = {
    "pan": "permanent account number",
    "cin": "company identity number",
    "lei": "legal entity identifier",
    "id_document_number": "identity document",
    "customer_reference": "customer reference",
}

#: Attributes that corroborate a resembling name without identifying anybody
#: on their own. Plenty of people share a birthday; few share one *and* a
#: name.
CORROBORATING = {
    "dob": "date of birth",
    "date_of_incorporation": "date of incorporation",
    "email": "email address",
    "phone": "telephone number",
}

#: Of those, the ones that belong to a party rather than to a place.
#:
#: A household shares an email address and a telephone number, and so does
#: an office: two of them agreeing is one fact about where somebody lives,
#: not two facts about who they are. A date of birth is not like that.
#:
#: This was found by widening the blocking, which brought a brother and a
#: sister together for the first time -- same surname, same family email,
#: same landline -- and the pair counted three agreeing facts and was
#: raised as possibly one person. Counting had treated a birthday and a
#: shared telephone as interchangeable, and they are not.
PERSONAL = frozenset({"dob", "date_of_incorporation"})

#: A customer reference is issued by the firm, not by an authority, so two
#: records sharing one is ordinary where the firm reuses them across
#: vehicles. It corroborates rather than identifies.
WEAKER = frozenset({"customer_reference"})


@dataclass(frozen=True)
class Resemblance:
    """One pair that may be one party, and what agrees between them."""

    #: Machine addresses. Never displayed.
    left: str
    right: str
    left_name: str
    right_name: str
    #: What agreed, in the words a reader would use.
    agrees: tuple[str, ...]
    #: What disagreed. Recorded rather than used to dismiss the pair --
    #: measurement showed every field used as a veto cost recall.
    disagrees: tuple[str, ...]
    #: True where an authority-issued identifier matched, which is the only
    #: evidence strong enough to stand alone.
    identified: bool
    because: str


@dataclass
class Resemblances:
    """Where to look for a party who may already be on the book.

    Comparing every party to every other is a square of the book and would
    make an import of fifty thousand investors quadratic. Two indexes cut
    that to the handful of records that could plausibly match: one on the
    identifiers, where an exact hit is decisive, and one on how the name
    sounds, which survives spelling.
    """

    by_identifier: dict = field(default_factory=dict)
    by_sound: dict = field(default_factory=dict)
    #: One name part at a time, for the pairs the index above cannot bring
    #: together: a two-part name with one part changed. Capped per part --
    #: see :data:`COMMON_PART`.
    by_part: dict = field(default_factory=dict)

    def apply(self, event: "Any") -> None:
        """Index one party.

        These three dictionaries are mutated where ``state.actors`` is
        rebuilt, and the difference is which readers exist. ``actors`` is
        iterated directly by several modules on request threads, so an
        insertion landing mid-``.items()`` would resize a dict somebody was
        walking. Nothing iterates these: :meth:`candidates` looks keys up
        one at a time and nothing else reads them at all. Rebuilding them
        instead cost the whole index copied on every registration -- with
        distinct names, the case a real client book is, per-party cost
        doubled every time the book doubled. Measured at 0.28ms a party
        over a thousand and 1.09ms over eight thousand: the block claimed
        the quadratic term had been removed, and it had only been moved.
        """
        if event.event_type is not EventType.ENTITY_REGISTERED:
            return
        payload = event.payload or {}
        attributes = payload.get("attributes") or {}

        for key in IDENTIFIERS:
            value = _plain(attributes.get(key))
            if not value:
                continue
            slot = (key, value)
            self.by_identifier[slot] = (
                self.by_identifier.get(slot, frozenset()) | {event.subject})

        name = str(payload.get("name") or "")
        for key in sounds_of(name):
            self.by_sound[key] = (
                self.by_sound.get(key, frozenset()) | {event.subject})

        for part in parts_of(name):
            group = self.by_part.get(part, frozenset())
            if group is None:
                continue                      # already too common to mean much
            group = group | {event.subject}
            self.by_part[part] = (None if len(group) > COMMON_PART else group)

    def candidates(self, name: str, attributes: Mapping,
                   excluding: str) -> frozenset:
        """Everyone already on the book who could be this party.

        Identifiers first and without limit: a shared permanent account
        number is exact, the group holding one is tiny, and it is the
        strongest evidence available.

        Names after, and rarest first. This ordering is not tidiness, it
        was measured: with the groups taken in any order, eight thousand
        investors with ordinary three-part Indian names took a minute and a
        half to load and the cost was still climbing, because a group like
        "rajesh + kumar" grows with the book and every new party was
        compared against all of it. Sorting by size spends the budget on
        the groups that mean something -- a name pair shared by four people
        says something, one shared by four hundred says only that the name
        is common.
        """
        found: set = set()
        for key in IDENTIFIERS:
            value = _plain(attributes.get(key))
            if value:
                found |= self.by_identifier.get((key, value), frozenset())

        # Ranked by how many of this name's groups each record turns up
        # in, and this is the whole of why the budget is safe. Ordering by
        # anything else meant ordering by record reference, which decided
        # whether a duplicate was found by where its reference happened to
        # sort: on a book of five thousand common names, the same pair was
        # found under one reference and missed under another. Nothing about
        # a compliance rule should depend on that.
        #
        # Overlap is the right order because it is what being a duplicate
        # looks like. Two records for one person share every part of the
        # name and so turn up in every group; a namesake shares one part
        # and turns up in one. Counting is cheap -- it is the comparing
        # that is not -- so every candidate is counted and only the best
        # are compared.
        tally: dict = {}
        for key in sounds_of(name):
            for other in self.by_sound.get(key, frozenset()):
                tally[other] = tally.get(other, 0) + 1

        # Then the records that share only one part of the name, and only
        # where that part is rare enough to mean something. Two shared
        # parts is the ordinary shape of a duplicate and the index above
        # finds it -- but a name with only two usable parts, one of which
        # changed, shares exactly one, and that is the shape of a marriage
        # ("Priya Raghavan" to "Priya Menon"), an initial ("R. Kumar"), a
        # two-word company gaining a suffix, and a name transliterated
        # another way. Measured before this existed: four of sixteen real
        # duplicate shapes were never compared at all, including the
        # marriage this module's own opening paragraph is about.
        singles: dict = {}
        for part in parts_of(name):
            group = self.by_part.get(part)
            if not group:      # unheard of, or too common to be evidence
                continue
            for other in group:
                singles[other] = singles.get(other, 0) + 1

        # Ties broken by reference so that replaying a log compares the
        # same records in the same order. Unrepeatable is not acceptable.
        #
        # Two shared parts always outranks one, whatever the counts, which
        # is why these are two lists and not one tally: a record that
        # shares half a dozen common single parts is not better evidence
        # than one that shares a name outright, and letting the counts
        # compete would have said it was.
        ranked = sorted(tally.items(), key=lambda pair: (-pair[1], pair[0]))
        ranked += sorted(singles.items(), key=lambda pair: (-pair[1], pair[0]))
        for other, _shared in ranked:
            if len(found) >= MOST_TO_COMPARE:
                break
            found.add(other)
        return frozenset(found - {excluding})


def _plain(value) -> str:
    """An identifier with the punctuation and case a form invites removed."""
    if value in (None, ""):
        return ""
    return "".join(ch for ch in str(value) if ch.isalnum()).upper()


#: How many parts of a name are used for blocking. A name with more parts
#: than this is not rarer for it, and every extra one multiplies the keys.
MOST_PARTS = 6

#: How many records one new party is compared against by name. A stated
#: limit rather than a hidden one, and the reason it exists is arithmetic:
#: without it the work grows with the square of the book, so a firm's
#: fiftieth thousand investor costs fifty times what their thousandth did.
#:
#: What it can cost: two records that share only a very common name, carry
#: no identifier between them, and would have been raised on two other
#: fields agreeing. Records sharing an authority-issued number are never
#: affected, because those are matched exactly and before this applies.
MOST_TO_COMPARE = 40

#: How many parties may share a single part of a name before that part
#: stops being evidence of anything. A surname four people share is a lead;
#: one four hundred share says only that the surname is common, and the
#: cost of tallying it is the cost blocking on pairs was introduced to
#: remove. Past this the part is marked common and stops being indexed at
#: all, so neither the tallying nor the group itself can grow without
#: bound.
#:
#: What it can cost: two records sharing one very common name part, no
#: identifier, and nothing else to bring them together -- "R. Kumar" and
#: "Rajesh Kumar" on a book of four hundred Kumars. That pair is not
#: findable from the name, by this product or any other; it needs the
#: permanent account number, which is matched exactly and before any of
#: this applies.
COMMON_PART = 25


def parts_of(name: str) -> list:
    """The parts of a name, as they sound, in a stable order.

    Parts shorter than three letters are dropped: they are initials and
    particles ("R.", "al", "de", "van"), which sound like too much to be
    evidence. It is a real cost and worth naming -- it is why "Kim Ho"
    reduces to one usable part -- but keeping them would put every party
    with an initial into one enormous group.
    """
    return sorted({_sounds_like(part) for part in _name_parts(name)
                   if len(part) > 2})[:MOST_PARTS]


def sounds_of(name: str) -> frozenset:
    """How a name sounds, as blocking keys: every *pair* of its parts.

    Parts rather than the whole, because the whole is what changes -- a
    married name, an initial where a middle name was, a company that gains
    "Private Limited". But single parts as keys does not survive a real
    book, and this was measured rather than guessed: blocking on one part
    at a time, five thousand investors with ordinary Indian surnames took
    six minutes to load, because every Kumar was compared against every
    other Kumar. The cost grows with the book, so fifty thousand would take
    hours.

    Pairs fix it without losing anything. Two records are only brought
    together if they share *two* name parts, so "Rajesh Kumar" and "Amit
    Kumar" never meet, while "Priya Raghavan" and "Priya Raghavan Menon"
    still do. The duplicates this rule exists to find keep at least two
    parts in common by construction -- that is what makes them duplicates
    rather than namesakes.
    """
    parts = parts_of(name)
    if not parts:
        return frozenset()
    if len(parts) == 1:
        return frozenset(parts)
    return frozenset(f"{first}+{second}"
                     for index, first in enumerate(parts)
                     for second in parts[index + 1:])


def _attributes_of(graph, entity_id: str) -> Mapping:
    entity = graph.entities.get(entity_id)
    return dict(getattr(entity, "attributes", {}) or {})


def compare(graph, left: str, right: str) -> Optional[Resemblance]:
    """Whether these two records may be one party, and what says so."""
    ours = _attributes_of(graph, left)
    theirs = _attributes_of(graph, right)
    left_name = graph.name_of(left)
    right_name = graph.name_of(right)

    agrees: list[str] = []
    disagrees: list[str] = []
    identified = False
    personal = False

    for key, plain in IDENTIFIERS.items():
        mine, yours = _plain(ours.get(key)), _plain(theirs.get(key))
        if not mine or not yours:
            continue
        if mine == yours:
            agrees.append(f"the same {plain}")
            if key not in WEAKER:
                identified = True
        elif key not in WEAKER:
            disagrees.append(f"a different {plain}")
        # A differing firm-issued reference is *what a duplicate looks
        # like* -- two folios for one person is the commonest way a book
        # ends up holding somebody twice. Reporting it as evidence against
        # the pair reverses the meaning of the only fact in the file that
        # is not in dispute.

    named = compare_names(left_name, right_name)
    same_name = named.verdict in (Verdict.IDENTICAL, Verdict.EQUIVALENT)
    # A name that is part of the other name, rather than the whole of it.
    # The two commonest duplicates a real book carries are exactly this
    # shape -- somebody marries and gains a surname, a company gains
    # "Private Limited" -- so refusing to look at them would miss most of
    # what this rule exists for. It is weaker evidence than a name that
    # matches outright, and asks for more agreeing with it below.
    part_of_the_name = named.verdict is Verdict.PARTIAL
    if same_name:
        agrees.append("the same name"
                      if named.verdict is Verdict.IDENTICAL
                      else "names that are versions of one another")
    elif part_of_the_name:
        agrees.append("one name contained in the other")

    for key, plain in CORROBORATING.items():
        mine = str(ours.get(key) or "").strip()
        yours = str(theirs.get(key) or "").strip()
        if not mine or not yours:
            continue
        if key in ("dob", "date_of_incorporation"):
            verdict = compare_dates(mine, yours).verdict
        else:
            verdict = compare_exact(plain, mine, [yours],
                                    "same", "different").verdict
        if verdict is Verdict.IDENTICAL:
            agrees.append(f"the same {plain}")
            if key in PERSONAL:
                personal = True
        elif verdict is Verdict.DIFFERENT:
            disagrees.append(f"a different {plain}")

    # An identifier issued by an authority stands alone. A name needs
    # something with it: books carry two people called Rajesh Kumar, and
    # raising every such pair would teach an officer to dismiss the lot.
    #
    # Half a name in common is what cousins have, so it needs two things
    # with it -- and one of them has to belong to the party rather than to
    # their address. A brother and sister share a surname, a family email
    # and a landline, which counts to three and means nothing; a woman who
    # married shares her given name and her birthday, which counts to two
    # and means a great deal. Counting alone could not tell those apart.
    worth_raising = (identified
                     or (same_name and len(agrees) >= 2)
                     or (part_of_the_name and personal and len(agrees) >= 3))
    if not worth_raising:
        return None

    because = (f"{left_name} and {right_name} may be the same party: "
               + _listed(agrees))
    if disagrees:
        because += f". Against that, they have {_listed(disagrees)}"
    return Resemblance(left=left, right=right, left_name=left_name,
                       right_name=right_name, agrees=tuple(agrees),
                       disagrees=tuple(disagrees), identified=identified,
                       because=because + ".")


def _listed(parts) -> str:
    parts = list(parts)
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def look(graph, resemblances, entity_id: str) -> tuple:
    """Everyone already on the book this party may already be."""
    attributes = _attributes_of(graph, entity_id)
    name = graph.name_of(entity_id)
    found = []
    for other in sorted(resemblances.candidates(name, attributes,
                                                excluding=entity_id)):
        pair = compare(graph, entity_id, other)
        if pair is not None:
            found.append(pair)
    return tuple(found)


def over_the_book(engine) -> tuple:
    """Every resembling pair on the whole book, each reported once.

    For the report rather than the queue. The queue sees a pair the moment
    the second record arrives; this answers the question an officer asks
    once, before an inspection: how much of this book is the same people
    counted twice.
    """
    graph = engine.state.graph
    resemblances = engine.state.resemblances
    seen: set = set()
    found = []
    for entity_id in sorted(graph.entities):
        for pair in look(graph, resemblances, entity_id):
            key = tuple(sorted((pair.left, pair.right)))
            if key in seen:
                continue
            seen.add(key)
            found.append(pair)
    return tuple(found)
