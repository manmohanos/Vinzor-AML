"""A starting point for a risk category, and the ways it must not become one.

Most of this file is guardrails rather than behaviour, and deliberately: the
weights will be retuned by somebody who is not reading this docstring, and the
properties that make a scorecard defensible under clause 4.2 have to survive
that. Each one is written against the whole table rather than against the
numbers as they stand today.
"""

from __future__ import annotations

import itertools

import pytest

from vinzor.risk import FACTORS, Assessment, Observation
from vinzor.scorecard import (
    HIGH,
    HIGH_AT,
    LOW,
    MEDIUM,
    MEDIUM_AT,
    MOST_ONE_FACTOR_MAY_WEIGH,
    SCORECARD,
    WEIGHTS,
    band_for,
    propose,
    propose_for,
)


def seen(*refs, absent=(), by=""):
    """Observations with these refs present, those absent, rest unassessed."""
    found = {ref: Observation(ref=ref, present=True, because="because",
                              answered_by=by) for ref in refs}
    found.update({ref: Observation(ref=ref, present=False) for ref in absent})
    return found


# -- the guardrails ----------------------------------------------------------


def test_no_single_factor_can_propose_a_high_category():
    """Clause 4.2 closes by saying the presence of one or more factors "may
    not always indicate a high risk". A scorecard where one observation
    reaches the high band is that sentence with extra steps.

    Written against every weight in the table rather than against the ones
    chosen today, so retuning cannot quietly break it.
    """
    for ref, weight in WEIGHTS.items():
        assert weight <= MOST_ONE_FACTOR_MAY_WEIGH, (
            f"{ref} weighs {weight}, enough to reach the high band alone")
        assert propose(seen(ref)).band != HIGH, (
            f"{ref} alone proposed HIGH")


def test_the_high_band_is_reachable_from_real_combinations():
    """The opposite failure, and the one the EBA guidelines warn about: a
    scorecard tuned so nothing ever scores high is a scorecard that has
    stopped doing its job. Reachable in principle is not enough -- this
    checks it is reachable from combinations of factors that actually
    co-occur."""
    reachable = [
        combination for size in range(2, 5)
        for combination in itertools.combinations(WEIGHTS, size)
        if propose(seen(*combination)).band == HIGH
    ]
    assert reachable, "no combination of factors reaches HIGH"
    assert min(len(c) for c in reachable) <= 3, (
        "the high band needs four or more factors at once, which on a real "
        "book means it is never reached")


def test_every_band_is_reachable():
    assert band_for(0) == LOW
    assert band_for(MEDIUM_AT) == MEDIUM
    assert band_for(HIGH_AT) == HIGH
    assert band_for(HIGH_AT + 100) == HIGH


def test_the_bands_do_not_overlap_or_leave_a_gap():
    seen_bands = [band_for(points) for points in range(0, HIGH_AT + 3)]
    assert seen_bands[0] == LOW and seen_bands[-1] == HIGH
    # Once it rises it never falls back: a scorecard where more evidence
    # produced a lower band would be indefensible in a single sentence.
    order = {LOW: 0, MEDIUM: 1, HIGH: 2}
    assert all(order[a] <= order[b]
               for a, b in zip(seen_bands, seen_bands[1:]))


def test_an_unassessed_factor_is_never_counted_as_absent():
    """The oldest mistake in this codebase, in its most respectable clothes:
    scoring silence as absence is how a customer nobody examined reads as a
    customer with nothing wrong."""
    nothing = propose({})
    assert nothing.points == 0
    assert len(nothing.unassessed) == len(FACTORS), (
        "a factor nobody answered was treated as answered")
    assert nothing.thin

    # An explicit "no" is answered, and so is not unassessed.
    answered_no = propose(seen(absent=tuple(WEIGHTS)))
    assert answered_no.points == 0
    assert not set(WEIGHTS) & set(answered_no.unassessed)


def test_thinness_is_measured_over_what_this_scorecard_can_weigh():
    """The first version of this measured against all nineteen factors and
    was wrong in a way worth keeping a test for.

    Eleven of clause 4.2's factors can only be answered by a person, so a
    party whose records had answered seven of the eight scorable ones --
    nearly everything the arithmetic can know -- was still reported as
    resting on very little. A caveat that fires on every customer is a
    caveat nobody reads by the second week, and here it would have been
    understating a real signal on a genuinely opaque company.
    """
    one = propose(seen("4.2(b)(v)"))
    assert one.thin, "one of eight weighed is thin"

    nearly = propose(seen("4.2(a)(ii)",
                          absent=tuple(r for r in WEIGHTS
                                       if r != "4.2(a)(ii)" and r != "4.2(c)(vi)")))
    assert nearly.weighed == len(WEIGHTS) - 1
    assert not nearly.thin, (
        "seven of eight weighed is not resting on very little, even though "
        "eleven of nineteen clause factors still need a person")
    assert len(nearly.unassessed) > len(WEIGHTS), (
        "the factors a person must answer are still carried, not forgotten")


def test_the_factors_this_scorecard_weighs_are_the_ones_records_can_answer():
    """The two sets must stay the same set. A weight on a factor only a
    person can answer would make ``thin`` unreachable -- every party would
    read as resting on very little forever, because the records can never
    close that gap on their own."""
    observable = {f.ref for f in FACTORS if f.we_can_look}
    assert set(WEIGHTS) == observable, (
        "the scorecard weighs something the records cannot answer, or "
        "ignores something they can")


def test_a_present_factor_this_scorecard_does_not_weigh_is_still_shown():
    """Noticed and not scored is different from not looked at, and an officer
    reading the proposal is entitled to tell them apart."""
    unweighted = next(f.ref for f in FACTORS if f.ref not in WEIGHTS)
    found = propose(seen(unweighted))
    assert found.points == 0
    assert unweighted in found.present_but_unweighted
    assert unweighted not in found.unassessed, "it was answered, not skipped"


# -- what it proposes --------------------------------------------------------


def test_a_sanctioned_jurisdiction_and_opaque_ownership_reaches_high():
    found = propose(seen("4.2(b)(v)", "4.2(b)(iv)", "4.2(a)(ii)"))
    assert found.band == HIGH
    assert found.points == 3 + 3 + 2


def test_one_structural_signal_alone_stays_low():
    assert propose(seen("4.2(a)(ii)")).band == LOW


def test_the_arithmetic_is_shown_not_just_the_answer():
    """An officer asked to agree with a band is entitled to see what made it,
    and an examiner asking in two years needs the same."""
    found = propose(seen("4.2(b)(iii)", "4.2(c)(iv)"))
    assert {c.ref for c in found.counted} == {"4.2(b)(iii)", "4.2(c)(iv)"}
    assert sum(c.weight for c in found.counted) == found.points
    assert all(c.because for c in found.counted)


def test_a_proposal_records_which_scorecard_made_it():
    """A firm asked in two years why this customer was rated medium answers
    with the scorecard as it stood, not as it stands."""
    assert propose({}).scorecard == SCORECARD


def test_who_answered_a_factor_travels_with_its_contribution():
    found = propose(seen("4.2(b)(v)", by="Meera Nair"))
    assert found.counted[0].answered_by == "Meera Nair"


def test_a_party_nobody_has_assessed_proposes_low_and_says_why(engine):
    """LOW on no evidence is what the arithmetic says. It is not a finding,
    and the proposal carries the sentence that stops it being read as one."""
    found = propose_for(None)
    assert found.band == LOW
    assert found.thin
    assert found.weighed == 0
    assert len(found.unassessed) == len(FACTORS)


def test_a_proposal_reads_an_assessment_as_it_stands():
    held = Assessment(entity_id="p1",
                      observations=seen("4.2(b)(v)", "4.2(b)(iv)"))
    assert propose_for(held).band == MEDIUM


# -- what it must not do -----------------------------------------------------


def test_the_scorecard_cannot_record_anything():
    """The category is a person's, recorded through assess_risk and gated as
    a decision is. This module has no engine to write to -- structurally,
    not by convention.

    Read as a syntax tree rather than as text. The first version of this
    grepped the source and failed on its own docstring, which names
    ``engine.assess_risk`` to explain where the category actually goes --
    prose about a boundary is not a crossing of it, and a test that cannot
    tell the difference trains somebody to stop writing the prose.
    """
    import ast
    import inspect

    from vinzor import scorecard

    tree = ast.parse(inspect.getsource(scorecard))
    forbidden = {"ingest", "assess_risk", "decide", "record_filing"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            named = node.func
            name = (named.attr if isinstance(named, ast.Attribute)
                    else getattr(named, "id", ""))
            assert name not in forbidden, (
                f"{name}() is called here, which would let this establish a "
                f"category rather than propose one")
        # An engine cannot be reached even by name: nothing in this module
        # takes one, so nothing in it can hold one.
        if isinstance(node, ast.arg):
            assert node.arg != "engine", (
                "this module takes an engine, so it can reach the log")


def test_every_weighted_ref_is_a_real_clause_factor():
    """A weight against a ref that no longer exists in the register would
    score nothing and say nothing about it -- silent dead weight in a table
    an examiner may read."""
    known = {factor.ref for factor in FACTORS}
    unknown = set(WEIGHTS) - known
    assert not unknown, f"weights for factors that do not exist: {unknown}"
