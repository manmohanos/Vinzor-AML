# Vinzor Synthetic FME Dataset — Schema

This document defines every table in `data/generated/`, its fields, and the
relations between entities. **All records are entirely synthetic (invented)** for
design and demonstration. The dataset is generated deterministically from a fixed
seed; `validate.py` enforces the structural invariants below.

* **Audience** — dataset consumers (the prototype loader), the Blueprint's
  knowledge-graph schema, and future design work.
* **Correspondence** — entity/node types here map 1:1 to the prototype's
  knowledge-graph node types and the Blueprint's schema.

## Conventions

* **ID prefixes** — one per entity type for greppable, stable IDs:

  | Prefix | Table |
  |--------|-------|
  | `per_` | persons |
  | `cmp_` | companies |
  | `trs_` | trusts |
  | `fnd_` | funds |
  | `bac_` | bank_accounts |
  | `par_` | fund_participations |
  | `ccm_` | capital_commitments |
  | `cca_` | capital_calls |
  | `calo_`| capital_call_allocations |
  | `pay_` | payments |
  | `pfo_` | portfolio_companies |
  | `doc_` | documents |
  | `san_` | sanctions_entries |
  | `pep_` | pep_entries |
  | `adm_` | adverse_media |
  | `alt_` | alerts |
  | `cas_` | cases |
  | `rpt_` | regulatory_reports |
  | `edg_` | edges |

* **Currencies** — quoted in ISO 4217 (USD, AED, EUR, GBP, ...). Monetary fields are
  nominal amounts (not scaled).
* **Dates** — ISO `YYYY-MM-DD`; all records are dated on/before the static
  dataset date **2026-08-07**.

## Tables

### persons
KYC counterparties — natural persons (investors, UBOs, directors, beneficiaries).
| Field | Type | Notes |
|-------|------|-------|
| id | key | `per_NNNN` |
| full_name | str | |
| nationality | code | ISO-2 |
| country_of_residence | code | |
| citizenship | code | |
| dob | date | |
| id_document_type | enum | PASSPORT / NATIONAL_ID |
| id_document_number | str | |
| email | str | |
| occupation | str | |
| pep_flag | 0/1 | |
| high_risk_jurisdiction | 0/1 | |
| risk_score | int | 0–100 baseline |
| status | enum | ACTIVE / BLOCKED / CLOSED |

### companies
Legal entities (fund vehicles, SPVs, operating companies, shells).
| id | legal_name | jurisdiction | registration_number | country_of_incorporation | industry | is_shell (0/1) | is_listed (0/1) | address | risk_score | status |

### trusts
Trust structures used for UBO analysis.
| id | trust_name | jurisdiction | trust_deed_date | settlor_count | trustee_count | has_protector | is_discretionary | has_beneficiary_class | trust_type | risk_score |

### funds
The GIFT City–resident fund vehicles under IFSCA supervision.
| id | fund_name | fund_type | vehicle_jurisdiction | gifsc_resident_flag | strategy | vintage_year | target_size | currency | nav_currency |

### bank_accounts
Bank/movement accounts.
| id | holder_id (FK) | holder_type | iban_local | account_holder_name | bank_name | bank_country | currency | account_open_date | is_nostro |

### fund_participations
Link table: investor ↔ fund, with a role.
| id | investor_id (FK) | investor_type | fund_id (FK) | role (LP/GP/SPV) | subscription_date | commitment_currency |

### capital_commitments
Capital an investor has committed to a fund (drives capital calls).
| id | participation_id (FK) | fund_id (FK) | investor_id (FK) | commitment_amount | commitment_currency | commitment_date | funded_amount | remaining_commitment | status |

### capital_calls
A drawdown notice issued by a fund.
| id | fund_id (FK) | call_number | call_date | due_date | total_call_amount | currency |

### capital_call_allocations
Per-investor share of a capital call (what each LP owes).
| id | capital_call_id (FK) | commitment_id (FK) | investor_id (FK) | fund_id (FK) | allocated_amount | currency | status (PAID/DUE/LATE) |

### payments
Inbound money movements for call funding / subscriptions. **This is the
transaction-monitoring table** — `anomaly_metadata` (JSON) tags anomalous rows.
| Field | Type | Notes |
|-------|------|------|
| id | key | `pay_NNNN` |
| payment_ref | str | |
| payment_date | date | |
| amount | num | |
| currency | code | actual |
| expected_currency | code | expected |
| from_account_id | FK | |
| from_counterparty_id | str | LP id or UNKNOWN |
| from_counterparty_type | enum | |
| to_fund_id | FK | |
| to_account_id | FK | |
| payment_purpose | str | |
| funding_source | enum | OWN_FUNDS / THIRD_PARTY / UNKNOWN |
| matching_capital_call_id | FK | |
| matching_allocated_amount | num | |
| status | enum | SETTLED / ... |
| anomaly_metadata | JSON | class tags (below) |

**Anomaly classes** (`anomaly_metadata.class`):
`OVERPAYMENT`, `THIRD_PARTY`, `UNKNOWN_SOURCE`, `UNEXPECTED_CURRENCY`,
`STRUCTURING`, `SANCTIONED_PAYER`.

### portfolio_companies
Companies the funds invest in.
| id | legal_name | jurisdiction | industry | round_invested | amount_invested | currency |

### documents
KYC/EDD evidence documents.
| id | doc_type | entity_id (FK) | entity_type | file_name | uploaded_date | verified (0/1) | verification_status |

### sanctions_entries
Reference watchlist (synthetic) used for sanctions screening.
| id | name | list_name | id_document | date_of_birth | citizenhip | source | match_key |

### pep_entries
Reference politically-exposed-persons list.
| id | name | role | country | term | source |

### adverse_media
Reference adverse-media entries.
| id | entity_name | headline | article_date | source_url | category | severity |

### alerts
Screening / transaction alerts (input to case management).
| id | entity_id | entity_type | alert_type (SANCTIONS/PEP/ADVERSE_MEDIA/UBO/TRANSACTION) | source_rule | severity | status | created_date | linked_case_id |

### cases
The Vinzor primitive — a compliance Case (onboarding, EDD, screening hit,
payment mismatch, STR, audit request, ...).
| id | case_type | entity_id | entity_type | priority | status (OPEN/CLOSED) | risk_score | opened_date | closed_date | assignee_role |

### regulatory_reports
Filings (STR → FIU-IND; FATCA/CRS/AML return → IFSCA).
| id | report_type | entity_id | entity_type | filing_date | due_date | status | filed_to |

### edges
The generic knowledge-graph edge store (node `source` →relation→ node `target`).
| Field | Type | Notes |
|-------|------|------|
| id | key | `edg_NNNN` |
| source_id | FK | |
| source_type | enum | PERSON/COMPANY/TRUST/FUND/PAYMENT/... |
| relation | enum | OWNS / CONTROLS / TRUSTEE_OF / BENEFICIARY_OF / DIRECTOR_OF / COMMITS_CAPITAL_TO / SATISFIES / ACCOUNT_OF |
| target_id | FK | |
| target_type | enum | |
| percentage | num/blank | ownership % when relevant |
| is_direct | 0/1 | |
| start_date / end_date | date | |
| metadata_json | JSON | |

## Relations / knowledge-graph edges

* `OWNS` — person→company, company→company (percentage = ownership share).
* `TRUSTEE_OF` — company→trust (low risk normally; a corporate trustee is a flag).
* `BENEFICIARY_OF` — trust→person (percentage = beneficiary share).
* `COMMITS_CAPITAL_TO` — investor→fund.
* `SATISFIES` — payment→capital_call.
* `ACCOUNT_OF` — bank_account→holder.

## Mandatory fixture contracts (enforced by `validate.py`)

1. **Multi-layer UBO chain** — an OWNS path of ≥ 3 hops resolves to a single UBO
   (> 25% effective); recorded in `ubochains.json` with conclusion
   `single_ubo`.
2. **Trust with no single UBO > 25%** — conclusion `no_single_ubo_over_25pct`;
   drives an EDD case.
3. **Ownership cycle** — A OWNS B(40%) → B OWNS C(50%) → C OWNS A(30%); conclusion
   `ownership_cycle_detected`; drives a UBO_REVIEW case.
4. **All six transaction anomalies** — each class appears ≥ 1 time in
   `payments.csv`.
5. **Screening alerts** — at least one each of SANCTIONS, PEP, ADVERSE_MEDIA.
6. **Shell-company layering in a secrecy jurisdiction** — the ownership-cycle
   and three-hop UBO-chain companies (`cmp_0001`–`cmp_0006`) are marked
   `is_shell=1` and domiciled in `KY` (Cayman Islands). FATF and the Egmont
   Group's *Concealment of Beneficial Ownership* (2018) name layered shell
   companies in a secrecy jurisdiction as the dominant real-world technique
   for hiding a true owner; without this, the fixtures read as an ordinary
   transparent group structure instead of the concealment pattern they exist
   to demonstrate.
7. **A PEP appears as a direct customer, not only as a company director** —
   `alerts.csv` has at least one `PEP` row with `entity_type=PERSON`
   (`source_rule=PEP_SELF`). FATF's PEP guidance (Recommendations 12 & 22)
   is fundamentally about a politically exposed *individual* as the
   customer or beneficial owner; every PEP alert previously targeted a
   COMPANY ("a director is a PEP"), so an LP who is themselves a serving or
   former public official — the most common real-world PEP scenario for a
   fund manager — never appeared anywhere in the dataset.

## `ubochains.json`

Resolved ultimate-beneficial-owner conclusions. Each element:
```json
{
  "target_entity": "cmp_0060",
  "resolved_at": "2026-07-08",
  "chain": [{"from": "...", "relation": "OWNS", "to": "...", "percentage": 70}],
  "effective_ubo": "per_0001",
  "ultimate_percentage": 56.0,
  "conclusion": "single_ubo"
}
```

## `manifest.json`

Generator metadata: version, seed, per-table counts, edge/ubo count,
synthetic-data disclaimer, and a content hash for reproducibility checks.

---

*Every field, name, and number in this dataset is synthetic and invented.*
