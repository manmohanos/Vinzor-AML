"""Deterministic synthetic FME dataset generator.

Produces every entity table in ``data/generated/`` (CSV + ``edges.csv`` +
``ubochains.json`` + ``manifest.json``) from the fixed seed in ``common.py``.

The dataset is designed to exercise the Vinzor architecture:

* **Knowledge-graph material** — the generic ``edges.csv`` with relations
  (OWNS, CONTROLS, TRUSTEE_OF, BENEFICIARY_OF, DIRECTOR_OF, COMMITS_CAPITAL_TO,
  ACCOUNT_OF, SATISFIES, ...) plus resolved UBO chains in ``ubochains.json``.

* **Mandatory "tricky" fixtures** (enforced by ``validate.py``):
    1. a multi-layer UBO chain,
    2. at least one trust with **no single UBO > 25%** (drives an EDD case),
    3. at least one **ownership cycle** (drives a UBO_REVIEW case),
    4. all six transaction-monitoring anomaly classes in ``payments.csv``,
    5. screening alerts (sanctions + PEP + adverse media).

Run as:  ``python -m generator.generate``  (from ``data/``)
Validated by:  ``python -m generator.validate``
"""

from __future__ import annotations

import csv
import json
import os
from datetime import date, timedelta

from .common import (  # noqa: E402
    ADVERSE_CATEGORIES, BANKS, COMPANY_WORD, COMPANY_SUFFIX, COUNTRY_NAMES,
    DOC_TYPES, FUND_TYPE, INDUSTRIES, JURISDICTIONS_HIGH_RISK,
    JURISDICTIONS_STANDARD, PEP_ROLES, STRATEGY, CURRENCIES,
    IdFactory, company_name, manifest_hash, person_name, rng,
)

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "generated")
os.makedirs(OUT_DIR, exist_ok=True)


def write_csv(name: str, headers: list[str], rows: list[dict]) -> str:
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def _rel_date(days_ago: int) -> str:
    return (date(2026, 8, 7) - timedelta(days=days_ago)).isoformat()


# --------------------------------------------------------------------------- #
# Entity columns (schema in data/schema.md)                                    #
# --------------------------------------------------------------------------- #
PERSONS_H = ["id", "full_name", "nationality", "country_of_residence", "citizenship",
             "dob", "id_document_type", "id_document_number", "email", "occupation",
             "pep_flag", "high_risk_jurisdiction", "risk_score", "status"]
COMPANIES_H = ["id", "legal_name", "jurisdiction", "registration_number",
               "country_of_incorporation", "industry", "is_shell", "is_listed",
               "address", "risk_score", "status"]
TRUSTS_H = ["id", "trust_name", "jurisdiction", "trust_deed_date", "settlor_count",
            "trustee_count", "has_protector", "is_discretionary",
            "has_beneficiary_class", "trust_type", "risk_score"]
FUNDS_H = ["id", "fund_name", "fund_type", "vehicle_jurisdiction", "gifsc_resident_flag",
           "strategy", "vintage_year", "target_size", "currency", "nav_currency"]
ACCOUNTS_H = ["id", "holder_id", "holder_type", "iban_local", "account_holder_name",
              "bank_name", "bank_country", "currency", "account_open_date", "is_nostro"]
PARTICIP_H = ["id", "investor_id", "investor_type", "fund_id", "role",
              "subscription_date", "commitment_currency"]
COMMIT_H = ["id", "participation_id", "fund_id", "investor_id", "commitment_amount",
            "commitment_currency", "commitment_date", "funded_amount",
            "remaining_commitment", "status"]
CALLC_H = ["id", "fund_id", "call_number", "call_date", "due_date",
           "total_call_amount", "currency"]
CALLA_H = ["id", "capital_call_id", "commitment_id", "investor_id", "allocated_amount",
           "currency", "status"]
PAY_H = ["id", "payment_ref", "payment_date", "amount", "currency", "expected_currency",
         "from_account_id", "from_counterparty_id", "from_counterparty_type",
         "to_fund_id", "to_account_id", "payment_purpose", "funding_source",
         "matching_capital_call_id", "matching_allocated_amount", "status", "anomaly_metadata"]
PFO_H = ["id", "legal_name", "jurisdiction", "industry", "round_invested",
         "amount_invested", "currency"]
DOC_H = ["id", "doc_type", "entity_id", "entity_type", "file_name",
         "uploaded_date", "verified", "verification_status"]
SAN_H = ["id", "name", "list_name", "id_document", "date_of_birth", "citizenship",
         "source", "match_key"]
PEP_H = ["id", "name", "role", "country", "term", "source"]
ADM_H = ["id", "entity_name", "headline", "article_date", "source_url", "category", "severity"]
ALT_H = ["id", "entity_id", "entity_type", "alert_type", "source_rule", "severity",
         "status", "created_date", "linked_case_id"]
CASE_H = ["id", "case_type", "entity_id", "entity_type", "priority", "status",
          "risk_score", "opened_date", "closed_date", "assignee_role"]
RPT_H = ["id", "report_type", "entity_id", "entity_type", "filing_date",
         "due_date", "status", "filed_to"]
EDGE_H = ["id", "source_id", "source_type", "relation", "target_id", "target_type",
          "percentage", "is_direct", "start_date", "end_date", "metadata_json"]


def generate() -> dict:
    r = rng()
    out: dict[str, list] = {}
    edges: list[dict] = []

    # ------------------------------------------------------------------ #
    # 1. PERSONS                                                          #
    # ------------------------------------------------------------------ #
    ids = IdFactory("per", 4)
    persons = []
    occupied = [f"Compliance Officer", "Investment Analyst", "Fund Manager",
                "Portfolio Manager", "Entrepreneur", "Consultant", "Financier"]
    for _ in range(120):
        pid = ids.next()
        country = r.choice(JURISDICTIONS_STANDARD)
        persons.append({
            "id": pid,
            "full_name": person_name(r),
            "nationality": country,
            "country_of_residence": country,
            "citizenship": country,
            "dob": _rel_date(r.randint(5000, 26000)),
            "id_document_type": r.choices(["PASSPORT", "NATIONAL_ID"], weights=[8, 2])[0],
            "id_document_number": f"{pid.upper()}{r.randint(1000, 9999)}",
            "email": "",
            "occupation": r.choice(occupied),
            "pep_flag": 0,
            "high_risk_jurisdiction": 0,
            "risk_score": r.randint(5, 40),
            "status": "ACTIVE",
        })
    out["persons.csv"] = persons

    # ------------------------------------------------------------------ #
    # 2. COMPANIES                                                         #
    # ------------------------------------------------------------------ #
    ids = IdFactory("cmp", 4)
    companies = []
    for _ in range(60):
        cid = ids.next()
        is_shell = r.random() < 0.18
        companies.append({
            "id": cid,
            "legal_name": company_name(r),
            "jurisdiction": r.choice(JURISDICTIONS_STANDARD + JURISDICTIONS_HIGH_RISK),
            "registration_number": f"REG-{cid.upper()}-{r.randint(100000, 999999)}",
            "country_of_incorporation": r.choice(JURISDICTIONS_STANDARD),
            "industry": r.choice(INDUSTRIES),
            "is_shell": int(is_shell),
            "is_listed": int(r.random() < 0.10),
            "address": f"{r.randint(1, 999)} Example Street, {r.choice(list(COUNTRY_NAMES.values()))}",
            "risk_score": r.randint(30, 65) if not is_shell else r.randint(55, 90),
            "status": "ACTIVE",
        })
    out["companies.csv"] = companies

    # ------------------------------------------------------------------ #
    # 3. TRUSTS                                                            #
    # ------------------------------------------------------------------ #
    ids = IdFactory("trs", 4)
    trusts = []
    for _ in range(15):
        tid = ids.next()
        trusts.append({
            "id": tid,
            "trust_name": r.choice(
                ["Krishna Family Trust", "Meridian Growth Trust", "Anand Discretionary Trust",
                 "Sovereign Succession Trust", "Harbor Beneficiary Trust", "Crest Settlor Trust"]),
            "jurisdiction": r.choice(["SG", "MU", "AE", "GG", "KY"]),
            "trust_deed_date": _rel_date(r.randint(1500, 9000)),
            "settlor_count": r.randint(1, 2),
            "trustee_count": r.randint(1, 3),
            "has_protector": int(r.random() < 0.4),
            "is_discretionary": int(r.random() < 0.7),
            "has_beneficiary_class": int(r.random() < 0.85),
            "trust_type": r.choice(["Discretionary", "Fixed", "Revocable", "Charitable"]),
            "risk_score": r.randint(45, 80),
        })
    # Designate the first trust as the high-risk EDD fixture (secrecy jurisdiction),
    # so its "no single UBO > 25%" EDD case scores above the approval threshold.
    if trusts:
        trusts[0]["jurisdiction"] = "GG"
        trusts[0]["risk_score"] = 75
        trusts[0]["is_discretionary"] = 1
        trusts[0]["has_beneficiary_class"] = 1
    out["trusts.csv"] = trusts

    # Designate one investor as a directly-screened PEP. FATF's PEP guidance
    # (Recommendations 12 & 22) is about a politically exposed *individual*
    # as the customer -- but every PEP alert this generator built before
    # this fix targeted a COMPANY ("one of its directors is a PEP"), so a
    # fund LP who is themselves a serving or former public official never
    # appeared anywhere in the dataset, and persons.csv's own pep_flag
    # column was 0 for all 120 rows. persons[50] is not used by any other
    # fixture.
    pep_investor = persons[50]
    pep_investor["pep_flag"] = 1
    pep_investor["occupation"] = "Minister of Finance"

    # ------------------------------------------------------------------ #
    # 4. FUNDS                                                             #
    # ------------------------------------------------------------------ #
    ids = IdFactory("fnd", 4)
    funds = []
    for i in range(8):
        fid = ids.next()
        funds.append({
            "id": fid,
            "fund_name": f"{r.choice(COMPANY_WORD)} {r.choice(['Fund', 'Capital', 'Partners', 'Growth Fund'])} {['I', 'II', 'III', 'IV'][i % 4]}",
            "fund_type": r.choice(FUND_TYPE),
            "vehicle_jurisdiction": "IN-GIFT",
            "gifsc_resident_flag": 1,
            "strategy": r.choice(STRATEGY),
            "vintage_year": r.randint(2020, 2025),
            "target_size": r.randint(50, 500) * 1_000_000,
            "currency": "USD",
            "nav_currency": "USD",
        })
    out["funds.csv"] = funds

    # ------------------------------------------------------------------ #
    # 5. BANK ACCOUNTS                                                     #
    # ------------------------------------------------------------------ #
    ids = IdFactory("bac", 4)
    bank_accounts = []
    holder_ids = [p["id"] for p in persons] + [c["id"] for c in companies]
    holder_types = ["PERSON"] * len(persons) + ["COMPANY"] * len(companies)
    # money movement ~ mostly from personal LPs / SPVs
    for hid, htype in zip(holder_ids, holder_types):
        bank_accounts.append({
            "id": ids.next(),
            "holder_id": hid,
            "holder_type": htype,
            "iban_local": f"IBAN-{r.randint(10**15, 10**16 - 1)}",
            "account_holder_name": (next(p["full_name"] for p in persons if p["id"] == hid) if htype == "PERSON"
                                    else next(c["legal_name"] for c in companies if c["id"] == hid)),
            "bank_name": r.choice(BANKS),
            "bank_country": r.choice(JURISDICTIONS_STANDARD),
            "currency": "USD",
            "account_open_date": _rel_date(r.randint(200, 4000)),
            "is_nostro": 0,
        })
    out["bank_accounts.csv"] = bank_accounts

    # ------------------------------------------------------------------ #
    # 6. PORTFOLIO COMPANIES                                                #
    # ------------------------------------------------------------------ #
    ids = IdFactory("pfo", 4)
    pcos = []
    for _ in range(25):
        pcos.append({
            "id": ids.next(),
            "legal_name": company_name(r),
            "jurisdiction": r.choice(JURISDICTIONS_STANDARD),
            "industry": r.choice(INDUSTRIES),
            "round_invested": r.choice(["Seed", "Series A", "Series B", "Growth"]),
            "amount_invested": r.randint(1, 60) * 1_000_000,
            "currency": "USD",
        })
    out["portfolio_companies.csv"] = pcos

    # ------------------------------------------------------------------ #
    # 7. FUND PARTICIPATIONS + CAPITAL COMMITMENTS                          #
    # ------------------------------------------------------------------ #
    # -------- Mandatory fixture: ensure a high-risk-country TRUST investor
    # (used to drive the EDD case). Create an explicit participation+commitment.
    investor_pool = ([("PERSON", p["id"]) for p in persons[:90]] +
                     [("COMPANY", c["id"]) for c in companies[:40]] +
                     [("TRUST", t["id"]) for t in trusts[:12]])
    fund_ids = [f["id"] for f in funds]
    ids = IdFactory("par", 4)
    participations = []
    commitments = []
    commit_ids = IdFactory("ccm", 4)
    participation_by_investor: dict[str, dict] = {}

    for _ in range(150):
        itype, iid = r.choice(investor_pool)
        fid = r.choice(fund_ids)
        pid = ids.next()
        sub_date = _rel_date(r.randint(30, 2000))
        role = r.choices(["LP", "GP", "SPV"], weights=[9, 0.5, 0.5])[0]
        participations.append({
            "id": pid, "investor_id": iid, "investor_type": itype, "fund_id": fid,
            "role": role, "subscription_date": sub_date, "commitment_currency": "USD",
        })
        participation_by_investor[iid] = {"participation_id": pid, "fund_id": fid}

    out["fund_participations.csv"] = participations

    # Capital commitments (one per participation; a few get a second)
    for par in participations:
        amount = r.choice([2, 5, 10, 20, 50, 100, 150, 300]) * 1_000_000
        funded = int(amount * r.uniform(0.2, 0.9))
        remaining = amount - funded
        commitments.append({
            "id": commit_ids.next(),
            "participation_id": par["id"],
            "fund_id": par["fund_id"],
            "investor_id": par["investor_id"],
            "commitment_amount": amount,
            "commitment_currency": "USD",
            "commitment_date": par["subscription_date"],
            "funded_amount": funded,
            "remaining_commitment": remaining,
            "status": "ACTIVE" if remaining > 0 else "FULLY_FUNDED",
        })
    out["capital_commitments.csv"] = commitments

    # ------------------------------------------------------------------ #
    # 8. CAPITAL CALLS + ALLOCATIONS                                        #
    # ------------------------------------------------------------------ #
    call_ids = IdFactory("cca", 4)
    calls = []
    for fid in fund_ids:
        n_calls = r.randint(3, 8)
        for n in range(1, n_calls + 1):
            calls.append({
                "id": call_ids.next(), "fund_id": fid, "call_number": n,
                "call_date": _rel_date(r.randint(10, 900)),
                "due_date": _rel_date(r.randint(0, 600)),
                "total_call_amount": r.randint(1, 40) * 1_000_000,
                "currency": "USD",
            })
    out["capital_calls.csv"] = calls

    alloc_ids = IdFactory("calo", 4)
    allocations = []
    # Map commitment->participation->fund for allocation consistency
    commit_lookup = {c["id"]: c for c in commitments}
    for call in calls:
        # pick commitments in this fund
        for c in commitments:
            if c["fund_id"] != call["fund_id"]:
                continue
            if r.random() < 0.55:  # not everyone participates in every call
                alloc_amount = int(c["commitment_amount"] * r.uniform(0.02, 0.12))
                allocations.append({
                    "id": alloc_ids.next(),
                    "capital_call_id": call["id"],
                    "commitment_id": c["id"],
                    "investor_id": c["investor_id"],
                    "fund_id": call["fund_id"],
                    "allocated_amount": alloc_amount,
                    "currency": "USD",
                    "status": r.choices(["PAID", "DUE", "LATE"], weights=[7, 2, 1])[0],
                })
    out["capital_call_allocations.csv"] = allocations

    # ------------------------------------------------------------------ #
    # ---- MANDATORY FIXTURE 3: ownership CYCLE                            #
    #       cmp_cycle_a OWNS cmp_cycle_b 40% -> b OWNS c 50% -> c OWNS a 30% #
    # ------------------------------------------------------------------ #
    cycle_a, cycle_b, cycle_c = [c["id"] for c in companies[:3]]
    edges.append({"source": cycle_a, "stype": "COMPANY", "relation": "OWNS",
                  "target": cycle_b, "ttype": "COMPANY", "percentage": 40,
                  "is_direct": 1, "meta": {}})
    edges.append({"source": cycle_b, "stype": "COMPANY", "relation": "OWNS",
                  "target": cycle_c, "ttype": "COMPANY", "percentage": 50,
                  "is_direct": 1, "meta": {}})
    edges.append({"source": cycle_c, "stype": "COMPANY", "relation": "OWNS",
                  "target": cycle_a, "ttype": "COMPANY", "percentage": 30,
                  "is_direct": 1, "meta": {}})

    # ------------------------------------------------------------------ #
    # ---- MANDATORY FIXTURE 1: multi-layer UBO chain                       #
    #       per_0001 -> cmp_0058 (100%) -> cmp_0059 (80%) -> cmp_0060 (70%) #
    # ------------------------------------------------------------------ #
    ubo_person = persons[0]["id"]
    # pick three companies not already used in the cycle
    chain_targets = [c["id"] for c in companies if c["id"] not in (cycle_a, cycle_b, cycle_c)][:3]
    c1, c2, c3 = chain_targets
    edges.append({"source": ubo_person, "stype": "PERSON", "relation": "OWNS",
                  "target": c1, "ttype": "COMPANY", "percentage": 100, "is_direct": 1, "meta": {}})
    edges.append({"source": c1, "stype": "COMPANY", "relation": "OWNS",
                  "target": c2, "ttype": "COMPANY", "percentage": 80, "is_direct": 1, "meta": {}})
    edges.append({"source": c2, "stype": "COMPANY", "relation": "OWNS",
                  "target": c3, "ttype": "COMPANY", "percentage": 70, "is_direct": 1, "meta": {}})

    # ---- CONCEALMENT REALISM: mark the cycle/chain companies as the shell
    # layer they exist to demonstrate. FATF and the Egmont Group's
    # "Concealment of Beneficial Ownership" (2018) find layered shell
    # companies registered in a secrecy jurisdiction the dominant technique
    # for hiding a true owner -- it is the report's single most repeated
    # red flag. Left to whatever is_shell/jurisdiction value they happened
    # to draw at random, the dataset's two flagship UBO fixtures (the
    # ownership cycle and the three-hop chain) could just as easily have
    # looked like an ordinary, transparent group structure. "KY" (Cayman
    # Islands) mirrors the secrecy-jurisdiction pool already used for the
    # high-risk trust fixture above.
    company_by_id = {c["id"]: c for c in companies}
    for shell_id in (cycle_a, cycle_b, cycle_c, c1, c2, c3):
        company_by_id[shell_id]["is_shell"] = 1
        company_by_id[shell_id]["jurisdiction"] = "KY"
        company_by_id[shell_id]["risk_score"] = 82

    # ------------------------------------------------------------------ #
    # 9. PAYMENTS                                                           #
    # ------------------------------------------------------------------ #
    pay_ids = IdFactory("pay", 4)
    payments = []
    recent_allocations = allocations[-180:]  # active/settled recent calls
    for _ in range(800):
        alloc = r.choice(recent_allocations) if recent_allocations else None
        from_acc = r.choice(bank_accounts)
        payer_counterparty = from_acc["holder_id"]
        payer_type = from_acc["holder_type"]
        purpose = r.choice(["Capital call funding", "Subsequent subscription", "Distribution", "Capital call funding"])
        expected_currency = "USD"
        currency = r.choice(CURRENCIES)
        anomaly = None
        amount = int((alloc["allocated_amount"] if alloc else r.randint(1, 30) * 1_000_000)
                     * r.uniform(0.95, 1.05))
        status = "SETTLED"
        matching_call = alloc["capital_call_id"] if alloc else ""
        matching_alloc = alloc["allocated_amount"] if alloc else 0

        if alloc and r.random() < 0.04:  # OVERPAYMENT
            amount = int(alloc["allocated_amount"] * 1.6)
            anomaly = {"class": "OVERPAYMENT", "detail": "amount exceeds allocated amount"}
        elif alloc and r.random() < 0.04:  # THIRD-PARTY
            other_acc = r.choice(bank_accounts)
            payer_counterparty = other_acc["holder_id"]
            payer_type = other_acc["holder_type"]
            anomaly = {"class": "THIRD_PARTY", "detail": "payer differs from LP legal entity"}
        elif alloc and r.random() < 0.04:  # UNKNOWN SOURCE
            payer_counterparty = "UNKNOWN"
            payer_type = "UNKNOWN"
            anomaly = {"class": "UNKNOWN_SOURCE", "detail": "no matching counterparty"}
        elif alloc and r.random() < 0.04:  # UNEXPECTED CURRENCY
            currency = "AED"
            expected_currency = "USD"
            anomaly = {"class": "UNEXPECTED_CURRENCY", "detail": "AED received, USD expected"}
        else:
            currency = expected_currency

        if anomaly is None and alloc and r.random() < 0.012:  # MATCHED SANCTIONED PAYER
            anomaly = {"class": "SANCTIONED_PAYER", "detail": "payer resembles sanctions entry"}

        payments.append({
            "id": pay_ids.next(),
            "payment_ref": f"TX-{r.randint(10**5, 10**6 - 1)}",
            "payment_date": _rel_date(r.randint(0, 120)),
            "amount": amount,
            "currency": currency,
            "expected_currency": expected_currency,
            "from_account_id": from_acc["id"],
            "from_counterparty_id": payer_counterparty,
            "from_counterparty_type": payer_type,
            "to_fund_id": alloc["fund_id"] if alloc else "",
            "to_account_id": "",
            "payment_purpose": purpose,
            "funding_source": r.choices(["OWN_FUNDS", "THIRD_PARTY", "UNKNOWN"],
                                        weights=[8, 1.5, 0.5])[0],
            "matching_capital_call_id": matching_call,
            "matching_allocated_amount": matching_alloc,
            "status": status,
            "anomaly_metadata": json.dumps(anomaly) if anomaly else "",
        })

    # ---- MANDATORY FIXTURE 4: STRUCTURING (5 small payments, one day) ----
    base_amount = 2_000_000
    struct_acc = r.choice(bank_accounts)
    struct_call_id = calls[0]["id"]
    for i in range(5):
        payments.append({
            "id": pay_ids.next(),
            "payment_ref": f"STRUC-{i + 1}",
            "payment_date": _rel_date(30),
            "amount": int(base_amount / 5),
            "currency": "USD", "expected_currency": "USD",
            "from_account_id": struct_acc["id"],
            "from_counterparty_id": struct_acc["holder_id"],
            "from_counterparty_type": struct_acc["holder_type"],
            "to_fund_id": funds[0]["id"], "to_account_id": "",
            "payment_purpose": "Capital call funding",
            "funding_source": "OWN_FUNDS",
            "matching_capital_call_id": struct_call_id,
            "matching_allocated_amount": base_amount,
            "status": "SETTLED",
            "anomaly_metadata": json.dumps({"class": "STRUCTURING",
                                            "detail": "5 sub-threshold payments same day"}),
        })
    out["payments.csv"] = payments

    # ------------------------------------------------------------------ #
    # 10. DOCUMENTS                                                         #
    # ------------------------------------------------------------------ #
    doc_ids = IdFactory("doc", 4)
    documents = []
    entity_tuples = ([("PERSON", p["id"]) for p in persons[:60]] +
                     [("COMPANY", c["id"]) for c in companies[:40]] +
                     [("TRUST", t["id"]) for t in trusts[:8]])
    for _ in range(150):
        etype, eid = r.choice(entity_tuples)
        dtype = r.choice(DOC_TYPES)
        documents.append({
            "id": doc_ids.next(), "doc_type": dtype, "entity_id": eid,
            "entity_type": etype,
            "file_name": f"{eid}_{dtype}_{r.randint(1, 999)}.pdf",
            "uploaded_date": _rel_date(r.randint(5, 1500)),
            "verified": int(r.random() < 0.85),
            "verification_status": r.choices(["VERIFIED", "PENDING", "FAILED"],
                                             weights=[8, 1.5, 0.5])[0],
        })
    out["documents.csv"] = documents

    # ------------------------------------------------------------------ #
    # 11. SANCTIONS / PEP / ADVERSE MEDIA reference lists                    #
    # ------------------------------------------------------------------ #
    san_ids = IdFactory("san", 4)
    sanctions = []
    for i in range(100):
        sanctions.append({
            "id": san_ids.next(),
            "name": person_name(r),
            "list_name": r.choice(["UN", "OFAC", "EU", "UK"]),
            "id_document": f"DOC-{r.randint(10**7, 10**8 - 1)}",
            "date_of_birth": _rel_date(r.randint(6000, 26000)),
            "citizenship": r.choice(JURISDICTIONS_STANDARD),
            "source": "synthetic watchlist",
            "match_key": f"san_{i}",
        })
    out["sanctions_entries.csv"] = sanctions

    pep_ids = IdFactory("pep", 4)
    peps = []
    for i in range(80):
        peps.append({
            "id": pep_ids.next(), "name": person_name(r),
            "role": r.choice(PEP_ROLES),
            "country": r.choice(JURISDICTIONS_STANDARD),
            "term": f"{r.randint(2015, 2024)}-Present",
            "source": "synthetic PEP list",
        })
    out["pep_entries.csv"] = peps

    adm_ids = IdFactory("adm", 4)
    adverse = []
    for i in range(50):
        adverse.append({
            "id": adm_ids.next(),
            "entity_name": r.choice([company_name(r), person_name(r)]),
            "headline": f"{r.choice(ADVERSE_CATEGORIES).replace('_', ' ').title()} probe reported",
            "article_date": _rel_date(r.randint(5, 900)),
            "source_url": f"https://news.example.com/article/{i}",
            "category": r.choice(ADVERSE_CATEGORIES),
            "severity": r.choices(["Low", "Medium", "High"], weights=[3, 5, 2])[0],
        })
    out["adverse_media.csv"] = adverse

    # ------------------------------------------------------------------ #
    # 12. ALERTS + CASES + REGULATORY REPORTS                               #
    # ------------------------------------------------------------------ #
    alt_ids = IdFactory("alt", 4)
    case_ids = IdFactory("cas", 4)
    rpt_ids = IdFactory("rpt", 4)
    alerts = []
    cases = []
    reports = []

    case_by_key: dict[str, str] = {}
    # Cases for the mandatory fixtures
    fixture_cases = []
    # (a) high-risk TRUST EDD case
    fixture_cases.append({
        "case_type": "EDD", "entity_type": "TRUST", "entity_id": trusts[0]["id"],
        "priority": "High", "risk_score": 88, "assignee_role": "COMPLIANCE",
        "opened_days_ago": 12,
    })
    # (b) ownership-cycle UBO review
    fixture_cases.append({
        "case_type": "UBO_REVIEW", "entity_type": "COMPANY", "entity_id": cycle_a,
        "priority": "Medium", "risk_score": 70, "assignee_role": "AML_OFFICER",
        "opened_days_ago": 20,
    })
    # (c) multi-layer UBO review on the outer target company
    fixture_cases.append({
        "case_type": "UBO_REVIEW", "entity_type": "COMPANY", "entity_id": c3,
        "priority": "Low", "risk_score": 45, "assignee_role": "COMPLIANCE",
        "opened_days_ago": 30,
    })
    # (d) sanctions screening hit on ubo person
    fixture_cases.append({
        "case_type": "SCREENING_HIT", "entity_type": "PERSON", "entity_id": ubo_person,
        "priority": "High", "risk_score": 95, "assignee_role": "AML_OFFICER",
        "opened_days_ago": 4,
    })

    for fcx in fixture_cases:
        cid = case_ids.next()
        case_by_key[f"{fcx['case_type']}|{fcx['entity_type']}|{fcx['entity_id']}"] = cid
        cases.append({
            "id": cid, "case_type": fcx["case_type"], "entity_id": fcx["entity_id"],
            "entity_type": fcx["entity_type"], "priority": fcx["priority"],
            "status": "OPEN", "risk_score": fcx["risk_score"],
            "opened_date": _rel_date(fcx["opened_days_ago"]), "closed_date": "",
            "assignee_role": fcx["assignee_role"],
        })

    # Bulk cases (screening / tx / onboarding)
    pool_cases = [
        ("INVESTOR_ONBOARDING", "PERSON", persons[10]["id"]),
        ("EDD", "COMPANY", companies[5]["id"]),
        ("PAYMENT_MISMATCH", "PAYMENT", payments[3]["id"]),
        ("PAYMENT_MISMATCH", "PAYMENT", payments[7]["id"]),
        ("CAPITAL_CALL_EXCEPTION", "PAYMENT", payments[11]["id"]),
        ("SCREENING_HIT", "PERSON", persons[2]["id"]),
        ("SCREENING_HIT", "PERSON", persons[20]["id"]),
        ("STR", "INVESTOR", persons[5]["id"]),
        ("AUDIT_REQUEST", "INVESTOR", companies[3]["id"]),
        ("INVESTOR_ONBOARDING", "TRUST", trusts[1]["id"]),
    ]
    for ctype, etype, eid in pool_cases:
        cid = case_ids.next()
        is_open = r.random() < 0.6
        cases.append({
            "id": cid, "case_type": ctype, "entity_id": eid, "entity_type": etype,
            "priority": r.choice(["Low", "Medium", "High", "High"]),
            "status": "OPEN" if is_open else "CLOSED",
            "risk_score": r.randint(30, 95),
            "opened_date": _rel_date(r.randint(2, 120)),
            "closed_date": "" if is_open else _rel_date(r.randint(0, 60)),
            "assignee_role": r.choice(["COMPLIANCE", "AML_OFFICER", "SENIOR_MGMT"]),
        })

    # Bulk cases (expand to ~30 total) — screening + tx-monitoring driven
    bulk_case_types = [
        ("SCREENING_HIT", "PERSON", persons),
        ("INVESTOR_ONBOARDING", "PERSON", persons),
        ("EDD", "COMPANY", companies),
        ("PAYMENT_MISMATCH", "PAYMENT", payments),
        ("CAPITAL_CALL_EXCEPTION", "PAYMENT", payments),
    ]
    while len(cases) < 28:
        ctype, etype, pool = bulk_case_types[r.randrange(5)]
        ent = r.choice(pool)
        eid = ent["id"] if etype != "PAYMENT" else ent.get("id")
        cid = case_ids.next()
        is_open = r.random() < 0.55
        cases.append({
            "id": cid, "case_type": ctype, "entity_id": eid, "entity_type": etype,
            "priority": r.choice(["Low", "Medium", "High", "High"]),
            "status": "OPEN" if is_open else "CLOSED",
            "risk_score": r.randint(30, 95),
            "opened_date": _rel_date(r.randint(2, 120)),
            "closed_date": "" if is_open else _rel_date(r.randint(0, 60)),
            "assignee_role": r.choice(["COMPLIANCE", "AML_OFFICER", "SENIOR_MGMT"]),
        })

    # Alerts tied to the cases above + a few loose
    alert_specs = [
        ("PERSON", ubo_person, "SANCTIONS", "SANCTIONS_MATCH", "High", 4),
        ("PERSON", persons[2]["id"], "ADVERSE_MEDIA", "ADVERSE_MEDIA_MATCH", "High", 6),
        ("COMPANY", companies[5]["id"], "PEP", "PEP_DIRECTOR", "Medium", 9),
        ("COMPANY", cycle_a, "UBO", "UBO_CYCLE", "Medium", 20),
        ("PAYMENT", payments[3]["id"], "TRANSACTION", "OVERPAYMENT_RULE", "Medium", 8),
        ("PAYMENT", payments[7]["id"], "TRANSACTION", "THIRD_PARTY_RULE", "Medium", 8),
        ("PAYMENT", payments[11]["id"], "TRANSACTION", "UNEXPECTED_CURRENCY_RULE", "Low", 8),
        ("TRUST", trusts[0]["id"], "UBO", "NO_SINGLE_UBO", "High", 12),
        # A PEP screened as a direct customer, not only as a company
        # director -- see the persons[50] fixture above.
        ("PERSON", pep_investor["id"], "PEP", "PEP_SELF", "High", 7),
    ]
    for etype, eid, atype, rule, sev, days in alert_specs:
        linked = case_by_key.get(f"{atype_mapping(atype)}|{etype}|{eid}", "")
        alerts.append({
            "id": alt_ids.next(), "entity_id": eid, "entity_type": etype,
            "alert_type": atype, "source_rule": rule, "severity": sev,
            "status": "OPEN", "created_date": _rel_date(days), "linked_case_id": linked,
        })

    # Bulk screening alerts (expand to ~40 alerts total).
    #
    # Two PEP sources, deliberately: FATF Recs. 12/22 cover a PEP who is
    # themselves the customer just as much as a PEP who sits behind a
    # corporate vehicle as a director. The entity_type now travels with the
    # source tuple instead of being inferred from alert_type (the old
    # inference -- "PERSON unless it's a PEP" -- could not express a PEP
    # alert against a PERSON at all, which was exactly the gap).
    bulk_alert_sources = [
        ("SANCTIONS", "SANCTIONS_MATCH", "High", "PERSON", persons),
        ("ADVERSE_MEDIA", "ADVERSE_MEDIA_MATCH", "Medium", "PERSON", persons),
        ("PEP", "PEP_DIRECTOR", "Medium", "COMPANY", companies),
        ("PEP", "PEP_SELF", "Medium", "PERSON", persons),
    ]
    while len(alerts) < 34:
        atype, rule, sev, etype, pool = bulk_alert_sources[r.randrange(len(bulk_alert_sources))]
        ent = r.choice(pool)
        alerts.append({
            "id": alt_ids.next(), "entity_id": ent["id"], "entity_type": etype,
            "alert_type": atype, "source_rule": rule, "severity": sev,
            "status": r.choices(["OPEN", "CLOSED", "REVIEW"], weights=[5, 3, 2])[0],
            "created_date": _rel_date(r.randint(2, 150)), "linked_case_id": "",
        })

    out["alerts.csv"] = alerts
    out["cases.csv"] = cases

    # Regulatory reports
    for ctype, etype, eid, rtype in [
        ("STR", "PERSON", persons[5]["id"], "STR"),
        ("FATCA", "PERSON", persons[10]["id"], "FATCA"),
        ("CRS", "COMPANY", companies[3]["id"], "CRS"),
        ("AML_RETURN", "FUND", funds[0]["id"], "AML_RETURN"),
    ]:
        reports.append({
            "id": rpt_ids.next(), "report_type": rtype, "entity_id": eid,
            "entity_type": etype, "filing_date": _rel_date(r.randint(0, 90)),
            "due_date": _rel_date(r.randint(-5, 90)),
            "status": r.choice(["FILED", "DRAFT", "DUE"]),
            "filed_to": "IFSCA" if rtype != "STR" else "FIU-IND",
        })
    out["regulatory_reports.csv"] = reports

    # ------------------------------------------------------------------ #
    # 13. EDGES + UBO CHAINS                                                #
    # ------------------------------------------------------------------ #
    edge_ids = IdFactory("edg", 4)
    edge_rows = []
    # direct ownership between some persons and companies (bulk, acyclic-ish)
    per_pool = [p["id"] for p in persons[:60]]
    for c in companies:
        if c["id"] in (cycle_a, cycle_b, cycle_c, c1, c2, c3):
            continue
        if r.random() < 0.6:
            owner = r.choice(per_pool)
            edges.append({"source": owner, "stype": "PERSON", "relation": "OWNS",
                          "target": c["id"], "ttype": "COMPANY",
                          "percentage": r.choice([100, 70, 60, 51, 40, 100]),
                          "is_direct": 1, "meta": {}})
    # trustee/beneficiary edges for trusts
    for t in trusts:
        if r.random() < 0.7 and r.choice(["tr", "be"]) == "be":
            ben = r.choice(per_pool)
            edges.append({"source": t["id"], "stype": "TRUST", "relation": "BENEFICIARY_OF",
                          "target": ben, "ttype": "PERSON", "percentage": r.choice([15, 20, 25, 30]),
                          "is_direct": 1, "meta": {}})
    for t in trusts:
        if r.random() < 0.5:
            trustee_cmp = r.choice([c["id"] for c in companies])
            edges.append({"source": trustee_cmp, "stype": "COMPANY", "relation": "TRUSTEE_OF",
                          "target": t["id"], "ttype": "TRUST", "percentage": None,
                          "is_direct": 1, "meta": {}})
    # commitment edges (investor -> fund)
    for par in participations[:60]:
        edges.append({"source": par["investor_id"], "stype": par["investor_type"],
                      "relation": "COMMITS_CAPITAL_TO", "target": par["fund_id"],
                      "ttype": "FUND", "percentage": None, "is_direct": 1, "meta": {}})
    # payments satisfy calls
    for p in payments[:40]:
        if p["matching_capital_call_id"]:
            edges.append({"source": p["id"], "stype": "PAYMENT", "relation": "SATISFIES",
                          "target": p["matching_capital_call_id"], "ttype": "CAPITAL_CALL",
                          "percentage": None, "is_direct": 1, "meta": {}})

    for e in edges:
        edge_rows.append({
            "id": edge_ids.next(), "source_id": e["source"], "source_type": e["stype"],
            "relation": e["relation"], "target_id": e["target"], "target_type": e["ttype"],
            "percentage": e["percentage"] if e["percentage"] is not None else "",
            "is_direct": e["is_direct"], "start_date": _rel_date(r.randint(200, 3000)),
            "end_date": "", "metadata_json": json.dumps(e["meta"]),
        })
    out["edges.csv"] = edge_rows

    # UBO chains (resolved) — nest for the multi-layer + trust + cycle
    ubochains = [
        {
            "target_entity": c3, "resolved_at": _rel_date(30),
            "chain": [
                {"from": c3, "relation": "OWNS", "to": c2, "percentage": 70},
                {"from": c2, "relation": "OWNS", "to": c1, "percentage": 80},
                {"from": c1, "relation": "OWNS", "to": ubo_person, "percentage": 100},
            ],
            "effective_ubo": ubo_person, "ultimate_percentage": 56.0,
            "conclusion": "single_ubo",
        },
        {
            "target_entity": trusts[0]["id"], "resolved_at": _rel_date(12),
            "chain": [{"from": trusts[0]["id"], "relation": "BENEFICIARY_OF",
                       "to": persons[44]["id"], "percentage": 24}],
            "effective_ubo": None, "ultimate_percentage": None,
            "conclusion": "no_single_ubo_over_25pct",
        },
        {
            "target_entity": cycle_a, "resolved_at": _rel_date(20),
            "chain": [{"from": cycle_a, "relation": "OWNS", "to": cycle_b, "percentage": 40},
                      {"from": cycle_b, "relation": "OWNS", "to": cycle_c, "percentage": 50},
                      {"from": cycle_c, "relation": "OWNS", "to": cycle_a, "percentage": 30}],
            "effective_ubo": None, "ultimate_percentage": None,
            "conclusion": "ownership_cycle_detected",
        },
    ]
    with open(os.path.join(OUT_DIR, "ubochains.json"), "w", encoding="utf-8") as f:
        json.dump(ubochains, f, indent=2)

    # ------------------------------------------------------------------ #
    # Write all CSVs + manifest                                             #
    # ------------------------------------------------------------------ #
    schemas = {
        "persons.csv": PERSONS_H, "companies.csv": COMPANIES_H, "trusts.csv": TRUSTS_H,
        "funds.csv": FUNDS_H, "bank_accounts.csv": ACCOUNTS_H,
        "fund_participations.csv": PARTICIP_H, "capital_commitments.csv": COMMIT_H,
        "capital_calls.csv": CALLC_H, "capital_call_allocations.csv": CALLA_H,
        "payments.csv": PAY_H, "portfolio_companies.csv": PFO_H, "documents.csv": DOC_H,
        "sanctions_entries.csv": SAN_H, "pep_entries.csv": PEP_H,
        "adverse_media.csv": ADM_H, "alerts.csv": ALT_H, "cases.csv": CASE_H,
        "regulatory_reports.csv": RPT_H, "edges.csv": EDGE_H,
    }
    for name, headers in schemas.items():
        write_csv(name, headers, out.get(name, []))

    counts = {name: len(out.get(name, [])) for name in schemas}
    manifest = {
        "generator_version": "1.0.0",
        "seed": 20260807,
        "generated_at": "2026-08-07",
        "counts": counts,
        "edges": len(edge_rows),
        "ubochains": len(ubochains),
        "disclaimer": "All records are entirely synthetic and invented.",
        "hash": manifest_hash(json.dumps(counts, sort_keys=True)),
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return out


def atype_mapping(alert_type: str) -> str:
    """Map alert_type -> case_type for linking alerts to cases."""
    return {
        "SANCTIONS": "SCREENING_HIT",
        "ADVERSE_MEDIA": "SCREENING_HIT",
        "PEP": "SCREENING_HIT",
        "UBO": "UBO_REVIEW",
        "TRANSACTION": "PAYMENT_MISMATCH",
    }.get(alert_type, "INVESTOR_ONBOARDING")


if __name__ == "__main__":
    generated = generate()
    print("Synthetic dataset generated in:", OUT_DIR)
    for name, rows in sorted(generated.items()):
        print(f"  {name}: {len(rows)} rows")
    print("  manifest.json written.")
