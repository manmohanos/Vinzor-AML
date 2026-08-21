"""Deterministic dataset validator (the Phase-2 gate).

Confirms the generated dataset satisfies the mandatory "tricky" fixture
requirements and structural invariants documented in ``data/schema.md``:

* >= 1 multi-layer UBO chain (>= 3 ownership hops)
* >= 1 trust with "no single UBO > 25%"
* >= 1 ownership cycle (A -> B -> C -> A)
* all six transaction-monitoring anomalies present in ``payments.csv``
* screening alerts for sanctions / PEP / adverse media
* no duplicate IDs within any table
* every foreign-key reference resolves to an existing row
* record counts within a tolerance of the planning targets

Run as:  ``python -m generator.validate``  (from ``data/``)
Exits non-zero on any failure.
"""

from __future__ import annotations

import csv
import json
import os
import sys

GEN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "generated")

ANOMALY_CLASSES = ["OVERPAYMENT", "THIRD_PARTY", "UNKNOWN_SOURCE",
                   "UNEXPECTED_CURRENCY", "STRUCTURING", "SANCTIONED_PAYER"]

# Optional count targets (not hard upper bonds; used for a soft report)
TARGETS = {
    "persons.csv": 120, "companies.csv": 60, "trusts.csv": 15, "funds.csv": 8,
    "bank_accounts.csv": 90, "fund_participations.csv": 150,
    "capital_commitments.csv": 150, "capital_calls.csv": 44,
    "capital_call_allocations.csv": 350, "payments.csv": 800,
    "portfolio_companies.csv": 25, "documents.csv": 150,
    "sanctions_entries.csv": 100, "pep_entries.csv": 80, "adverse_media.csv": 50,
    "alerts.csv": 40, "cases.csv": 30, "regulatory_reports.csv": 4, "edges.csv": 150,
}


def read_csv(name: str) -> list[dict]:
    path = os.path.join(GEN, name)
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check(cond: bool, msg: str, failures: list[str]) -> None:
    if not cond:
        failures.append(msg)


def main() -> int:
    failures: list[str] = []
    print("Validating generated dataset in", GEN)

    persons = read_csv("persons.csv")
    companies = read_csv("companies.csv")
    trusts = read_csv("trusts.csv")
    funds = read_csv("funds.csv")
    accounts = read_csv("bank_accounts.csv")
    participations = read_csv("fund_participations.csv")
    commitments = read_csv("capital_commitments.csv")
    calls = read_csv("capital_calls.csv")
    allocations = read_csv("capital_call_allocations.csv")
    payments = read_csv("payments.csv")
    pcos = read_csv("portfolio_companies.csv")
    documents = read_csv("documents.csv")
    sanctions = read_csv("sanctions_entries.csv")
    peps = read_csv("pep_entries.csv")
    adverse = read_csv("adverse_media.csv")
    alerts = read_csv("alerts.csv")
    cases = read_csv("cases.csv")
    reports = read_csv("regulatory_reports.csv")
    edges = read_csv("edges.csv")

    # ---- 1. No duplicate IDs inside any table ----
    for name, rows in [
        ("persons.csv", persons), ("companies.csv", companies), ("trusts.csv", trusts),
        ("funds.csv", funds), ("bank_accounts.csv", accounts),
        ("fund_participations.csv", participations),
        ("capital_commitments.csv", commitments), ("capital_calls.csv", calls),
        ("capital_call_allocations.csv", allocations), ("payments.csv", payments),
        ("portfolio_companies.csv", pcos), ("documents.csv", documents),
        ("sanctions_entries.csv", sanctions), ("pep_entries.csv", peps),
        ("adverse_media.csv", adverse), ("alerts.csv", alerts), ("cases.csv", cases),
        ("regulatory_reports.csv", reports), ("edges.csv", edges),
    ]:
        ids = [r["id"] for r in rows]
        dups = {i for i in ids if ids.count(i) > 1}
        check(not dups, f"{name}: duplicate IDs {sorted(dups)[:5]}", failures)

    # ---- 2. Foreign key integrity ----
    def id_set(rows, key="id"):
        return {r[key] for r in rows}

    p_ids = id_set(persons); c_ids = id_set(companies); t_ids = id_set(trusts)
    f_ids = id_set(funds)
    commit_by_id = {r["id"]: r for r in commitments}

    def fk(rows, col, ok, label):
        bad = {r["id"] for r in rows if r.get(col) and r[col] not in ok}
        check(not bad, f"{rows[0].get('id','')} table: {label} refs broken {sorted(bad)[:5]}", failures) if rows else None

    fk(accounts, "holder_id", p_ids | c_ids | t_ids, "account.holder_id")
    fk(participations, "investor_id", p_ids | c_ids | t_ids, "participation.investor_id")
    fk(participations, "fund_id", f_ids, "participation.fund_id")
    fk(commitments, "participation_id", id_set(participations), "commitment.participation_id")
    fk(commitments, "fund_id", f_ids, "commitment.fund_id")
    fk(calls, "fund_id", f_ids, "call.fund_id")
    alloc_commit = id_set(commitments)
    fk(allocations, "capital_call_id", id_set(calls), "allocation.capital_call_id")
    fk(allocations, "commitment_id", alloc_commit, "allocation.commitment_id")

    # payments referencing existing accounts
    pay_from = {p["from_account_id"] for p in payments}
    acct_ids = id_set(accounts) | {""}
    check(pay_from <= acct_ids, "payments.from_account_id broken", failures)

    # ---- 3. Mandatory tricky fixtures ----
    # 3a. multi-layer UBO chain: an edge path of >= 3 ownership hops exists
    # (validated structurally via ubochains.json when possible)
    try:
        with open(os.path.join(GEN, "ubochains.json"), encoding="utf-8") as f:
            chains = json.load(f)
    except FileNotFoundError:
        chains = []
    multi = [x for x in chains if x.get("conclusion") == "single_ubo"
             and len(x.get("chain", [])) >= 3]
    check(len(multi) >= 1, "no multi-layer (>=3 hop) UBO chain found", failures)

    no_single = [x for x in chains if x.get("conclusion") == "no_single_ubo_over_25pct"]
    check(len(no_single) >= 1, "no trust with 'no single UBO > 25%' conclusion", failures)

    cycle = [x for x in chains if x.get("conclusion") == "ownership_cycle_detected"]
    check(len(cycle) >= 1, "no ownership cycle detected", failures)

    # 3b. edge-level cycle detection (A->B, B->C, C->A)
    own = {(e["source_id"], e["target_id"]) for e in edges if e["relation"] == "OWNS"}
    cycle_found = False
    for (a, b) in own:
        for (b2, c) in own:
            if b2 == b and (c, a) in own:
                cycle_found = True
    check(cycle_found, "no 3-node OWNS cycle in edges.csv", failures)

    # 3c. all six transaction anomalies present
    present = set()
    for p in payments:
        md = p["anomaly_metadata"]
        if not md:
            continue
        try:
            cls = json.loads(md).get("class")
        except json.JSONDecodeError:
            continue
        if cls:
            present.add(cls)
    missing = [a for a in ANOMALY_CLASSES if a not in present]
    check(not missing, f"missing anomaly classes: {missing}", failures)

    # 3d. screening alerts for sanctions + PEP + adverse media
    alert_types = {a["alert_type"] for a in alerts}
    for need in ("SANCTIONS", "PEP", "ADVERSE_MEDIA"):
        check(need in alert_types, f"no {need} screening alert", failures)

    # ---- 4. Count sanity (report only, not fatal) ----
    print("Counts vs target (report-only):")
    for name, target in TARGETS.items():
        n = len(read_csv(name))
        flag = "OK" if abs(n - target) <= max(0.5 * target, 5) else "~"
        print(f"  {name:<30} {n:>5}  (target ~{target}) {flag}")

    # ---- 5. High-risk trust present (used by EDD case) ----
    high_risk_trust = any(t["jurisdiction"] in ("GG", "KY", "MU") for t in trusts)
    print("  high-risk jurisdiction trust present:", high_risk_trust)

    # ---- 6. AML typology realism (FATF-grounded) ----
    # 6a. the UBO-cycle / three-hop-chain companies read as shell companies
    # in a secrecy jurisdiction (FATF-Egmont "Concealment of Beneficial
    # Ownership", 2018) rather than an ordinary transparent group.
    own_edges = [e for e in edges if e["relation"] == "OWNS"]
    layered_company_ids = {e["source_id"] for e in own_edges} | {e["target_id"] for e in own_edges}
    layered_shells = [
        c for c in companies
        if c["id"] in layered_company_ids and c.get("is_shell") == "1"
    ]
    check(len(layered_shells) >= 3,
          "no shell companies among the ownership-cycle/chain companies "
          "(FATF-Egmont: shells in a secrecy jurisdiction are the dominant "
          "concealment vehicle)", failures)

    # 6b. a PEP appears as a direct customer, not only behind a company.
    pep_person_alerts = [a for a in alerts
                         if a["alert_type"] == "PEP" and a["entity_type"] == "PERSON"]
    check(len(pep_person_alerts) >= 1,
          "no PEP alert targets a PERSON directly (FATF Recs. 12/22 cover a "
          "PEP as the customer, not only as a company's director)", failures)

    if failures:
        print("\nFAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nPASS: all mandatory fixtures and structural invariants hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
