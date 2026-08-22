"""What a party of this kind has to produce before it can be onboarded.

``readiness.py`` answers *what does clause 5.4.2 want us to know*, from the
attributes on a record. This answers the question underneath it: **what papers
does this kind of customer actually owe us**, and which of them are still
outstanding.

The two are different, and the difference is clause 5.4.5. A spreadsheet cell
saying an investor was born in 1979 satisfies 5.4.2 and evidences nothing; the
passport behind it is what 5.4.5 asks for. A firm that conflates them has a
book that looks complete and cannot be defended.

**This list is never shown all at once.** An officer handed a form with thirty
fields on it fills in the easy ones and stops. They are told the next thing
that is missing, in their own words, and this module is what knows the answer.

## What is here and what is not

Sourced against the IFSCA AML/CFT/KYC Guidelines and the PML Rules the
Guidelines adopt, on 22 August 2026. Where a requirement rests on a Guidance
Note rather than a numbered clause, or on a document this project has not
pinned by digest, it is marked ``firm_practice`` rather than ``mandatory``.
That distinction is the whole point of the field: a firm should be able to see
which of its own checklist is law and which is its own policy, because only one
of those is arguable with a regulator.

**Seven things this module deliberately does not model**, listed in
``NOT_MODELLED`` and printed with any result rather than left to be inferred
from silence. Each needs data the product does not hold, so none can be
answered by looking harder at what it does.

The most important is the last one: **there is no such thing as a party that
this module can call finished.** It reports what is outstanding against what it
models. Completeness against the whole of Chapter 5 is a person's judgement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from .model import EntityKind


#: Sourced on 22 August 2026 against the pinned AML/CFT/KYC Guidelines and
#: the PML (Maintenance of Records) Rules the Guidelines adopt, by reading
#: the documents rather than by recalling them.
#:
#: **Six things could not be sourced and are therefore not here.** They are
#: listed because a checklist is judged as much by what it leaves out:
#: the FATCA and CRS self-certification, which rests on Income Tax Rule 114H
#: and is tax law rather than these Guidelines; accredited-investor
#: confirmations, whose circular this project has not pinned by digest; the
#: KYC registration agency upload obligation, whose date this product asserts
#: elsewhere and cannot cite; the certification requirements for a copy where
#: originals cannot be produced, which the Guidelines express as "should"
#: rather than "shall"; and whether the Guidance Notes bind in the same way
#: as the numbered clauses, which several obligations here quietly turn on.
#:
#: Anything resting on a Guidance Note is marked ``mandatory=False``. That is
#: the honest reading and it is deliberately the cautious one: a firm should
#: be able to see which half of its own checklist is arguable.
SOURCED_ON = "2026-08-22"


@dataclass(frozen=True)
class Requirement:
    """One thing a party owes, and what would satisfy it."""

    #: Stable identifier. Used as a dedupe key, never shown.
    slug: str
    #: What a person calls it. Shown.
    asks_for: str
    #: Why it is being asked for, in the officer's own vocabulary. Shown
    #: beside the ask, because "we need a utility bill" invites an argument
    #: and "clause 5.4.2 wants a residential address, and a utility bill is
    #: what evidences one" does not.
    because: str
    #: Document kinds from ``documents.KINDS``, any one of which satisfies
    #: this. Empty means nothing on file can satisfy it -- it is a fact
    #: somebody has to assert, not a paper.
    satisfied_by: tuple[str, ...]
    #: True where a numbered clause or rule requires it. False where it is
    #: ordinary practice, or rests on a Guidance Note. Both are collected;
    #: only one is arguable with a regulator.
    mandatory: bool = True
    #: The clause, rule or circular. Empty where this module could not
    #: source one, which is itself worth showing.
    basis: str = ""


def _person(extra: tuple[Requirement, ...] = ()) -> tuple[Requirement, ...]:
    """The natural-person set, shared by every flavour of individual."""
    return (
        Requirement(
            slug="identity",
            asks_for="a photo identity document",
            because="it is the only thing that evidences who this person is, "
                    "rather than what they told us",
            # A voter identity card is named in PML Rules 9(4)(a) alongside
            # the others and was missing from this list, so an investor
            # holding one had nothing on file that could satisfy this.
            #
            # A non-Indian national identity card is deliberately absent.
            # It can be filed and it is read, but clause 1.3.30 and PML
            # Rules 9(4)(a) name what counts as an officially valid
            # document, and a German or Singaporean identity card is not
            # among them. Accepting one here would be this system inventing
            # a rule in the firm's favour, which is the direction that gets
            # a firm into trouble.
            satisfied_by=("passport", "driving_licence", "aadhaar",
                          "voter_id"),
            basis="1.3.30 (what counts as an officially valid document); 5.4.3(c); Annexure II Part B(a); PML Rules 9(4)(a)",
        ),
        Requirement(
            slug="tax_number",
            asks_for="a permanent account number",
            because="clause 5.4.2 wants an identifying number, and this is "
                    "the one an Indian record is built around",
            satisfied_by=("pan_card",),
            basis="Annexure II Part B(b); PML Rules 9(4)(b), which also accepts Form 60 where the customer holds no permanent account number",
        ),
        Requirement(
            slug="address",
            asks_for="proof of the address they live at",
            because="the identity document often carries an old address, and "
                    "clause 5.4.2 asks for the current one",
            satisfied_by=("proof_of_address", "utility_bill",
                          "bank_statement", "aadhaar", "driving_licence",
                          "voter_id"),
            basis="5.4.2(a)(vi), which excludes a post office box; 5.4.3(c); 1.3.30 third proviso",
        ),
        Requirement(
            slug="source_of_funds",
            asks_for="where the money is coming from",
            because="an investor whose funds have no explanation is the "
                    "single most common shape of a laundering file",
            satisfied_by=("source_of_funds", "bank_statement"),
            mandatory=False,
            basis="5.4.1(d) where necessary; 5.6(a)(ii) and 5.5 Guidance Note (2) make it mandatory for a high-risk customer or a politically exposed person",
        ),
    ) + extra


#: Every document a legal person owes on its own account, before anybody
#: looks at the humans behind it.
def _legal(constitution: tuple[str, ...],
           extra: tuple[Requirement, ...] = ()) -> tuple[Requirement, ...]:
    return (
        Requirement(
            slug="existence",
            asks_for="proof that it exists and in what form",
            because="clause 5.4.2(b) asks for the legal form and the date and "
                    "place it was registered, and a name on a letterhead is "
                    "not evidence of any of them",
            satisfied_by=constitution,
            basis="5.4.2(b); 5.4.2(c), which also asks for the legal form, the constitution and the powers that bind the arrangement",
        ),
        Requirement(
            slug="tax_number",
            asks_for="its permanent account number, or the local equivalent",
            because="clause 5.4.2 wants an identifying number for a legal "
                    "person as much as for a natural one",
            satisfied_by=("pan_card",),
            basis="5.4.2(b)(ii)",
        ),
        Requirement(
            slug="address",
            asks_for="its registered or business address",
            because="a registered office that turns out to be a mailbox is a "
                    "risk factor under clause 4.2, and cannot be one until "
                    "somebody has the address",
            satisfied_by=("incorporation", "constitution", "proof_of_address",
                          "utility_bill"),
            basis="5.4.2(b)(iii)",
        ),
        Requirement(
            slug="authority",
            asks_for="proof that whoever signs may sign",
            because="a subscription signed by somebody with no authority to "
                    "sign it is not a subscription",
            satisfied_by=("board_resolution", "power_of_attorney",
                          "constitution"),
            basis="PML Rules 9(3); 5.4.2(c)",
        ),
        Requirement(
            slug="signatory_identity",
            asks_for="photo identity for each authorised signatory",
            because="the person acting for a company is a person, and clause "
                    "5.4.2(a) applies to them exactly as it would if they "
                    "were investing themselves",
            # A voter identity card is named in PML Rules 9(4)(a) alongside
            # the others and was missing from this list, so an investor
            # holding one had nothing on file that could satisfy this.
            #
            # A non-Indian national identity card is deliberately absent.
            # It can be filed and it is read, but clause 1.3.30 and PML
            # Rules 9(4)(a) name what counts as an officially valid
            # document, and a German or Singaporean identity card is not
            # among them. Accepting one here would be this system inventing
            # a rule in the firm's favour, which is the direction that gets
            # a firm into trouble.
            satisfied_by=("passport", "driving_licence", "aadhaar",
                          "voter_id"),
            basis="5.4.2(c); PML Rules 9(3), which asks for the identity of each person authorised to transact",
        ),
        Requirement(
            slug="beneficial_owners",
            asks_for="the natural people behind it, named and evidenced",
            because="clause 1.3.3 is about people, not companies, and a "
                    "structure that stops at another company has not been "
                    "resolved",
            satisfied_by=("ubo_declaration", "register_of_members"),
            basis="1.3.3, 5.4.5",
        ),
        Requirement(
            slug="source_of_funds",
            asks_for="where the money is coming from",
            because="an investor whose funds have no explanation is the "
                    "single most common shape of a laundering file",
            satisfied_by=("source_of_funds", "bank_statement"),
            mandatory=False,
            basis="4.2, 5.6",
        ),
    ) + extra


#: What each kind of customer owes. Read by ``outstanding`` and by nothing
#: else -- a caller wanting "what is missing" should ask the question rather
#: than walk this.
REQUIRED: Mapping[EntityKind, tuple[Requirement, ...]] = {
    EntityKind.PERSON: _person(),
    EntityKind.COMPANY: _legal(("incorporation", "constitution")),
    EntityKind.PARTNERSHIP: _legal(("partnership_deed", "constitution")),
    EntityKind.FUND: _legal(("incorporation", "constitution")),
    EntityKind.TRUST: _legal(
        ("trust_deed", "constitution"),
        extra=(
            Requirement(
                slug="trustee_status",
                asks_for="the trustee's own disclosure that they are acting "
                         "as trustee",
                because="a trustee who does not say so is indistinguishable "
                        "from a beneficial owner, and clause 1.3.3(d) treats "
                        "them very differently",
                satisfied_by=("trust_deed", "ubo_declaration"),
                basis="5.4.4(a) proviso; PML Rules 9(1)(b)",
            ),
        )),
    EntityKind.UNINCORPORATED_BODY: _legal(("constitution",)),
    # A party whose type nobody recorded cannot be asked for anything,
    # because the two lists ask for different things. Establishing the type
    # *is* the outstanding item, and readiness.py says the same.
    EntityKind.UNKNOWN: (
        Requirement(
            slug="kind",
            asks_for="what kind of party this is",
            because="an individual and a trust owe completely different "
                    "documents, and nothing can be asked for until this is "
                    "settled",
            satisfied_by=(),
            basis="1.3.3",
        ),
    ),
}


#: What this module does not model. Printed with any result. Not a backlog
#: and not an apology: a statement of the difference between what was checked
#: and what Chapter 5 asks for, so nobody reads "nothing outstanding" as
#: "onboarded".
NOT_MODELLED: tuple[str, ...] = (
    "whether the copy held was certified, and by whom -- the Guidelines "
    "accept a certified copy and this cannot tell one from a photograph",
    "whether the original was seen, which clause 5.4.5 asks for separately "
    "from holding a copy",
    "the FATCA and CRS self-certification, which is tax law rather than "
    "these Guidelines and is not modelled anywhere in this product",
    "accredited-investor confirmations, where a scheme is offered only to "
    "accredited investors",
    "whether the KYC record was uploaded to a registration agency",
    "any document a firm's own policy requires beyond these",
    "whether the documents held are internally consistent with each other, "
    "which is a person's judgement and not a checklist",
)

NOT_MODELLED_NOTE = (
    "This lists what is outstanding against {count} things that are not "
    "checked here at all, listed with the result. A party with nothing "
    "outstanding is complete against what was measured, which is not the "
    "same as ready to onboard."
).format(count=len(NOT_MODELLED))


@dataclass(frozen=True)
class Outstanding:
    """One thing still owed, ready to be put in front of a person."""

    requirement: Requirement
    #: True where a document of a satisfying kind is on file but nobody has
    #: said what it evidences. A different sentence, and a different remedy:
    #: this one is answered by a person, not by the investor.
    held_but_unevidenced: bool = False


def required_of(kind: Optional[EntityKind]) -> tuple[Requirement, ...]:
    """What a party of this kind owes."""
    if kind is None:
        return REQUIRED[EntityKind.UNKNOWN]
    return REQUIRED.get(kind, REQUIRED[EntityKind.UNKNOWN])


def outstanding(kind: Optional[EntityKind],
                papers: Iterable) -> tuple[Outstanding, ...]:
    """What this party still owes, given the documents on their file.

    ``papers`` is whatever ``documents.Papers`` holds for the subject: each
    needs a ``kind`` and an ``evidences`` collection. A document filed but
    not yet said to evidence anything counts as *held but unevidenced*
    rather than as satisfying the requirement -- that is the whole of clause
    5.4.5 in one branch, and it is the state most books are actually in.

    Pure. Same party and same file, same answer, today and in eleven months
    when somebody asks why this investor was taken on.
    """
    on_file: dict[str, bool] = {}
    for paper in papers or ():
        paper_kind = str(getattr(paper, "kind", "") or "")
        if not paper_kind:
            continue
        evidenced = bool(getattr(paper, "evidences", ()) or ())
        # Any evidenced copy beats an unevidenced one.
        on_file[paper_kind] = on_file.get(paper_kind, False) or evidenced

    still: list[Outstanding] = []
    for requirement in required_of(kind):
        if not requirement.satisfied_by:
            still.append(Outstanding(requirement))
            continue
        held = [k for k in requirement.satisfied_by if k in on_file]
        if any(on_file[k] for k in held):
            continue
        still.append(Outstanding(requirement, held_but_unevidenced=bool(held)))
    return tuple(still)
