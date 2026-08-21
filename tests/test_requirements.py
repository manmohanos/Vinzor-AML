"""What a party of this kind owes, and what is still outstanding.

The distinction under test is clause 5.4.5: a document on file that nobody
has said anything about does not satisfy a requirement. It is a different
state from missing, it has a different remedy -- a person answers it, not the
investor -- and most real books are full of it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from vinzor.documents import KINDS
from vinzor.model import EntityKind
from vinzor.requirements import (
    NOT_MODELLED,
    REQUIRED,
    Requirement,
    outstanding,
    required_of,
)


@dataclass(frozen=True)
class Filed:
    """Stands in for documents.Paper: the two fields this reads."""

    kind: str
    evidences: tuple = ()


def slugs(items):
    return {o.requirement.slug for o in items}


# -- the lists themselves ----------------------------------------------------


def test_every_customer_type_owes_something():
    """A kind with an empty list would be a party this product silently
    considers finished the moment it is created."""
    for kind in EntityKind:
        assert required_of(kind), f"{kind} owes nothing"


def test_every_requirement_names_documents_that_exist():
    """A requirement satisfied by a document kind the cabinet cannot store
    is a requirement nothing can ever satisfy -- and it would read on screen
    as an investor who will not send their papers."""
    for kind, reqs in REQUIRED.items():
        for req in reqs:
            for satisfies in req.satisfied_by:
                assert satisfies in KINDS, (
                    f"{kind.value}/{req.slug} wants {satisfies!r}, "
                    f"which is not a document this system can hold")


def test_every_requirement_says_why_in_the_officers_words():
    """The ask is refused by investors far less often when it carries the
    reason, and the reason is a compliance sentence rather than ours."""
    for reqs in REQUIRED.values():
        for req in reqs:
            assert len(req.because) > 30
            assert not req.because.endswith(".")
            assert req.asks_for[0].islower(), "shown mid-sentence"


def test_a_requirement_that_cannot_be_sourced_says_so_rather_than_inventing():
    """The register refuses to fabricate a citation and so does this. An
    empty basis is honest; a plausible-looking wrong one is not."""
    for reqs in REQUIRED.values():
        for req in reqs:
            assert isinstance(req.basis, str)
            if req.mandatory:
                assert req.basis, f"{req.slug} claims to be law and cites none"


def test_the_limits_are_stated_rather_than_left_to_be_inferred():
    assert len(NOT_MODELLED) >= 5
    assert any("certified" in n for n in NOT_MODELLED)


# -- what is outstanding -----------------------------------------------------


def test_a_party_with_nothing_on_file_owes_everything():
    still = outstanding(EntityKind.PERSON, [])
    assert slugs(still) == {r.slug for r in REQUIRED[EntityKind.PERSON]}


def test_an_evidenced_document_settles_its_requirement():
    still = outstanding(EntityKind.PERSON,
                        [Filed("passport", ("name", "dob", "nationality"))])
    assert "identity" not in slugs(still)


def test_a_document_on_file_that_evidences_nothing_does_not_settle_it():
    """Clause 5.4.5 in one branch. The passport is in the cabinet and
    nobody has said what it proves, so the firm holds a scan rather than
    a verified identity."""
    still = outstanding(EntityKind.PERSON, [Filed("passport", ())])
    identity = next(o for o in still if o.requirement.slug == "identity")
    assert identity.held_but_unevidenced is True


def test_held_but_unevidenced_is_not_reported_as_missing():
    """Different state, different remedy: this one is answered by an
    officer looking at a document already on the file, not by writing to
    the investor again. Reporting it as missing sends the wrong letter."""
    still = outstanding(EntityKind.PERSON, [Filed("passport", ())])
    missing = [o for o in still if not o.held_but_unevidenced]
    assert "identity" not in {o.requirement.slug for o in missing}


def test_any_one_of_the_satisfying_kinds_will_do():
    """Address is evidenced by a utility bill or a bank statement or an
    Aadhaar. Demanding a particular one is a firm's policy, not the rule."""
    for kind in ("utility_bill", "bank_statement", "aadhaar"):
        still = outstanding(EntityKind.PERSON, [Filed(kind, ("address",))])
        assert "address" not in slugs(still), kind


def test_an_evidenced_copy_beats_an_unevidenced_one_of_the_same_kind():
    """Two scans of the same passport, one looked at. The file is answered."""
    still = outstanding(EntityKind.PERSON,
                        [Filed("passport", ()), Filed("passport", ("name",))])
    assert "identity" not in slugs(still)


def test_a_company_is_asked_for_the_people_behind_it():
    still = outstanding(EntityKind.COMPANY, [])
    assert "beneficial_owners" in slugs(still)
    assert "signatory_identity" in slugs(still)


def test_a_trust_is_asked_for_the_trustees_own_disclosure():
    """1.3.3(d) treats a trustee and a beneficial owner very differently,
    and a trustee who does not say which they are is indistinguishable."""
    assert "trustee_status" in {r.slug for r in REQUIRED[EntityKind.TRUST]}


def test_an_unrecorded_kind_is_asked_only_what_kind_it_is():
    """Nothing else can be asked for until this is settled, because an
    individual and a trust owe completely different documents."""
    still = outstanding(EntityKind.UNKNOWN, [])
    assert slugs(still) == {"kind"}


def test_establishing_the_kind_is_not_satisfiable_by_a_document():
    still = outstanding(EntityKind.UNKNOWN, [Filed("passport", ("name",))])
    assert slugs(still) == {"kind"}


def test_the_same_file_gives_the_same_answer_twice():
    """Deterministic, because an onboarding that changes its mind between
    two readings of the same file is not evidence of anything."""
    papers = [Filed("passport", ("name",)), Filed("pan_card", ())]
    first = outstanding(EntityKind.PERSON, papers)
    second = outstanding(EntityKind.PERSON, papers)
    assert [(o.requirement.slug, o.held_but_unevidenced) for o in first] == \
           [(o.requirement.slug, o.held_but_unevidenced) for o in second]


def test_a_junk_paper_cannot_satisfy_anything():
    """'other' evidences nothing, by design, and must not quietly close a
    requirement because it happens to be on the file."""
    still = outstanding(EntityKind.PERSON, [Filed("other", ("name",))])
    assert slugs(still) == {r.slug for r in REQUIRED[EntityKind.PERSON]}
