# PLAN-001 — Assisted review

**Implements:** SPEC-001 · **Status: awaiting your approval — no code written yet**

## What I found in the codebase first

- `vinzor/screening.py` is the pattern to copy exactly: a boundary adapter with
  an **injected transport**, so every test runs offline against canned
  responses and no test ever touches the network.
- The human gate is already structural (`engine.decide` + `_verify_decider` on
  the fold). **The model needs no new restraint — it simply is not an enrolled
  actor.** Nothing to build here; this is the payoff of the earlier work.
- The event vocabulary is additive-only, so new event types are safe.
- `briefing.py` is the only place user-facing sentences may live, and
  `test_briefing.py` sweeps every string for leaked jargon. Draft text must go
  through it.

## One correction to the spec

**Spec open question 4 assumed we would redact names before sending. That is
wrong for this agent, and the fix is better than the original idea.**

You cannot ask a model "are these the same person" after replacing both names
with "Person A" — the names *are* the task. But sending the raw file to a model
and asking it to compare is also wrong: it invites the model to hallucinate a
date of birth or a passport number into a compliance record.

So the design splits the work:

| Step | Who does it | Why |
|---|---|---|
| Compare the fields — names, dates, nationality, identifiers | **Deterministic code** (`compare.py`) | Facts must be facts. A hallucinated date in a regulatory file is unacceptable, and this comparison is simple code. |
| Judge whether the differences are *significant* | **Model** | Genuine judgement: transliteration (Mohammed/Muhamad), name order (Wei Zhang/Zhang Wei), whether 2 years apart is a data-entry error but 23 years is decisive. |
| Write it up for the officer | **Model** | What it is actually good at. |
| Decide | **Human** | Always. |

The model receives the *computed comparison*, not the raw file. And then:

> **The hallucination guard.** Before a draft is shown, it is checked against
> the comparison it was given: any date, number or name in the draft that was
> not in the input rejects the draft. The officer sees "no draft available"
> rather than a confident invention. This is a test, not a hope.

## Architecture

```
  Case (screening hit)
        │
        ▼
  compare.py          deterministic: what matches, what differs   ← no AI
        │
        ▼
  assist.py           build prompt · call model · validate · cost  ← the boundary
        │                     ▲
        │                     └── azure.py (transport, injected in tests)
        ▼
  DRAFT_PREPARED      an event: recommendation, wording, model, prompt version, cost
        │
        ▼
  the fold            attaches the draft to the Case (runs no rules)
        │
        ▼
  briefing.py         the officer's sentences · jargon-swept
        │
        ▼
  the screen          "Suggested for your review" + [Use this wording]
```

Drafting is **never** in the write path. Like `observe_deadlines`, it is a
separate boundary call: `prepare_drafts(engine, today, drafter, limit)`.
A slow or dead model can never block a page load or a decision.

## Changes to the record

Additive only:

- **`DRAFT_PREPARED`** — case_id, recommendation, reasoning, suggested wording,
  checks to perform, model, prompt version, input/output tokens, cost, whether
  identity data was sent, and the comparison it was based on.
- **`CASE_DECIDED`** gains two optional fields: which draft was on screen, and
  what the officer did with it (accepted / edited / rejected / contradicted).

No schema migration — the log is JSON payloads under a hash chain.

## Security and cost

- Key from `AZURE_OPENAI_KEY` env only. Never in a file, never in the log,
  never in an error message. (There is already a plaintext key committed in
  `01/.claude/settings.json` — **please rotate that one**.)
- Every request records exactly what was sent, so "what did you send to a
  third party about my investor" is answerable.
- Hard budget cap, default USD 50. Costs are events, so the running total is
  summed from the log. At the cap, drafting stops with a plain sentence and the
  product keeps working.
- **No customer data in prompts for the demo dataset** — it is synthetic
  anyway, which makes this slice safe to build before a data-residency answer.

## Tests — all offline, no network, no key

| Test | Proves |
|---|---|
| `test_the_comparison_is_deterministic` | Same inputs, same comparison, always |
| `test_a_draft_that_invents_a_fact_is_rejected` | The hallucination guard, with a canned bad response |
| `test_a_draft_never_closes_a_case` | The gate holds against the drafter |
| `test_an_unavailable_model_records_nothing` | Failure writes no event, says one sentence |
| `test_drafting_stops_at_the_budget_cap` | No call is made past the cap |
| `test_the_draft_says_nothing_technical` | Draft text joins the jargon sweep |
| `test_the_decision_records_what_the_officer_did_with_the_draft` | Accepted/edited/rejected/contradicted |
| `test_drafts_replay_identically` | Still one auditable history |
| `test_the_prompt_never_contains_the_api_key` | Obvious, worth pinning |

## Steps — each one a commit, in this order

1. **`compare.py`** — deterministic field comparison. No AI, no network. *(Can
   be built and shipped today; useful on its own — it improves the evidence
   panel even with no model at all.)*
2. **Event types + fold** for `DRAFT_PREPARED`.
3. **`assist.py`** — Draft type, prompt builder, hallucination validator,
   `Drafter` protocol with injected transport. Fully tested offline.
4. **`azure.py`** — the real HTTP call. *Blocked on your answers below.*
5. **Budget guard** and cost recording.
6. **`briefing.py`** — the officer's sentences for the draft panel.
7. **Server route + the panel in the UI.**
8. **Decision captures the draft outcome.**
9. **Quality page** — accepted / edited / rejected / **contradicted**, and
   spend to date.

Steps 1–3 and 5–9 need no Azure access at all. **Only step 4 is blocked**, so
if the answers take a day, nothing stalls.

## What I do not know

Stated rather than guessed:

1. **Azure's current API surface.** My web search hit a session limit before I
   could verify the current `api-version` and endpoint shape. I will read it
   from your live deployment rather than write it from memory.
2. **Whether Azure OpenAI is enabled on your subscription** — in some regions
   it needs an approval step. Worth checking before we count on it.
3. **Which model is deployed, and where.** Region matters for the data-residency
   answer we will eventually give a GIFT City customer.
4. **Whether the $600 is Azure-wide.** If so, Azure Document Intelligence is a
   strong second use for the KYC-extraction spec — possibly better value than
   spending it all on tokens.

## Cost sanity check

A draft is roughly a few thousand input tokens and a few hundred output. At
current frontier-model rates that is **cents, not dollars** — a few hundred
drafts would sit inside USD 50. Exact figures go in the plan once step 5
measures real spend.

**So the honest risk is not overspending. It is the credits expiring with
nothing shipped.** That argues for starting steps 1–3 now rather than waiting
on the Azure answers.

---

# Built — 12 August 2026

All nine steps. What follows is what actually happened, including where the
plan was wrong, because a plan nobody corrects afterwards is decoration.

| Step | Landed in | Held in place by |
|---|---|---|
| 1 | `vinzor/compare.py` | `tests/test_compare.py` — 23 |
| 2 | `model.py`, `cases.py`, `engine.py` | folded into the existing replay tests |
| 3 | `vinzor/assist.py` | `tests/test_assist.py` — 31 |
| 4 | `vinzor/azure.py` | `tests/test_azure.py` — 28, all offline |
| 5 | `assist.spent_so_far` / `prepare_drafts` | budget tests in `test_assist.py` |
| 6 | `briefing.py` — `Line`, `Suggestion`, `Report` | the jargon sweep now walks them |
| 7 | `server.py` `/api/quality`, `web/app.js`, `web/app.css` | `tests/test_server.py` |
| 8 | `DraftUse` on the decision, `assist.draft_use` | `test_assist.py` |
| 9 | `vinzor/quality.py`, `briefing.report` | `test_briefing.py` |

292 tests, ~12 seconds, no network.

## Answers that arrived, and what they changed

- **The $600 is Azure-wide.** Azure Document Intelligence is now a named
  candidate against Docling for KYC intake (backlog #8, ECOSYSTEM.md).
- **India region only, from the start.** This became the strongest constraint
  in the module: an allowlist checked at construction, *and* the `x-ms-region`
  header checked on every reply — because a Global Standard deployment routes
  wherever there is capacity, and the declared region proves nothing about
  where the tokens went. It is also the only failure here that is not silent.

## Where the plan was wrong

- **Redacting names before sending (dropped, and rightly).** The task *is*
  name comparison. What replaced it is narrower and stronger: the model never
  sees the file, only a comparison computed by `compare.py`, and every figure
  it writes back is checked against that comparison. Presidio's trigger has
  been rewritten in ECOSYSTEM.md accordingly.
- **`comparison_for` first looked in the finding's `detail`.** A finding
  records what a rule *concluded*, not a copy of its input. It now follows
  `evidence.source_seq` back to the screening event. Caught by a test that
  returned `None` against real data.
- **The guard only policed figures.** A draft saying "as an AI language model"
  is a different failure and just as unpublishable. `_OFF_LIMITS` now rejects
  it; formatting characters are stripped rather than rejected, since a good
  draft wrapped in asterisks is still a good draft.
- **`AzureTransport`'s dataclass `repr` printed the environment**, key
  included — `repr(os.environ)` prints every variable, and a repr is what a
  traceback reaches for first. Found by a test written to assert the opposite.
  Fixed with `repr=False` and a second test that reproduces the old leak.

## Two things real data taught the screen

Neither was visible against fixtures. Both were found by running the whole
chain against the self-hosted watchlist and reading the output as an officer.

- The comparison put **`SG` beside `cn`** — the source cases codes however it
  likes. `countries.py` now renders them as countries, falling back to the code
  when it is not one we know.
- The name note read **"shares zhang; differs on lei, li"** — set arithmetic,
  leaving the reader to reconstruct the comparison. It now reads "both names
  include Zhang; ours also has Li; the list entry also has Lei."

## Still open

- **No Azure deployment is configured yet**, so the model half has never run
  against a live endpoint. Everything below it has, end to end: the local
  watchlist matched a synthetic investor against a real sanctions entry and
  the comparison, panel and quality page all rendered from it.
- **The guard's own firing rate is not counted.** A destroyed draft writes
  nothing — which keeps invented figures out of an append-only record, and
  leaves one number the quality page cannot show. It says so on screen.
  Backlog #4.
