"""Policies: what opens a Case, at what severity, and what does not."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vinzor.model import EventType, Severity

from conftest import WHEN, commits, company, owns, paid, person, screened, trust_of


# -- screening -------------------------------------------------------------


@pytest.mark.parametrize(
    "list_type,severity,policy_id",
    [
        ("SANCTIONS", Severity.CRITICAL, "POL_SANCTIONS_HIT"),
        ("PEP", Severity.HIGH, "POL_PEP_HIT"),
        ("ADVERSE_MEDIA", Severity.MEDIUM, "POL_ADVERSE_MEDIA"),
    ],
)
def test_watchlist_match_opens_a_case(engine, list_type, severity, policy_id):
    person(engine, "p1", "Alice")
    result = screened(engine, "p1", list_type)

    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.severity is severity
    assert case.case_type == "SCREENING_HIT"
    assert case.evidence[0].policy_id == policy_id


def test_a_clean_screening_opens_nothing(engine):
    person(engine, "p1")
    assert screened(engine, "p1", "SANCTIONS", matched=False).cases == []


def test_an_unrecognised_list_still_opens_a_case_for_a_human_to_triage(engine):
    """A real match this register cannot name used to vanish entirely.

    OpenSanctions' own topic taxonomy has categories -- ``role.rca``,
    ``debarment``, ``reg.warn``, ``crime.*``, ``wanted``, ``asset.frozen`` --
    that are none of SANCTIONS, PEP or ADVERSE_MEDIA. ``screening.py`` records
    a match against any of them as ``list_type: "WATCHLIST"`` rather than
    guessing a category, and ``screening_hit`` used to return nothing at all
    for it: the fact was in the log, ``matched: true`` and everything, and no
    Case, no queue entry and no briefing line ever pointed at it. Silently
    ignoring it was indistinguishable, to the officer, from there being no
    match. It still does not guess a specific severity or clause -- it opens
    a Case on the chapeau risk-assessment obligation, the same one this file
    already uses for exactly this problem at ADVERSE_MEDIA, so a human sees it
    and decides what it actually is.
    """
    person(engine, "p1", "Alice")
    case = screened(engine, "p1", "SOME_NEW_LIST").cases[0]
    assert case.case_type == "SCREENING_HIT"
    assert case.severity is Severity.MEDIUM
    assert case.evidence[0].policy_id == "POL_WATCHLIST_HIT_UNCLASSIFIED"
    assert {c["clause"] for c in case.evidence[0].citations} == {"4.2", "5.6"}


def test_a_watchlist_match_with_no_list_type_at_all_still_opens_a_case(engine):
    """Belt and braces: even a malformed match record (``list_type`` missing
    entirely, not merely unrecognised) must still reach a human rather than
    disappear -- a match with `matched: true` is never a safe thing to drop.
    """
    person(engine, "p1")
    result = engine.ingest(
        event_type=EventType.SCREENING_COMPLETED,
        subject="p1",
        occurred_at=WHEN,
        payload={"matched": True, "alert_id": "alt_9"},
    )
    assert result.cases[0].evidence[0].policy_id == "POL_WATCHLIST_HIT_UNCLASSIFIED"


def test_two_alerts_on_one_entity_are_two_cases(engine):
    person(engine, "p1")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_2")
    assert len(engine.state.casebook) == 2


# -- beneficial ownership --------------------------------------------------


def test_commitment_with_unresolved_ownership_opens_a_case(engine):
    company(engine, "c1")
    result = commits(engine, "c1")

    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.case_type == "UBO_REVIEW"
    assert case.evidence[0].policy_id == "POL_UBO_NOT_DECLARED"


def test_commitment_with_a_resolved_owner_opens_nothing(engine):
    person(engine, "p1", "Alice")
    company(engine, "c1")
    owns(engine, "p1", "c1", 100)
    assert commits(engine, "c1").cases == []


def test_a_natural_person_is_their_own_beneficial_owner(engine):
    person(engine, "p1", "Alice")
    assert commits(engine, "p1").cases == []


def test_dilute_ownership_requires_the_senior_managing_official(engine):
    """No holder above 10% -> 1.3.3(c) obliges you to record the SMO."""
    company(engine, "c1")
    for i in range(12):
        person(engine, f"p{i}")
        owns(engine, f"p{i}", "c1", 8)

    case = commits(engine, "c1").cases[0]
    assert case.evidence[0].policy_id == "POL_UBO_SENIOR_OFFICIAL_REQUIRED"
    assert case.severity is Severity.HIGH
    assert any(c["clause"] == "1.3.3(c)" for c in case.evidence[0].citations)


def test_ownership_question_stays_one_case_across_many_commitments(engine):
    company(engine, "c1")
    commits(engine, "c1", fund="fnd_1")
    commits(engine, "c1", fund="fnd_2")
    commits(engine, "c1", fund="fnd_3")

    ubo_cases = [c for c in engine.state.casebook.cases.values()
                 if c.case_type == "UBO_REVIEW"]
    assert len(ubo_cases) == 1
    # ...but every commitment that raised it is on the record.
    assert len(ubo_cases[0].evidence) == 3


def test_an_incomplete_trust_ubo_cites_clauses_in_a_fixed_order(engine):
    """``ubo_must_be_identified`` used to build its citations from a raw set
    literal (``{result.test.clause, *clauses}``), so the order depended on
    Python's set iteration -- itself seeded by ``PYTHONHASHSEED`` -- rather
    than on anything about the finding. Sorted, it is fixed however the
    process was started.
    """
    trust_of(engine, "t1", "Family Trust")  # no settlor, no trustee declared
    case = commits(engine, "t1").cases[0]
    assert case.evidence[0].detail["conclusion"] == "INCOMPLETE"
    clauses = [c["clause"] for c in case.evidence[0].citations]
    assert clauses == ["1.3.3(d)", "5.4.5"]


def test_the_case_carries_the_ownership_chain_as_evidence(engine):
    company(engine, "c1")
    company(engine, "c2")
    owns(engine, "c2", "c1", 100)

    evidence = commits(engine, "c1").cases[0].evidence[0]
    assert evidence.detail["conclusion"] == "INCOMPLETE"
    assert evidence.detail["dead_ends"] == ["c2"]
    assert evidence.detail["test"]["threshold_pct"] == 10.0
    assert evidence.detail["test"]["clause"] == "1.3.3(a)"


# -- cycles ----------------------------------------------------------------


def test_closing_a_loop_opens_a_cycle_case(engine):
    for c in ("c1", "c2", "c3"):
        company(engine, c)
    owns(engine, "c1", "c2", 40)
    owns(engine, "c2", "c3", 50)
    result = owns(engine, "c3", "c1", 30)

    assert len(result.cases) == 1
    assert result.cases[0].evidence[0].policy_id == "POL_UBO_CYCLE"


def test_one_loop_is_one_case_however_it_is_reported(engine):
    for c in ("c1", "c2"):
        company(engine, c)
    owns(engine, "c1", "c2", 50)
    owns(engine, "c2", "c1", 50)
    owns(engine, "c2", "c1", 50)  # re-declared

    cycle_cases = [c for c in engine.state.casebook.cases.values()
                   if c.evidence[0].policy_id == "POL_UBO_CYCLE"]
    assert len(cycle_cases) == 1


# -- payments --------------------------------------------------------------


@pytest.mark.parametrize("what,severity,arrange", [
    # Two rules, which is all there are since 21 August 2026. The first is
    # declared: it needs the payer's screening record, which a policy cannot
    # see. The second is built, so the rule has to work it out rather than be
    # told. There were five here -- an unrecorded payer, an overpayment and an
    # unexpected currency have gone with the rules that read them.
    ("SANCTIONED_PAYER", Severity.CRITICAL, {"anomaly": "SANCTIONED_PAYER"}),
    ("THIRD_PARTY", Severity.MEDIUM, {"payer": "somebody_else"}),
])
def test_every_payment_anomaly_is_graded(engine, what, severity, arrange):
    """The old version passed anomaly="OVERPAYMENT" and trusted the rule to
    believe it, which tested the routing and nothing else."""
    person(engine, "p1")
    case = paid(engine, "p1", **arrange).cases[0]
    assert case.severity is severity
    assert case.case_type == "PAYMENT_MISMATCH"
    assert what in case.evidence[0].summary


# The two structuring tests that stood here -- five split transfers are the
# pattern, one large transfer is not -- were deleted on 21 August 2026 with
# the rule. The second went with the first deliberately: a test asserting
# that one large payment is not structuring reads as a claim that the product
# tells the two apart, and it no longer looks at either.


def test_a_clean_payment_opens_nothing(engine):
    person(engine, "p1")
    assert paid(engine, "p1", anomaly=None).cases == []


def test_each_anomalous_payment_gets_its_own_case(engine):
    person(engine, "p1")
    outsider = {"payer": "somebody_else"}
    paid(engine, "p1", payment_id="pay_1", **outsider)
    paid(engine, "p1", payment_id="pay_2", **outsider)
    assert len(engine.state.casebook) == 2


# -- the queue -------------------------------------------------------------


def test_queue_is_ordered_by_severity_then_age(engine):
    """Two severities rather than three, because two payment rules is all
    there are since 21 August 2026. The age half of the ordering is what the
    pair of MEDIUMs is for: the older of two equally severe files leads."""
    person(engine, "p1")
    paid(engine, "p1", payment_id="pay_1", payer="somebody_else")      # MEDIUM
    paid(engine, "p1", payment_id="pay_2",
         anomaly="SANCTIONED_PAYER")                                   # CRITICAL
    paid(engine, "p1", payment_id="pay_3", payer="another_party")      # MEDIUM

    queue = engine.queue()
    assert [c.severity for c in queue] == [
        Severity.CRITICAL,
        Severity.MEDIUM,
        Severity.MEDIUM,
    ]
    assert queue[1].opened_seq < queue[2].opened_seq


def test_every_case_can_explain_itself(engine):
    """No Case exists without evidence pointing at the event that caused it."""
    person(engine, "p1")
    company(engine, "c1")
    screened(engine, "p1", "SANCTIONS")
    commits(engine, "c1")
    paid(engine, "p1", payer="somebody_else")

    seqs = {e.seq for e in engine.log}
    for case in engine.state.casebook.cases.values():
        assert case.evidence, f"{case.case_id} has no evidence"
        for evidence in case.evidence:
            assert evidence.summary
            assert evidence.source_seq in seqs
            assert evidence.citations, f"{case.case_id} evidence has no clause"
            for citation in evidence.citations:
                assert citation["clause"] and citation["extract"]


# -- determinism -------------------------------------------------------------

#: Builds one trust UBO finding and prints the resulting CASE_OPENED event's
#: canonical JSON. Run as a fresh interpreter under different PYTHONHASHSEED
#: values so set iteration order, if it ever leaked into the payload again,
#: would show up as a different line of output.
_UBO_FINDING_SCRIPT = """
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType, canonical_json

WHEN = "2026-08-07"
engine = Vinzor(EventLog())
engine.ingest(
    event_type=EventType.ENTITY_REGISTERED, subject="t1", occurred_at=WHEN,
    actor="system",
    payload={"kind": EntityKind.TRUST.value, "name": "Family Trust", "attributes": {}},
)
engine.ingest(
    event_type=EventType.COMMITMENT_MADE, subject="t1", occurred_at=WHEN,
    actor="system", payload={"investor": "t1", "fund": "fnd_1", "amount": 1000000.0},
)
opened = next(e for e in engine.log if e.event_type is EventType.CASE_OPENED)
print(canonical_json(opened.payload))
"""


def test_ubo_citation_order_is_identical_across_pythonhashseed_values():
    """The verified reproduction: PYTHONHASHSEED=1 and PYTHONHASHSEED=3 used
    to order the same finding's citations as ``['5.4.5','1.3.3(d)']`` versus
    ``['1.3.3(d)','5.4.5']`` -- identical facts, different canonical JSON,
    different event hash, depending on nothing but how the process was
    started. This goes through a real policy (``evaluate`` -> ``ingest``),
    unlike the hash-chain determinism tests in test_eventlog.py, which use
    raw ``_append`` and so never exercised this code path.
    """
    repo_root = Path(__file__).resolve().parents[1]
    outputs = {}
    for seed in ("1", "3"):
        # The payload carries the clause extracts, and IFSCA sets them with
        # typographic dashes and quotes. Left to the machine's locale the
        # child writes them as cp1252 on a Windows console and the parent
        # reads them as UTF-8, so this test failed on the encoding rather
        # than on the ordering it exists to check.
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            [sys.executable, "-c", _UBO_FINDING_SCRIPT],
            cwd=repo_root, env=env, capture_output=True, text=True,
            encoding="utf-8",
        )
        assert proc.returncode == 0, proc.stderr
        outputs[seed] = proc.stdout.strip()

    assert outputs["1"] == outputs["3"], (
        f"same facts produced different canonical JSON depending on "
        f"PYTHONHASHSEED:\nseed=1: {outputs['1']}\nseed=3: {outputs['3']}"
    )
    payload = json.loads(outputs["1"])
    assert [c["clause"] for c in payload["citations"]] == ["1.3.3(d)", "5.4.5"]


# -- money that cannot be read -----------------------------------------------


def test_an_amount_sent_as_text_still_counts(engine):
    """Every amount rule guarded with isinstance(amount, (int, float)), so a
    feed sending "5000" as text switched overpayment and structuring off
    silently -- no error, no finding, the queue simply stopped mentioning that
    investor. Plenty of feeds send numbers as text.

    The rules that incident was found through were removed on 21 August 2026,
    and the coercion in ``model.check_amount`` that fixed it was not: the
    amount still reaches the log as a number, and the reporting, the briefing
    and every figure a reader sees still depend on it doing so. So this now
    asserts the coercion rather than a rule, and keeps the incident, because
    the next feed that sends numbers as text will not announce itself either.
    """
    person(engine, "p1")
    recorded = paid(engine, "p1", amount="5000", called_amount="1000")
    written = recorded.event.payload
    assert written["amount"] == 5000.0
    assert isinstance(written["amount"], float), \
        "a numeric string reached the log as text"
    assert written["called_amount"] == 1000.0


def test_an_amount_that_is_not_a_number_is_refused_rather_than_ignored(engine):
    person(engine, "p1")
    before = len(engine.log)
    with pytest.raises(ValueError, match="not an amount"):
        paid(engine, "p1", amount="about five thousand")
    assert len(engine.log) == before


def test_money_moving_backwards_is_refused(engine):
    """A reversal needs its own record. A payment with a minus sign in front
    of it quietly satisfies a capital call it did not satisfy."""
    person(engine, "p1")
    with pytest.raises(ValueError, match="negative"):
        paid(engine, "p1", amount=-5000.0)


# The lower-case currency test stood here until 21 August 2026. It held that
# "usd" against "USD" is not a mismatch, which was worth holding while a rule
# compared the two. Nothing compares them now, so there is nothing left for it
# to be right about.


# -- ownership declared more than once ---------------------------------------


def test_declaring_the_same_holding_twice_does_not_double_it(engine):
    """Appending meant re-importing an ownership file doubled every
    percentage in it, and six per cent declared twice became a twelve per cent
    beneficial owner who does not exist. Since the importer is idempotent for
    parties, this was the one way a second run could invent people.
    """
    company(engine, "c1", "Customer Ltd")
    person(engine, "p1", "A Person")
    owns(engine, "p1", "c1", 6.0)
    owns(engine, "p1", "c1", 6.0)

    result = engine.state.graph.resolve_ubo("c1")
    assert [round(o.effective_percentage, 1) for o in result.owners] == []
    assert [round(o.effective_percentage, 1)
            for o in result.below_threshold] == [6.0]


def test_a_restated_holding_replaces_the_earlier_one(engine):
    """A firm correcting a filing is not adding a second holding."""
    company(engine, "c1", "Customer Ltd")
    person(engine, "p1", "A Person")
    owns(engine, "p1", "c1", 6.0)
    owns(engine, "p1", "c1", 30.0)

    result = engine.state.graph.resolve_ubo("c1")
    assert [round(o.effective_percentage, 1) for o in result.owners] == [30.0]


def test_a_share_nobody_can_hold_is_refused(engine):
    """150% was accepted and reported as an identified beneficial owner, which
    is a fact about nothing. -20% was read as being under the threshold and
    quietly became a senior managing official instead."""
    company(engine, "c1", "Customer Ltd")
    person(engine, "p1", "A Person")
    for impossible in (150.0, -20.0, 100.5):
        with pytest.raises(ValueError, match="share anybody can hold"):
            owns(engine, "p1", "c1", impossible)
    # The ends of the range are real holdings.
    owns(engine, "p1", "c1", 100.0)
    assert engine.state.graph.resolve_ubo("c1").owners
