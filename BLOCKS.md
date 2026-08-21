# The blocks

Seventeen separable pieces. Each one has a job, a measured position, and a
named next step, so any of them can be picked up on its own without reading
the other sixteen.

Two things this map is careful about. **Line counts are size, not value** —
the interface is a third of the codebase and the Ledger is the reason any of
it can be trusted. And **"done" appears nowhere**: every block below says
what it cannot do, because that is the sentence that decides what to build
next.

At the time of writing: **27,522 lines of product, 20,809 of tests, 1,538
tests passing.** Four more talk to the deployed model and are run on
purpose with `pytest -m live`. Zero third-party dependencies in the core.

---

## The spine — everything else rests on these

### 1. The Ledger
`eventlog.py` · `model.py` · `engine.py` — 1,813 lines, 978 of tests

The hash-chained append-only log, the event vocabulary, and the single fold
that interprets it. One SQLite file per workspace, immutability enforced by
database trigger rather than by convention. Every screen, every report and
every agent step is a projection of this and nothing else.

**Why it matters more than it looks:** it is the reason a decision made in
March still reads as it did in March after the rules change in June, the
reason an agent's progress bar is evidence rather than animation, and the
reason "show me the audit trail" and "replay the system" are the same
operation.

**Audited 20 August 2026 by attacking every claim it makes.** Two attacks
succeeded and both are now fixed.

*A hash chain cannot see its own tail.* Four events erased from the end and
`verify()` returned **True** — every remaining link still checked, because
each one points backwards. For a record whose entire promise is completeness
that was the worst possible answer. Witness marks now record how long the log
has been and what its head was, so a shorter log is provably missing its
tail; the fingerprint also travels out on printed reports, where nobody
holding the database can reach it.

*Python writes NaN and Infinity into JSON, and they are not JSON.* One
division that went wrong upstream would have put a payload on the permanent
record that no strict parser could read, under a hash covering bytes no other
implementation would agree with. Now refused at the door.

Everything else held under attack: triggers block UPDATE and DELETE, a
middle cut is caught by the sequence check, 150 concurrent writes produced
150 distinct sequence numbers, replay equals live byte-for-byte including
tuples and unicode, and a failing batch leaves nothing behind.

**What it cannot do:** one writer, one machine. Multi-tenant serving is a
layer that does not exist. Nothing inside a file defends against somebody
who holds the file — what changed is that the log can now *tell you*
afterwards.

**Next:** nothing urgent. 20,000 events verify in 0.74s.

### 2. The Rulebook
`citations.py` · `enforcement.py` · `licence.py` · `calendar.py` · `pdftext.py` — 2,398 lines, 1,678 of tests

IFSCA's own text: 21 clauses transcribed from the published PDFs, 25
enforcement actions scored by ground, licence categories and permitted
activities under Regulation 3(4), and the obligation calendar derived from
the circulars.

**Audited 20 August 2026 by making the check a test.** The 21 clauses had
been read against IFSCA's PDFs once, by hand, and **12 had a real problem**
— wrong pages, extracts missing half a sentence, one quoting the wrong
subsection entirely. All were fixed, and then nothing stopped them drifting
again: an extract is a string in a Python file, and a string in a Python
file can be changed by anybody who thinks they are tidying a quotation.

So the check now runs on every build. `pdftext.py` reads the regulator's
PDF with nothing installed, and each extract must appear in it, word for
word, on the page the register names.

*Running it found three more the hand check had passed.* A semicolon
printed as a full stop, which turns half a clause into what reads as a
whole sentence; a space inserted into a Home Affairs file number; a
semicolon inserted into the list of things an employee may know or suspect.
None changes what the rule requires; all three meant the file was quoting
something the document does not say while telling a compliance officer it
was verbatim. **12 of 12 now match exactly.**

*The reader had to be built twice.* IFSCA sets its body text in subset
Aptos encoded Identity-H, so every letter is a two-byte glyph number that
means nothing without the font's own translation table. The first version
read only the plain strings and returned page 5 as `1.3.2 1.3.3 (a) (i) 4`
— the numbering, and not one word of the beneficial-ownership definition
under it. That is worse than a page that fails outright, because it looks
like a page that read cleanly: a clause check run against it would have
reported the correct wording as missing from the document that states it.
Now 73 pages, 29,405 words, **nothing left untranslated**, and a page that
cannot be read says so rather than coming back empty.

The check also pins the PDF by digest. IFSCA republishes its consolidated
master at the same address every time a circular lands and the pages move —
that is what moved all four beneficial-ownership clauses from page 4 to
page 5 with nothing to announce it. A replaced file now fails a test
instead of silently invalidating every page number.

*Then the second document arrived and found two more.* For a week the 9
Fund Management Regulations clauses were checked by nothing, because no
copy of that document was kept — the rules on who a fund manager must
appoint, what it must tell the Authority, and which activities each licence
permits. With the Regulations in `docs/`, 7 of the 9 matched at once. Of
the two that did not, one was the licence categories: the register quoted
them as `Authorised FME; Registered FME (Non-Retail); Registered FME
(Retail)`, a semicolon list that appears nowhere in the Regulations, which
set them out as a lettered list running across a page break. The other
needed the reader taught that a hyphen at a line end is ambiguous —
*compli-* over *ance* is one word, *sub-* over *regulation* is two — so
every reading is tried rather than a favourite picked.

*And one claim that was the wrong way round.* The file recorded that most
Fund Management headings were its own descriptions rather than IFSCA's
words. Checking every heading found the opposite: all of them are printed
in the document. `EDITORIAL_HEADINGS` now names the six that really are
this register's own, and a test holds both directions.

**All 27 clauses now match, in 2.5 seconds, on every build.** No document
in the register is without a copy, and `uncheckable()` is empty by test
rather than by hope.

**The capital figures are no longer a guess.** They were read out of two
law-firm summaries, disclaimed on every screen that used one, because on
this regulator secondary sources had been measured and found wanting. The
Second Schedule on page 89 sets them: USD 75,000, USD 500,000, USD
1,000,000, with Regulation 107F adding USD 500,000 for third-party fund
management. The law firms were right to the dollar. What changed is that a
firm told it is short of capital is now shown the schedule that says so —
the capital finding used to cite 3(4), the clause about *which category to
register under*, and nothing that set an amount.

**What it cannot do:** the figure is a floor, not a total. Regulation 8(3)
makes it separate from and in addition to the minimum for any other
activity a firm carries on inside or outside the IFSC, and this system
knows nothing about those; 8(2) lets a branch hold its net worth at its
parent. Nothing here reads a KMP's qualifications or counts their years
either — only whether an office is filled and its holder recorded as based
in the IFSC. The circular history behind the obligation calendar is still
unchecked against a primary source; only the two Regulations texts are.

**Next:** an hour of a CA or CS — still the cheapest unblocking on the
board, and still not a coding task. What changed is that the hour is now
spent on whether the right clause was chosen, not on hunting for stray
semicolons.

---

## Knowing who somebody is

### 3. Screening
`screening.py` · `compare.py` · `romanise.py` · `countries.py` — 1,612 lines, 1,525 of tests
plus the self-hosted stack in `selfhost/`

**3,989,103** sanctioned, politically exposed, wanted and debarred entities,
indexed locally as at the 19 August 2026 rebuild. No name typed here leaves
the machine.

**The measured position:** against 455,219 analyst-judged pairs from the
OpenSanctions benchmark, our name matching scores **90.7% F1** — against
91.33% published for a full-attribute matcher reading up to 132 fields.
Separately measured and counter-intuitive: **every field used as a veto made
matching worse**, while a *matching* identity document alone scored 97.1%
precision. So documents corroborate and never dismiss.

**Audited 20 August 2026 by attacking all three of its claims.**

*The residency guard held.* "No name leaves the machine" was attacked with
the addresses that fool a naive parser: `http://127.0.0.1@evil.example/`,
where the local address is userinfo and the real host is somebody else;
lookalikes like `127.0.0.1.evil.example`; the integer and hex spellings of
127.0.0.1 that a substring check misses. Every one is reported as leaving.
The cases are now tests.

*A setting that was not an address escaped the contract.* This block
promises a caller either results or a refusal in plain words. An empty
service address broke that with a raw `ValueError` out of urllib — and
where it surfaced was the background screening run after an import, which
left a progress bar counting toward a total it would never reach and no
message saying why. Addresses are checked before anything is sent, and the
message names the right remedy: an address typed without `http://` is a
setting to correct, not a service to restart.

*A party nobody had screened read exactly like a party screened and found
clean.* Both produced "No watchlist check on this party has found
anything" — on the screen where an officer decides how risky somebody is.
It is true of a party nobody looked for, in the way that says nothing, and
it reads as reassurance. Three states now read differently: nobody looked,
a check on this date found nothing, and a match. The same fix makes a
**delisting** visible for the first time — a party who matched in March and
is on no list in August used to read as still listed, forever.

**Aliases are screened now (20 August 2026).** This block reported that
nothing held *our own* parties' other names, so only the name on the record
was ever asked about. Intake collects them, and every recorded name goes to
the watchlist in the **same request** — the protocol takes several queries
at once, so a book of fifty thousand does not pay a round trip per alias.
Proven against the live index: a party recorded as "Ravi Shah" carrying one
sanctioned alias returns the match at 1.00 where before it returned
nothing. Capped at 8 names, stated, and the extra names go on the record so
an officer meeting more matches than expected can see they were the firm's
own.

**What it cannot do:** commercial use needs an OpenSanctions licence, and
self-hosting does not avoid it. Adverse media is not a real feed. And
nothing judges whether a check is recent enough: clause 5.9 requires
screening to be ongoing without saying how often, so the date is reported
and the interval is the firm's policy to set.

**Next:** the licence quote. It gates selling at all.

### 4. Entity resolution
`duplicates.py` — 451 lines, 631 of tests
plus the measurement in `tools/duplicate_shapes.py`

The same party entered twice, which quietly defeats every rule that counts.

**Audited 20 August 2026, and it had stated a speed where every other block
states an accuracy.** "61× faster", "flat at ~7ms a party" — fast at what
was never asked. So sixteen ways a real book ends up holding one party
twice were planted, with seven pairs who genuinely are different people as
a control, because a detector that raises everything scores perfect recall
and teaches an officer to stop reading.

**It saw 12 of 16.** The four it missed all failed for one reason:
blocking brought two records together only if *two* parts of their names
agreed, so a name with two usable parts and one part changed shared nothing
and was never compared at all. That is a marriage where the surname was
replaced, a name recorded with an initial, a name transliterated another
way, and a short name that gained a part — including the marriage this
module's own opening paragraph is about. Single parts are indexed now, but
only while a part is rare enough to mean something (`COMMON_PART = 25`),
which is what keeps it affordable.

**The flat cost was not flat.** The index was rebuilt on every registration
— safe for a reader mid-iteration, and it copies the whole index. On a book
of *distinct* names, which is what a real client book is, per-party cost
doubled every time the book doubled: **0.28ms at a thousand parties,
1.09ms at eight thousand**. The original measurement had used a small pool
of repeated names, where the key set stops growing and the cost genuinely
does flatten. Nothing iterates these dictionaries, so they are updated in
place, and the same measurement is now **0.39ms and 0.27ms** — flat, and
about twice as fast overall. The same rebuild pattern is in `payments.py`
and has not been touched.

**Widening the blocking exposed a wrong sentence.** A brother and sister —
same surname, same family email, same landline — met for the first time,
counted three agreeing facts and were raised as possibly one person, under
the words "one name contained in the other", which was true of neither
name. Counting had treated a shared telephone and a birthday as
interchangeable. A household shares an address; a person has a birthday. A
half-matched name now needs something personal agreeing with it.

**16 of 16 duplicate shapes found, 0 of 7 namesake pairs raised.**

**What it cannot do:** two records sharing only a very common surname, with
no identifier between them — "R. Kumar" and "Rajesh Kumar" on a book of
four hundred Kumars — are not findable from the name, here or anywhere. A
permanent account number finds them; nothing else will. And a second
identity sharing nothing at all — different name, tax number, birthday —
is invisible here and in every product, without evidence from outside the
book.

**Next:** merge workflow. It reports pairs and deliberately refuses to merge
them; somebody still has to decide, and there is no screen for recording
that decision.

### 5. Ownership
`graph.py` — 476 lines, 505 of tests
plus the frozen spec in `tools/ownership_spec.py`

Beneficial ownership resolved to real people at IFSCA's own thresholds —
10% for a company, 15% unincorporated, the trust rule including author and
trustee.

**What it does that most don't:** reports where the chain *loops*, where it
*runs out* before reaching a person, and who sits *just below* the
threshold — which is the most useful line on the page for anyone judging
whether a structure was arranged to sit under it.

**Audited 20 August 2026.** This block carried a known defect and a reason
for leaving it alone: the walk is exponential on a densely reconvergent
structure, *"confirmed not reachable by real data"*, and the fix would
change the most legally sensitive number in the system. The caution was
right. The confirmation was wrong.

*It is reachable, and not by anything exotic.* Enter a group of companies
by listing each as owned by the others — what a spreadsheet produces when
somebody fills in a group structure the obvious way. Eight companies took
**29 seconds**; ten took eight; eleven took **106 seconds**. And beneficial
ownership is resolved when money is promised, not when a screen is opened,
so an import carrying that mistake would not have been a slow page. It
would have stopped the write.

*Almost none of that was the exponential walk.* The eight-company case
visits 13,701 edges; a lattice visiting 147,622 finishes in a quarter of a
second. The time went on `if cycle not in cycles` — a scan of a list that
grew to 27,391 entries, once per cycle found. Asking a set instead took
that case from **29.46s to 0.05s** and moved the wall from eight companies
to about ten.

*The rest is genuinely exponential and now has a stated budget.* Past
`MOST_EDGES` (100,000) the walk stops and the result says so: the
conclusion is INCOMPLETE, holdings read as "at least what is shown", and
nothing reads as a clean answer — a truncated walk reporting "no
beneficial owner" would be the worst outcome available here. The subject's
own owners are exempt from the budget, because a person holding 40% of the
company directly is both the most important line on the page and the one
found while writing the test that caught it being missed. Every shape that
used to hang now answers in **under 0.15 seconds**.

*And no percentage moved.* `tools/ownership_spec.py` freezes every number,
every route and the order of every route across 18 structures, percentages
held as `repr` so a change in the last bit shows. The frozen file was taken
from the resolver *as it was before any of this*: **all 18 identical**, and
all 94 non-person parties in the real workspace identical too.

**What it cannot do:** a structure past the budget is reported as
unfinished, not resolved — and that is a real limit, not a formality. The
margin is wide: the worst walk across a real workspace visited **four**
edges. The control limb of 1.3.3(a)(ii) is still not evaluated at all,
because no directorship or voting-agreement data reaches this system, and
every result says so.

**Next:** nothing urgent here. The control limb needs data the product does
not yet collect, which is an intake question rather than a graph one.

### 8. Documents
`documents.py` — 388 lines, 589 of tests

Which document evidences which fact. Deliberately **not** an OCR pipeline:
the gap was never reading PDFs, it was that every fact came from a
spreadsheet column with nothing behind it. Clause 5.4.2 asks a firm to
*hold* data; 5.4.5 asks it to *verify* from reliable independent sources.

**What falls out for free:** the fingerprint catches the same scan filed
against two investors. Expiry cascades — a lapsed passport stops supporting
a nationality while the tax card keeps supporting the name. Both were
attacked on 20 August 2026 and both held exactly as described.

**Audited 20 August 2026. Its central promise had a door through it.** The
module's own rule is that a document *"may be said to support less than it
could, never more"*, enforced by an allowlist per document kind — except
the check read `if overreach and kind != "other"`. An unclassified file
could be filed as evidence of a name, a date of birth, a nationality and a
permanent account number at once. On a party holding the seven items 5.4.2
asks of a person, one such file left **five of the seven reading as backed
by a document**. It was also the easiest path in the product: "Other
document" is what somebody picks when they cannot find their document in
the list.

*The allowlist was a door and not a rule.* Removing the exemption fixes the
write path, and the log is append-only — so a claim recorded before the
fix would have been honoured for ever. The allowlist is now applied where
the record is **read** as well. The claim itself is kept, unhonoured rather
than erased, because a claim somebody made is a thing an inspector may want
to see.

*And the expiry cascade could be switched off by a keystroke.* The door
accepts `2026-1-1` — how a person writes 1 January — and expiry was a text
comparison, in which `"2026-1-1" > "2026-08-20"`. A passport seven months
out of date read as current and went on evidencing a nationality. Dates are
compared as dates now, in the reading, so records already carrying that
form are read correctly too.

**A correction worth recording.** The first reading of this called the
party "ready, every fact verified". That was wrong: `ready` answers clause
5.4.2 — whether the firm *holds* the data — and has nothing to do with
documents, while `evidenced` answers 5.4.5. The two are correctly separated
in the code and were conflated in the audit, not in the product. The defect
is real and smaller than first stated: five facts wrongly shown as backed,
not a party wrongly cleared.

**What it cannot do:** still not a reader. And a document kind this list
does not name can be filed but evidences nothing — by design, because the
alternative is letting an unrecognised file evidence anything, which is
what was just removed. Adding a kind is a deliberate act.

**Next:** extraction, feeding *suggestions* into this structure rather than
writing facts. This is where Docling or Azure Document Intelligence belongs.

---

## Watching the money

### 6. Transaction monitoring
`payments.py` — 147 lines, 260 of tests
plus the measurement in `tools/ordinary_traffic.py`

**Cut to one derived rule on 21 August 2026.** This block was ten payment
rules and 580 lines. What is left is: the money came from someone other than
the investor (clauses 10.2 and 5.4.5), quiet where the book already declares
that the payer and the investor belong together. Beside it stands the one
payment finding that is not derived at all — a payer named on a sanctions
list, which needs a screening record a policy cannot see and says so.

**Why.** Against 20,000 analyst-judged alerts (`tools/against_synthaml.py`,
kept as the record), **every amount-and-timing rule scored a lift of exactly
1.00** — no discriminating power at all. That is the published result for the
category, not a defect we introduced. The plain three-payments-in-two-days
shape fired on 95% of those alerts.

**What went, stated so that nothing here later reads as present.** A payment
split below a reporting threshold. A payment larger than the call. A payment
in an unexpected currency. A payment with no sender recorded at all — 29 of
them in the demo dataset, and the case the importer's blank-remitter path was
built to produce. One account funding several unrelated investors. One
investor funded from several accounts. Money that left an investor and came
back through other hands. Money passed along a chain. With them went the
`Counterparties` projection (which is where the multi-hop tracing lived —
never in `graph.py`), the recent-payments window, the habit index and every
threshold the firm used to declare.

**What was given up, measured rather than argued.**

| | before | after |
| --- | --- | --- |
| named laundering typologies recognised (`typologies.py`) | 7 of 7 | **0 of 7** |
| evasion lab | 10 trials, 4 rules, 6 worked | 1 trial, 1 rule, **it works** |
| open files on the seeded demo book | 206 | **56** |
| of those, payment files | 158 | **8**, all sanctioned payers |
| false positives per 100 ordinary payments | 24.4 | 11.5 |

Read the last row carefully. **11.5 is not a calibration win.** The surviving
rule opened 9 files on that 78-payment book before the cut and opens the same
9 now. The other 10 went because the rules that opened them were deleted.
Same book, fewer rules, smaller number. The earlier fall — 57.7 to 24.4 — was
earned, by teaching two rules to ask the ownership graph whether the book
already declared the parties related, so that a feeder subscribing for its
own investors stopped opening a file. That fix is the only reason the one
remaining rule is usable at all.

Two more things the table does not say. The rule kept is the one
`typologies.py` uses as its **control**, on the stated ground that it fires
on every payment where the sender is not the investor; counting it as
detection is the error this product exists to prevent. And on the seeded demo
book that rule fires **zero** times, because `seed.py` makes the payment's
subject the payer, so payer and subject are never different. The P0 rule this
block is now built around is invisible on the demonstration data.

**The one door out is still measured, not hidden.** Declaring an ownership
link between the sender and the investor silences the rule: three
third-party files become none, for the price of three declarations and no
extra accounts or payments. It used to buy the evader a worse question — the
natural people behind the sender, under 1.3.3 — with three further payment
rules underneath that a declaration did not reach. Those three are gone, so
the ownership question is all that stands behind the door. It is the single
row in `adversarial.py`, and it reads EVADED.

**Folding a payment was quadratic, found 20 August 2026**, and that finding
outlived the code it was made on. Both payment projections rebuilt their
whole index on every payment, each with a comment saying why: readers hold a
reference while another thread folds. The reasoning is sound, and it is why
`state.actors` in `engine.py` is still rebuilt — several modules walk that one
with `.items()` on request threads. It did not apply to the payment indexes:
every reader of them asked for one key. Rebuilding cost the size of the book
per payment and so the book's square overall — 214 µs per payment at a
thousand, 2,395 µs at sixteen thousand, against a flat ~290 µs in place.

Those projections were deleted with the rules that read them, and the timing
table went with `tools/payments_at_scale.py`, which existed only to measure
them. The line it settled still holds elsewhere and is the part worth
keeping: three indexes are still rebuilt on every event — the actors in
`engine.py`, the agent tasks in `agents.py`, the regulator notices in
`correspondence.py` — because every one of them is walked with `.values()` or
`.items()` on a request thread, and a resize under a reader is a crash rather
than a slow morning. They are also all small by nature.

**Nobody had measured how loud it is**, and the tool that does still exists.
`tools/ordinary_traffic.py` builds a book with nothing wrong in it: calls met
from the investor's own account, a feeder paying the investors who hold units
in it, a nominee paying for its clients, foreign currency subscriptions, a
running account settling both ways, a drawdown met in instalments, a payment
held on account, an ordinary chain of service payments. Three of those eight
now control nothing — the foreign currency, the instalments and the
overpayment were each innocent against a rule that no longer exists. They are
kept because they are 17 of the 78 payments the rate is measured over, and a
rate over a hand-picked numerator is not a rate.

**All 9 remaining false positives are one shape.** Eight are the running
account and one is the chain of service payments: two firms that settle both
ways are third parties to each other on every leg, and the book declares no
ownership between them. That is the whole cost of this product on an innocent
book, and it is now a single question — should two parties with a running
account be declared related, or should the rule ask something more.

**Next:** decide whether one derived rule is a transaction-monitoring block
at all, or whether what is really here is a third-party-payment check that
should be described as one. If it is to be a block again, the thing to
restore is a counterparty rule — that is what took the typology tool from 5
of 7 to 7 of 7, and its absence is why the tool now reports 0 and cannot
report worse.

---

## Judging and recording

### 7. Risk and readiness
`risk.py` · `readiness.py` — 874 lines, 1,008 of tests

Clause 4.2's 19 risk factors — 8 observable from our own records, 11 that
only a person can answer, and the screen says which. Clause 5.11's review
calendar. Clause 5.4.2 completeness across the book.

**The design that matters:** the category is never computed. A person sets
it and signs it, because 4.2 itself says the factors "may not always
indicate a high risk" — which is on page 17, checked.

**Audited 20 August 2026.** This block said *"Next: nothing structural"*,
which is the kind of sentence worth attacking. Two things were wrong.

*It enforced three clauses it could not cite.* Ten modules told officers
what clauses **5.4.2** and **5.11** require — the dossier, the export, the
CLI, the assistant, the readiness screen — in the product's own words, with
no verified extract anywhere. So did the sentence that decides whether a
politically exposed person is treated as high risk, attributed to Guidance
Note (4) under 5.5. That is the paraphrase-in-a-docstring the register
exists to replace, sitting beside two dozen clauses matched against the
regulator's PDF on every build. All three are registered now and checked by
the same machinery. **The register is 27 clauses; it was 21 this morning.**

*And "measured against clause 5.4.2" was a larger claim than the code.* The
clause has three limbs. Limb **(c)** requires a firm to identify the legal
form, constitution and powers of a company or arrangement, and to identify
**and screen** its connected parties. Two qualifiers inside (a) and (b) ask
for aliases, a trading name, a principal place of business, and an address
that is not a post office box. None of it was measured and nothing said so
— a party could be reported complete under 5.4.2 having never been checked
against a third of it. `readiness.NOT_MEASURED` names all five, and the
list prints with every result on both the report and the file.

*What held.* The nineteen factors are nineteen and the eight-eleven split
is right. The review intervals are the clause's own numbers — and so is
the proviso underneath them, a second schedule of two, eight and ten years
for a resident Indian customer already known to the Financial Group in
India, which is easy to read past because it is *longer* rather than
shorter. Both are modelled. Nothing computes a category.

**What it cannot do:** the eight factors it can look at are the ones a
record can answer; the other eleven wait for a person and always will. Of
the five things `NOT_MEASURED` names, **one is closed**: intake collects
aliases as of 20 August 2026, so 5.4.2(a)(i) can now be answered where a
firm holds one. The rest — a trading name, a principal place of business,
and limb (c)'s legal form, constitution and connected parties — still need
data the product does not collect.

**Next:** collect what limb (c) asks for. It is an intake question, and it
carries a screening obligation with it: connected parties must be screened,
not merely recorded.

### 11. Casework
`cases.py` · `policies.py` · `whosework.py` — 1,448 lines, 1,297 of tests

Findings recorded as facts, decisions with the decider's own words,
four-eyes escalation, the senior-management gate on politically exposed
persons, and per-role queue ordering.

**The rule worth knowing:** work *blocked on you* outranks everything on
your screen and reaches nobody else. A file passed up never returns to whoever
passed it.

**Audited 20 August 2026, and the one hard permission boundary in the
product was open on exactly the people it exists for.**

Clause 5.5(b)(iii) reserves the clearance of a politically exposed person
for senior management, and it is enforced twice — on the command side and
in the fold. Both held. **Both were asking the wrong question.** A watchlist
match is filed under the most serious thing it is, because that is what a
file should be *called*: a sanctioned head of state is a sanctions matter
first, since that is the one that stops the money. The gate then read that
same single label to decide who may settle the file, and a sanctioned head
of state is not labelled PEP.

Against the watchlist this product ships with, **Vladimir Putin, Bashar
Assad and Kim Jong-un all classify as SANCTIONS and all three carry
`role.pep`** — so any officer could clear them. Measured on the local index:
of 847 sanctioned persons sampled, **21.4% were politically exposed or a
close associate of one, and filed as sanctions**.

The product already held the fact it needed — `role.pep` was on the
permanent record in the screening event's topics, and nothing read it. Every
kind is now recorded beside the headline one, and **three** readers were
asking the single value: the gate, the queue that reserves an escalated file
for senior management, and the risk screen that decides whether an officer
categorising somebody sees the guidance about public office at all.

Everything else attacked held: no AI, VIEWER, SYSTEM or unenrolled actor
could settle a file by any path including a raw write to the log, four eyes
survived promotion, and "work blocked on you outranks everything" was true
for all four roles.

**Re-audited 20 August 2026: the fold was closed, and passing a file up was
walked to the end of where it leads.**

`cases.py` says the gate is enforced twice on purpose, "so a guarantee that
holds in only one direction is a guarantee someone will eventually route
around". The two sides had drifted: `engine.decide` applied six checks and the
fold applied four, and the two missing ones were *decided once* and *a
decision has a reason*. On a file an AML officer had rejected in writing,
appending a second `CASE_DECIDED` straight to the log was accepted:

    honest decision       REJECTED · REJECT by Meera · "Same passport number…"
    command-side second   refused: already REJECTED; Cases are decided once
    raw second decision   ACCEPTED → APPROVED · APPROVE by Devika · reason ''
    rows on the audit tab 1

A written rejection of a sanctions match became an approval with an empty
reason, on every replay, on every machine, with no way to take it back. Both
guards now live in the fold. `thin_reason` stays on the command side alone,
deliberately: it is a calibration of what counts as saying something, and
hardening a calibration into the fold would make a log written under
yesterday's wording unreplayable tomorrow.

**Escalation named who passed a file up and never who it was passed to.** With
the three deciding roles enrolled — an ordinary GIFT City FME — each could
pass the same file up in turn, and four eyes then locked every one of them
out permanently:

    status ESCALATED · open · passed up by Meera, Aarav, Devika
    all three:  waiting on you: no    can settle: no

A file open for ever, waiting on nobody, sitting in the ordinary band of every
screen with no marker on it — while the period report said of it "1 file is
waiting for a second officer after being passed up". On a politically exposed
file it took **one** click, because only senior management may clear one. The
escalation that would leave nobody is now refused with a remedy; a file
already in that state gets its own group above everything, on every screen;
and the report says what is true of it. The group heading also stopped
claiming "nobody else can settle it" — the same sentence was being shown to
two officers at once about one file, and either of them could have settled it.

**The reason gate was catching the wrong side.** Measured on 12 reasons a
screening officer would really type and 13 one-line closures: **5 of the 12
genuine ones refused, 10 of the 13 closures accepted**. `re.findall(r"[a-z']+",
…)` is an ASCII-only class, so every reason written in an Indian script was
refused outright — the product could not be used in a language it was built
for, and the officer was told their reason said nothing. Ignoring digits
refused "DOB 1971 vs 1985", the commonest true reason on a name match and item
one on OFAC's own checklist. Now 0 of 12 refused, 4 of 13 accepted — and the
four are named in a test rather than left as an implied claim. A maximum
length is stated too: a 100,011-character reason went onto a permanent event
unchanged, bounded only by a constant about HTTP request bodies.

*And two smaller things on the same file.* The letters panel sorted deadlines
by the raw text of `answer_by`, so an unpadded month put a nearer deadline
below a further one — a letter due in 13 days listed below one due in 43. And
reason codes were not a closed set: `same-party`, the REJECT-only code
captioned "Confirmed as the same party", was accepted and recorded against an
APPROVE, and so was `i-invented-this-code`, and so was a 200-character string
silently cut to forty. The codes exist so that reasons can be **counted**, and
a count over invented values counts nothing. They are derived from the one
list the screen offers, checked against the outcome, and refused rather than
cut.

**Next:** nothing reports on the reason codes yet, and they are offered only
on name checks — so a count would cover one case type of eleven.

### 12. The firm
`capital.py` · `disclosure.py` · `correspondence.py` — 637 lines, 749 of tests

Entity-level rather than customer-level: net worth against the licence
minimum, what was reported to IFSCA beside what the book holds, and letters
from a regulator with the clock running.

**The restraint that defines it:** a reported figure need not equal anything
computed from the book — capital is called in tranches and values move — so
the *difference* is shown and only a figure with **nothing at all** behind it
opens a file.

**Changed 20 August 2026:** the net-worth minimums now come from the
Second Schedule to the Fund Management Regulations rather than from two
law-firm summaries, and a shortfall cites the schedule that sets the
amount. The caveat did not go away, it got sharper: it used to say the
figure was unchecked, and now says the figure is a *floor* — other
activities inside or outside the IFSC each require their own minimum on
top, and this system knows nothing about them.

**Audited 20 August 2026. Both of the correspondence promises broke.**

*A letter that was answered went on being reported as never answered* — on
the queue, on the case page, and in the exported evidence pack an inspector
reads. Recorded as answered on 12 August, the file still said "that date
passed 19 days ago and nothing has been recorded as sent". The projection
knew otherwise the whole time; the file was reading the finding frozen at
the moment the rule fired. The answer now attaches to the letter's own file
as later evidence — the same shape as a refilled seat attaching to the
vacancy it fills, which this codebase had already solved once for
governance. The file still stays open, because answering a regulator and
closing the record of having been asked are two different acts.

*And the deadline was the one date in the product nothing checked.* Every
event's date goes through `check_date`; this went into the permanent log as
whatever arrived, cut to ten characters. So **"31-07-2026" — how a date is
written in India — was stored untouched and read back as no date at all**:
the letter was nineteen days overdue and the screen said "no date was set".
And a date pasted out of a PDF with a leading space became " 2026-07-3", a
real date **twenty-eight days earlier** than the one the regulator gave. It
now reads through the importer's parser, which accepts the forms a person
uses and refuses the genuinely ambiguous ones — 07-08-2026 is either August
or July depending on who typed it, and guessing on a regulator's deadline is
not this product's to do.

**Re-audited 20 August 2026, and the half of the calendar that did not
exist.**

*The capital rule watched one side of a comparison.* Its own docstring said
it was "raised on the report rather than swept for, because the report is the
only moment the answer can change with it". The answer is *held against
required*, and three ordinary orderings moved the other half with nothing
reaching a queue: net worth recorded before the licence — the order a fresh
workspace fills up in — left a USD 190,000 shortfall unfiled; a third-party
activity recorded afterwards, which is the very mechanism this module chose
for itself, left USD 400,000; an officer confirming a higher minimum, the
same. The regulatory page said the firm was short in all three cases. Nothing
that reaches a queue did.

*A confirmed minimum outlived the licence it was confirmed for.* A firm that
upgraded from Authorised to Registered (Retail) kept its USD 75,000 floor,
held USD 100,000, and read as **compliant** — USD 900,000 below the Second
Schedule figure, with the reassuring word *confirmed* attached. The
confirmation is never thrown away; it stops standing for a question nobody
asked it, and the sentence says who made it, for what, and what to do.

*"Nothing at all behind it" was measured against a projection that counted
investors only from commitments.* Built the ordinary way, through the real
intake — a registrar's investor list with no commitment column, which the
importer explicitly supports — 87 parties and 87 payments produced an
investor count of **nought**, and a return claiming 87, every figure of it
true, produced this module's gravest accusation.

*And the side-by-side row dropped every non-dollar payment,* then called the
difference "more than arrived". On the shipped demo that is **83 of 805
payments** in six currencies, none of them mentioned on the row, the column
heading or the summary. The decision not to convert is right and is argued in
the code; the decision not to *say so* was argued nowhere. It says so now, and
does not claim more arrived than the record supports.

**Nothing in the product could record that a return was filed.**
`FILING_SUBMITTED` existed in the model and in six files; no command, no route
and no import produced one — while `FILING_OVERDUE` was swept for on every
briefing load. A firm licensed in April 2023 and opened here for the first
time in August 2026 collected **19 permanent overdue records in one call**, 13
quarterly reports and 6 fees, USD 24,700 of computed late charges, with no way
to say it had filed any of them and no way to take them off. There is a
command, a route and a guarded engine method now — and the "what the last
return claimed" panel, which returned nothing on every workspace ever built,
has an input path at last.

*A reported figure that was not a number* opened a HIGH case whose own
permanent record read "reported: nothing recorded" — a case that exists
because a figure was filed, stating that no figure was filed — and a
non-numeric count raised a raw Python error out of a policy, on a code path
that runs on every render of the regulatory page. Figures are read as figures
at the boundary now, and a name nobody reports on is refused rather than
silently dropped.

**Next:** the remaining returns calendar. Three obligations are modelled;
AML/CFT returns, FATCA/CRS and scheme filings are not.

---

## Data in and out

### 9. Intake
`importing.py` · `xlsx.py` — 1,849 lines, tested in `test_intake.py`,
`test_importing.py`, `test_intake_audit.py`

CSV and Excel from any institution. **30** party fields and 11 payment
fields against the shapes banks and registrars actually export — split
debit/credit columns, names in three pieces wearing honorifics, .xlsx read
with no dependency.

**The doctrine:** nothing is guessed. A column it cannot name is reported,
not approximated; two columns claiming the same field refuse the import
outright; nothing is written until a person confirms the mapping.

**Audited 20 August 2026. This is where untrusted bytes enter the
product**, so the workbook reader was attacked directly. Three attempts;
two were already stopped and one was not.

*A decompression bomb went straight through.* A .xlsx is a zip, and a zip
compresses repetition extravagantly. **1 MB on disk** built from one
repeated string unpacked to 360 MB of XML, took **34 seconds** and peaked
at **1.3 GB of memory** — and read successfully. The upload limit is 20 MB,
so the same trick at full size would have asked for roughly **26 GB** and
eleven minutes of a request thread. Every check the reader had was about
what arrived; none about what it became. There is a ceiling on unpacking
now, shared across the files in the archive because a bomb split five ways
is the same bomb. The same file is refused in **0.0s at 0 MB**, and a
genuine fifty-thousand-row book — which unpacks to 5.9 MB — reads in 14.9s
at 82 MB.

*Two held, and neither because of anything here.* A billion-laughs entity
bomb is stopped by the amplification limit in Python's own parser; an
external entity naming a local file is refused because ElementTree does not
resolve them. Both are now tests, precisely because they are somebody
else's guarantee and a change of runtime could withdraw either silently.

**And the gap two other blocks had already reported from the far side.**
Clause 5.4.2(a)(i) asks for a full name *"including any aliases"*. Block 3
found that screening could only ever ask a watchlist about the one name on
the record; Block 7 had to declare the aliases limb unmeasured. Both for
the same reason: there was nowhere on a party to put one. There is now —
17 spellings, from `aka` to `maidenname` to `doingbusinessas` — and one
cell carrying several names is read as several.

**Next:** the mapping page should let a person *correct* a column, not only
accept or abandon. The three remaining 5.4.2 fields — a trading name, a
principal place of business, and limb (c)'s connected parties — belong
here too, and the last of them carries a screening obligation with it.

### 10. Export
`spreadsheet.py` · `exporting.py` — 538 lines, 214 of tests

A hand-written .xlsx writer and the four-tab book export: parties with what
we have since worked out about them, open files, decisions, payments. The
whole book comes out in **0.17 seconds, 91 KB, four tabs**.

**Audited 20 August 2026, as the far end of a round trip.** A firm uploads
a workbook its registrar produced, every name in it becomes a party, and
this writes those same names back out into a workbook somebody opens.
Nothing in between is under this product's control, so it was attacked with
the values an importer can actually deliver.

*The classic one does not apply, and it is worth writing down why.* A value
beginning `=`, `+`, `-` or `@` is a formula to a spreadsheet, and an export
that emits those as raw CSV hands the reader a command to run. This writer
emits `.xlsx`, and every cell is typed `inlineStr` — literal text, in a
format where formulas live in a separate `<f>` element this module never
writes. Thirty cells of payload produced thirty `inlineStr` cells and no
`<f>` anywhere; the real book export is 3,944 text cells and 218 numbers,
with no formula in it. The only CSV the product serves is an empty import
template with fixed headings. **Nothing was changed here, and that is the
finding** — prefixing a quote "to be safe" would put a character in a
compliance export that the record does not contain.

*XML injection does not apply either.* A name closing its own tag —
`Ravi</t></is></c><c r="Z9"><v>1</v></c>` — round-trips as exactly those
characters.

*One thing did not hold.* The module already strips control characters, for
a stated reason: a workbook Excel offers to repair reads as the export being
untrustworthy rather than the value being odd. The same is true of a cell
longer than Excel holds — **32,767 characters** — and a 40,000-character
value went straight through. An imported narration or address has no length
anybody bounds. Values are cut to fit now, and the cell says how much was
left behind rather than quietly ending early. The cut happens before
escaping, because one ampersand becomes five characters in the file.

**What it cannot do:** it is one worksheet per tab written as one string,
so the whole export is built in memory. At a real book's size that is 91 KB
and a fifth of a second; nobody has measured it at a million rows, and
Excel stops at 1,048,576 of them anyway.

**Next:** PDF. Print-to-PDF works; a real generated document does not exist.

---

## The agentic layer

### 13. Agents
`agents.py` · `planning.py` — 816 lines, 194 of tests

Nine tools, five recipes, model-composed plans, and live progress that is a
*projection of the event log* rather than an animation.

**Measured:** the morning check does 7.5 seconds of real work — 40 parties
screened against the local index, duplicates resolved, letters read, capital
checked.

**Audited 20 August 2026. The structure held; the arithmetic did not.** Nine
tools, five recipes, none of the nine writes or mutates anything, progress
really is a reading of the log, and the fold really does refuse a decision
authored under an agent's own name. But three steps put counts on the
permanent record that did not mean what their words said — each one failing
in the safe-sounding direction.

*The handover check reported zero ownership problems on a book with
eighteen.* It walked the first sixty entities of **any** kind, in
registration order, and called them structures. On the shipped book that is
one structure and fifty-nine natural people — who have no ownership chain,
so nothing about them can be incomplete. It recorded **"60 structures
followed, none could not be completed"** while eighty-three structures it
never looked at held eighteen broken chains. It now follows structures, and
says how many the book holds.

*A run in which every check was refused read as a clean pass.* The screening
step counted an attempt as a check and swallowed the failure. One character
wrong in an environment variable — `sanction` for `sanctions` — and forty
refusals recorded **"40 of 218 checked, 0 worth a look"**. It now counts
what it did, names the reason, and a step that reached nothing is marked
failed rather than done.

*And it cut its list of matched parties at eight without saying so.* A
morning check that found twelve named eight and dropped four, two of them
debarments. The cap is a named constant now and the step says how many it
left out.

The screening step also took no injected client, which is why the defect
sat in the one step that talks to the outside world, unexamined. It does
now, and the counting is tested.

**What it cannot do:** an agent can look, count, compare and draft. It
cannot settle a file, because the fold refuses decisions from anything not
enrolled as a person.

**Re-audited 20 August 2026, and three more of the same shape.**

*A step that crashed was counted as a step that found something.* The test was
`if found.how not in (DONE, "skipped")`, and `FAILED` is neither. It is on the
shipped workspace's own log — live.db seq 1568/1569 record a screening step
that broke outright, and a summary reading **"2 of 3 steps found something
worth a person's time"**. A run where the watchlist never answered and a run
that found two sanctioned investors closed on the same reassuring sentence,
and that sentence is the whole of a collapsed task card. Steps are counted by
what they are now, and a run with a failure says so: *"1 of 3 steps found
something worth a person's time; 1 step could not be run, so nothing was
checked there."*

*And it said so in Python.* `could not finish: type object 'WatchlistClient'
has no attribute 'from_environment'` is on that same permanent log — a raw
`AttributeError` on a compliance officer's screen. The reason is evidence and
is kept, in the step's details; the headline is a sentence for the reader.

*The author of every agent event was a name the model chose.* `run_task` wrote
`actor=step.agent`, and `step.agent` comes straight from the model's reply —
seq 1594/1595 of live.db carry `actor='sanctions screening'`. Two things
followed. A transport answering `{"agent": "Meera Nair"}` put an enrolled AML
officer's name on a hash-chained event she had nothing to do with,
permanently. And that same model-chosen string was the input to
`may_produce_findings`, so **whether the rulepack ran over an agent's event
was decided by untrusted model output** — adding one policy that named
`TASK_STEP` opened three real Cases from agent-authored events. Steps are now
authored by "the agents", the label travels as data, and `TASK_STEP` and
`TASK_FINISHED` joined `DRAFT_PREPARED` in `MODEL_AUTHORED`.

*A run whose process stopped read "Working now" for ever.* `running` was
defined as the *absence* of a finish record, and the work runs on a daemon
thread, so an ordinary clean shutdown left a card under **"Working now —
Checking parties against the watchlists"**, present tense, bar at 0%, with the
browser re-fetching every 1,200 ms for a thread that no longer existed. It
survived restarts, so a workspace collected permanent phantom jobs an officer
could not tell from live ones. This is the Ledger block's own lesson — a chain
cannot see its own tail, absence read as a positive state — turning up again
in the agent projection. A job given before today with nothing recorded since
now says it stopped, names how many steps had been recorded, and the browser
stops polling it.

*And two more from the same pass.* A model-composed plan had **no cap at all**
on how many steps it could have, and the whole plan goes into one permanent
event: a transport returning 2,000 steps produced a 155 KB payload, 2,002
permanent events and a workspace file a megabyte larger — with the cheapest
tool, and with no way to stop a run once started. The discipline already
existed one function over, where the screening step caps at forty and says so
in words. Twelve now, and a plan that was cut says so on screen. Task ids were
also minted outside the lock, so twelve near-simultaneous delegations
collapsed onto one card, permanently, with 48 step events folded into a
four-step plan.

**And "an agent cannot settle a file" rested on nothing testable.** ``run_task``
handed each tool the whole engine, and ``decide``'s ``actor`` is a free string
the fold checks against the *payload*, never against the caller. A tenth tool
dropped into the registry settled three files from inside a run — permanently,
attributed to an officer who never touched them, and a replay agreed. The
guard the product cited against exactly this iterates the **assistant's**
registry, so a write-capable tool inserted into the agents' one passed both of
its tests untouched; across the whole suite, no test imported ``agents.py`` or
``planning.py`` at all — 744 lines with nothing on them. The safety was real
and it was a coincidence: nine hand-written functions happening not to write.
Tools are handed a read-only view of the workspace now — an allowlist, so a
way of writing added next year is refused by default — and the registry has
tests of its own.

**Next:** per-step progress during long steps. A 6-second screening step
currently sits at 0% then jumps.

### 14. The assistant
`ask.py` · `assist.py` · `narrative.py` · `azure.py` · `conversation.py` — 1,803 lines, 1,414 of tests

Read-only Q&A through nine named tools with prompt-injection defence,
drafting with a hallucination guard, written openings on records, the Azure
wire with India-only residency enforced twice, and the conversation thread —
which needed no store because every turn is already an event.

**The guards:** a summary containing a figure not in the material is thrown
away, not repaired. So is one that concludes anything. There is a test
asserting the tool registry can never grow a tool that writes.

**Audited 20 August 2026. All three hallucination guards were checking a
bag of digits, not a value.** Every figure was split on commas, hyphens and
slashes and the *fragments* were checked against what the model had been
given. So:

* **A date was never checked as a date.** Given a record and a listing that
  both say 1978-04-12, this draft cleared the sanctions match with nothing
  reported as invented: *"our investor was born on 12 April 1978 and the
  listed party on 4 December 1978, so they are different people."* Every
  digit of the fabricated date — 4, 12, 1978 — is a digit of the true one.
  The invention is in the **arrangement**, and only reading it as a date can
  see it. Dates are now read as dates, in every form a person writes one.
* **Every number from 0 to 100 was an unconditional free pass** in the
  answers guard — exempted as "counting, not quoting". Asked how many
  parties were unscreened where the answer was 77, the assistant could say
  87 or 99 and nothing objected, while a fabricated 4,321 *was* caught. A
  count is the question an officer most often puts to an assistant, and a
  count was the one figure it could not get wrong out loud. Only a single
  digit passes unchecked now; everything else has to appear in what was
  actually read — which is what let "10%" through all along, since the
  clause text is among the things it read.
* **Money was split on its commas**, so `1,797,000` was three fragments of
  `1,797,478` and passed against a record holding the latter. Values are
  compared whole now, and `17,97,478` still passes — because that *is*
  1,797,478 written the way it is written in India.

**Re-audited 20 August 2026. The Azure boundary makes three promises in its
own docstring and none of the three held.**

*"Data residency is enforced here, in two places."* One `Location` header
defeated both at once. `urlopen` follows a redirect by default and carries
every request header to the new address — `api-key` included, and across
origins. So the call went where the header pointed, and the second guard,
which reads `x-ms-region` off the reply, read a header **the redirect target
had written for itself**. A throwaway server sent a 302 for the
chat-completions POST and received `api-key: sk-SENTINEL-REDIRECT`; the region
check passed and the call succeeded. Nothing follows a redirect now, on either
half of the assistant, and a 3xx is a loud `DataResidencyError` rather than a
quiet "no draft today" — because it means somebody put a proxy or a wrong
endpoint in front of the model.

*"A spend ceiling across the whole workspace, summed from the log."* It summed
one event type. Four questions typed into the ask box made **11 model calls
and 22,848 input tokens**, and `spent_so_far` afterwards read **0.00 of
50.00** — the transport threw the `usage` block away, and the
`ASSISTANT_ASKED` payload carried no model, no region, no prompt version, no
tokens and no cost, where `DRAFT_PREPARED` carried all six. The ceiling
covered the half of the assistant nobody drives and missed the half a person
types into all day. The transport prices its own call now, the ceiling is
checked before the first one, and the record answers "which model, which
prompt, what did it cost".

*"Identical inputs produce identical logs — no clock in the core."* `ask.py`
read `date.today()` on a write path, the only one in `vinzor/`. Two engines
built from identical events, asked the identical question, given the identical
answer, came out with different chain heads. The date is the caller's to
supply now, and a sweep **parses** every module in `vinzor/` — rather than
grepping it, since half of them explain in prose why they may not call a clock
— so the next one fails a test instead of an audit.

**And the assistant was speaking the workspace's own vocabulary out loud.**
Rule 5 of the prompt already forbade identifiers and field names; three of six
live answers broke it — *"The first file in your queue is case_2027b6adf581"*,
*"I tried open_files, but it did not provide the required amounts"*. Nothing
checked: the jargon sweep is a static test over sentences written into
`briefing.py`, and these are written at runtime by a model and then onto a
permanent event. The tool-name half was required by the prompt itself, which
said "say which tool you tried" when the tools had only snake_case internal
names to give. Every tool has a name a person would use now, and identifiers
are **translated, not refused** — `case_…` becomes "the name check on Rohan
Desai" — because the identifier was not wrong, only unreadable, and
withholding a correct answer over how it is spelled costs the officer more
than it saves them. What was said plainly goes on the record beside the
answer.

*Two more, both about a paragraph nobody could point at.* The written opening
on a party's record was regenerated on **every page view and every print** and
recorded nowhere: three consecutive views of an identical, unchanged record —
at temperature 0, top_p 1, seed 7 — produced three materially different
paragraphs, and one of them printed the raw address, email, date of birth and
identifying number that the other two summarised. Neither the paragraph nor
the withheld sentence reached the log, while every withheld answer at the ask
boundary is recorded on the stated ground that a guard which fires silently is
a guard nobody can audit. It is written once, recorded with its model, region
and prompt fingerprint, and read back thereafter — which also takes a model
call out of the latency of every record page. And ``narrative.material`` ended
in a bare ``[:12000]`` with no name, no comment and no marker: past roughly
200 dated lines on one party the tail sections were dropped silently, and the
last section is "What is still open".

**Next:** streaming. Answers arrive all at once after several seconds. And
the guard against *concluding* is still a phrase blocklist, which is a
weaker thing than the figure guards now are.

---

## Around the edges

### 15. Access
`credentials.py` — 330 lines, 458 of tests

scrypt at 2^14 with per-record parameters, hashed session tokens,
HttpOnly + SameSite cookies, lockout that expires.

**The bug worth remembering:** the visible half was the password screen. The
half that mattered was that every write — and later, every *read* — took the
actor's name from the request.

**"Both fixed" was half true, and the audit of 20 August 2026 found the other
half.** The writes were fixed. The reads were fixed only *inside the handlers
that thought to ask*: three of them fell back to `PEOPLE[0]["name"]` when
nobody was signed in, and the rest never asked at all. On this workspace —
where all four people have passwords — an unauthenticated request to
`/api/briefing` was served **282 KB of the client book, greeted by name**.
Who has committed money, who matched a watchlist, what an officer wrote about
them. The sign-in screen was decoration for everything except writes.

Nothing in the test suite caught it, because nothing asked the question from
outside. The gate now lives once, at the dispatcher, on both verbs — a guard
each route has to remember to ask for is a guard some route will forget — and
seven routes are checked signed-out and signed-in by name.

**Two more, from the same audit.** `/api/chat`, `/api/tasks` and the sign-in
returned *before* the body cap and the same-origin check, so the three routes
that set an agent working, put a question to the model and answered the door
were the three a page on another site could reach and the three with no
ceiling on the body. A cross-site page could spend five requests and **lock an
officer out of their own compliance system** without ever holding a
credential. Both guards were hoisted above every route.

What held under attack: 256-bit tokens stored only hashed, a constant-time
compare, idle expiry, sign-out and password-change invalidation, and no VIEWER
able to reach any write route.

**What it cannot do:** no `Secure` flag, because this serves plain HTTP on
loopback. Behind TLS that must be added. No password reset, no audit of
sign-ins.

**And the sign-in was an enrolment oracle, in two ways with two different
answers.** For a single attempt the claim held: wrong-password-on-enrolled
against unknown-name measured 80.2 ms against 78.7 ms with identical text.
Across attempts it did not. The lockout applies only where a record exists,
so an enrolled name with a password stops answering after five wrong tries
and an unknown name never does — which classified the whole roster over HTTP
in **24 requests and 2.3 seconds**. That half is inherent to a per-account
lockout: locking names nobody has enrolled would let a stranger lock the
roster out by guessing at it, and the alternative is an unbounded table of
every string anybody has ever submitted. It is a **stated limit** now, in the
docstring and here: this sign-in does not hide *who is enrolled* from
somebody willing to spend attempts. It hides their passwords.

The timing half was not inherent and is closed. A locked name returned before
any hashing ran — **0.03 ms against 60.75 ms**, roughly two thousand times
faster, and readable from one request. The stretch runs before every branch
now, and the locked path makes the same write and commit as the others;
measured strictly alternating, the two paths differ by 0.63 ms.

**Next:** TLS, then reset. And a rate limit in front of the sign-in —
lockout tells a caller which names are real.

### 16. The interface
`briefing.py` · `dossier.py` · `reporting.py` · `server.py` + `web/` — 7,524 lines + 4,955 of web

Every screen, the HTTP layer, the design system. Dark ground, one amber that
means *live*, a navigation rail, role-aware ordering, and a jargon sweep that
runs as a **test** — no id, policy name, SCREAMING_CASE or raw JSON
punctuation may reach a reader.

**Audited 20 August 2026 as a web surface, in a real browser.** The escaping
story held: six shapes of hostile party name were thrown at every screen and
produced **zero injected nodes and zero alerts** — the `h` tagged template is
genuinely safe by default.

**The access control did not hold, and it is written up under Access (block
15).** Ten read routes served the whole customer book to a request with no
session, and three write routes returned before the body cap and the
same-origin check. Both are fixed at the dispatcher and tested from outside.

**Re-audited 20 August 2026: the sweep, the report period, and where an
uploaded spreadsheet lives.**

*The jargon sweep could not walk a dictionary,* so the largest body of prose
in the product was swept by nothing. `briefing.UI` is 124 strings injected
into every JSON response and rendered on every screen; the walker descended
dataclasses, lists and tuples, and returned **zero** strings for it. It was
hiding a live offence: pressing "Check the watchlists now" on a workspace with
no watchlist replaced the screen with *"Set VINZOR_SCREENING_URL to your
watchlist index"* — an instruction to whoever installed the software, printed
to somebody who cannot act on it, and the first thing every new user saw. The
walker reads dictionaries now, `UI` and all 24 messages are swept, and named
`{holes}` a caller fills are a stated exemption rather than something the
JSON-punctuation rule trips over.

*The same claim was open a second way.* The record page — "the document you
would hand an inspector", with a print button on it — showed **NATIONAL_ID**
to the reader on 29 of the live book's 218 parties, and a date of birth as
`2005-12-17` beside "First went on the record = 7 August 2026". `dossier._said`
fell through to `str(value)` for any attribute nobody had named, and the sweep
that should have caught it used a fixture whose parties carried none of the
fields 55% of the real book carries. Identity documents and dates are said in
words now, borrowed from the officer's own screen rather than copied so the
two cannot drift, and the swept party carries what a real one carries.

*The period report accepted any string as its period.* `since` was truncated
to ten characters and compared as text, which is right for an ISO date and
silently wrong for anything else. Against the live book, same server, same
instant:

    since=banana       "Covering banana to 20 August 2026", every figure zero,
                       "No file was opened or settled in this period"
                       — while 221 files had in fact been opened.
    since=01-08-2026   a date written the ordinary Indian way became
                       "Covering 2026 August 1", and a one-month report
                       quietly became an all-time one: 154 commitments
                       instead of 16, 53 ownership declarations instead of 0.

This page carries the firm's name and a print button, and "no file was opened
or settled in this period" is the sentence a firm would least like to have to
defend. A period that cannot be read is refused with a remedy, never guessed
at and never echoed into the covering sentence.

*And uploaded customer spreadsheets never went away.* `_HELD_UPLOADS = 25` was
described as "a bound rather than none at all". It bounded one directory, and
the directory was a fresh `tempfile.mkdtemp()` per process — so every restart
minted a new one, reset the count to zero and orphaned the last, and nothing
removed any of them. Measured on the development machine: **170 leftover
`vinzor-imports-*` directories holding 491 uploaded sheets**, the oldest four
days old, under the customers' own filenames, in the clear, in a shared OS
temp folder — while the product's answer to "where does a customer's data
live" is "one workspace file, and that file is the tenant boundary". The
holding area now sits beside the workspace, is per application rather than per
process, is pruned by age as well as by count, and is deleted when the server
stops.

**What it cannot do:** `briefing.py` is 4,612 lines and holds both the words
and the assembly. It is the most obvious thing in the codebase to split.

**Next:** that split, then mobile.

### 17. Evaluation
`tools/` (10 scripts) · `check.py` · `quality.py` · `evidence.py` — 3,321 lines

The measurement culture, and arguably the most valuable block: SynthAML
lift, the OpenSanctions pairs protocol, the planted typology suite, the
**adversarial lab** that asks what it costs to walk around each rule, and
the quality page that counts how often an officer decided against the
assistant.

**Why it earns its place:** the 1.00-lift finding, the 12-of-21 clause
errors, the every-veto-hurts result and the four free evasions all came from
here. None of them was visible by reading the code.

**Audited 20 August 2026 by running every one of them against the rewritten
code.** All 14 tools imported and ran with no API drift, and every number
this map quoted reproduced — 7 of 7 typologies, 16 of 16 duplicate shapes
with 0 of 7 false alarms, 24.4 files per hundred ordinary payments, the
widening speedup on payment folds, the four zero-cost evasions.

**Four of those numbers stopped being true on 21 August 2026**, when nine of
the ten payment rules were removed. The typology tool now reports 0 of 7, the
evasion lab one trial against one rule, ordinary traffic 11.5 per hundred,
and the payment-fold measurement went with the projections it timed and the
tool that timed it. Block 6 carries all of it. The duplicate-shape numbers
are untouched, and so is `tools/against_labelled_pairs.py`, which grades name
comparison against OpenSanctions pairs and has nothing to do with payments.

**But the verifier shipped inside the evidence pack called a truncated
record intact.** The pack is the artefact handed to an inspector, an auditor
or a board, and its whole design argument is that the recipient does not
have to trust the tool that produced it — they run `verify.py`, which reads
nothing but the file. It seeded its expectation *from the file it was
checking*, and never asserted where the log began or ended. Ten lines cut
off the front and it printed **"INTACT: 30 records, none altered, none
missing"**; ten off the back and it printed the same.

That is the defect the Ledger itself was audited for in block 1 — a chain
cannot see its own ends — reappearing in the one file whose job is to be
believed, and it was a weaker guarantee than the product enforces on itself.
The pack now writes both anchors into the verifier when it is made: the
first line must be record 1 following sixty-four zeroes, and the last must
be the record the log ended at, with the count that was in it. The sentence
printed inside every pack has been corrected too — it claimed the chain
alone caught removal, and it does not.

**The quality page could not do arithmetic.** It tallied decision *events*
for its numerator and counted *files* for its denominator, so the ordinary
AML path — escalate, then settle, which is one of the three buttons on every
file and is forced for every politically exposed person — made it read
**"Decided against the suggestion: 2 of 1"**. A reader with any arithmetic
stops believing the rest of the page. It counts one use per file now, the
settling one, and an escalation is not counted as a verdict at all: the code
says in as many words that a handover is "not an answer", and the file stays
open.

**The one measurement whose ground truth nobody here wrote was measuring
nothing.** `against_real_lists.py` draws its names from the sanctions index
itself, so a name in it is on a real list by construction — it is the number
that would decide whether screening is fit to sell. Run exactly as documented,
with the stack up and healthy, it printed:

    0 genuinely listed people, 25 invented ones
    caught, of people really on a list   0/0
    quiet, of people on no list at all   25/25
    exit 0

Both halves vacuous, neither saying so, and a clean exit code so nothing
downstream could notice. It defaulted to scope `sanctions`; the repo's own
`.env` sets `default`, and `_load_dotenv` was only ever called from
`vinzor/__main__.py`, so a script under `tools/` never saw it. There is no
`sanctions` index on the machine, and Elasticsearch answers a wildcard
matching nothing with HTTP 200 and no hits — nothing raised, nothing was
measured. Run with the scope the product actually uses, the same tool reports

    caught, of people really on a list   25/25
    quiet, of people on no list at all   20/25

**recall 25/25 and a 20% false-positive rate** on invented Indian names — a
real calibration finding it was hiding from its own author. Tools now load the
same `.env` the product does, an empty draw is refused with exit 2 rather than
reported, and a check the watchlist never answered is counted apart from a
control that stayed quiet, so a screening outage can never score as a clean
run.

**And the "Next" would have achieved nothing.** CI already existed and ran the
suite and the demo walk on two Python versions; it ran nothing from `tools/`.
Adding them would not have helped, because **10 of the 14 ended in a bare
`return 0`**. Simulated total detection failure, in memory:

    typologies  → "0 of 7 shapes are recognised as shapes."   exit 0
    adversarial → "0 evasions failed, 0 worked, 10 could not
                   be tested."                                exit 0
    ordinary    → "every payment rule  10000  12820.5"        exit 0

All three green. A build that goes green on "0 of 7 shapes are recognised" is
worse than no build, because it is read as evidence. Each fast tool now
carries a floor — the number measured on 20 August 2026, written into the file
with the date — and returns 1 below it: 16 duplicate shapes with 0 false
alarms, no more than 1 evasion working against the 1 trial that remains, and
a stated `LOUDEST_ACCEPTABLE = 30.0` false positives per hundred ordinary
payments against the 11.5 measured. Six tools run in CI, in about five
seconds, all byte-deterministic. Ten tests hold each floor in place *and fire
it*, because a guard nobody has seen fail is a guard nobody should trust.

**One of those floors is no longer a guard, and it is named rather than left
looking like one.** The typology floor stood at 7 of 7 until the payment cut
of 21 August 2026 and now stands at 0. Nothing goes below zero, so that tool
can only ever report an improvement — which is precisely the failure this
paragraph was written about, reached by a different route. `typologies.py`
prints that in its own words when it runs, and the paired test that used to
rehearse the floor firing now says in its name that it proves the comparison
works and nothing about detection.

`shots.py` pointed at port 7500 while the product serves 8000 everywhere, so
run as documented it printed eight connection-refused lines and exited 0 — a
camera that photographs nothing and reports success. It uses the real port and
fails when it takes no picture.

**Next:** the slower tools. `payments_at_scale.py` was the candidate — 2m46s
overall, with an exact-arithmetic half that ran in 8.8s and was
machine-independent — and it was deleted on 21 August 2026 along with the two
projections it timed. `at_scale.py` is the remaining slow one.

---

## What is not a block yet

Named so nobody assumes otherwise.

| Missing | Why it matters |
|---|---|
| **Multi-tenant serving** | One SQLite file per workspace is the tenant boundary. There is no layer above it. |
| **PDF generation** | Print-to-PDF only. |
| **Adverse media** | The count comes from OpenSanctions datasets, not a news feed. That is a purchase. |
| **Document extraction** | Deliberately deferred until a real firm's pack is in hand. |
| ~~**CI**~~ | *Exists.* GitHub Actions runs the suite and the demo walk on Python 3.11 and 3.13 on every push and pull request, plus the six measuring tools that can now fail. |
| **Regulatory change tracking** | The register knows the 3 Aug 2026 amendment is pending; nothing folds it in. |

---

## Suggested order for the deep dives

Ranked by what unblocks the most, not by what is most interesting.

1. **The Rulebook** — a CA/CS hour. Not code, and it gates every clause claim.
2. **Screening** — the OpenSanctions quote. Gates selling at all.
3. **The interface** — split `briefing.py` before it grows again.
4. **Transaction monitoring** — calibrate against one real book.
5. **Evaluation** — into CI, so the rest cannot rot quietly.
6. **Entity resolution** — the merge workflow it currently refuses to have.
7. **Documents** — extraction, once a real pack exists.
