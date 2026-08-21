# What this is actually for

Written for somebody who has not read the code, and does not want to.

---

## The problem, in one paragraph

A fund manager in GIFT City takes on an investor. Before they can accept the
money, somebody has to work out what documents that kind of investor owes,
chase them, check the name against sanctions lists, work out whether the
person holds public office, read the news for anything ugly, follow a company
back through its owners to the actual human beings behind it, decide whether
any of that is a problem, and write it all down in a way that can be defended
to a regulator eleven months later.

That is a day's work, most of it clerical, and it happens every week.

**Vinzor does the clerical part and stops at the judgement.**

---

## The one sentence

> An investor goes in. A defensible, permanent, citable record comes out — and
> a named human being made every decision in it.

---

## Why this is not "an AI compliance tool"

Almost every product in this space puts a model in the middle and asks it to
be clever. That is the wrong shape for this problem, for a reason that has
nothing to do with taste:

**A compliance record has to mean the same thing tomorrow as it meant today.**

If a model reads an article and decides it is adverse, that judgement cannot
be reproduced. Run it again next week and it may say something else. An
inspector asking *why did you accept this investor* gets an answer that
changes while they are looking at it. That is not evidence, and a firm that
built its file on it has nothing to show.

So the division here is strict, and it is the whole architecture:

| Deterministic code does | A model does |
| --- | --- |
| Establish facts | Judge what a fact **means** |
| Compare records | Write prose a person could sign |
| Follow ownership | Summarise |
| Decide what a clause requires | Suggest wording |
| **Nothing else** | **Never decide anything** |

The eight checks that run during an onboarding contain no model at all. Each
is a pure function over recorded facts and one named external source. Same
investor in, same findings out, today and in a year. There is a test that runs
the same party twice and compares every sentence.

A model appears exactly once — writing the opening paragraph of the report
from figures it was handed — and a guard destroys that paragraph if it invents
so much as a date.

---

## What actually happens when you onboard somebody

You type a name and pick what kind of party they are. That is the whole form.

Then eight checks run, and **you watch them run** — not a spinner, but each
step's own sentence, and what it found, appearing as it lands:

```
[found]  5 identification detail(s) missing for Nirav Modi
             an identifying number — clause 5.4.2(a)(ii)
             a date of birth — clause 5.4.2(a)(iii)
[found]  4 document(s) still needed
             a photo identity document — it is the only thing that evidences
             who this person is, rather than what they told us
[found]  CRIMINAL match for Nirav Modi
[done ]  nothing records Nirav Modi as politically exposed
[done ]  a person is their own beneficial owner
[done ]  nothing else on the book looks like Nirav Modi
```

That is a real run against four million watchlist entities, and every line of
it landed on a permanent, tamper-evident log as it happened.

Then you get a report: what was checked and against what, what is still
missing and from whom, every finding with the clause behind it, the ownership
chain through to the people — and three buttons that only you can press, with
a box you have to type a reason into.

---

## The three ideas everything else follows from

### 1. The record is the product

Nothing is edited, ever. Every fact is appended in sequence and sealed against
the one before it. Change one character of something from last March and every
seal after it stops matching, visibly, on demand.

That means *"this is what your firm knew, and when it knew it"* is **provable**
rather than claimed. The AI makes it fast; the ledger is why anyone would
trust it.

### 2. A check that did not happen is not a check that found nothing

This sounds obvious and it is the single most dangerous bug class in the whole
product. Three separate versions of it were found and closed while building
this:

- The watchlist was still loading, so it answered "no match" — which would
  have written *"we checked and found nothing"* against every investor on the
  book, permanently, into a log with no undo.
- The news service rate-limited us and answered in plain text. Read
  carelessly, that is an empty article list, which is to say *"we searched the
  world's news and there was nothing about this person"*.
- A guard written to catch the first one had a fallback that defeated it.

All three now refuse rather than reassure. **An honest "nobody has looked at
this yet" is worth more than a comfortable lie**, because the first one gets
acted on and the second one gets believed.

### 3. Nothing reaches a file without a clause behind it

Every finding cites the regulation it rests on, in the regulator's own words.
A rule cannot get into a case file on an engineer's sense of good practice.

And where there is no clause, the product says so. Adverse media is a good
example: **no IFSCA clause requires an adverse media check.** There isn't one.
So the finding cites clause 4.2 — the risk factors a firm shall take into
account — and calls itself a risk factor rather than a breach. Citing
something adjacent would be a fabricated legal reference in a compliance file,
which is worse than having none.

---

## The thing we got right that most people get wrong

**The beneficial ownership threshold in IFSCA is 10%, not 25%.**

FATF says 25%. Every global vendor assumes 25%. IFSCA cut it to ten by
circular in May 2023 — and it is not one threshold but four different tests,
with two different boundary conditions:

| Customer type | Test |
| --- | --- |
| Company, fund, partnership | **more than** 10% |
| Unincorporated body | **more than** 15% |
| Trust | **10% or more** — plus the author and trustee at any percentage |

"More than" and "or more" are different tests. Somebody holding exactly 10% of
a trust is a beneficial owner; the same person holding exactly 10% of a
company is not. One character of code apart, opposite answers.

Anything built to 25% under-reports beneficial owners against this regulator.

---

## What is honestly not here

This matters as much as the list of what is, and it is stated on screen rather
than buried:

- **No qualified person has verified the clause register.** Thirty clauses,
  every one marked unverified, on screen, on every file. They were checked
  word by word against the regulator's own PDFs — twelve of the first
  twenty-one had a real error — but that confirms the *quotations*, not that a
  CA or CS agrees these are the right rules to be citing.
- **Seven things in the document checklist could not be sourced** and are
  listed rather than guessed at.
- **Eleven of the nineteen clause 4.2 risk factors need a person.** They
  cannot be read from any record and are not pretended to be.
- **The best available AI model cannot be used**, because in India every
  Anthropic model on AWS is only reachable through a routing profile that
  sends data outside the country. The product uses a weaker one and says so.
- **No real regulator has looked at any of this.**

---

## Where it runs

Live on AWS in Mumbai, at **https://dikytp5q85njb.cloudfront.net**.

Every push to `main` lands there within about three minutes, and only if the
test suite passes first — 1,591 tests, no network, no database.

The watchlist is four million entities on the same machine, so no investor
name ever leaves the building. That was a deliberate choice over a hosted API
that would have been simpler and cheaper: sending a client book to a third
party is a cross-border transfer of customer identity data, and the whole
architecture refuses it.

---

## The honest summary

The engine is real, measured, and can be defended line by line. The regulatory
model is deeper than any general-purpose vendor's for this jurisdiction. The
containment — an AI that structurally *cannot* decide anything — is real
rather than a policy someone might change.

What it does not have is a customer, a price, a data licence for commercial
use of the watchlist, and a qualified person's signature on the clause
register. Those are the four things standing between this and a product
somebody pays for, and none of them is an engineering problem.
