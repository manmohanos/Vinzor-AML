"""Does it catch what it should, and stay quiet about the rest?

    python tools/benchmark.py            # the whole pack
    python tools/benchmark.py --rule ubo # one rule
    python tools/benchmark.py --verbose  # show every case

The queue says 195 files are open. Nothing in the product says how many
*should* be, or what it walked past, because a workspace of invented investors
has no answer key. This pack is the answer key: every case below is built by
hand with the outcome written down first, and half of them are built to
produce nothing at all.

That second half is the point. A rule that fires on everything catches every
breach and is worthless, and false positives are what get a compliance product
switched off -- so a case expecting silence counts exactly as much as a case
expecting a finding.

The boundaries are where the value is. IFSCA 1.3.3 says "more than ten per
cent" for a company and "ten per cent or more" for a trust's beneficiaries,
which is a real difference in the law and a one-character difference in the
code. Ten per cent exactly should be silent for a company and a finding for a
trust, and there is a case for each.

Each case runs in its own workspace, so nothing leaks between them and a case
cannot pass because of something an earlier one wrote.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType, Relation

WHEN = "2026-08-07"


# ---------------------------------------------------------------------------
# Building a workspace by hand
# ---------------------------------------------------------------------------


def fresh() -> Vinzor:
    return Vinzor(EventLog())


def register(engine, entity_id, kind, name=None, **attrs):
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=entity_id,
                  occurred_at=WHEN,
                  payload={"kind": kind.value, "name": name or entity_id,
                           "attributes": attrs})


def owns(engine, owner, owned, percentage, relation=Relation.OWNS):
    engine.ingest(event_type=EventType.OWNERSHIP_DECLARED, subject=owned,
                  occurred_at=WHEN,
                  payload={"owner": owner, "owned": owned,
                           "percentage": percentage,
                           "relation": relation.value,
                           "edge_id": f"edg_{owner}_{owned}"})


def commits(engine, investor, amount=1_000_000.0):
    engine.ingest(event_type=EventType.COMMITMENT_MADE, subject=investor,
                  occurred_at=WHEN,
                  payload={"investor": investor, "fund": "fnd_1",
                           "amount": amount, "currency": "USD",
                           "commitment_id": f"ccm_{investor}"})


def paid(engine, subject, payment_id="pay_1", anomaly=None, **extra):
    """An ordinary payment: the investor pays what was called, in the currency
    expected, from their own account. The rules derive rather than read a
    label now, so anything left out of this is a finding in its own right --
    a payment with no payer really is a payment with no payer."""
    payload = {"payment_id": payment_id, "payment_ref": "TX-1",
               "amount": 1000.0, "called_amount": 1000.0, "currency": "USD",
               "expected_currency": "USD", "fund": "fnd_1", "payer": subject,
               "anomaly": anomaly, "anomaly_detail": None}
    payload.update(extra)
    engine.ingest(event_type=EventType.PAYMENT_RECEIVED, subject=subject,
                  occurred_at=WHEN, payload=payload)


def screened(engine, subject, list_type="SANCTIONS", matched=True):
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject=subject,
                  occurred_at=WHEN, actor="system",
                  payload={"list_type": list_type, "matched": matched,
                           "alert_id": f"alt_{subject}", "rule": "TEST"})


def licensed(engine, category="REGISTERED_NON_RETAIL", staffed=True):
    """A licensed firm. Staffed by default, because a licence with nobody in
    post is its own finding and would otherwise fire inside every case that
    is really about something else."""
    register(engine, "fme", EntityKind.COMPANY, "The Firm")
    # Appointed before the licence is granted, which is the order a real firm
    # does it in. Granting first opens a vacancy the same instant -- correctly,
    # since at that moment nobody is in post -- and an append-only log does not
    # un-open it when the appointment lands a line later. That finding is right
    # and it is not what these cases are testing.
    if staffed:
        for office in ("PRINCIPAL_OFFICER", "COMPLIANCE_OFFICER"):
            engine.ingest(event_type=EventType.OFFICE_APPOINTED, subject="fme",
                          occurred_at="2025-01-09",
                          payload={"office": office,
                                   "person": f"Holder of {office}",
                                   "based_in_ifsc": True})
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="fme",
                  occurred_at="2025-01-10",
                  payload={"category": category, "number": "IFSCA/TEST/1"})


# ---------------------------------------------------------------------------
# The pack
# ---------------------------------------------------------------------------


@dataclass
class Case:
    """One planted scenario and the answer, written down before it runs."""

    rule: str
    name: str
    build: Callable[[Vinzor], None]
    #: Policy ids that must fire. Empty means the workspace must stay silent.
    expect: tuple = ()
    why: str = ""


def _company_at(percentage):
    def build(engine):
        register(engine, "c1", EntityKind.COMPANY, "Customer Ltd")
        register(engine, "p1", EntityKind.PERSON, "A Person")
        owns(engine, "p1", "c1", percentage)
        commits(engine, "c1")
    return build


def _trust_beneficiary_at(percentage):
    def build(engine):
        register(engine, "t1", EntityKind.TRUST, "A Trust")
        register(engine, "p1", EntityKind.PERSON, "A Beneficiary")
        register(engine, "p2", EntityKind.PERSON, "A Trustee")
        register(engine, "p3", EntityKind.PERSON, "A Settlor")
        owns(engine, "p1", "t1", percentage, Relation.BENEFICIARY_OF)
        owns(engine, "p2", "t1", 0.0, Relation.TRUSTEE_OF)
        owns(engine, "p3", "t1", 0.0, Relation.SETTLOR_OF)
        commits(engine, "t1")
    return build


def _chain(first, second):
    """p1 owns c2 by `first`%, c2 owns c1 by `second`%. Effective is the
    product, which is the whole reason a resolver exists."""
    def build(engine):
        register(engine, "c1", EntityKind.COMPANY, "Customer Ltd")
        register(engine, "c2", EntityKind.COMPANY, "Holding Ltd")
        register(engine, "p1", EntityKind.PERSON, "A Person")
        owns(engine, "c2", "c1", second)
        owns(engine, "p1", "c2", first)
        commits(engine, "c1")
    return build


PACK: tuple = (
    # -- beneficial ownership, clause 1.3.3 ---------------------------------
    Case("ubo", "company owner at 25% is a beneficial owner",
         _company_at(25.0), (),
         "identified, so nothing is owed -- silence is the pass"),
    Case("ubo", "company owner at exactly 10% is NOT one",
         _company_at(10.0), ("POL_UBO_SENIOR_OFFICIAL_REQUIRED",),
         "1.3.3(a) says MORE than ten per cent; nobody qualifies, so the "
         "senior managing official is owed instead"),
    Case("ubo", "company owner at 10.5% is one",
         _company_at(10.5), (),
         "just over the line, so it resolves"),
    Case("ubo", "chain of 40% x 30% = 12% resolves",
         _chain(40.0, 30.0), (),
         "the product crosses ten per cent"),
    Case("ubo", "chain of 40% x 20% = 8% does not",
         _chain(40.0, 20.0), ("POL_UBO_SENIOR_OFFICIAL_REQUIRED",),
         "8% is below the test, and nothing else identifies a person"),
    Case("ubo", "trust beneficiary at exactly 10% IS one",
         _trust_beneficiary_at(10.0), (),
         "1.3.3(d) says ten per cent OR MORE -- the opposite boundary from a "
         "company, and one character of code apart"),
    Case("ubo", "circular ownership is caught",
         lambda e: (register(e, "c1", EntityKind.COMPANY, "A Ltd"),
                    register(e, "c2", EntityKind.COMPANY, "B Ltd"),
                    register(e, "c3", EntityKind.COMPANY, "C Ltd"),
                    owns(e, "c1", "c2", 40.0), owns(e, "c2", "c3", 50.0),
                    owns(e, "c3", "c1", 30.0), commits(e, "c1")),
         ("POL_UBO_CYCLE", "POL_UBO_INCOMPLETE"),
         "a loop can never reach a natural person, and the chain is also "
         "incomplete -- both are true and both are recorded"),
    Case("ubo", "a company that declared no ownership at all is caught",
         lambda e: (register(e, "c1", EntityKind.COMPANY, "Opaque Ltd"),
                    commits(e, "c1")),
         ("POL_UBO_NOT_DECLARED",),
         "money committed by a company nobody stands behind"),
    Case("ubo", "a person investing directly raises nothing",
         lambda e: (register(e, "p1", EntityKind.PERSON, "A Person"),
                    commits(e, "p1")),
         (),
         "a natural person is their own beneficial owner"),

    # -- screening, clause 5.9 ----------------------------------------------
    Case("screening", "a sanctions match is caught",
         lambda e: (register(e, "p1", EntityKind.PERSON, "A Person"),
                    screened(e, "p1", "SANCTIONS")),
         ("POL_SANCTIONS_HIT",), ""),
    Case("screening", "a PEP match is caught",
         lambda e: (register(e, "p1", EntityKind.PERSON, "A Person"),
                    screened(e, "p1", "PEP")),
         ("POL_PEP_HIT",), ""),
    Case("screening", "a clean check raises nothing",
         lambda e: (register(e, "p1", EntityKind.PERSON, "A Person"),
                    screened(e, "p1", "SANCTIONS", matched=False)),
         (),
         "the check happened and found nothing; a finding here would be the "
         "false positive that empties the queue of meaning"),

    # -- payments ------------------------------------------------------------
    Case("payment", "a payment matching the call raises nothing",
         lambda e: (register(e, "p1", EntityKind.PERSON, "A Person"),
                    paid(e, "p1")),
         (), "the ordinary case, and most payments are ordinary"),
    Case("payment", "a third-party payer is caught",
         lambda e: (register(e, "p1", EntityKind.PERSON, "A Person"),
                    paid(e, "p1", payer="somebody_else")),
         ("POL_PAY_THIRD_PARTY",), ""),
    # Six payment cases were removed here on 21 August 2026 with the rules
    # they exercised: a split transfer, one large payment that is not a split
    # transfer, a payment with no named source, an unexpected currency, an
    # overpayment and a 3% overage that is a wire fee. The two negative cases
    # went with the positives on purpose -- asserting that one large payment
    # is not structuring claims a discrimination this product no longer
    # makes, and a benchmark that claims one is worse than a benchmark that
    # is silent.
    Case("payment", "a payment from a sanctioned payer is caught",
         lambda e: (register(e, "p1", EntityKind.PERSON, "A Person"),
                    paid(e, "p1", anomaly="SANCTIONED_PAYER")),
         ("POL_PAY_SANCTIONED_PAYER",), ""),

    # -- licence and governance ---------------------------------------------
    Case("licence", "an activity inside the licence raises nothing",
         lambda e: (licensed(e),
                    e.ingest(event_type=EventType.ACTIVITY_UNDERTAKEN,
                             subject="fme", occurred_at=WHEN,
                             payload={"activity": "RESTRICTED_SCHEME"})),
         (), "permitted for a Registered FME (non-retail)"),
    Case("licence", "an activity outside the licence is caught",
         lambda e: (licensed(e),
                    e.ingest(event_type=EventType.ACTIVITY_UNDERTAKEN,
                             subject="fme", occurred_at=WHEN,
                             payload={"activity": "RETAIL_SCHEME"})),
         ("POL_ACTIVITY_OUTSIDE_LICENCE",),
         "a retail scheme needs a retail registration"),
    Case("governance", "a required post left vacant is caught",
         lambda e: (licensed(e, staffed=False),
                    e.ingest(event_type=EventType.OFFICE_APPOINTED,
                             subject="fme", occurred_at="2025-01-10",
                             payload={"office": "PRINCIPAL_OFFICER",
                                      "person": "A Name",
                                      "based_in_ifsc": True}),
                    e.ingest(event_type=EventType.OFFICE_VACATED,
                             subject="fme", occurred_at="2026-01-10",
                             payload={"office": "PRINCIPAL_OFFICER"})),
         ("POL_OFFICE_VACANT",), ""),
)


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


@dataclass
class Result:
    case: Case
    fired: tuple
    missed: tuple = ()
    unexpected: tuple = ()

    @property
    def passed(self) -> bool:
        return not self.missed and not self.unexpected


def run(case: Case) -> Result:
    engine = fresh()
    case.build(engine)
    fired = tuple(sorted({
        piece.policy_id
        for kase in engine.state.casebook.cases.values()
        for piece in kase.evidence
        if getattr(piece, "policy_id", None)
    }))
    expected = set(case.expect)
    return Result(
        case=case, fired=fired,
        missed=tuple(sorted(expected - set(fired))),
        unexpected=tuple(sorted(set(fired) - expected)),
    )


def main(argv: Sequence[str]) -> int:
    wanted = None
    if "--rule" in argv:
        wanted = argv[argv.index("--rule") + 1]
    verbose = "--verbose" in argv

    cases = [c for c in PACK if wanted is None or c.rule == wanted]
    results = [run(c) for c in cases]

    should_fire = [r for r in results if r.case.expect]
    should_not = [r for r in results if not r.case.expect]
    caught = sum(1 for r in should_fire if r.passed)
    quiet = sum(1 for r in should_not if r.passed)

    print()
    print(f"  {len(cases)} planted cases, each in its own workspace")
    print()
    for result in results:
        mark = "pass" if result.passed else "FAIL"
        if verbose or not result.passed:
            print(f"  [{mark}] {result.case.rule:11} {result.case.name}")
            if result.missed:
                print(f"         missed: {', '.join(result.missed)}")
            if result.unexpected:
                print(f"         raised without cause: "
                      f"{', '.join(result.unexpected)}")
            if verbose and result.case.why:
                print(f"         why: {result.case.why}")

    print()
    print(f"  caught what it should      {caught}/{len(should_fire)}")
    print(f"  stayed quiet when it should {quiet}/{len(should_not)}")
    failed = [r for r in results if not r.passed]
    print(f"  {'all cases pass' if not failed else str(len(failed)) + ' FAILING'}")
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
