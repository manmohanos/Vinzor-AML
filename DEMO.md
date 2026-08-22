# The ten minutes

Everything you need to run the demo, in the order you run it.

**The site:** <https://dikytp5q85njb.cloudfront.net>
**Sign in as:** Meera Nair · `saffron amber willow ember` (AML Officer)

Have a second tab open on **Rohan Kapoor** · `lantern copper amber pewter` —
he is Senior Management, and there is one thing only he can do.

---

## Where the documents are

All twelve are in the repository at **`vinzor-core/examples/pack/`**.

Download them to the demo machine before you start — you cannot drag a file
you do not have locally. Every one is marked **SPECIMEN — NOT A REAL
DOCUMENT** across the top, and every identifier is from a range no authority
issues (`ZZZPB0000Z` is not a PAN series; `Z9999999` is not a passport). If a
judge asks whether that is real data, the answer is on the face of the page.

| File | Upload it as | It reads back |
| --- | --- | --- |
| `passport-bhat.pdf` | Passport | name, date of birth, nationality, passport number |
| `pan-bhat.pdf` | PAN card | name, date of birth, PAN |
| `aadhaar-bhat.pdf` | Aadhaar | name, date of birth, address |
| `utility-bhat.pdf` | Utility bill | name, address |
| `bank-bhat.pdf` | Bank statement | name, address |
| `incorporation-orion.pdf` | Certificate of incorporation | name, CIN, date and country |
| `moa-orion.pdf` | Constitutional documents | name |
| `board-orion.pdf` | Board resolution | name |
| `ubo-orion.pdf` | Beneficial ownership declaration | name |
| `deed-sharma.pdf` | Trust deed | name |
| `trustee-sharma.pdf` | Beneficial ownership declaration | name |
| `deed-kesari.pdf` | Partnership or LLP deed | name, date of registration |

To upload: onboarding **step two** has a drop zone. Drag the file on, or use
*Choose files*. Pick the kind from the list — the kind is what decides which
fields the document is allowed to evidence, which is worth saying out loud.

---

## The run, in order

### 1. Start on Home — ten seconds

*"This is a compliance officer's morning. Everything here is one firm's real
position: 80 files open, 22 that stop the money, 177 parties nobody has
checked. The first thing on the screen is not a dashboard — it is the thing
she came here to do."*

### 2. Onboard a person — two minutes

**Onboard an investor → Person → "Anand Bhat" → Next.**

*"One question per screen. Six choices, one line each. No training."*

On step two, before uploading:

*"It is not showing her a form with thirty fields. It is telling her the next
thing that is missing, why it is being asked for, and the clause it comes
from."*

**Now drag in `passport-bhat.pdf`, kind: Passport.**

*"It read the document. Name, date of birth, nationality, passport number —
and it shows the line it read each one off, so she can check it without
opening the file. It also shows which reader found each field: a generated
PDF is parsed deterministically, a photograph is looked at by a model, and
those are not equally strong claims.*

*It proposes. It does not write. Accepting a proposed field onto the record
is the next thing being built — today an officer reads it and types it. The
reason it is a proposal at all is that 'an officer looked at this passport
and said it shows this date of birth' is the record a regulator wants, and
'our software read a PDF' is not."*

**Then run the checks.** Eight agents, each one visible as it lands.

### 3. The moment — ninety seconds

**Onboard an investor → Person → "Vladimir Putin" → country RU → run.**

*"Fifteen seconds. Four million watchlist entities on our own machine —
nothing left the building. Sanctions, matched on OFAC and the French and New
Zealand lists. Politically exposed. Twenty-five news articles, live from
GDELT."*

Then open **"says who?"** on the sanctions finding:

*"Every finding cites the clause — and shows the regulator's own sentence,
the edition, the page number, and a link to IFSCA's own PDF. And it tells you
no qualified person has signed the register off yet, which is true of all
thirty clauses and is the largest open gap in the product. A citation that
hides its own provenance is worse than none."*

### 4. The trust — the one that shows the depth

**Onboard an investor → Trust → "Sharma Family Trust" → Next.**

Point at the outstanding list:

*"A trust owes different papers from a person. The trustee's own disclosure
that they are acting as trustee — because clause 1.3.3(d) treats a trustee
and a beneficial owner completely differently, and a trustee who does not say
which they are is indistinguishable from one."*

**Drag in `deed-sharma.pdf` and `trustee-sharma.pdf`.**

Then the ownership section:

> **Beneficial ownership under IFSCA is 10%, not 25%.**
> FATF says 25. Every global vendor assumes 25. IFSCA cut it to ten by
> circular in May 2023 — and it is four different tests. For a company it is
> *more than* 10%. For a trust it is *10% or more*, **plus the author and the
> trustee at any percentage whatsoever**.
>
> Somebody holding exactly 10% of a trust is a beneficial owner. The same
> person holding exactly 10% of a company is not. One character of code apart,
> opposite answers. **Anything built to 25% under-reports beneficial owners
> against this regulator.**

That paragraph is the strongest thing you have. It is a specific, checkable,
consequential fact that the incumbents get wrong.

### 5. The decision — thirty seconds

Scroll to the bottom of the report.

*"Nothing here decided anything. Three buttons, a reason box that cannot be
left empty, and the sentence saying this goes into a permanent record that
cannot be edited afterwards, by anyone, including us."*

If you have time: try to clear the politically-exposed file as Meera and let
it refuse — **clause 5.5(b)(iii) reserves that to senior management.** Then
switch to Rohan Kapoor and do it. That is the human gate, live, in fifteen
seconds.

---

## The four questions you will get

**"Is this real or a mock-up?"**
Four million watchlist entities indexed on our own server in Mumbai. Live
news from GDELT. A hash-chained SQLite ledger with 1,489 events. The only
synthetic thing is the demo firm's own investor book, deliberately — you do
not mix invented parties into a real one, and the log is append-only so they
could never be removed.

**"How is this different from ComplyAdvantage or Sumsub?"**
They sell the check. We sell the defensible record of the decision. And none
of them knows what IFSCA clause 1.3.3 says — they are all built to FATF's 25%.

**"What does the AI actually do?"**
The eight checks contain no AI at all. They are pure functions over recorded
facts — same investor in, same findings out, today and in a year, and there
is a test that proves it. A model appears once, writing one paragraph, and a
guard destroys that paragraph if it invents a figure. A model may judge; only
recorded facts and deterministic rules may establish.

**"What is not finished?"**
A proposed field cannot yet be accepted onto the record — the reader
proposes and an officer retypes it, which is slower than it should be.
Nothing checks whether a document is genuine, tampered with or conformant to
its template; it reads what a document says and never asks whether the
document is real. No qualified person has verified the clause register — it
says so on every screen. Seven document requirements could not be sourced and are listed
rather than invented. Eleven of the nineteen clause 4.2 risk factors need a
person and cannot be read from any record. We have no design partner, no
price, and no data licence for commercial use of the watchlist.

Say that list out loud. It is more convincing than a claim of completeness,
and it is the same honesty the product applies to itself: **a check that did
not happen is never reported as a check that found nothing.**

---

## If something breaks

The demo does not depend on the internet except for the site itself. If a
run stalls, the checks report the absence honestly rather than hanging — that
is the design, and it is worth pointing at rather than apologising for.

Fall back to a party already on the book: **Your list → open any file.** The
findings, the clauses and the decision are all there without needing a run.
