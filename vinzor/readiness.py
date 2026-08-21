"""Whether a firm's client book is complete enough to hand over.

From 1 September 2026 every regulated entity in GIFT IFSC must upload each
client's KYC record to an IFSCA-registered KYC Registration Agency within
three working days of completing the diligence, and must upload its
existing book by 30 October. The first and, so far, only registered agency
is CDSL Ventures, on a portal separate from its domestic one.

Almost every firm will discover the same thing when they try: the book they
have is not the book the upload wants. Fields were never collected, dates
are missing, a party has a name and nothing else. Finding that out in
October is a bad way to find it out.

So this module reads a workspace and says, party by party, what is missing.

**What it measures, and what it does not.** The IFSC agency's own file
layout is not a document we hold, and inventing a field list and calling it
"the KRA format" would be exactly the guessing this product refuses
everywhere else. What is measured instead is clause 5.4.2 of the IFSCA
guidelines -- the regulator's own list of the identification information a
Regulated Entity **shall obtain at least** -- which is upstream of any
upload: a record missing what 5.4.2 requires is not ready for anybody,
whatever schema it is eventually poured into.

Two consequences of that honesty are stated on the report itself rather
than buried here: passing this check does not mean a file will be accepted,
and the agency may want more.

The clause distinguishes natural persons from legal persons and
arrangements, and so does this. A trust has no date of birth and a person
has no place of incorporation; a check that asked both of everybody would
produce a page of failures that mean nothing.

**And it measures two of the clause's three limbs.** That was true from the
first version and was not written down anywhere until 20 August 2026, which
made "measured against clause 5.4.2" a larger claim than the code. Limb (c)
and two qualifiers inside (a) and (b) are not checked, they are listed in
:data:`NOT_MEASURED`, and the list is printed wherever the result is. A
book this module calls ready is ready against the parts of 5.4.2 a
spreadsheet can answer, which is not the same as ready against 5.4.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from .model import EntityKind

#: Clause 5.4.2(a): what a Regulated Entity shall obtain at least for a
#: natural person. Each entry is (sub-clause, what a reader calls it, the
#: attributes any one of which satisfies it).
FOR_A_PERSON: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("5.4.2(a)(i)", "a full name", ("name",)),
    ("5.4.2(a)(ii)", "an identifying number",
     ("id_document_number", "pan", "customer_reference")),
    ("5.4.2(a)(iii)", "a date of birth", ("dob",)),
    ("5.4.2(a)(iv)", "a nationality", ("nationality",)),
    ("5.4.2(a)(v)", "a legal domicile",
     ("jurisdiction", "country_of_residence")),
    ("5.4.2(a)(vi)", "a residential address", ("address",)),
    ("5.4.2(a)(vii)", "contact details", ("phone", "email")),
)

#: Clause 5.4.2(b): the same, for a legal person or legal arrangement.
FOR_A_LEGAL_PERSON: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("5.4.2(b)(i)", "a full name", ("name",)),
    ("5.4.2(b)(ii)", "an identifying number",
     ("cin", "lei", "id_document_number", "pan", "customer_reference")),
    ("5.4.2(b)(iii)", "a registered or business address", ("address",)),
    ("5.4.2(b)(iv)", "a date of incorporation or registration",
     ("date_of_incorporation",)),
    ("5.4.2(b)(v)", "a place of incorporation or registration",
     ("country_of_incorporation", "jurisdiction")),
)

#: What clause 5.4.2 asks for that this module does not look at.
#:
#: Not a backlog and not an apology -- a statement, printed with every
#: result, of the difference between what was checked and what the clause
#: says. Each of these needs data the product does not collect, so none of
#: them can be answered by looking harder at the records we have.
NOT_MEASURED: tuple[tuple[str, str], ...] = (
    ("5.4.2(a)(i)", "any aliases a person is also known by"),
    ("5.4.2(a)(vi)", "whether the address given is a post office box, which "
                     "the clause does not accept"),
    ("5.4.2(b)(i)", "a trading name, where it differs from the full name"),
    ("5.4.2(b)(iii)", "a principal place of business, where it differs from "
                      "the registered address"),
    ("5.4.2(c)", "the legal form, constitution and powers of a company or "
                 "arrangement, and its connected parties -- whom the clause "
                 "also requires to be screened"),
)

#: One sentence a reader meets beside any count of what is missing.
NOT_MEASURED_NOTE = (
    "This checks the parts of clause 5.4.2 a record can answer. It does not "
    "check {count} other things the clause asks for, listed with the result, "
    "so a party counted as complete here is complete against what was "
    "measured rather than against the whole clause."
).format(count=len(NOT_MEASURED))


#: A party whose type nobody recorded cannot be measured against either
#: list, because the two lists ask for different things. That is itself the
#: finding: the type has to be established before anything else can be.
UNKNOWN_KIND_GAP = (
    "1.3.3", "what kind of party this is", ())


def _requirements(kind: Optional[EntityKind]):
    if kind is EntityKind.PERSON:
        return FOR_A_PERSON
    if kind in (EntityKind.COMPANY, EntityKind.PARTNERSHIP, EntityKind.TRUST,
                EntityKind.FUND, EntityKind.UNINCORPORATED_BODY):
        return FOR_A_LEGAL_PERSON
    return ()


@dataclass(frozen=True)
class Gap:
    """One thing clause 5.4.2 requires that this party does not have."""

    clause: str
    what: str


@dataclass(frozen=True)
class Standing:
    """One party, and whether its record could be handed over."""

    entity_id: str
    name: str
    kind: str
    gaps: tuple[Gap, ...]
    #: Items the record *has* and nothing supports. Clause 5.4.2 asks a
    #: firm to hold the data; clause 5.4.5 asks it to verify identity from
    #: reliable, independent sources. A column in a spreadsheet is the
    #: first and not the second, and the distinction was invisible until
    #: documents could be filed -- so every party on this book looked
    #: equally well evidenced, which none of them was.
    unsupported: tuple[Gap, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.gaps

    @property
    def evidenced(self) -> bool:
        """Held *and* backed by a document that has not lapsed."""
        return not self.gaps and not self.unsupported


@dataclass
class Readiness:
    """The whole book, measured."""

    parties: tuple[Standing, ...] = ()
    #: Gap counts by clause, so a firm can see that one missing column
    #: explains most of the shortfall rather than reading four hundred rows.
    by_clause: Mapping[str, int] = field(default_factory=dict)

    @property
    def ready(self) -> tuple[Standing, ...]:
        return tuple(p for p in self.parties if p.ready)

    @property
    def short(self) -> tuple[Standing, ...]:
        return tuple(p for p in self.parties if not p.ready)


def _has(entity, attribute: str) -> bool:
    """Whether this one field is filled in."""
    if attribute == "name":
        return bool(str(entity.name or "").strip())
    return bool(str((entity.attributes or {}).get(attribute) or "").strip())


def _held(entity, names) -> bool:
    attributes = entity.attributes or {}
    for attribute in names:
        if attribute == "name":
            if str(entity.name or "").strip():
                return True
            continue
        if str(attributes.get(attribute) or "").strip():
            return True
    return False


def measure(engine, only=None, today: str = "") -> Readiness:
    """Read the workspace and report what each party is missing.

    ``only`` limits the check to particular parties; by default the whole
    book is measured, because the October obligation is over the whole book.

    ``today`` is needed only to tell a live document from a lapsed one. It
    is supplied rather than read, like every other date here; without one,
    nothing is reported as unsupported, because a question about whether a
    passport has run out cannot be answered without a date.
    """
    parties = []
    counted: dict = {}
    papers = getattr(engine.state, "papers", None)

    for entity_id, entity in engine.state.graph.entities.items():
        if only is not None and entity_id not in only:
            continue
        wanted = _requirements(entity.kind)
        if not wanted:
            gaps = (Gap(clause=UNKNOWN_KIND_GAP[0], what=UNKNOWN_KIND_GAP[1]),)
            unsupported: tuple = ()
        else:
            gaps = tuple(
                Gap(clause=clause, what=what)
                for clause, what, attributes in wanted
                if not _held(entity, attributes)
            )
            backed = (papers.supporting(entity_id, today)
                      if papers is not None and today else {})
            unsupported = tuple(
                Gap(clause=clause, what=what)
                for clause, what, attributes in wanted
                if _held(entity, attributes)
                # The supported field must also be one the party actually
                # holds. A passport says it evidences an identity document
                # number; where the party's identifying number is a tax
                # number instead, the passport has evidenced nothing about
                # what is on this record.
                and not any(key in backed and _has(entity, key)
                            for key in attributes)
            ) if today else ()
        for gap in gaps:
            counted[gap.clause] = counted.get(gap.clause, 0) + 1
        parties.append(Standing(
            entity_id=entity_id,
            name=entity.name,
            kind=str(entity.kind),
            gaps=gaps,
            unsupported=unsupported,
        ))

    parties.sort(key=lambda p: (len(p.gaps) == 0, p.name))
    return Readiness(parties=tuple(parties), by_clause=counted)
