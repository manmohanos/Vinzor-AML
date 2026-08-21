# SPEC-002 — Assisted investor onboarding

**Status:** building · **Written:** 22 Aug 2026

## The problem, in the officer's words

> "Somebody sends me a passport scan and a bank statement and says they want to
> invest. Now I have to work out what else I need from them, chase it, check
> the name against sanctions, check whether they are politically exposed, read
> the news for anything ugly, follow the company back to the humans behind it,
> and write it all up. Then do it again for the next one."

Today Vinzor tells an officer what is wrong with a book that already exists. It
has no answer at all to *"here is a new investor, take them on."* That is the
one thing every FME does every week, and it is where the manual hours are.

## What this is

**An onboarding that runs itself, and stops at the decision.**

A party is proposed. Vinzor works out what documents that kind of party owes,
takes what is offered, and then runs eight checks — each one a deterministic
agent over a real source — while the officer watches it happen. It ends with a
report: every finding, the evidence under it, the clause behind it, and three
buttons that only a human may press.

## What it is not

**Not a dashboard.** The existing screen answers *"what needs me?"*, which is
the right question at nine in the morning and the wrong one when somebody is
waiting to be onboarded. A dashboard is a thing you are handed. This is a thing
you start.

**Not an AI that decides.** Eight agents, and not one of them reasons. Each is
a pure function over recorded facts and a named external source: same party in,
same findings out, today and in eleven months when an inspector asks. A model
appears exactly once, at the end, writing the opening paragraph of the report
from figures it was handed — and `narrative.py`'s guard destroys that paragraph
if it invents so much as a date.

That is not caution for its own sake. A screening result that changes between
two runs is not evidence, and the whole product rests on the claim that its
records can be relied on afterwards.

## The eight agents

Each has one job, one source, and cites the clause it works to.

| Agent | What it does | Source | Clause |
| --- | --- | --- | --- |
| **Identification** | What this kind of party must produce, and what is missing | `readiness.py` | 5.4.2 |
| **Documents** | Which of the required papers are held, and what each actually evidences | `documents.py`, new `requirements.py` | 5.4.5 |
| **Sanctions** | The name against every sanctions list | local watchlist, 4,001,232 entities | 5.9, 11.2 |
| **Politically exposed** | The same result read for `role.pep` and `role.rca` | same | 5.5, 5.5(b)(iii) |
| **Adverse media** | Negative coverage, by theme rather than by sentiment | new `adversemedia.py` over GDELT | 4.2 |
| **Ownership** | Through the structure to the natural people | `graph.py` | 1.3.3 |
| **Duplicate** | Whether this party is already on the book under another spelling | `duplicates.py` | — |
| **Risk factors** | Which of the nineteen factors the records can observe | `risk.py` | 4.2 |

**The officer sees each one work.** Not a spinner: the step's own sentence, the
count it reached, and what it found, appended to the permanent record as it
finishes. That is already how `agents.py` behaves — every step is a real call
to a real tool, and *"nothing animates a progress bar over a sleep"* — and this
extends it rather than replacing it.

## The document checklist

Held internally, shown as need. An officer should not be handed a form with
thirty fields on it; they should be told the next thing that is missing.

`requirements.py` holds, per customer type, what evidences identity, address,
date of birth, tax identity, legal form, beneficial ownership and authority to
act. A party's state is then computable: **held and evidenced**, **held but
not evidenced**, **missing**. The middle one is the finding clause 5.4.5
exists for and the one a spreadsheet cannot express.

## What the report says

Assembled deterministically, in this order, because it is the order somebody
reads it in:

1. **What was checked, and against what** — including the checks that found
   nothing, because "we looked and there was nothing" is the evidence an
   inspector asks for
2. **What is still missing**, and from whom
3. **Every finding**, worst first, each with its evidence and its clause
4. **The ownership chain**, through to the people or to where it runs out
5. **What only a person may now do** — clear, refer upwards, or refuse

## Invariants this must not break

- Replay equals live. Every agent step and every finding is an event.
- No finding without a clause.
- No agent writes a decision; the read-only facade already refuses it.
- No clock inside the core.
- Every sentence a person reads lives in `briefing.py`.
- The core takes no dependency.

## Open, and stated

- **GDELT is not deterministic across time.** Yesterday's search and today's
  return different articles, because the world changed. The adapter therefore
  records the query, the window and the articles it saw, and the *finding* rests
  on that recorded snapshot rather than on a live re-query. Replay reads the
  record. This is the same shape as `SCREENING_COMPLETED`.
- **Adverse media has no IFSCA clause of its own.** It is a 4.2 risk factor,
  and the register has no extract for one. It will say so on screen rather than
  cite something that does not exist.
