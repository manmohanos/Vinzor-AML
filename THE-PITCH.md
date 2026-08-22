# The two minutes

Roughly 300 words. Read it aloud twice and it will be yours.

---

Every fund manager in GIFT City has to do anti-money-laundering checks on
every investor they take on. Today that is a compliance officer, a
spreadsheet, and Google. It takes days, and when IFSCA inspects, the firm has
to prove not just that they checked — but *what* they checked, *when*, and
*which rule* made them.

We built Vinzor. You onboard an investor by answering one question per
screen, and eight checks run: identification, documents, sanctions,
politically exposed persons, adverse media, beneficial ownership, duplicates,
and the risk factors. Fifteen seconds, and every one of them cites the IFSCA
clause it comes from — with the regulator's own sentence, the edition, and
the page.

Three things make it different.

**First — the checks contain no AI at all.** They are deterministic. The same
investor in gives the same findings out, today and in a year, and there is a
test that proves it. An inspector can re-run a file from two years ago and
get the identical answer. No LLM-based product can say that.

**Second — a check that did not happen is never reported as a check that
found nothing.** If the watchlist is unreachable, it says so. That distinction
is the difference between a clean file and a false one, and we found and fixed
that bug four separate times building this.

**Third — we implement IFSCA's actual beneficial ownership rule, which is ten
per cent, not FATF's twenty-five.** Every global vendor is built to
twenty-five. And it is four different tests — for a company it is *more than*
ten; for a trust it is *ten or more*, plus the author and the trustee at any
percentage at all. Anything built to twenty-five under-reports beneficial
owners against this regulator.

Nothing decides anything. Only an enrolled human closes a file, into an
append-only, hash-chained record that cannot be edited afterwards — by anyone,
including us.

---

# "If there's no LLM, what is it actually doing?"

Answer this precisely. It is your strongest technical moment.

## Sanctions and PEP — Elasticsearch, on our own machine

> "We run **yente**, the OpenSanctions matching engine, against an
> **Elasticsearch** index of **four million** watchlist entities, on our own
> EC2 instance in Mumbai. Nothing about a customer leaves the building —
> which matters, because this is Indian customer data.
>
> The query is not SQL and it is not a prompt. We POST a
> **FollowTheMoney** entity — the OpenSanctions wire format:
>
>     { "schema": "Person",
>       "properties": { "name": ["Vladimir Putin"],
>                       "nationality": ["ru"] } }
>
> Elasticsearch retrieves candidates on analysed name fields — phonetics,
> transliteration, aliases. yente then scores each candidate on name,
> date of birth, nationality and identifiers. We accept at **0.70**.
>
> The interesting part is that we ask **twice**. A book holds 'J. Smith';
> a sanctions list holds 'John Smith'. We measured it against forty genuinely
> listed people: the initialled form found twenty-three and missed
> seventeen. Lowering the threshold recovered none of them — at 0.40 the
> result was identical to 0.70 — because those entities were never returned
> as candidates at all. It is a recall problem in the query, not a filter
> problem. Asking again without the initial recovers all seventeen."

**That paragraph will win the technical question.** It is a measured number,
a wrong hypothesis discarded, and a fix.

## The other seven checks — pure functions over an event log

> "The whole system is event-sourced. Every fact is an append-only,
> hash-chained record — a party added, a document filed, a screening
> completed, an officer's decision. The eight checks are **pure Python
> functions that fold over that log.** No query to an outside service, no
> model, no randomness, no clock in the core — there is a test that fails the
> build if anything in the core reads the time.
>
> Ownership is a **graph walk** over declared holdings, applying IFSCA's four
> tests, with **cycle detection** — which is how it draws that loop where a
> company ends up owning itself and no human is ever reached."

## Adverse media — a live HTTP call, no model

> "**GDELT**, filtered on nine named themes for financial crime. It returns
> articles. It does not read them or judge them, and the screen says so:
> *'Nothing has read these. They are for you to read.'*
> If GDELT rate-limits us, the check records that it failed. It never returns
> an empty list that looks like good news."

## Where a model *is* used — say this before they ask

> "Four places, all narrow, and none of them decides anything.
>
> **Ask** — an officer types a question and it reads the records through a
> read-only tool interface. It can look at everything and change nothing.
>
> **The assistant on a report** — it is handed what the eight checks
> recorded and says which of them matters most and what to do next. It reads
> the findings; it does not produce them.
>
> **Reading a photographed document** — a customer sends a photo of a
> passport, not a text-layer PDF, so a vision model transcribes it. It is
> asked to transcribe and explicitly not to judge whether the document is
> genuine. Every field it reads is marked as a model's reading, and it still
> cannot widen what a kind of document is allowed to prove — we filter its
> answer afterwards, because it is not trusted to have obeyed its own
> instruction.
>
> **One summary paragraph**, with a guard that destroys the paragraph if it
> contains a figure not present in the record.
>
> The eight checks themselves contain none. The rule we hold to: **a model
> may propose or judge; only recorded facts and deterministic rules may
> establish.**"

**If asked where the photo goes:** Bedrock in Mumbai, `mistral-large-3`,
served on demand in region. Every Anthropic model in `ap-south-1` is only
reachable through a cross-region inference profile, and our code refuses
those by prefix — we use a lesser model on purpose so investor data stays
in the country.
