# Vinzor Core

Operational trust infrastructure for private capital — the trust spine, rebuilt small,
enforcing IFSCA's rules and citing them.

Facts arrive as **events** and are appended to a hash-chained log that is *both* the
source of truth and the audit trail. Rules evaluate each fact **once, at the moment it
is recorded**, and what they conclude — the finding, its severity, the clause text as it
then stood — is itself written to the log. Everything a person sees is a pure fold over
that log; replay runs no rules, so no change to any policy can rewrite what the system
said last month. Only an enrolled **human** in a deciding role can close a Case — and who
may decide is itself recorded in the log.

The full architecture, its invariants and the decision records live in
[DESIGN.md](DESIGN.md).

```
events ──► graph ──► policies ──► cases ──► human decision ──► (back into the log)
             │          │
             │          └─ every finding cites IFSCA AML/CFT/KYC Guidelines, 2022
             └─ beneficial ownership computed per clause 1.3.3
        └──────────────── one hash-chained log ────────────────────┘
```

Stdlib only. No dependencies, no services, no build step.

## Live

<https://dikytp5q85njb.cloudfront.net>

The real thing, on the synthetic book, in Mumbai (`ap-south-1`). Every push to
`main` lands there once the suite passes -- the workflow in
`.github/workflows/deploy.yml` refuses to deploy a red build, because the
suite is the only thing holding the invariants in DESIGN.md in place.

Signing in needs a password, and they are deliberately not published: this
repository is public, and a password in a public file is a door, not a
credential.

**The assistant runs there**, over Bedrock in Mumbai — no key anywhere, the
instance holds a role and `bedrock.py` mints a credential per request. What
it cannot do is use a good model, and the reason is the whole residency
argument rather than a limitation of the adapter: in `ap-south-1` every
Anthropic model is offered **only** through a cross-region inference profile,
which routes to whichever region in Asia-Pacific has capacity. So Claude is
refused and something lesser is used. That trade is stated on the record
because a firm should hear it from us rather than from an inspector.

**Watchlist screening runs there too**, against a local index of all
4,001,232 entities OpenSanctions publishes -- every sanctions list, every
published PEP list, criminal, debarment and wanted registers -- answering in
about a fifth of a second with nothing leaving the machine. The alternative
was a key against a hosted API, which needs no infrastructure and sends a
client book across a border; `leaves_this_machine()` in `screening.py` exists
to make that choice visible, and its default is the case that leaves.

Screening the narrower `sanctions` collection alone would have fitted a
machine a third of the size: 291,264 entities against four million. It was
measured and rejected, because five of the six topic branches in
`screening.py` would then never fire -- including the politically-exposed one
that clause 5.5(b)(iii) reserves for senior management. On the real book that
difference is visible: of the first forty parties checked, the matches worth
a look are PEPs and a debarment, not sanctions.

The data is CC-BY-NC: evaluation and internal research only. Selling on top of
it needs a licence from OpenSanctions, which is an open commercial item.

## Run it

```bash
python -m vinzor
```

Loads the synthetic FME dataset (1,238 events), opens 180 cases, resolves beneficial
ownership against IFSCA's own test, shows a Case with the clause and the event behind
every claim on it, demonstrates that an AI actor cannot approve anything, and proves the
chain verifies and replays identically.

```bash
python -m vinzor serve
```

```powershell
# self-hosted screening (one-time setup in selfhost/, then):
selfhost\yente.ps1 start
$env:VINZOR_SCREENING_URL = "http://127.0.0.1:8090"
$env:VINZOR_SCREENING_SCOPE = "sanctions"
python -m vinzor screen "Some Name"
```

Opens the workspace at <http://127.0.0.1:8000>: pick who you are, work the morning
list, settle a file. Pass `--workspace <path>` to persist it — decisions are events, so
they survive a restart.

```bash
python -m pytest tests -q
```

126 tests, ~12s, no database and no network.

## Layout

Nine layers, bottom to top. Each depends only on the ones beneath it, and that is
the order to read them in.

| Layer | Files | Lines | What it is |
| --- | --- | --- | --- |
| **1 · The record** | `model.py`, `eventlog.py` | 604 | The vocabulary of facts, and the only thing written to disk. SQLite, append-only, hash-chained. Data only — no I/O, no clock in `model.py`. |
| **2 · What we know** | `graph.py`, `licence.py`, `calendar.py`, `cases.py` | 1,162 | Ownership and beneficial ownership per IFSCA 1.3.3; the FME's own registration and required posts; what is owed to IFSCA and when; open Cases. All four are rebuilt from the log, never stored. |
| **3 · The rules** | `policies.py`, `citations.py`, `enforcement.py` | 1,153 | The checks that open a Case, the clause each one cites verbatim with provenance, and a scorecard against IFSCA's 25 published enforcement actions. |
| **4 · The engine** | `engine.py` | 297 | The wiring. One `apply_event`, used identically by the live path and by replay, running no policies. |
| **5 · The outside world** | `screening.py`, `compare.py`, `assist.py`, `azure.py`, `quality.py`, `countries.py` | 1,471 | Watchlists over the OpenSanctions/yente protocol; the deterministic comparison; the drafting boundary and its hallucination guard; Azure with India-only residency; what the assistant cost and how often it was overruled. |
| **6 · The words** | `briefing.py` | 1,326 | **Every sentence the system says to a person.** Nothing user-facing lives anywhere else. |
| **7 · The screen** | `server.py`, `web/`, `__main__.py`, `__init__.py` | 1,491 | HTTP over the engine — four reads, one write. One page, no framework, no build step. The CLI, and where the clock lives. |
| **8 · The demo firm** | `seed.py`, `data/` | 4,515 | A synthetic GIFT City fund manager: 21 tables, ownership chains with deliberate loops, 1,300 payments — and the generator that produced them. |
| **9 · The proof** | `tests/`, `selfhost/` | 3,862 | 292 tests, ~12 seconds, no network. Plus portable Elasticsearch + yente with no Docker and no admin rights: `yente.ps1 start`, then `reindex`. |

Alongside them: **`DESIGN.md`** (the architecture, its invariants, the decision
records — read it first), **`AGENTS.md`** (the rules of engagement for anyone,
human or model, touching this code), **`ECOSYSTEM.md`** (every tool from the
open-source survey: in use, earmarked with its trigger, or rejected with its
reason), **`BACKLOG.md`**, and **`specs/`**.

Everything else that was once in this project now sits in `../archive/`, which
nothing here reads.

---

## Decisions

### The event log is also the audit trail

The previous build kept an event store *and* a separate hash-chained audit log — two
records that could disagree. Here a human decision is an event like any other. "Show me
the audit trail" is "read the log."

### Findings are facts; replay runs no rules

The load-bearing decision, made after demonstrating the alternative was broken: when
findings were derived at fold time, editing a policy and rebuilding **changed history** —
a case the officer saw as CRITICAL replayed as LOW, citing amended clause text that did
not exist when they decided. Now the rulepack evaluates each fact once at the write
boundary, and its conclusions are recorded as `CASE_OPENED` / `EVIDENCE_RECORDED` events,
stamped with the rulepack version, the fact and its findings committed as one
transaction. `test_history_survives_the_deletion_of_every_policy` folds the same log with
an empty rulepack and gets identical Cases.

### One `apply_event`, used by both the live path and rebuild

Replay-equals-live is true by construction, not by discipline — and the fold is now pure:
`test_replay_never_runs_policies` detonates if a rebuild ever evaluates a rule.

### Who may decide is workspace data, not server configuration

People are enrolled by event; the fold verifies every decision against the enrolment that
precedes it in the log. A forged decision event claiming a deciding role fails on replay
unless a forged enrolment was written too — and that one is sitting in the audit trail
with a hash over it.

### The core never reads a clock

Every timestamp is supplied by the caller. `__main__.py` reads `date.today()` because a
boundary is the right place for I/O. `test_identical_inputs_produce_identical_hashes`
fails the moment one creeps into the core.

### Policies are Python functions, not a YAML DSL

The previous build had a YAML rule DSL *and* a second engine running Python expressions
from a config file through `eval()`. Both existed so a non-engineer could edit rules
without a deploy — a feature bought on credit for a customer who does not exist yet. What
it cost: two engines pointed at one filename, a `policies.yaml` the engine that claimed it
could no longer parse, and an arbitrary-code-execution path in compliance logic.

### Nothing reaches a Case uncited

`evaluate()` raises `UncitedFinding` if a policy produces a finding with no clause behind
it. A rule cannot get into the case file on nothing but an engineer's sense of good
practice. The obligation text on a Case is the regulator's words, not mine.

### The clause register says what it does not know

Every clause is `verified=False` until a human reads it in the source PDF and signs it
off. These were extracted by machine; the system says so, on the Case, in the demo output.
A compliance product that overstates the provenance of its own rules is worse than one
that has none. The register also carries `KNOWN_PENDING_AMENDMENTS` — currently the
IFSCA circular of **3 August 2026**, which is not yet incorporated. The gap is visible
rather than silent.

### No numeric risk score

Severity comes from the policy that opened the Case, because the policy knows why. A
composite 0–100 score is a lossy summary of evidence the Case already carries.

### UBO is computed, never stored — and to IFSCA's test, not FATF's

See below. This is the substantive finding of the build.

### Plain language is core logic, not presentation

`briefing.py` holds every word a Principal Officer will ever read. Not the web
app, not the audit export, not an email template — one file.

Two reasons. If each surface translated `POL_UBO_CYCLE` into a sentence for
itself, the screen and the file handed to a regulator would eventually say
different things. And the wording of a compliance obligation *is* domain logic:
a sentence that tells a Principal Officer the wrong thing is a compliance
failure, not a styling bug, so it needs a test rather than a designer. The
practical benefit is that a compliance consultant can review the entire
product's language by reading one file, without reading any code.

`tests/test_briefing.py` walks every string the system can display and fails the
build if implementation vocabulary leaks — case ids, policy ids, entity ids,
SCREAMING_CASE, hashes, sequence numbers, JSON punctuation. It has caught two
real leaks so far, both only visible against the real dataset: an internal
record id printed where a payer's name belongs, and raw entity ids inside the
sentence describing an ownership loop.

Their vocabulary stays — beneficial owner, PEP, sanctions, enhanced due
diligence, clause 1.3.3(a). That is their profession, not jargon, and a clause
reference is their strongest defence. Ours goes, all of it.

### Work is grouped by the question being asked, not listed flat

180 items in one queue is a spreadsheet with extra steps. Items raising the same
obligation — eight payments held for the same reason under the same clause — are
one piece of work with eight instances: explain once, list them, decide each.
The real dataset collapses from 180 rows to 12 groups.

### Standard library over the wire, too

`http.server` rather than FastAPI, one page of vanilla JS rather than Next.js. The API
is three reads and one write; an ASGI stack, npm and a build step would buy nothing a
user could see, and the core's zero-dependency property is worth more than a generated
OpenAPI page. Moving to FastAPI is a rewrite of `server.py` and nothing else.

The browser holds no compliance wording of its own — every sentence arrives from
`briefing.py` over the wire, so the screen cannot drift from the audit file.

**It is not a deployment.** It binds to localhost and does not authenticate anyone: you
say who you are and it believes you. The human gate is structural and real — an AI actor
can never settle a file — but *which human* is self-asserted, and the sign-in page says
so rather than implying otherwise. Real identity is the first thing to add before this
touches customer data.

### One connection, serialised

`ThreadingHTTPServer` gives each request its own thread and SQLite binds a connection to
its creating thread, so the first browser load broke the write path. The fix is one
shared connection behind a lock rather than a connection per thread: this is a
single-writer ledger, and reading the tail then appending has to be atomic or two writers
derive the same sequence number and the same previous hash. Caught by
`tests/test_server.py`, which drives a real socket rather than a mocked handler.

### The roadmap comes from the regulator's enforcement record

`enforcement.py` scores this system against IFSCA's published enforcement actions —
25 of them, July 2024 to July 2026. It started at **0 of 8** and is now **7 of 8**, with
three of those counted as `PARTIAL` rather than `FULL`.

That distinction is the point. IFSCA established the Neo Asset Management failure by
walking into the office on four separate days and finding it shut. No software sees an
empty room. What this models is the *precondition* — a post nobody holds, a holder not
recorded as based in the IFSC, a threshold crossed with the clock running — and the
scorecard says so rather than claiming the observation.

The one action still missed is Karvy Broking, whose registration was cancelled for
quarterly reports it never filed. Nothing here knows that anything is due. That is next,
and the record chose it, not an opinion.

### Licence scope and required offices

Built because the enforcement record said so, from the regulations rather than from a
guess: Regulation 3(4) fixes what each of the three FME categories may undertake and the
categories nest; Regulation 137 forbids anything else without prior approval; Regulation 7
sets out who must hold office and 7(5) requires them to be based out of the IFSC.

Two details worth keeping: an unknown licence category permits **nothing** — it fails
closed, because an unregistered entity must not read as unrestricted. And the six-month
grace period after AUM passes USD 1 billion is derived from the reported year-end date
rather than from a clock, so it replays identically.

A Case opened for a vacant post does not close itself when the post is filled. It gains
evidence saying who filled it and when, and a person still closes it — the confirmation
that the appointment was made *and notified* is the audit record worth having.

### The obligation calendar is computed, never stored

Given the date a licence was granted and a date to look from, every obligation instance
since is derivable. A stored schedule would be a stored conclusion — the same mistake as
persisting a UBO answer. Only the *filings* are events, because only they are facts.

Three obligations, all from primary sources: the **quarterly report** (circular of 31 May
2023, amended 3 November 2023 from half-yearly to quarterly, formats revised 3 April 2025
— due within **21 calendar days** of the quarter end), and the **flat** and
**turnover-based recurring fees** (fee circular IFSCA-DTFA/1/2026 — due 1 April, payable
by 30 April). The USD 100-per-month-or-part late charge is modelled too, and the circular's
warning that paying it is "without prejudice to any other action" is the whole point:
Karvy paid with its registration.

### Time enters as an observation, not as a clock reading

A deadline passing is a fact about the world, so a boundary observes it and appends
`FILING_OVERDUE` — exactly as a bank feed observes a payment. The Case then rests on a
dated fact rather than on whatever the clock said when someone happened to open the page,
and `observe_deadlines` is idempotent: looking twice writes nothing the second time.

`datetime.date` *arithmetic* is used freely — adding 21 days to a quarter end replays
identically. `date.today()` remains forbidden in the core. Date maths is pure; date
reading is I/O.

### A pending filing is not a Case

Something due in three weeks is not yet a problem, and putting it in the case queue would
bury the things that are. Upcoming obligations appear in their own forward-looking
section of the briefing; a Case opens only once something is actually late. One missed
return is `HIGH`; a second outstanding period is `CRITICAL`, because the enforcement
record is not about one late filing — it is about a warning ignored and then another
quarter missed.

### Tenant isolation is one file per workspace

Not a `tenant_id` column. A column must be filtered correctly in every query forever; a
separate file cannot leak even when a query is wrong.

### SQLite, not Postgres

A single-writer append-only ledger. Move when there are concurrent writers or a real
operational read load; it is a port of one module.

---

## The beneficial-ownership test is 10%, not 25%

FATF guidance says 25%. The previous build, its synthetic dataset, and its research notes
all assumed 25%. **IFSCA does not.**

Clause 1.3.3 of the AML/CFT/KYC Guidelines sets a different test per customer type, and
the company threshold was cut from twenty-five per cent to **ten** by circular in May 2023:

| Customer type | Test | Clause |
| --- | --- | --- |
| Company | **more than 10%** of shares, capital or profits | 1.3.3(a) |
| Partnership firm | **more than 10%** of capital or profits | 1.3.3(b) |
| Unincorporated association | **more than 15%** of property, capital or profits | 1.3.3(c) |
| Trust | author, trustee, beneficiaries at **10% or more**, and anyone with ultimate effective control | 1.3.3(d) |

Three consequences the engine now implements:

1. **"More than" and "or more" are different tests.** 1.3.3(a) excludes a holder at
   exactly 10%; 1.3.3(d) includes one. Both are in the text, so both are in the code.
2. **A trust must name its author and trustee whatever their percentage.** Undeclared
   mandatory parties make the answer `INCOMPLETE`, not "resolved".
3. **Failing the test is not a dead end.** Under the 1.3.3(c) explanation, where no
   natural person is identified the beneficial owner *is* the senior managing official.
   The Case says that, instead of shrugging.

The engine also states what it **cannot** assess: 1.3.3(a)(ii) makes someone a beneficial
owner if they can appoint a majority of directors or otherwise control management, and no
directorship or control-agreement data reaches this system. Every result carries that
caveat rather than implying the ownership limb is the whole test.

**Honest measurement of the impact.** On this synthetic dataset the change flips exactly
one of thirty non-person investors — `trs_0006`, where a beneficiary holding exactly 25.0%
is a beneficial owner under IFSCA and invisible under a `> 25%` test. The generator made
holdings large, so the dataset understates the effect; on real ownership data, where
sub-25% holdings are ordinary, the difference is the point.

---

## Deliberately not here

| Not built | Add it when |
| --- | --- |
| Waterfalls, NAV, distributions, fund accounting | A customer is paying for fund ops, not compliance |
| Capital-call reconciliation engine | Payments have a live bank feed to reconcile against |
| STR / regulatory filing generation | A real FIU-IND schema and a fund actually filing |
| Watchlist *ingestion* (maintaining merged lists in-house) | We stop querying a service and start curating lists — nomenklatura/zavod territory, per ECOSYSTEM.md. Live screening itself is now built: `python -m vinzor screen "Name"` |
| A rule-authoring DSL | A paying customer needs to write rules without a deploy |
| LLM inference in the decision path | Never in the path. Beside it as a drafting seam, once a human reviews the drafts |
| Neo4j | The graph outgrows an adjacency map — it is 51 edges today |
| HTTP API and UI | Below. It is the next thing, not a missing thing |
| Multi-tenancy, JWT auth, Alembic, SQLAlchemy, Docker | There is one workspace and no deployment |

---

## What the inherited work got wrong

Found by building against it.

1. **The 25% threshold is wrong for this regulator** — see above. It runs through the
   prototype, the dataset fixtures and `docs/`.

2. **`ubochains.json` disagrees with `edges.csv`.** Its `single_ubo` chain cites three hops
   that do not exist in the edge table — the path is written back to front — and its
   `no_single_ubo_over_25pct` chain names a `BENEFICIARY_OF` edge the graph does not
   contain. The 56% answer is right; the provenance is fiction. `validate.py` checks that
   the file says the right words, not that the graph supports them.

3. **`schema.md` documents the opposite edge direction from the one the data uses** for
   person-terminated chains.

4. **`vinzor/screening/` (package) shadows `vinzor/screening.py` (module)**, so the entire
   foundation prototype fails at import: 23 failed, 26 errors.

5. **`model.Event.type` was renamed to `event_type` without updating callers.**

6. **`policies.yaml` was overwritten with a shape its own engine cannot parse**, belonging
   to a second policy engine that nothing imports and that runs `eval()`.

7. **A live OpenRouter API key sits in plaintext in `01/.claude/settings.json`.** Rotate it.

8. **The corpus is behind.** `Vinzor Fund Launch OS/corpus/ifsca/` holds a 30-section
   parse of the January 2026 modifications circular, not the 82-page consolidated Master
   Guidelines — and IFSCA issued a further amending circular on 3 August 2026 (Rule 8,
   FINgate 2.0, V-CIP jurisdictions, cross-border wire transfer reporting) that nothing in
   this repository reflects.

## The assistant

A model drafts; a person decides. The seam the architecture was shaped around,
now filled — and shaped by one rule: **a model may judge, never establish.**

`compare.py` computes what is the same and what differs between an investor and
a watchlist entry. Pure, deterministic, no model. `assist.py` hands that
comparison to Azure OpenAI, which decides what it *means* and writes it as
English an officer could sign. Every figure in the reply is checked against the
comparison it was given; one invention and the draft is destroyed rather than
shown, because a fabricated passport number in a compliance file is not a
nearly-right answer.

It cannot decide anything. A model is not an enrolled actor, so the human gate
that was already there refuses it — no new restraint was needed, which is the
point of having built the gate first.

Three properties worth knowing:

- **India only.** Checked against an allowlist before the first call, and
  against Azure's `x-ms-region` header on every reply. Every other failure
  here is silent and cheap; this one raises.
- **Capped.** Spend is summed from the log, so the cap cannot drift out of step
  with what was actually spent.
- **Measured on being wrong.** Every decision records what happened to the
  suggestion: accepted, edited, rejected, or **contradicted**. Contradiction is
  computed from the recorded outcome, not reported by the screen.

```bash
python -m vinzor rescreen --workspace fund.db   # record what actually matched
python -m vinzor assist --workspace fund.db --dry-run   # the comparison, no model
python -m vinzor assist --workspace fund.db     # prepare suggestions
```

## Next

Three things, in order.

1. **Someone qualified verifies the 21 clauses in `citations.py`** and flips them
   to `verified=True`. Half a day with a GIFT City CA or CS. Until then every
   screen tells the user the clause has not been checked by a person — which is
   honest, and is also the largest open gap in the product.
2. **A real sign-in.** Enrolment already lives in the log, so this is the session
   layer on top of it, not a redesign. Required before this touches a customer's
   data — today you say who you are and the server believes you.
3. **Regulator-correspondence tracking** — the one enforcement ground with nothing
   built against it. A notice arrives, a clock starts, and silence is itself a
   breach.

`BACKLOG.md` carries the ordered list and the reasoning behind the order.
