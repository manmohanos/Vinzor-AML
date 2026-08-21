"""End to end against the real synthetic dataset.

These lock the fixtures the dataset was built to provide -- and they derive
them from the edge table rather than trusting the generator's own conclusions.
"""

from __future__ import annotations

import pytest

from vinzor.graph import Conclusion
from vinzor.model import EntityKind, Severity
from vinzor.seed import DEFAULT_DATASET, seed

pytestmark = pytest.mark.skipif(
    not DEFAULT_DATASET.exists(), reason="synthetic dataset not present"
)


@pytest.fixture(scope="module")
def seeded():
    return seed()


def test_the_whole_dataset_loads_and_the_chain_verifies(seeded):
    assert len(seeded.log) > 1000
    assert seeded.verify() == (True, None)


def test_seeding_is_reproducible():
    """Same dataset in, byte-identical log out. No clock, no ordering wobble."""
    a, b = seed(), seed()
    assert [e.event_hash for e in a.log] == [e.event_hash for e in b.log]
    assert sorted(a.state.casebook.cases) == sorted(b.state.casebook.cases)


def test_state_is_a_pure_replay_of_the_dataset(seeded):
    assert seeded.rebuild().casebook.cases == seeded.state.casebook.cases


# -- the fixtures the dataset promises -------------------------------------


def test_the_three_hop_chain_resolves_to_fifty_six_percent(seeded):
    """100% x 80% x 70%, computed from edges.csv.

    ``ubochains.json`` asserts the same 56% but cites hops that are not in the
    edge table, written in the wrong direction. The number here is derived, and
    the path it reports is one that actually exists.
    """
    result = seeded.state.graph.resolve_ubo("cmp_0006")
    assert result.conclusion is Conclusion.IDENTIFIED
    assert result.owners[0].person_id == "per_0001"
    assert result.owners[0].effective_percentage == 56.0
    assert result.owners[0].paths == (("cmp_0006", "cmp_0005", "cmp_0004", "per_0001"),)


def test_the_ownership_cycle_is_found(seeded):
    result = seeded.state.graph.resolve_ubo("cmp_0001")
    assert result.conclusion is Conclusion.INCOMPLETE
    assert result.cycles
    ring = set(result.cycles[0])
    assert {"cmp_0001", "cmp_0002", "cmp_0003"} <= ring


def test_the_cycle_also_opened_a_case(seeded):
    cycle_cases = [
        c
        for c in seeded.state.casebook.cases.values()
        if any(e.policy_id == "POL_UBO_CYCLE" for e in c.evidence)
    ]
    assert len(cycle_cases) == 1
    assert cycle_cases[0].severity is Severity.MEDIUM


def test_the_payment_rules_derive_what_the_dataset_contains(seeded):
    """One payment rule is derived, and on this dataset it opens nothing.

    This test used to say that five of six payment findings were worked out
    from the payment itself, and name the two that were correctly silent
    here. After 21 August 2026 there are two payment rules, and only one of
    them is derived.

    The derived one is THIRD_PARTY, and it needs a feed that distinguishes
    who paid from whose commitment was met. This dataset does not have one:
    ``seed.py`` makes the payment's subject the payer, so the two are always
    equal and there is nothing to compare. That is a correct silence and not
    a broken rule, but it does mean the rule this whole payment category now
    rests on is invisible on the demonstration book.

    So every payment file on this dataset is a declared sanctioned payer --
    the one payment finding that is an input rather than a derivation.
    """
    fired = {
        e.policy_id
        for c in seeded.state.casebook.cases.values()
        for e in c.evidence
        if e.policy_id
    }
    assert "POL_PAY_SANCTIONED_PAYER" in fired
    assert "POL_PAY_THIRD_PARTY" not in fired
    assert {p for p in fired if p.startswith("POL_PAY")} == {
        "POL_PAY_SANCTIONED_PAYER"}


def test_no_derived_payment_rule_fires_on_this_dataset(seeded):
    """What replaced the strongest check this file had.

    That check was: the generator labelled 29 payments as having no
    identifiable source and 38 as overpayments, and the rules -- which read
    no label -- found exactly those numbers. It was the strongest evidence
    available that the rules derive rather than believe, because the numbers
    were arrived at independently and agreed.

    Both rules were removed on 21 August 2026, and the derived rule that
    remains cannot fire here for the reason given above. There is nothing
    left to agree with the dataset, and this test says so out loud rather
    than being deleted, because an absent check that nobody can see is how a
    product ends up believing it still measures something.
    """
    from collections import Counter

    fired = Counter(
        e.policy_id
        for c in seeded.state.casebook.cases.values()
        for e in c.evidence
        if e.policy_id
    )
    assert fired["POL_PAY_UNKNOWN_SOURCE"] == 0
    assert fired["POL_PAY_OVERPAYMENT"] == 0
    assert fired["POL_PAY_THIRD_PARTY"] == 0
    assert fired["POL_PAY_SANCTIONED_PAYER"] == 8


def test_the_book_opens_the_number_of_files_it_opens(seeded):
    """The size of the demonstration book, written down so a change to it is
    a decision rather than a surprise.

    206 open files before 21 August 2026, of which 158 were payments: 83 an
    unexpected currency, 38 an overpayment, 29 no recorded sender and 8 a
    sanctioned payer. Nine payment rules were removed that day and 150 of
    those files went with them.

    56 now. The 8 that remain are the declared sanctioned payers, and they
    are the whole payment category on this book.
    """
    from collections import Counter

    cases = seeded.state.casebook.cases.values()
    assert sum(1 for c in cases if c.is_open) == 56
    by_type = Counter(c.case_type for c in cases)
    assert by_type["PAYMENT_MISMATCH"] == 8


def test_all_three_watchlists_produce_cases(seeded):
    fired = {
        e.policy_id
        for c in seeded.state.casebook.cases.values()
        for e in c.evidence
        if e.policy_id
    }
    assert {"POL_SANCTIONS_HIT", "POL_PEP_HIT", "POL_ADVERSE_MEDIA"} <= fired


def test_a_pep_hit_lands_on_a_person_not_only_a_company_director(seeded):
    """FATF's PEP guidance (Recommendations 12 & 22) is about a politically
    exposed *individual* as the customer. Every PEP hit the generator built
    before this fix targeted a COMPANY ('one of its directors is a PEP'), so
    a fund LP who is themselves a serving or former public official never
    appeared -- the single most common real-world PEP scenario was entirely
    absent from the dataset.
    """
    pep_hits = [
        e
        for c in seeded.state.casebook.cases.values()
        for e in c.evidence
        if e.policy_id == "POL_PEP_HIT"
    ]
    assert pep_hits
    assert any(
        seeded.state.graph.kind_of(e.detail.get("entity")) is EntityKind.PERSON
        for e in pep_hits
    )


def test_the_ubo_chain_and_cycle_companies_are_shells_in_a_secrecy_jurisdiction(seeded):
    """FATF and the Egmont Group's 'Concealment of Beneficial Ownership'
    (2018) find layered shell companies registered in a secrecy jurisdiction
    the dominant technique for hiding a true owner -- the report's single
    most repeated red flag. Before this fix, the dataset's two flagship UBO
    fixtures (the three-hop chain and the ownership cycle) sat at whatever
    is_shell/jurisdiction value they happened to draw at random and could
    just as easily have looked like an ordinary, transparent group.
    """
    layered = ("cmp_0001", "cmp_0002", "cmp_0003", "cmp_0004", "cmp_0005", "cmp_0006")
    for entity_id in layered:
        attrs = seeded.state.graph.entities[entity_id].attributes
        assert attrs["is_shell"] == "1"
        assert attrs["jurisdiction"] == "KY"


# -- invariants that must hold over the whole corpus -----------------------


def test_every_case_traces_back_to_a_real_event(seeded):
    seqs = {e.seq for e in seeded.log}
    for case in seeded.state.casebook.cases.values():
        assert case.evidence
        for evidence in case.evidence:
            assert evidence.source_seq in seqs


def test_nothing_is_decided_until_a_human_decides_it(seeded):
    """Ingest alone never closes a Case, however obvious the answer looks."""
    assert all(c.is_open for c in seeded.state.casebook.cases.values())


def test_the_queue_is_led_by_the_most_severe_work(seeded):
    queue = seeded.queue()
    assert queue[0].severity is Severity.CRITICAL
    ranks = [c.severity.rank for c in queue]
    assert ranks == sorted(ranks, reverse=True)


def test_derived_conclusions_from_the_dataset_are_not_ingested(seeded):
    """UBO and TRANSACTION alerts are the generator's answers, not observations.

    They are re-derived here, so they must not appear as screening evidence.
    """
    screening_rules = {
        e.detail.get("matched_rule")
        for c in seeded.state.casebook.cases.values()
        for e in c.evidence
        if e.policy_id in {"POL_SANCTIONS_HIT", "POL_PEP_HIT", "POL_ADVERSE_MEDIA"}
    }
    assert not {"NO_SINGLE_UBO", "UBO_CYCLE"} & screening_rules
