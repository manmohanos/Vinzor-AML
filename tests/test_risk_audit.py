"""What the risk block claims, tested against the clauses themselves.

The block said "Next: nothing structural", which is the kind of sentence
worth attacking. Two things were wrong with it.

**It enforced two clauses it could not cite.** Ten modules told officers
what clauses 5.4.2 and 5.11 require -- the dossier, the export, the CLI,
the assistant, the readiness screen -- in the product's own words, with no
verified extract anywhere. That is the paraphrase-in-a-docstring the whole
register exists to replace, sitting beside twenty-four clauses each matched
against the regulator's PDF on every build. Both are registered now, and
both are checked by the same machinery as the rest.

**And "measured against clause 5.4.2" was a larger claim than the code.**
The clause has three limbs. Limb (c) requires a firm to identify the legal
form, constitution and powers of a company or arrangement, and to identify
*and screen* its connected parties; two qualifiers inside (a) and (b) ask
for aliases, a trading name, a principal place of business, and an address
that is not a post office box. None of that was measured, and nothing said
so. It is now named in ``readiness.NOT_MEASURED`` and printed with every
result.

What held: the nineteen factors are nineteen, the eight-and-eleven split is
right, the review intervals are the clause's own numbers including the
proviso most readers would miss, and the category is never computed.
"""

from __future__ import annotations

import pytest

from vinzor import readiness
from vinzor.citations import CLAUSES
from vinzor.risk import EVERY_YEARS, EVERY_YEARS_IN_GROUP, FACTORS


@pytest.fixture(scope="module")
def guidelines():
    from vinzor import pdftext
    from vinzor.citations import held

    source = held("IFSCA-AML-2022")
    if not source.path.exists():
        pytest.skip("no copy of the guidelines is kept")
    return pdftext.pages(source.path)


# -- the clauses this block enforces are now clauses it can cite -------------


@pytest.mark.parametrize("clause_id", ["5.4.2", "5.11"])
def test_the_clause_this_block_enforces_is_in_the_register(clause_id):
    """Neither was, for weeks, while both were quoted to officers from ten
    different modules. A rule the product enforces and cannot cite is the
    one thing ``citations.py`` was written to make impossible."""
    assert clause_id in CLAUSES
    clause = CLAUSES[clause_id]
    assert clause.doc_id == "IFSCA-AML-2022"
    assert clause.page and clause.extract


def test_the_review_intervals_are_the_ones_the_clause_prints(guidelines):
    """Not "roughly annually" -- the clause names three numbers and this
    holds those three."""
    from vinzor import pdftext

    assert EVERY_YEARS == {"HIGH": 1, "MEDIUM": 3, "LOW": 5}
    assert pdftext.find(
        "(i) Annually- for high-risk customers; (ii) once in three years- for "
        "medium risk customer; and (iii) once in every five years- for "
        "low-risk customers.", guidelines) == CLAUSES["5.11"].page


def test_the_proviso_most_readers_would_miss_is_modelled(guidelines):
    """A second schedule on the same page gives a *longer* cycle to a
    resident Indian customer already known to the Financial Group in India.
    Longer, not shorter -- so a firm applying the ordinary schedule to such
    a customer is early rather than late, which is the safe direction and
    the reason this is easy to read past."""
    from vinzor import pdftext

    assert EVERY_YEARS_IN_GROUP == {"HIGH": 2, "MEDIUM": 8, "LOW": 10}
    assert all(EVERY_YEARS_IN_GROUP[k] > EVERY_YEARS[k] for k in EVERY_YEARS)
    assert pdftext.find(
        "(a) once in every two years - for high-risk customers, (b) once in "
        "every eight years - for medium risk customers, and (c) once in every "
        "ten years - for low-risk customers.", guidelines) is not None


# -- what the readiness check does not measure, said out loud ----------------


def test_the_unmeasured_parts_of_the_clause_are_named():
    """"Measured against clause 5.4.2" was true of two limbs out of three,
    and nothing anywhere said which two."""
    named = {clause for clause, _what in readiness.NOT_MEASURED}
    assert "5.4.2(c)" in named
    assert len(readiness.NOT_MEASURED) >= 5
    for clause, what in readiness.NOT_MEASURED:
        assert clause.startswith("5.4.2")
        assert len(what) > 20, "a gap named too briefly to act on"


def test_the_connected_parties_limb_is_the_one_that_matters_most():
    """Limb (c) does not only ask a firm to record something. It asks it to
    *screen* the connected parties of a legal person, which is an
    obligation of a different kind from a missing field."""
    said = dict(readiness.NOT_MEASURED)["5.4.2(c)"]
    assert "connected parties" in said
    assert "screen" in said


def test_the_note_travels_with_every_result():
    said = readiness.NOT_MEASURED_NOTE
    assert str(len(readiness.NOT_MEASURED)) in said
    assert "against the whole clause" in said


def test_what_is_measured_and_what_is_not_do_not_overlap():
    """A gap that is both measured and declared unmeasured would mean the
    two lists had drifted, and a reader could not tell which was true."""
    measured = {clause for clause, _what, _keys in
                readiness.FOR_A_PERSON + readiness.FOR_A_LEGAL_PERSON}
    declared = {clause for clause, _what in readiness.NOT_MEASURED}
    assert measured & declared == {
        "5.4.2(a)(i)", "5.4.2(a)(vi)", "5.4.2(b)(i)", "5.4.2(b)(iii)"}, (
        "the overlap should be exactly the four limbs that are measured in "
        "part -- a name without its aliases, an address without the post "
        "office box test, and so on")
    assert "5.4.2(c)" not in measured


# -- and what held ------------------------------------------------------------


def test_the_nineteen_factors_are_nineteen_and_split_where_the_block_says():
    """The block's own numbers, checked rather than trusted."""
    assert len(FACTORS) == 19
    assert len([f for f in FACTORS if f.we_can_look]) == 8
    assert len([f for f in FACTORS if not f.we_can_look]) == 11


def test_every_factor_points_at_a_real_limb_of_the_clause():
    """The wordings are lightly rendered -- the clause's slashes become
    words and its interrogative opener is dropped -- so they are not all
    verbatim. What must hold is that each one is a limb 4.2 actually
    has."""
    refs = [f.ref for f in FACTORS]
    assert len(set(refs)) == len(refs), "two factors share a reference"
    assert all(ref.startswith("4.2(") for ref in refs)
    for group in ("a", "b", "c"):
        assert any(f".2({group})(" in ref for ref in refs)


def test_a_category_is_never_reached_without_a_person(engine):
    """The design the block rests on. Nothing in the module computes a
    category, so there is no path by which a party acquires one from the
    records alone -- 4.2 itself says the factors "may not always indicate a
    high risk"."""
    import inspect

    import vinzor.risk as risk

    source = inspect.getsource(risk)
    for banned in ("def compute_category", "def suggest_category",
                   "def assign_category"):
        assert banned not in source
    # And the reason is the regulator's, not ours. Both sentences the module
    # shows an officer about public office are now registered clauses
    # checked against the PDF, rather than assertions about what the
    # guidelines "say".
    assert "5.5 Guidance Note (4)" in CLAUSES
    assert "should not automatically treat" in CLAUSES[
        "5.5 Guidance Note (4)"].extract
