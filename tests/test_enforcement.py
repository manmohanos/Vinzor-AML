"""The scorecard, and the rule that it must keep telling the truth.

These tests are unusual: several of them assert that the product is *bad* at
something. That is deliberate. The scorecard exists to stop us quietly
believing we cover more than we do, and a scorecard nobody can fail is
decoration.
"""

from __future__ import annotations

import pytest

from vinzor.enforcement import (
    ACTIONS,
    COVERAGE,
    PUBLISHED_ACTIONS,
    Ground,
    Level,
    roadmap,
    scorecard,
    would_surface,
)


def test_every_recorded_action_is_attributable():
    for action in ACTIONS:
        assert action.entity and action.date and action.conduct and action.outcome
        assert action.source, f"{action.entity} has no source"
        assert action.grounds, f"{action.entity} has no grounds"


def test_the_orders_actually_read_are_marked_as_such():
    """Two orders have been read at source; the rest are still summaries."""
    score = scorecard()
    assert score.read_from_primary == 2
    primary = [a for a in ACTIONS if a.read_from_primary]
    for action in primary:
        assert "IFSCA Order" in action.source
        assert "F.No." in action.source
    assert score.read_from_primary < score.scored, "do not claim more than was read"


def test_the_gap_between_known_and_scored_stays_visible():
    """25 actions exist on IFSCA's own list; we hold detail on fewer."""
    score = scorecard()
    assert score.published == PUBLISHED_ACTIONS == 25
    assert score.scored < score.published


def test_every_ground_has_an_assessed_position():
    used = {g for a in ACTIONS for g in a.grounds}
    assert used <= set(COVERAGE)
    for ground, capability in COVERAGE.items():
        assert capability.position
        if capability.level is Level.NONE:
            assert capability.needs, f"{ground.value} does not say what to build"
        else:
            assert capability.caveat or capability.level is Level.FULL


def test_coverage_improved_as_the_roadmap_was_worked_through():
    """0 of 8, then 7 of 8 with scope and governance, now 8 of 8 with the
    calendar. Each step was chosen by the enforcement record, not by us.
    """
    score = scorecard()
    assert score.would_surface == 8
    assert score.scored == 8


def test_partial_coverage_is_never_counted_as_full():
    """Half of them are caught only in part, and every one says so.

    A score of 8 out of 8 would be a lie without this. Governance surfaces
    the empty seat, not the empty room; the calendar carries three
    obligations, not every return IFSCA wants.
    """
    score = scorecard()
    assert score.partial_only == 4
    assert COVERAGE[Ground.GOVERNANCE].level is Level.PARTIAL
    assert "empty room" in COVERAGE[Ground.GOVERNANCE].caveat


def test_the_karvy_pattern_is_now_surfaced_in_part():
    """Registration cancelled for quarterly reports never filed."""
    karvy = next(a for a in ACTIONS if "Karvy" in a.entity)
    assert would_surface(karvy)
    assert COVERAGE[Ground.REPORTING].level is Level.PARTIAL
    assert "AML/CFT returns" in COVERAGE[Ground.REPORTING].caveat
    # The other half of why it was cancelled is now built -- and still
    # would not have saved Karvy, which is the point of the caveat. The
    # show cause notice was served by affixture because post and e-mail
    # both failed, so there was nobody to type it in. A firm that has
    # stopped opening its post is not a firm any of this reaches.
    assert Ground.COOPERATION in karvy.grounds
    assert COVERAGE[Ground.COOPERATION].level is Level.PARTIAL
    assert "affixture" in COVERAGE[Ground.COOPERATION].caveat


def test_the_fme_governance_case_is_now_surfaced_but_only_in_part(seeded_check=None):
    """Neo Asset Management: we would see the empty seat, not the shut door."""
    fmes = [a for a in ACTIONS if a.entity_type == "Fund Management Entity"]
    governance = [a for a in fmes if Ground.GOVERNANCE in a.grounds]
    assert governance
    action = governance[0]
    assert would_surface(action)
    assert action.read_from_primary
    assert "Regulation 7(4)" in action.conduct and "7(5)" in action.conduct


def test_the_roadmap_is_ordered_by_what_has_actually_cost_someone():
    """Empty now, and the ordering still has to hold when it refills.

    Every ground has something built against it, so there is nothing left
    to order. The property under test is the one that matters when a new
    ground is added or a capability is honestly downgraded: what the
    regulator has acted on most often comes first, and nothing appears
    that already has something built for it.
    """
    items = roadmap()
    counts = [count for _, count, _ in items]
    assert counts == sorted(counts, reverse=True)
    for ground, _, needs in items:
        assert COVERAGE[ground].level is Level.NONE
        assert needs


def test_every_ground_now_has_something_built_against_it():
    """The roadmap is empty, and emptying it is not the same as finishing.

    Four of the seven are *partial*, and each says in its own caveat what
    it cannot do -- an empty room, a firm that stopped opening its post, a
    figure this system cannot audit, a misclassification inside accounts
    it never sees. The list is empty because there is nothing with
    *nothing* built for it, which is a much smaller claim.
    """
    assert list(roadmap()) == []
    assert all(ground in COVERAGE for ground in Ground)
    assert any(COVERAGE[ground].level is Level.PARTIAL for ground in Ground)
    # Every partial one has to say what it still cannot do. A partial with
    # no caveat is a full one that has not been checked.
    for ground in Ground:
        if COVERAGE[ground].level is Level.PARTIAL:
            assert COVERAGE[ground].caveat
