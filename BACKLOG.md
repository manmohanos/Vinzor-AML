# Backlog

One ordered list. Work comes off the top. Anything not here is not being built.

Order is set by evidence where evidence exists: `vinzor/enforcement.py` scores
us against IFSCA's 25 published enforcement actions, and what the regulator
actually acts on outranks what would be fun to build.

**Status:** `spec` → `plan` → `approved` → `building` → `done`

---

## Now

| # | Item | Status | Note |
|---|---|---|---|
| 1 | **Verify the 21 clauses** | **AI cross-check done; still needs a person** | No CA/CS available, so instead: fetched IFSCA's own PDFs fresh and compared every extract, heading and page against them. 12 of 21 had a real problem — 4 wrong page numbers, several extracts that silently dropped part of the source sentence, one (`4.2`) quoting the wrong subsection entirely, one (`10.1`) whose extract wasn't in the source at all, one document version tag naming a superseded edition. All fixed. `verified` stays `False` on every clause — this confirms the *quotations*, not that a professional has confirmed the *rules are the right ones to be citing*. See `vinzor/citations.py`'s own docstring for what changed. |
| 2 | **Rotate five leaked credentials** | **done** | Rotated by the user 13 August 2026. |
| 3 | **Point `assist` at a real Azure deployment** | **steps + `.env.example` done; waiting on the user's values** | `.env.example` added, and `.env` now actually loads (nothing read it before). User has the four values to fill in. |
| 4 | **Count how often the guard fires** | not specified | When a draft invents a figure it is destroyed and nothing is written, so the hallucination rate is the one number the quality page cannot show. It says so on screen; that is honest, not sufficient. |

## Next

| # | Item | Status | Why here |
|---|---|---|---|
| 5 | Regulator-correspondence tracking | **done** | `vinzor/correspondence.py`. A letter is recorded with the date it arrived and the date it set, sits on the morning screen until answered, and opens a Case that stops everything once the date passes, citing Regulation 120. Nothing is stored as "overdue": the thing that would set that flag is exactly what nobody does when a notice is being ignored. A letter with no date is not given one. `python -m vinzor notice --list`. Still **partly** covered rather than covered, because somebody has to type the letter in and Karvy's notice was served by affixture after post and e-mail both failed. |
| 6 | Real sign-in and identity | **done** | `vinzor/credentials.py`. The visible half was the password screen; the half that mattered was that every write read the actor's name out of the request body — post `{"person": "Rohan Kapoor"}` and you were Senior Management. Verified against the running server: it answered 200 and settled the file. It now answers 401. scrypt at 2^14 with parameters stored per record, session token stored hashed, HttpOnly + SameSite=Strict cookie, lockout after five wrong tries. Credentials are deliberately **not** events: an append-only log is one you can never rotate away from. `python -m vinzor password --name "Their Name"`. |
| 7 | Audit export | **done** | `vinzor/dossier.py`: everything on one party as one printable document — the decisions in the deciders' own words, each finding with its clause, the ownership chain including where it loops or runs out, what clause 5.4.2 still wants, and a seal over the exact records cited. Reachable from any party page as **The full record**. The design decision that took the longest: there is deliberately **no redacted version**, because the danger is not that the document holds secrets but that its existence discloses that a customer was examined — which is what clause 4.1(d) forbids. A shorter export would look safe to hand over and would not be. |
| 8 | KYC document intake | **done, and deliberately not a reader** | `vinzor/documents.py`. The gap was never reading PDFs — it was that every fact on every party came from a spreadsheet column with nothing behind it. Clause 5.4.2 asks a firm to *hold* identification data; clause 5.4.5 asks it to verify identity from reliable, independent sources, and until now the two looked identical on every screen. A document is filed against a party, **a person says what it evidences**, and readiness reports held-but-unevidenced separately from missing. A kind cannot be promoted past what it can support. Expiry cascades — a lapsed passport stops supporting a nationality while the PAN card keeps supporting the name. The fingerprint of the bytes catches the same scan filed against two investors, which is free and is a real finding. Bytes go to a cabinet beside the log, never in it. `python -m vinzor document --kinds`. **Extraction is still unbuilt on purpose**: when it comes it feeds suggestions into this structure, as assisted review already does. |
| 9 | Incorporate the 3 Aug 2026 amendment | tracked, not built | Register knows it is pending. Needs the re-assessment seam: new findings dated today, never rewriting the past. |
| 10 | The rest of `REVIEW-2026-08-12.md` | **done** | All 39 confirmed findings closed, each independently re-verified by a second agent that reproduced the original bug and confirmed it gone — not just that a test passed. Two left open on purpose, not by omission: item 11 below, and `resolve_ubo`'s path explosion (see the note under item 16). |
| 11 | Register the fee clauses | blocked on a person | An unpaid-fee Case cites Regulation 120, which is about returns. `Schedule.clause` already names `fee-4` and `fee-5`; neither is in the register because the fee circular has not been transcribed from its primary source. Belongs with item 1, document in hand. |

**Capital and disclosure, the last two enforcement grounds — done.** `vinzor/capital.py` holds the minimum each licence category requires, takes the firm's reported net worth as an event, and opens a Case that stops everything when it falls short. `vinzor/disclosure.py` lets a return carry the figures it claimed and shows them beside what the book holds. Both are **partial and say why**: the capital figures came from law-firm summaries rather than the regulations, so every screen using one carries a caveat and a person can confirm the minimum that actually applies; and only a figure the records hold *nothing* for opens a file, because assets under management are properly not the sum of commitments and a rule on the ordinary difference would fire every quarter of every firm's life. `enforcement.roadmap()` is now empty — which means nothing has *nothing* built for it, a much smaller claim than finished.

---

## Later

| # | Item | Why not now |
|---|---|---|
| 12 | Agents 2–5 from SPEC-001 | Prove the first one is accepted by a real officer before building four more. |
| 13 | The full returns calendar (AML/CFT, FATCA/CRS, scheme filings) | Three obligations are modelled; the rest need the same primary-source treatment. |
| 14 | Hosted, multi-firm service | One file per workspace already; this is the serving layer. |
| 15 | Second entity type (brokers, insurers) | Same regulator, same spine. After the first FMEs say yes. |
| 16 | Bound `resolve_ubo`'s path enumeration | Deliberately left unpatched (see below). |

**Item 16, in detail — left broken on purpose, like item 11.** `graph.py`'s
`resolve_ubo` enumerates every distinct ownership path with no memoisation,
which is exponential in a densely reconvergent structure: eight tiers of
cross-held companies produced a 5.87 MiB `CASE_OPENED` payload, permanently
re-hashed on every `verify()`. Confirmed **not reachable by real data** — the
shipped dataset's worst case is 0.0001s and a 2.5 KB payload, because paths
only multiply where ownership chains fan out and reconverge, and a tree costs
nothing extra. The reviewed fix would change how effective ownership
percentages are accumulated across paths — the single most legally sensitive
number in the system — and the adversarial review's own performance
investigation said as much: *"this wants a spec ... not a drive-by patch."*
Fixing it under a workflow deadline risks silently changing a percentage
nobody would notice was wrong until an audit. Belongs with a spec that states,
before any code changes, which existing beneficial-ownership numbers must stay
byte-identical.

---

## Done

Kept short deliberately — the detail is in `DESIGN.md` and the tests.

- The trust spine: hash-chained log, findings recorded as facts, pure-fold
  replay, the human gate enforced on write and on read
- Beneficial ownership to IFSCA's real test (10%, per customer type)
- Licence scope and required offices (Regulations 3(4), 7, 10, 137)
- The obligation calendar (quarterly return, recurring fees, late charges)
- Live sanctions screening, self-hosted (OpenSanctions/yente + Elasticsearch)
- The officer's screen, in plain language, jargon-swept by test
- **SPEC-001, all nine steps: assisted review.** The deterministic comparison,
  the drafting boundary with its hallucination guard, the Azure adapter with
  India-only residency enforced twice, the budget cap summed from the log, the
  suggestion panel, and the quality page that counts how often an officer
  decided against it
- **One project, not three.** `vinzor-foundation/prototype` (11,249 lines) and
  `vinzor-web` (1,393 lines plus 27,393 installed files) moved to `archive/`;
  the synthetic dataset moved into `vinzor-core/data/`, so the live system is
  self-contained and there is exactly one folder to open
- **Adversarial review, and every finding it survived.** Six reviewers read the
  layers, six skeptics reproduced or refuted every claim in a shell: 39
  confirmed, 13 refuted, all in `REVIEW-2026-08-12.md`. All 39 are now fixed
  and independently re-verified — a second, unrelated pass of agents that
  reproduced each original bug from scratch and confirmed it gone, catching
  one fix that was subtly wrong on its first attempt (a grammar branch
  pluralising on the wrong count) before it landed. Closed: the breach
  double-reported to concurrent readers, the watchlist entry whose second
  passport was ignored, the invented passport number the guard could not see,
  the fee that told an officer to file a return, the filled post that still
  read as empty, the decision any website could make on the officer's behalf,
  the co-trustees that vanished from a trust, a closed Case silently absorbing
  a recurring breach, citation order that depended on `PYTHONHASHSEED`, a
  malformed watchlist reply escaping as a raw traceback, a credential visible
  in a `repr()`, an unbounded/undeadlined screening read, a server thread a
  silent client could pin forever, an AUM grace period anchored to the wrong
  date, an annual fee's period ending before it began, and group text on the
  officer's screen that named a party absent from most of the group
- **The code is under version control**, which it was not until 12 August 2026,
  and the suite now runs itself on every change
- **Every clause cross-checked against IFSCA's own published text.** 12 of 21
  had a real problem — 4 clauses on the wrong page, extracts that silently
  dropped part of the source sentence, one citing the wrong subsection of the
  regulation entirely, one whose extract did not exist in the source at all.
  All fixed; none marked `verified` — this is textual accuracy, not the CA/CS
  sign-off the product still needs and does not have
- 372 tests, ~25s, zero dependencies in the core
