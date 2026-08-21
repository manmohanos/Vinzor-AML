# Vinzor Core — System Design

The architecture, its invariants, the decisions behind them, and the seams
deliberately left open. The README says what the system does; this says why it
is shaped the way it is, and what would have to be true before that shape
changes.

## The system in one paragraph

Vinzor is operational trust infrastructure for an IFSCA-regulated Fund
Management Entity. Facts about the world enter at boundaries and are appended
to a hash-chained log. Rules evaluate each fact **once, at the moment it is
recorded**, and what they conclude — the finding, its severity, the clause
text it rests on — is itself written to the log as a fact. Everything a person
sees is a fold over that log. Only a human in a deciding role can close a
Case, and who may decide is itself recorded in the log. The log is the audit
trail; there is nothing beside it.

```
   the world                    the boundary                the log (one, hash-chained)
┌──────────────┐   ┌──────────────────────────────┐   ┌────────────────────────────────┐
│ registries    │   │ ingest(fact)                 │   │ FACTS        entity registered │
│ bank feeds    ├──►│   fold fact into state       ├──►│              ownership, money  │
│ screening     │   │   evaluate rulepack ONCE     │   │              screening, filing │
│ people typing │   │   record findings as events  │   │ FINDINGS     case opened       │
│ the calendar  │   │ observe_deadlines(today)     │   │              evidence recorded │
│ (a clock)     │   │ decide(case, human, reason)  │   │ DECISIONS    case decided      │
└──────────────┘   └──────────────────────────────┘   │ ENROLMENT    who may decide    │
                                                       └───────────────┬────────────────┘
                                                                       │  pure fold,
                                                                       ▼  no rules run
                                                       ┌────────────────────────────────┐
                                                       │ state: graph · licence ·       │
                                                       │ calendar · casebook · actors   │
                                                       └───────────────┬────────────────┘
                                                                       ▼
                                                       briefing (every sentence) → screen,
                                                       demo, audit export — same words
```

## The two kinds of record

**Facts** are observations: an ownership declaration, a payment, a screening
result, a licence granted, a deadline observed to have passed. They arrive
only at boundaries, which are the only places that may read a clock.

**Findings and decisions** are also facts — about the system and the people
operating it. *"On 12 August, rulepack 2026-08-12.1 opened a CRITICAL case
citing clause 5.9 as it then stood"* and *"Meera Nair, enrolled as AML
Officer, escalated it, for this reason"* are events in the same log as the
payment that triggered them.

This is the load-bearing decision of the design, made after demonstrating the
alternative was broken: when findings were derived at fold time, editing a
policy and rebuilding **changed history** — a case the officer saw as CRITICAL
replayed as LOW, citing amended clause text that did not exist when they
decided. The hash chain protected the inputs and not what the system said.
For a product whose promise is "reconstruct the decision as it was made,"
what the system said *is* evidence.

Consequences, all intended:

- **Rules run exactly once, at the write boundary.** Replay folds recorded
  events and runs no policies — deleting every policy tomorrow would not
  change a single historical Case.
- **Rule changes apply forward only**, which is the correct regulatory
  semantics. Re-assessing old facts under new rules is a deliberate act that
  appends new findings dated the day of re-assessment (a seam, not yet built).
- **Decisions cannot dangle.** A decision references a case id recorded in the
  log, not one recomputed by whatever the dedupe logic is this month.
- **Clause text is frozen at finding time.** The citation on a Case is the
  text the officer saw, however many circulars land afterwards.
- **Each finding is stamped with the rulepack version** that produced it.

## Invariants

Each is enforced by a named test; a claim without a test is not on this list.

| # | Invariant | Enforced by |
|---|---|---|
| 1 | The log is append-only, at the database layer | `test_database_refuses_update` / `_delete` |
| 2 | Any edit, removal or reorder of history breaks the chain | `test_editing_a_payload_breaks_the_chain` etc. |
| 3 | Identical inputs produce identical logs (no clock, no randomness in the core) | `test_identical_inputs_produce_identical_hashes` |
| 4 | Replay equals live state, always | `test_live_state_equals_a_full_replay` |
| 5 | Replay runs no policies; history is immune to rule changes | `test_replay_never_runs_policies`, `test_history_survives_the_deletion_of_every_policy` |
| 6 | A fact and its findings commit atomically — the log never holds half a thought | `test_a_fact_and_its_findings_are_one_transaction` |
| 7 | No finding reaches a Case without a clause citation | `test_a_policy_cannot_open_a_case_on_an_uncited_finding` |
| 8 | Only an enrolled human in a deciding role can close a Case — enforced at the API, and again when folding the log | `test_no_one_else_can`, `test_a_forged_decision_is_refused_on_replay_too`, `test_a_forged_enrolment_claim_is_refused_on_replay` |
| 9 | A decision requires a written reason, recorded permanently | `test_a_decision_requires_a_rationale` |
| 10 | No implementation vocabulary reaches a reader, on any surface | `test_no_implementation_vocabulary_reaches_the_reader` (+ the real-dataset sweep) |
| 11 | Every machine-extracted clause says whether a human has verified it | `test_a_citation_says_whether_a_human_has_checked_it` |
| 12 | Coverage claims match the enforcement scorecard, partial never counted as full | `test_partial_coverage_is_never_counted_as_full` |

## Decisions

Short records; the module docstrings carry the detail.

1. **One log, and it is the audit trail.** A separate audit store is a second
   truth that can disagree with the first.
2. **Findings are facts** (above). Evaluation at the write boundary; folds
   everywhere else.
3. **The core never reads a clock.** Date arithmetic is pure and allowed;
   `date.today()` is I/O and lives only at boundaries. A deadline passing
   enters as an observed event, exactly like a payment.
4. **Who may decide is workspace data, not server configuration.** People are
   enrolled by event; the fold verifies every decision against the enrolment
   that precedes it in the log. A forged decision event needs a forged
   enrolment event too — both visible in the audit trail.
5. **Policies are Python functions**, versioned as a rulepack constant. No
   YAML dialect, no `eval`. A customer-authored rule language is a seam for a
   paying customer.
6. **Plain language is core logic.** `briefing.py` holds every sentence any
   surface shows; the screen and the regulator's file cannot drift apart.
7. **Derived conclusions are never stored; observations always are.** UBO
   answers and obligation schedules are computed on demand. What the system
   *told someone* is an observation about the system, hence recorded.
8. **Tenant isolation is one file per workspace.** A misfiltered column can
   leak; a separate file cannot.
9. **Standard library throughout.** SQLite, `http.server`, vanilla JS. Every
   dependency is someone else's release schedule in the audit path.
10. **The roadmap is the regulator's enforcement record**, encoded as a
    scorecard the product can fail.
11. **A model may judge, never establish.** `compare.py` computes what is the
    same and what differs — pure, deterministic, no model. `assist.py` hands
    that comparison to a model, which decides what it *means* and writes it as
    English. Every figure in the reply is checked against the comparison it was
    given; one invention and the draft is destroyed rather than shown. This is
    the only division that makes a language model safe near a regulatory file:
    a hallucinated date of birth is not a nearly-right answer, it is a
    fabricated record.
12. **The assistant is measured on how often it was overruled.** `DraftUse`
    records what happened to every suggestion: accepted, edited, rejected, or
    **contradicted**. Contradiction is computed from the recorded outcome, not
    reported by the screen, because it is the number a firm would be tempted
    not to report. `quality.py` counts it from the same log as the files.
13. **Residency is enforced twice and fails loudly.** India-only, checked
    against an allowlist before the first call and against Azure's
    `x-ms-region` header on every reply. Every other assistant failure is
    silent and cheap — no model, no draft, the officer works as they did
    yesterday. A residency breach is the one exception: it means data went
    somewhere it should not have, so it raises.

## Provenance convention

`Event.actor` names who asserted a fact. Where a fact has a documentary basis
(an extracted register, a bank statement line, a provider response), the
payload carries it under `basis` — by convention, not schema, until a real
ingestion source exists. The event vocabulary is **additive only**: types are
never renamed or removed, because logs outlive code.

## Seams deliberately open

Designed so they bolt on without reshaping the log; not built, because
nothing real consumes them yet.

| Seam | Shape when built | Build when |
|---|---|---|
| Identity | Signed sessions resolving to an enrolled actor; enrolment events already carry the role | First pilot with real users |
| Multi-workspace serving | `workspaces/<name>.db`, workspace in the URL path, one engine per file; nothing shared | We host for more than one FME |
| AI drafting | **Built** (`assist.py`, `azure.py`): a boundary, never in the write path, that reads a Case and appends a `DRAFT_PREPARED` fact. A model is not an enrolled actor, so the existing human gate refuses it without a single new restraint | *Trigger fired* |
| Document / provider ingestion | Adapters that mint facts with `basis` provenance. **Screening is built**: `screening.py` speaks the OpenSanctions/yente protocol over stdlib urllib (see ECOSYSTEM.md). Documents follow the same shape | First real KYC pack (Docling, per the register) |
| Re-assessment under a new rulepack | A command that evaluates current state and appends findings dated *now*, marked as re-assessment | First incorporated amendment (the 3 Aug 2026 circular is queued) |
| Regulator export | Copy of the workspace file + chain verification + the briefing rendered to a document | First audit or inspection request |
| Agents 2–5 of SPEC-001 | Same shape as the match investigator: deterministic facts in, prose out, a guard, a recorded draft, a human gate | After a real officer accepts the first one |
| Postgres | Port `eventlog.py`; schema is plain SQL | Concurrent writers or real read load |

## One fact, end to end

A payment arrives flagged as from a possible sanctioned party.

1. A boundary calls `ingest(PAYMENT_RECEIVED, …)` with the date it happened.
2. The fact folds into state; the rulepack evaluates it once. `POL_PAY_SANCTIONED_PAYER`
   fires, citing clauses 5.9 and 11.2 verbatim from the register.
3. The fact and a `CASE_OPENED` finding — severity, summary, citations, clause
   text, rulepack version — commit to the log as one transaction.
4. The briefing folds the log and renders the group *"1 payment arrived from a
   party that may be sanctioned"*, with the obligation in plain words and the
   regulator's, and the caution that the clause is not yet human-verified.
5. Meera Nair — enrolled as AML Officer by an event earlier in the log — reads
   it, writes her reason, records *Refer upwards*. The decision appends;
   the fold verifies her enrolment and role before accepting it.
6. Any future rebuild, under any future rulepack, reproduces exactly this
   history. The chain proves nothing was altered; the recorded findings prove
   what the system said; the enrolment proves who was allowed to say yes.
