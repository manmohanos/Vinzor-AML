# SPEC-001 — Assisted review

**Status:** awaiting approval · **Owner:** founder · **Written:** 12 Aug 2026

## The problem, in the officer's words

> "I open a file that says a payment came from a possibly sanctioned party. Now
> I have to pull up the watchlist entry, compare the date of birth, the
> nationality, the passport number and the address against what the investor
> gave us, decide whether it is the same person, and then write a paragraph
> explaining why. That paragraph is what protects me if the regulator asks.
> Every one of these takes me twenty minutes and nineteen of them are the same
> twenty minutes."

Industry research puts false positives in sanctions screening above 95%. The
officer's day is not judgement — it is assembling the same comparison over and
over so that the rare real match is caught and the common false one is
defensibly cleared.

**Today Vinzor tells them what to look at. It does not help them look.**

## What we are building

An **assisted review** layer: before the officer opens a file, a draft is
already waiting — the comparison assembled, the reasoning written out, the
recommendation stated, and the sources shown. The officer reads, corrects,
and signs. The draft is never the decision.

This is the "AI prepares, humans approve" seam the architecture was shaped
around, finally filled.

## Who it is for

A Principal or AML Officer at a GIFT City FME. Typically 30–50, from finance
or law, personally accountable to IFSCA. They have never seen JSON and never
will. They do not know or care which model wrote the draft.

## What the officer experiences

**1. A draft is already there.** Opening a file, below the evidence, a panel:

> **Suggested for your review** — prepared 08:14 today
>
> This is probably **not** the same person.
>
> The listed party is *Vladimir Petrov*, born 3 March 1961, a Russian national
> on the UK and EU sanctions lists. Your investor is *Vladimir Petrov*, born
> 19 August 1984, an Indian national resident in Singapore. The names match
> exactly but the dates of birth differ by 23 years and the nationalities do
> not match.
>
> **Before clearing this, check:** that the passport number on file
> (K4471829) is not an alias recorded against the listed party.
>
> *A draft, not a decision. Read the evidence above and decide yourself.*
>
> [ Use this wording ]  [ Write my own ]

**2. "Use this wording"** copies the draft into the reason box, where the
officer edits it freely. Nothing is submitted until they press Record.

**3. The record shows both.** The permanent file keeps the draft *and* the
officer's final wording, so an inspector can see exactly what was suggested
and what the human actually concluded.

**4. Nothing changes if the model is unavailable.** The panel says so in one
sentence and the officer works as they do today. No spinner, no blocked queue.

## The agents, in order

Each is the same shape — read the Case, draft something, never decide.

| # | Agent | Drafts | Slice |
|---|---|---|---|
| 1 | **Match investigator** | The comparison and clear/escalate recommendation for a screening hit | **First — this spec** |
| 2 | **Ownership explainer** | What is missing from an ownership chain and the exact document to request | Next |
| 3 | **Payment investigator** | Whether a payment fits the investor's history, and what to ask | Next |
| 4 | **Report writer** | The narrative for a regulatory filing or an audit pack, from the case history | After |
| 5 | **Day narrator** | Two sentences on what today's list actually means | After |

## How we know it works

Not "the output looks good." Every draft the officer touches produces a signal
we already record, because decisions are events:

- **Accepted** — used the wording unchanged
- **Edited** — used it and changed the words
- **Rejected** — wrote their own instead
- **Contradicted** — decided the opposite of the recommendation

That last one is the number that matters. **A draft that recommends "clear"
on a file the officer escalates is the failure mode that could cost a
licence.** It is measured from day one, shown on a quality page, and it is the
metric we would put in front of a design partner.

## Acceptance criteria

1. A screening-hit file shows a draft comparison, recommendation and
   suggested wording, in plain English, with no technical vocabulary.
2. The draft cites the clause the file already cites — it invents no obligation
   of its own.
3. "Use this wording" fills the reason box and remains fully editable.
4. Recording a decision stores the draft, the final wording, and whether the
   officer accepted, edited, rejected or contradicted it.
5. Every draft records which model produced it, the prompt version, and its
   cost — visible on the file, not hidden in a log.
6. The model can never close a file. Attempting it fails on write and on
   replay, as today.
7. If the model is unreachable, slow or returns nonsense, the officer sees one
   plain sentence and the rest of the product is unaffected.
8. No personal identifiers leave the machine unredacted without an explicit,
   recorded decision to allow it.
9. A quality page shows accepted / edited / rejected / contradicted rates and
   spend to date.
10. Cost is capped. When the cap is reached, drafting stops and says so; the
    product keeps working.

## Out of scope

- The model deciding anything, ever.
- A chatbot. There is no free-text box for the officer to converse with.
- Document extraction from KYC packs (separate spec — needs Docling).
- Fine-tuning or training on customer data.
- Replacing any deterministic rule with a model. Rules stay rules.

## Open questions for the founder

1. **Azure resource** — which region, which deployment name, and which model
   is deployed? (I could not verify Azure's current API surface; I will read
   the live deployment rather than guess.)
2. **Data residency** — is the Azure OpenAI resource in India, and does that
   matter to a GIFT City customer? My assumption: it will matter, and we
   should be able to say "your data stays in India."
3. **Spend cap** — I suggest USD 50 of the $600 for this slice. The workload
   is a few cents per draft, so the real risk is credits expiring unused, not
   overspend.
4. **Redaction default** — start with names and identifiers redacted before
   they reach the model (safest, slightly worse drafts), or send in the clear
   on the argument that it is our own Azure tenancy? My recommendation:
   redact by default, with an explicit switch.
