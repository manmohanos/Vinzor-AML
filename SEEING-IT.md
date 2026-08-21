# Seeing it for yourself

Everything below is running on your own machine. Nothing leaves it.

## Starting it

Two things run. Both are already started — this is only for next time, or if
something stops.

The watchlist search (nearly 4 million sanctioned, politically exposed and wanted
entities, held locally):

```bash
cd "C:\Users\manmo\Desktop\Vinzor Projects\August\01\vinzor-core" && powershell -File selfhost/yente.ps1 start
```

The application itself:

```bash
cd "C:\Users\manmo\Desktop\Vinzor Projects\August\01\vinzor-core" && python -m vinzor serve --workspace live.db --port 8000
```

Then open **http://127.0.0.1:8000** in your browser. Leave that second window
open while you use it — closing it stops the site.

The first screen now asks for a name **and a password**. They are already set
on this workspace:

| Sign in as    | Password                 | Their job          | Why you would pick them                     |
| ------------- | ------------------------ | ------------------ | ------------------------------------------- |
| Meera Nair    | `morning queue august`   | AML Officer        | Does the day-to-day work. Start here.       |
| Aarav Sharma  | `second pair of eyes`    | Compliance Officer | Second pair of eyes on escalated files.     |
| Rohan Kapoor  | `senior sign off please` | Senior Management  | The only one who can clear a PEP.           |
| Priya Rao     | `read only access here`  | Read-only          | Can look at everything, can decide nothing. |

These are demonstration passwords written down in a text file, which is not
how you would run this for real. Change one with:

```bash
cd "C:\Users\manmo\Desktop\Vinzor Projects\August\01\vinzor-core" && python -m vinzor password --name "Meera Nair" --workspace live.db
```

**What signing in actually fixed, which was not the missing password box.**
Every write used to take the acting person's name *out of the request*.
Anyone who could reach the port could send a body saying they were Rohan
Kapoor and act as Senior Management — including clearing the
politically-exposed files only Senior Management may clear. A login page in
front of that would have been decoration. What changed is that the server
works out who you are from the session and ignores what the request claims.

Two doors, and which you get is a property of the workspace rather than a
setting. Where **nobody** has a password it still works the old way — pick a
name, no password — and says so in a red box, because that is a
demonstration and not a compliance record. The moment anybody is given a
password, everybody needs one. There is no per-person exemption: a system
where some people need a password is a system where the rest are the way in.

The session cookie is `HttpOnly` (no script on the page can read it) and
`SameSite=Strict` (no other site can cause a decision in your name). Behind
TLS it would also need `Secure`, which is not set here only because this
serves plain HTTP on loopback — the startup message says so.
------------- | ------------------ | ------------------------------------------ |
| Meera Nair    | AML Officer        | Does the day-to-day work. Start here.      |
| Aarav Sharma  | Compliance Officer | Second pair of eyes on escalated files.    |
| Rohan Kapoor  | Senior Management  | The only one who can clear a PEP.          |
| Priya Rao     | Read-only          | Can look at everything, can decide nothing.|

---

## Before you start: three of these show screens the product can no longer open

On 21 August 2026 nine of the ten payment rules were removed. Sections 1, 2
and part of 3 below walk through queue groups those rules produced, and the
product cannot produce them again.

**You will still see them.** `live.db` holds the findings that were recorded
when those rules ran, and this system records findings as facts rather than
recomputing them when somebody opens a page — so a case opened under the old
rulepack stays exactly as it was written, permanently, and the walkthrough
below is accurate about what is on that screen. It is a record of what was
found, not a claim about what would be found today. The rulepack stamped on
each of those cases is `2026-08-12.1`; anything opened since says
`2026-08-21.1`, and that difference is how the two are told apart.

Start a fresh workspace and load the demonstration data and the queue is 56
files rather than 206, of which 8 are payments — every one a payer named on a
sanctions list. What each section can and cannot still show is said at the
end of that section.

## The thirteen things worth looking at

### 1. One sender paying several investors

**Sign in as Meera Nair.** On the main queue, look for:

> *1 payment came from a sender who is funding several investors*

Open it. It names Tobias Lindqvist, and says the same sender has paid three
different investors on this book. Underneath it, a second group:

> *1 payment went to an investor funded from several accounts*

which names Priya Raghavan, funded from three different accounts.

**Why this one matters more than the rest.** We measured every rule we had
against twenty thousand real alerts a Danish bank's analysts had already
judged. Every rule that looked only at amounts and timing — the round number,
the payment just under a threshold, the burst of small ones — scored a lift of
exactly 1.00. That means no discriminating power at all: those rules flagged
the bad cases at precisely the rate they flagged everything. This is not a
defect we introduced; it is the published finding for the whole category.
Rules that look at *who paid whom* score two to three times better in the
literature. These two are that kind of rule, and they are the only two we have
that are.

**Both rules were removed on 21 August 2026.** The measurement above is the
reason given for removing them, which is the opposite of the reason they were
written — they were written *because* the amount-and-timing rules scored 1.00,
and they are the two that scored better. The files described here are still on
`live.db` and will still open. Nothing on a new book will produce another one.

### 2. Money that went out and came back

Two more groups on the same queue:

> *1 payment came back to the investor who sent it out*
>
> *1 payment was passed along a chain before arriving*

Open the first. Anand Bhat paid Kesari Holdings, Kesari paid Blue Harbour, and
Blue Harbour paid Anand Bhat. The money did a lap. Nothing was bought and
nothing was settled — the only thing that changed is the history the money now
carries, which is usually the entire point.

The second follows a chain of five parties, each passing it on.

**Why these two exist.** I planted the seven laundering shapes the research
literature names — fan-out, fan-in, ring, bipartite, layering, gather-scatter,
scatter-gather — and measured which ones we could see. Five. The two we
couldn't were the ring and the chain, and both for the same reason: we recorded
*who paid whom* but nothing about *when*, so we could ask "did this come from an
odd place" but never "did it come back". Now we follow the money six steps.

**The hard part was not finding rings — it was not finding them everywhere.**
The first version opened a critical finding on a *refund*: A pays B, B pays A
back, money has technically returned to where it started. Same for any two firms
with a running account. A round trip now has to pass through somebody else, and
two parties who pay each other directly are taken at their word.

Six steps is a stated limit, not a hidden one. A ring wider than six is not
reported — rather than reported as absent.

**Both of these rules were removed on 21 August 2026, and with them the code
that followed money more than one step.** Nothing in the product now traces a
payment past the two parties on it. Money that leaves an investor and comes
back through other hands, and money passed along a chain, open no file and
are not looked for. The two cases on `live.db` are still there and still
open; they are the last two of their kind.

### 3. One person, on the book twice

On the same queue:

> *1 party may already be on the book under another record*

Open it. **Rajesh Kumar Sharma** and **R K Sharma** share a permanent account
number, a date of birth and an email address, under two different folios.

**Why this is here at all.** I built a lab that takes a shape we *do* detect,
then does the same thing the way somebody avoiding detection would, and asks
what the evasion cost. Seven of eight worked, four of them for free. The
cheapest was this one: three senders funding one investor opens a file, but
enter that investor twice and the same three payments land on two records,
neither reaching a threshold, and nothing is said. Price of that evasion: one
extra line on a spreadsheet.

**That lab now has one row in it.** Every payment rule it attacked was
removed on 21 August 2026, and the trials went with them; what is left is one
trial against the one rule remaining, and it reads EVADED. The
duplicate-record work described in the rest of this section is untouched and
still does everything below — but the reason it was built, that counting
rules are defeated by splitting one party into two records, is now a reason
about rules the product no longer has.

And mostly it isn't evasion. Registrars export a customer under two folios,
investors subscribe through two vehicles, people marry and change surnames.
Nobody was hiding anything, and every counting rule is fooled just the same.

**Nothing is merged for you, deliberately.** A wrong merge in a log with no
undo puts two people's payments, screenings and decisions on one record, and
nothing afterwards can unpick whose was whose. So the file says what agrees,
what disagrees, and what follows if they are one party — that everything this
product counts is being counted twice.

**What it will not find.** Somebody determined enough to use a second identity
that shares nothing — different name, different tax number, different birthday
— is invisible to this, and to every product, without evidence from outside
the book. That row is in the lab too, marked EVADED, rather than left out to
make the numbers look better.

### 4. A letter from the regulator nobody answered

At the top of Meera's screen, above every file: **Letters from a regulator
waiting for an answer** — three of them, with a clock on each.

> IFSCA — 19 days past the date they set
>
> FIU-IND — 16 days left
>
> IFSCA — no date was set, so nothing here can tell you when it is late

The overdue one also has a file on the queue, and it is the most severe thing
this product opens.

**Why this and not something more interesting.** Scored against IFSCA's 25
published enforcement actions, this was the ground with the most orders
against it and *nothing built* — three of twenty-five. It is also the quietest
failure in compliance: no transaction happens, no rule breaks at the moment of
breach, the letter just sits. By the time anyone notices, the breach is the
silence, and it is already months old.

**Three choices worth seeing.** Nothing is stored as "overdue" — the thing
that would have to set that flag is exactly what nobody does when a letter is
being ignored, so lateness is worked out from the dates every time. A letter
with **no date** is not given one; inventing a deadline would put a date on a
compliance record the regulator never wrote. And an open letter reaches the
screen *before* it is late, as a panel rather than a file, because a deadline
in three days is work somebody has to do, not a decision anybody has to make.

To see them, or add your own:

```bash
cd "C:\Users\manmo\Desktop\Vinzor Projects\August\01\vinzor-core" && python -m vinzor notice --list --workspace live.db
```

**What it will not save you from.** Karvy Broking lost its registration partly
this way — and its show cause notice was served by *affixture*, because post
and e-mail both failed. Somebody still has to put the letter in. A firm that
has stopped opening its post is not a firm any of this reaches, and the
regulatory page says "partly covered" rather than showing a green tick.

### 5. What the facts actually rest on

**"Look up a party"**, search *Rajesh Kumar Sharma*, and open him. Below the
traits is a new panel: **The papers behind these facts**. It shows one PAN
card, what it evidences, who filed it and when — and then the line that
matters:

> 2 things on this record are held but not evidenced: a nationality and
> contact details.

**Why this and not document reading.** The obvious build here is scanning and
a model that fills the record in from a photograph. It is the wrong thing to
build first. Every fact on every party in this workspace arrived in a
spreadsheet column — ask how the firm knows an investor's date of birth and
the honest answer is *a column said so*, which is not evidence of anything.
Clause 5.4.2 asks a firm to **hold** identification data; clause 5.4.5 asks it
to **verify** identity from reliable, independent sources. Two different
obligations, and until now they looked identical on every screen.

A machine-read field written onto a compliance record with nothing saying
where it came from is exactly the failure this product exists to prevent. And
most Indian KYC packs are photographs of paper, so a reader would be
confidently wrong on the documents that matter most. When extraction does come
it will feed *suggestions* into this structure, the way assisted review already
suggests rather than decides.

**Three things you can try.** File a document:

```bash
cd "C:\Users\manmo\Desktop\Vinzor Projects\August\01\vinzor-core" && python -m vinzor document --kinds
```

Try to promote one past what it is — a utility bill said to evidence a
nationality is refused, because a document may be said to support less than
its kind allows and never more. Try filing something that is not a document at
all; it is refused at the door rather than stored as somebody's evidence of
identity.

**And the one nobody set out to build.** On the queue:

> *1 document is on file for more than one party*

The same passport scan is filed against both Anand Bhat and Lakshmi Iyer —
byte for byte the same file. The same scan cannot be evidence of two people:
either one record has somebody else's document attached, or one identity is
being used twice, and the file says so without assuming which. That check was
free, because the fingerprint was already there to notice a re-upload.

### 6. A spreadsheet from any institution

**Click "Import a spreadsheet"** in the top bar, and drop in
`examples/payments-shared-sender.csv` from the project folder.

Before anything is written, you get a page listing every column it recognised
and what it decided each one means. Nothing lands until you confirm. That page
is the whole design: a column called "Country" could be nationality, residence
or place of incorporation, and quietly picking one would put a fact on a
compliance record that nobody actually asserted. Where it cannot tell, it
refuses the file and says why, rather than guessing.

Try breaking it. Rename a column to something it will not know, or give it two
columns that both claim to be the name. It should tell you rather than assume.

### 7. How risky a customer is, and who said so

**Click "Look up a party"**, search *Crest Settlor*, and open the **United Arab
Emirates** one.

Halfway down is *How risky this customer is*. It shows:

- **Medium risk, set by Meera Nair on 19 August 2026**, with her reason in her
  own words. The category is never computed. A person sets it and signs it.
- The factors from **clause 4.2** it could check on its own — 7 of the 19.
- **12 of the 19 have not been answered by anyone**, said plainly, because a
  blank that looks like a "no" is how a book quietly rots.
- **Due to be looked at again on 19 August 2029** — clause 5.11 refreshes
  medium risk every three years, counted from the day it was set.
- A note that the categorisation is confidential under clause 4.1(d), because
  telling a customer they are under scrutiny is tipping off.

You can set a category yourself on any party. The control is on that same
panel.

### 8. Files it refuses to let you clear

**Still as Meera Nair**, find a file in the group *parties may hold or be close
to public office*. Open it, choose **Clear**, write a reason, and record it.

It refuses:

> Clearing a politically exposed person is senior management's to give —
> clause 5.5(b)(iii). You can stop this one, or pass it up to somebody who can
> approve it.

Nothing is written. Now escalate it instead, then **switch to Rohan Kapoor**
(top right) and clear it from his queue. That is the same file, the same
evidence, and two names on the record.

One file — Dev Kumar — is already sitting escalated in Rohan's queue, if you
want to see the receiving end first.

### 9. Everything on one investor, as one document

**"Look up a party"**, search any name, open them, then click **The full
record** at the top.

This is the file you hand an inspector when they ask *show me everything you
have on this investor*. It is built to be printed — there is a print button at
the bottom — and it holds four things no screen shows:

- **The decisions in the deciders' own words**, quoted rather than
  summarised. An officer is accountable for the sentence they wrote, not for
  our paraphrase of it.
- **Each finding with the clause it answers to.**
- **The ownership chain followed through**, including the awkward parts: who
  sits *just below* the beneficial-ownership threshold, where the chain loops
  back on itself, and where it runs out before reaching a person.
- **A seal**: how many records the document was built from, and whether the
  chain over them still verifies.

**Read the box at the top before anything else.** This is the one thing in the
product that is dangerous in the wrong hands, and the danger is not the
obvious one. The file does not contain secrets — it discloses that a customer
was *examined*, and clause 4.1(d) exists precisely to stop a customer under
examination being tipped off. There is deliberately no shortened version,
because a shortened version would look safe to hand over and would not be.

Try **Dev Kumar** to see a real decision quoted, or the **Crest Settlor Trust
(United Arab Emirates)** to see the ownership section report that nobody has
ever been named as its trustee or its author.

### 10. The money, and what was said about it

On the queue, at the top:

> **This firm is below the capital its licence requires**

USD 385,000 against a minimum of USD 500,000. This is what cost an IFSC
aircraft lessor its registration — capital never infused — and it is the
easiest obligation in the whole product to stop noticing, because nothing
about it moves.

**Read the third paragraph of that file.** It says the figure has not been
checked against the regulations. It came from two law-firm readings that
agree with each other and with nothing primary — and this project has already
measured what secondary sources on IFSCA are worth: when the twenty-one
clauses elsewhere were finally checked against IFSCA's own text, **twelve had
a real problem**. So the number is offered rather than asserted, and somebody
accountable can confirm the minimum that actually applies to you. Until then
the caveat travels with every finding that used it.

```bash
cd "C:\Users\manmo\Desktop\Vinzor Projects\August\01\vinzor-core" && python -m vinzor capital --workspace live.db
```

**Then click "Where you stand with IFSCA"** and scroll past the capital
panel to *What the last return claimed*:

> how many investors — reported 220, records show 93
>
> capital received — reported USD 44,000,000, records show USD 5,477,875,418

**Notice what did not happen: neither of those opened a file.** That restraint
is the design. A reported figure does not have to equal anything computed from
the book — capital is called in tranches, values move, a fund can properly be
worth more or less than was promised to it. A rule that fired on the
difference would fire every quarter of every firm's life and be switched off
by March. So the difference is *shown*, and explaining it is the officer's job.

A file opens only when the records hold **nothing at all** for a claimed
figure. That is not a difference of degree — it is a number from nowhere, and
it is the nearest thing in this data to what cost Prowess Insurance Brokers
its authorisation: reinsurance income recorded as risk management fees.

### 11. What you could hand a regulator tomorrow

**Click "What you can show".**

Scroll to **Whether the book could be handed over**. It currently reads:

- Parties on the record: **212**
- Complete enough to hand over: **0**
- Short of something the guidelines require: **212**

Then it breaks down what is missing, item by item, against **clause 5.4.2** —
120 parties with no residential address, 84 with no identifying number, and so
on. This is not a score we invented. It is the regulator's own minimum list.

Zero out of 212 is the honest answer for a book of synthetic test data. On a
real book it is the number that tells you how far you are from an inspection
going well.

Above it, **How long files have been waiting** — 88 files older than three
months. Ageing is what an inspector asks about first.

### 12. Where the sanctions data comes from

**Click "Watchlist screening"** and search any name.

It is searching a copy of the OpenSanctions default collection sitting on this
machine — **4,128,278 entities**, covering UN, EU, UK, US OFAC, and the
politically-exposed and wanted-person datasets. No name you type leaves your
machine. For a firm that has not signed a data agreement yet, that is the
difference between being able to test and not.

A match tells you which kind of list it is on — sanctions, public office, close
associate of someone in public office, wanted or charged, or debarred — in
those words, not in list codes.

**What we measured.** Against 455,219 pairs that OpenSanctions' own analysts
had judged same-or-different, our name matching scores **90.7% F1**. The
published figure for their full rule-based matcher — which reads birth dates,
nationalities, passport numbers, addresses, up to 132 fields — is 91.33%. We
are within a point of it while reading only the name.

The more useful finding was the opposite of what we expected: **every extra
field we tried using as a veto made matching worse.** Ruling out a match on a
conflicting birth date cost recall. On nationality, more. On identity
documents, most of all. But a *matching* identity document, on its own,
scored **97.1% precision**. So the product treats a document that agrees as
corroboration and never treats one that disagrees as grounds to dismiss.

### 13. The record behind all of it

At the bottom of "What you can show": **1,511 records in the permanent log**,
and **The chain: Verifies**.

Every screen in the product is computed from that log and nothing else. Each
record is sealed against the one before it, so a record cannot be changed or
removed without the chain failing. There is no edit button anywhere, by
design — a decision made in March stays as it was made in March, even after
the rules change in June.

---

## Two things you cannot see, and why

**A document corroborating a match.** The code is in and tested, but this
workspace is synthetic — invented parties do not share passport numbers with
real listed entities, so no example exists to look at. Producing one would
mean writing a fake screening record, which is exactly the kind of thing this
product exists to prevent. You will see it on the first real book.

**Adverse media.** The queue says *There is adverse media about 8 parties*.
That comes from OpenSanctions' own datasets, not a news feed. A real adverse
media feed is a purchase decision, not a build one.

---

## If something stops working

Nothing here can corrupt data — the log only ever gains records. If a page
looks stale, reload it. If it looks stale after a reload, the server is
holding old code: stop that window and start it again with the command above.
