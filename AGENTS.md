# AGENTS.md — persistent context for coding agents

Vinzor is compliance infrastructure for fund managers regulated by IFSCA in
GIFT City. Correctness and auditability outrank speed and cleverness, always.

Read **DESIGN.md** before changing anything structural. It carries the
architecture, twelve invariants and the decision records. **ECOSYSTEM.md**
carries every third-party tool with its adoption trigger.

## How work happens here

1. A **spec** in `specs/` says what the user gets (`SPEC-nnn`).
2. A **plan** says how it will be built (`PLAN-nnn`) — and a human approves it
   *before* any implementation.
3. Implement **one step of the approved plan** at a time. Touch nothing else.
4. Prove it: run the tests, show the output. "Looks good" is not evidence.
5. One meaningful change, one commit.

If a request is ambiguous, do not guess: investigate the codebase, state what
you found, state what you do not know, and ask. `BACKLOG.md` is the ordered
work list.

## Never

- **Never let anything but an enrolled human close a Case.** Not a rule, not a
  model, not a script. Enforced on write and again on replay.
- **Never derive findings at read time.** Rules run once, at the write
  boundary; what they concluded is recorded. Replay must run no policies, or
  changing a rule silently rewrites history.
- **Never read a clock inside `vinzor/`** (`date.today()`, `time.time()`,
  randomness). Callers pass dates in. Date *arithmetic* is fine.
- **Never open a Case without a clause citation.** `evaluate()` raises if you
  try.
- **Never put implementation vocabulary in front of a user** — no ids, enum
  values, JSON, hashes, stack traces. Every user-facing sentence lives in
  `briefing.py` and a test sweeps for leaks.
- **Never add a dependency to the core.** Adapters at boundaries may use one if
  ECOSYSTEM.md justifies it; `vinzor/` itself is standard library only.
- **Never claim coverage you cannot show.** Partial is labelled partial;
  unverified clauses say so on screen.
- **Never let a model establish a fact.** Deterministic code computes the
  comparison; the model judges what it means and writes prose. A draft that
  states a figure it was not given is destroyed, not shown (`assist.py`).
- **Never send investor data outside India.** On Azure the region is checked
  before the first call and again on every reply, from the `x-ms-region`
  header. On Bedrock there is no such header, so the guarantee is structural
  instead: the endpoint is derived from the region, cross-region inference
  profiles are refused by prefix, and SigV4 names the region in the string it
  signs. A breach raises loudly — it is the one failure that is not silent
  (`azure.py`, `bedrock.py`). **This rule costs something and it is still the
  rule:** every Anthropic model in `ap-south-1` is offered only through a
  cross-region profile, so the best model available is refused and a weaker
  one used.
- **Never put a secret anywhere but the environment.** Not a file, not an
  argument, not an event, not an exception, not a `repr`. The log is
  append-only: a key written there cannot be taken back.

## Commands

```bash
python -m pytest tests -q        # the whole suite, ~10s, no network
python -m vinzor                 # walk the full chain over the sample dataset
python -m vinzor serve           # the real screen at http://127.0.0.1:8000
python -m vinzor screen "Name"   # live watchlist check
python -m vinzor rescreen        # screen a whole workspace, record what matched
python -m vinzor assist --dry-run  # the comparison, with no model involved
python -m vinzor assist          # prepare suggestions (Azure, India only)
selfhost\yente.ps1 start         # local sanctions stack (Elasticsearch + yente)
```

## Domain facts that are easy to get wrong

- **Beneficial ownership is 10%, not 25%**, and it varies by customer type
  (IFSCA clause 1.3.3). The FATF 25% figure is wrong for this regulator.
- **IFSCA enforces mostly on governance, scope and filings — not AML.** See
  `vinzor/enforcement.py`; it scores us against the real record.
- **Quarterly returns are due 21 calendar days after quarter end**; recurring
  fees by 30 April. Late returns cost USD 100/month, and payment does not cure
  the breach.
- **Sanctions screening is ~95% false positives.** The work is not finding
  matches, it is clearing them. That is what the assistant exists for, and why
  the number it is judged on is how often an officer decided *against* it.
- **The user is a compliance officer, not an engineer** — typically 30–50, from
  finance or law, personally accountable to the regulator. Their vocabulary
  (PEP, EDD, beneficial owner, clause 1.3.3) stays. Ours goes.
