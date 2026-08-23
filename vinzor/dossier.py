"""Everything on one party, as a document somebody can hand over.

A Principal Officer gets asked one question by an inspector, a bank, or an
auditor: *show me everything you have on this investor.* Until now the only
answer was a screen — the party page — which is the right information and
the wrong artefact. A screen cannot be dated, cannot be signed, cannot be
carried into a meeting, and cannot be reproduced identically in eighteen
months when somebody asks what the file looked like at the time.

So this folds the log, filtered to one subject, into a document. Three
things go in it that no screen shows:

* **The decisions in the deciders' own words.** The party page says a person
  settled a file. It does not say what they concluded or why, and that
  sentence — written by a named officer on a named day — is the thing an
  inspector actually reads.
* **The evidence under each finding, with its clause.** Not "a review was
  opened" but what was found, which rule found it, and the paragraph of the
  guidelines it answers to.
* **A seal over the exact records cited.** The document names how many
  records it was built from and whether the chain over them still holds,
  which is what makes it evidence rather than an assertion.

Nothing here is computed fresh. Every sentence comes from a recorded event,
so the document produced today for a period that closed in March is the
document that would have been produced in March.

**On who may read it.** This is the one artefact in the product that is
dangerous in the wrong hands, and the danger is not the obvious one. It is
not that the file contains secrets; it is that its *existence* discloses
that a customer was scrutinised. Clause 4.1(d) forbids revealing a risk
categorisation to the customer precisely so that a customer under suspicion
is not tipped off, and every part of this document — the findings, the
screening checks, the fact that anybody looked — carries that same
disclosure. There is deliberately no redacted version, because a redacted
version would look safe to hand over and would not be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from . import readiness, risk
from .briefing import (KIND, PARTY_KINDS, _article, _counted, _date,
                       _money, _money_summary, _pct, describer,
                       item_for, qualified_name, shared_names,
                       waited_for)
from .countries import COUNTRIES
from .model import EventType, Outcome

#: What each decision meant, in the words a reader uses rather than the word
#: the record stores.
SETTLED_AS = {
    Outcome.APPROVE: "Cleared",
    Outcome.REJECT: "Stopped",
    Outcome.ESCALATE: "Passed up",
}

#: What each screening result means when it is written on a line of its own.
#: The queue says this at greater length; here it has to fit a column.
FOUND = {
    "SANCTIONS": "Possible match on a sanctions list",
    "PEP": "Possible match: may hold or be close to public office",
    "PEP_ASSOCIATE": "Possible match: may be close to someone in public office",
    "CRIMINAL": "Possible match: wanted or charged somewhere",
    "DEBARRED": "Possible match: barred from public contracts",
    "ADVERSE_MEDIA": "Adverse media reported",
}

#: What to call each recorded attribute on the page. The clause 5.4.2 items
#: are read straight out of ``readiness`` so the two cannot drift apart --
#: a document that names a field differently from the module measuring it
#: is how two screens start disagreeing about the same file. The rest are
#: named here because nothing else names them.
def _labels() -> dict:
    out: dict = {}
    for wanted in (readiness.FOR_A_PERSON, readiness.FOR_A_LEGAL_PERSON):
        for _clause, what, keys in wanted:
            for key in keys:
                out.setdefault(key, what.capitalize())
    out.update({
        "id_document_type": "Kind of identity document",
        "jurisdiction": "Jurisdiction",
        "trust_type": "Kind of trust",
        "is_discretionary": "A discretionary trust",
        "has_protector": "Has a protector",
        "is_listed": "Listed on a stock exchange",
        "is_shell": "Recorded as a shell company",
        "pep_flag": "Recorded as holding public office",
        "high_risk_jurisdiction": "Recorded as tied to a high-risk country",
    })
    return out


LABELS = _labels()


#: Attributes that answer a yes-or-no question. They arrive as 0 and 1 as
#: often as they arrive as true and false, and both spellings are unreadable
#: on a document somebody hands to a regulator.
YES_OR_NO = frozenset({
    "is_discretionary", "has_protector", "is_listed", "is_shell",
    "pep_flag", "high_risk_jurisdiction",
})

#: Attributes holding a date, which the records keep as 2005-12-17 and a
#: reader says as 17 December 2005. Named rather than sniffed: a passport
#: number is not a date however much it looks like one.
_A_DATE = frozenset({
    "dob", "date_of_birth", "incorporated_on", "id_document_expiry",
    "expires_on", "issued_on",
})

#: Attributes holding a country, which the records keep as a two-letter code.
A_COUNTRY = frozenset({
    "nationality", "country_of_residence", "country_of_incorporation",
    "jurisdiction",
})


def _said(key: str, value) -> str:
    """A recorded value as a reader would say it back.

    ``True`` on a compliance document is a word from a programming language
    wearing the authority of a finding, and ``AE`` is a country only to
    somebody who already knows which one.

    The fall-through to ``str(value)`` was quietly doing most of the work,
    because an import carries whatever the firm's spreadsheet carries and
    only a handful of keys were named here. On the live book that put
    **NATIONAL_ID** on the record page of 29 parties -- the page the product
    calls the document you would hand an inspector, with a print button on
    it -- and a date of birth as 2005-12-17 next to "First went on the record
    = 7 August 2026". The vocabularies are borrowed from the officer's own
    screen rather than copied, so the two cannot drift apart.
    """
    from .briefing import _DATE_TRAITS, _ID_DOCUMENTS, _date

    if key in YES_OR_NO:
        return ("Yes" if value in (True, 1, "1", "Y", "y", "true", "True")
                else "No")
    if key in A_COUNTRY:
        code = str(value).strip().upper()
        return COUNTRIES.get(code, str(value))
    if key in _ID_DOCUMENTS or key == "id_document_type":
        raw = str(value).strip()
        return _ID_DOCUMENTS.get(raw.upper(), raw.replace("_", " ").capitalize())
    if key in _DATE_TRAITS or key.endswith("_date") or key in _A_DATE:
        return _date(str(value))
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _label_for(key: str) -> str:
    """A name for a column nobody anticipated, rather than dropping it.

    An import can carry anything. Leaving an unnamed field out of a document
    that claims to hold everything is the worse of the two failures, so an
    unrecognised key is spelled out rather than discarded.
    """
    return LABELS.get(key) or key.replace("_", " ").strip().capitalize()


#: The sentence that governs who may see this document. Said once, at the
#: top, in the plainest words available.
CONFIDENTIAL = (
    "This document is for the firm and for a regulator. It must never be "
    "given to the party it is about, or to anyone acting for them. It "
    "records that this party was examined, what was suspected, and by whom "
    "— and clause 4.1(d) requires that a customer under examination is not "
    "tipped off. There is deliberately no shortened version that is safe to "
    "hand over, because the fact that this document exists is itself the "
    "disclosure."
)


@dataclass(frozen=True)
class Fact:
    """One recorded thing: what it is, what it says, and any qualification."""

    label: str
    value: str
    note: str = ""
    tone: str = ""


@dataclass(frozen=True)
class Entry:
    """One thing that happened, on a dated line."""

    when: str
    what: str
    who: str = ""
    #: The decider's own sentence, quoted rather than summarised. An officer
    #: is accountable for the words they wrote, not for our paraphrase.
    why: str = ""
    clause: str = ""
    tone: str = ""


@dataclass(frozen=True)
class Part:
    heading: str
    lead: str
    facts: tuple[Fact, ...] = ()
    entries: tuple[Entry, ...] = ()
    tail: str = ""


@dataclass(frozen=True)
class Dossier:
    """Everything recorded about one party, as one document."""

    title: str
    kind: str
    workspace: str
    printed: str
    confidential: str
    summary: tuple[str, ...]
    parts: tuple[Part, ...]
    back: str
    print_label: str
    #: Empty unless the party is not on the record at all, in which case it
    #: is the only thing the document says.
    refusal: str = ""
    ui: Mapping[str, Any] = field(default_factory=dict)
    #: A machine address. Never displayed.
    entity_id: str = ""
    #: Two or three sentences opening the record, written by the assistant
    #: from the sections below and checked before it is shown. Empty is a
    #: normal outcome and carries no apology: a record is complete without
    #: it, and one with a fabricated paragraph is a liability.
    opening: str = ""
    #: Why there is no opening, where one was prepared and thrown away.
    opening_withheld: str = ""


# ---------------------------------------------------------------------------
# the parts
# ---------------------------------------------------------------------------


def _who(engine, entity_id: str, events) -> Part:
    graph = engine.state.graph
    entity = graph.entities.get(entity_id)
    facts = []
    added = next((event for event in events
                  if event.event_type is EventType.ENTITY_REGISTERED), None)
    if added is not None:
        facts.append(Fact(
            label="First went on the record",
            value=_date(added.occurred_at),
            note=("Brought in from a spreadsheet." if added.actor == "import"
                  else "")))

    attributes = dict(getattr(entity, "attributes", {}) or {})
    for key in sorted(attributes):
        value = attributes[key]
        if value in (None, ""):
            continue
        facts.append(Fact(label=_label_for(key), value=_said(key, value)))

    return Part(
        heading="Who this party is",
        lead="Everything the records hold about the party itself. Each line "
             "was declared by whoever supplied it; nothing here was inferred.",
        facts=tuple(facts),
        tail=("Nothing beyond a name has ever been recorded for this party."
              if len(facts) <= 1 else ""))


def _missing(engine, entity_id: str) -> Optional[Part]:
    """What clause 5.4.2 asks for and this file does not have.

    An inspector reads the gaps before the contents, and a document that
    lists only what is present invites the reader to assume the rest was
    checked. Saying it plainly is the difference between an incomplete file
    and a misleading one.
    """
    measured = readiness.measure(engine, only=(entity_id,))
    standing = next((s for s in measured.parties
                     if s.entity_id == entity_id), None)
    if standing is None or not standing.gaps:
        return None

    facts = tuple(Fact(label=gap.what.capitalize(), value="Not on file",
                       note=f"Clause {gap.clause}.", tone="stop")
                  for gap in standing.gaps)
    return Part(
        heading="What this file is still missing",
        lead=f"Clause 5.4.2 sets out the minimum a firm must hold on a "
             f"customer of this kind. "
             f"{_counted(len(standing.gaps), 'item is', 'items are')} not "
             f"on file.",
        facts=facts,
        tail="A gap here is not a finding against the customer. It is work "
             "the firm has not finished. " + readiness.NOT_MEASURED_NOTE)


def _control(engine, entity_id: str) -> Optional[Part]:
    """Declared holdings, then what they come to once followed through.

    The declared edges and the worked-through result are kept apart on
    purpose. One is what somebody told us; the other is what our own
    arithmetic makes of it, and a document that runs them together invites
    a reader to treat a computed percentage as a declared fact.
    """
    graph = engine.state.graph
    from .briefing import _HELD_BY

    owners = list(graph.owners_of(entity_id))
    holdings = list(graph.holdings_of(entity_id))
    resolved = graph.resolve_ubo(entity_id)
    # A trust with nobody declared has no edges at all, and returning early
    # on that would drop the most important sentence on the page: that the
    # trustee and the author were never named.
    if not (owners or holdings or resolved.owners or resolved.below_threshold
            or resolved.missing_roles or resolved.cycles
            or resolved.dead_ends):
        return None

    facts = []
    for edge in owners:
        verb = _HELD_BY.get(str(edge.relation), "is connected to")
        facts.append(Fact(
            label=graph.name_of(edge.owner),
            value=(_pct(edge.percentage) if str(edge.relation) == "OWNS"
                   else "Connected"),
            note=f"{verb} this party".capitalize()))
    for edge in holdings:
        verb = _HELD_BY.get(str(edge.relation), "is connected to")
        facts.append(Fact(
            label=graph.name_of(edge.owned),
            value=(_pct(edge.percentage) if str(edge.relation) == "OWNS"
                   else "Connected"),
            note=f"this party {verb} them".capitalize()))

    entries = []

    def _reached(owner) -> str:
        paths = tuple(owner.paths or ())
        if not paths or len(paths[0]) <= 2:
            return "held directly"
        return "through " + ", ".join(graph.name_of(step)
                                      for step in paths[0][1:-1])

    for owner in resolved.owners:
        entries.append(Entry(
            when="", what=f"{owner.name} — "
                          f"{_pct(owner.effective_percentage)} in all, "
                          f"{_reached(owner)}",
            who="Worked out from the declared holdings above",
            clause=resolved.test.clause, tone="fact"))

    # Named, not dropped. Somebody sitting just under the threshold is the
    # single most useful line on this page for a reader deciding whether the
    # structure was arranged to sit under it.
    for owner in resolved.below_threshold:
        entries.append(Entry(
            when="", what=f"{owner.name} — "
                          f"{_pct(owner.effective_percentage)} in all, "
                          f"{_reached(owner)}",
            who=f"Below the {_pct(resolved.test.threshold)} threshold, so "
                f"not a beneficial owner on this test",
            clause=resolved.test.clause, tone="detail"))

    if resolved.missing_roles:
        entries.append(Entry(
            when="", what="Nobody has been named as: "
                          + ", ".join(resolved.missing_roles),
            who="The chain cannot be completed without them",
            clause=resolved.test.clause, tone="stop"))
    if resolved.cycles:
        entries.append(Entry(
            when="",
            what=f"The ownership chain loops back on itself in "
                 f"{_counted(len(resolved.cycles), 'place', 'places')}.",
            who="Followed as far as it goes and no further",
            tone="stop"))
    if resolved.dead_ends:
        entries.append(Entry(
            when="",
            what=f"The chain runs out before reaching a person in "
                 f"{_counted(len(resolved.dead_ends), 'place', 'places')}.",
            who="Whoever sits above that point has never been declared",
            tone="stop"))

    return Part(
        heading="Who owns or controls this party",
        lead="What was declared, and who that comes back to once the chain "
             "is followed through.",
        facts=tuple(facts),
        entries=tuple(entries),
        tail=(f"Beneficial ownership here is tested at "
              f"{_pct(resolved.test.threshold)}, which is the threshold "
              f"clause {resolved.test.clause} sets for this kind of "
              f"customer. It is not the same threshold for every kind."
              if entries else ""))


def _judged(engine, entity_id: str, today: str) -> Part:
    assessed = engine.state.risk.get(entity_id)
    if assessed is None:
        return Part(
            heading="How risky this party has been judged",
            lead="Nobody has categorised this party.",
            tail="Clause 4.2 requires every customer to be categorised. "
                 "Until somebody does, this line is a gap and not a low "
                 "score — the two are not the same thing.")

    facts = [
        Fact(label="Category", value=str(assessed.category).capitalize()),
        Fact(label="Set by", value=str(assessed.by)),
        Fact(label="Set on", value=_date(assessed.on)),
    ]
    due = risk.next_review(assessed.category, assessed.on)
    if due is not None:
        facts.append(Fact(label="To be looked at again", value=_date(due.on),
                          note=f"Clause {due.clause}."))

    entries = ()
    if assessed.reason:
        entries = (Entry(when=_date(assessed.on),
                         what="The reason given, in their own words",
                         who=str(assessed.by), why=str(assessed.reason)),)

    return Part(
        heading="How risky this party has been judged",
        lead="A person set this, and their name is on it. The product does "
             "not compute a category and never has.",
        facts=tuple(facts),
        entries=entries,
        tail="This categorisation and the reasons for it are confidential "
             "under clause 4.1(d).")


def _checked(engine, entity_id: str, events) -> Part:
    checks = [event for event in events
              if event.event_type is EventType.SCREENING_COMPLETED]
    if not checks:
        return Part(
            heading="What this party has been checked against",
            lead="This party has never been checked against a watchlist.",
            tail="Clause 5.9 requires screening. A party with no check is "
                 "not a party that came back clean.")

    entries = []
    for event in checks:
        payload = event.payload or {}
        kind = str(payload.get("list_type") or "")
        matched = bool(payload.get("matched"))
        entries.append(Entry(
            when=_date(event.occurred_at),
            what=(FOUND.get(kind, "Possible match found") if matched
                  else "Checked, and nothing was found"),
            who="The watchlist check",
            clause="5.9",
            tone="rule" if matched else "fact"))

    hits = sum(1 for event in checks if (event.payload or {}).get("matched"))
    said = []
    if hits:
        said.append("A possible match is not a finding of wrongdoing. It is "
                    "a name that resembles a listed name closely enough that "
                    "a person had to look.")
    # "Checked, and nothing was found" is true of the day it was written and
    # says less every day after it. The watchlist is rebuilt continuously, so
    # a check made against a list this workspace has since moved past did not
    # look at anybody added in between -- and a record that reads as a clean
    # answer about today, when it is an answer about April, is the same defect
    # this system refuses everywhere else, wearing time as a disguise.
    behind = _behind_the_newest_list(engine, checks)
    if behind:
        said.append(behind)
    return Part(
        heading="What this party has been checked against",
        lead=f"{_counted(len(checks), 'check has', 'checks have')} been run "
             f"against the watchlists.",
        entries=tuple(entries),
        tail=" ".join(said))


def _behind_the_newest_list(engine, checks) -> str:
    """Said where this party's last check predates the newest list seen.

    Compared against the newest version *this workspace* has been screened
    against, not against whatever the service holds right now: reading that
    would mean a network call to render a document, and a record that cannot
    be printed while the watchlist is unreachable is not a record. Where the
    workspace has never recorded a version at all, nothing is claimed either
    way -- an unknown is not evidence of staleness, and saying so would put a
    warning on every document in a workspace that has simply not swept yet.
    """
    from .rescreening import newest_version

    newest = newest_version(engine)
    if not newest:
        return ""
    seen = ""
    for event in checks:
        version = str(((event.payload or {}).get("basis") or {})
                      .get("list_version") or "")
        if version:
            seen = version
    if not seen:
        return ("This party's checks do not record which version of the "
                "watchlist they were made against, so whether they are "
                "current cannot be established from this record.")
    if seen == newest:
        return ""
    return ("The most recent check above was made against an older version "
            "of the watchlist than this workspace has since screened "
            "against. Anyone added to the list in between has not been "
            "checked against this party.")


def _found(engine, entity_id: str, cases, today: str) -> Part:
    """Every finding, in the words the queue already puts on a screen.

    ``Evidence.summary`` is internal record text -- it names parties by
    reference and rules by identifier -- so it is never read here. The queue
    renders the same Case through ``item_for``, which is written for a person
    and swept for jargon by test, and reading it twice from one place is what
    keeps a document and a screen from disagreeing about the same file.
    """
    describe = describer(engine.state.graph)
    entries = []
    counts: dict = {}
    for case in cases:
        label = KIND.get(case.case_type, "Review")
        counts[label] = counts.get(label, 0) + 1
        item = item_for(case, describe, f"{label} {counts[label]}", today)
        clause = ""
        for evidence in case.evidence:
            for citation in evidence.citations or ():
                clause = str(citation.get("clause") or "")
                break
            if clause:
                break
        entries.append(Entry(
            when=_date(case.opened_at), what=item.headline,
            who=f"Opened by the rules as {_article(label.lower())} "
                f"{label.lower()}",
            clause=clause, tone="rule"))
        for because in item.because:
            entries.append(Entry(when="", what=because, tone="detail"))

    if not entries:
        return Part(
            heading="What the rules found",
            lead="No rule has ever opened a file on this party.")

    return Part(
        heading="What the rules found",
        lead=f"The rules opened {_counted(len(cases), 'file', 'files')} on "
             f"this party, oldest first. Each was written down as a fact at "
             f"the time and is never rewritten when a rule later changes.",
        entries=tuple(entries))


def _decided(engine, entity_id: str, cases) -> Part:
    # (sortable date, entry). ``Entry.when`` is written the way a person
    # reads it -- "29 April 2021" -- and ordering on that text would put
    # April before November before December, alphabetically. The date the
    # record actually holds does the sorting.
    dated = []
    for case in cases:
        label = KIND.get(case.case_type, "Review")
        for step in case.escalations:
            on = str(step.get("on", ""))[:10]
            dated.append((on, Entry(
                when=_date(on),
                what=f"{label} — passed up for a more senior decision",
                who=str(step.get("by", "")),
                why=str(step.get("why", "")),
                tone="decision")))
        decision = case.decision
        if decision is None:
            continue
        on = str(decision.decided_at)[:10]
        dated.append((on, Entry(
            when=_date(on),
            what=f"{label} — {SETTLED_AS.get(decision.outcome, 'Settled')}",
            who=str(decision.actor),
            why=str(decision.rationale or ""),
            tone="decision")))

    dated.sort(key=lambda pair: pair[0])
    entries = [entry for _on, entry in dated]
    if not entries:
        return Part(
            heading="What people decided",
            lead="Nobody has settled anything on this party yet.")

    return Part(
        heading="What people decided",
        lead=f"{_counted(len(entries), 'decision', 'decisions')}, with the "
             f"name of whoever made "
             f"{'it' if len(entries) == 1 else 'each one'} and the reason "
             f"they wrote at the time. The wording is theirs and has not "
             f"been tidied.",
        entries=tuple(entries),
        tail="No decision here can be edited or removed. A conclusion "
             "reached in March stays as it was reached in March, even after "
             "the rules change.")


def _movements(engine, entity_id: str, events) -> Optional[Part]:
    movements = [event for event in events
                 if event.event_type in (EventType.COMMITMENT_MADE,
                                         EventType.PAYMENT_RECEIVED)]
    if not movements:
        return None

    entries = []
    for event in movements:
        payload = event.payload or {}
        amount = _money(payload.get("amount"), payload.get("currency"))
        if event.event_type is EventType.COMMITMENT_MADE:
            entries.append(Entry(when=_date(event.occurred_at),
                                 what=f"Committed {amount}", tone="fact"))
            continue
        payer = str(payload.get("payer") or "")
        note = "Raised a query" if payload.get("anomaly") else \
            "Matched what was called"
        who = ""
        if payer and payer != entity_id:
            who = f"sent by {engine.state.graph.name_of(payer)}"
        entries.append(Entry(when=_date(event.occurred_at),
                             what=f"Received {amount} — {note}",
                             who=who,
                             tone="rule" if payload.get("anomaly") else "fact"))

    return Part(
        heading="Money recorded against this party",
        lead=_money_summary(events) or "Everything recorded, in date order.",
        entries=tuple(entries),
        tail="Totals are never added across currencies. Doing so would need "
             "a rate this system does not hold.")


def _open(engine, entity_id: str, cases, today: str) -> Optional[Part]:
    still = [case for case in cases if case.is_open]
    if not still:
        return None

    facts = []
    for case in still:
        label = KIND.get(case.case_type, "Review")
        waited = waited_for(case, today)
        facts.append(Fact(
            label=label,
            value="Awaiting a decision",
            note=(waited.capitalize() if waited else "Opened recently"),
            tone="stop"))

    return Part(
        heading="What is still open",
        lead=f"{_counted(len(still), 'file has', 'files have')} not been "
             f"settled. This document does not close them.",
        facts=tuple(facts))


def _seal(engine, entity_id: str, events) -> Part:
    intact, why = engine.verify()
    try:
        engine.log.mark("")
    except Exception:
        pass
    count, head = engine.log.head()
    facts = (
        Fact(label="Records this document was built from",
             value=f"{len(events):,}"),
        Fact(label="Records in the whole log", value=f"{len(engine.log):,}"),
        # See reporting.py: the chain cannot prove its own tail is intact,
        # so the fingerprint travels out on paper where nobody holding the
        # database can reach it.
        Fact(label="Fingerprint of the last record", value=head[:16],
             note=f"At {count:,} records."),
        Fact(label="The chain",
             value="Verifies" if intact else "Broken",
             note=("Every record still seals to the one before it."
                   if intact else str(why)),
             tone="" if intact else "stop"),
    )
    return Part(
        heading="The record behind this document",
        lead="Every line above was read from these records. Nothing in this "
             "document was typed in by hand.",
        facts=facts,
        tail="Each record is sealed to the one before it, so a line in this "
             "document cannot be changed without breaking the chain that "
             "proves it. Anyone can re-run that check against the same log "
             "and get the same answer.")


# ---------------------------------------------------------------------------
# the document
# ---------------------------------------------------------------------------


def dossier(engine, entity_id: str, today: str,
            workspace: str = "", transport=None,
            record: bool = True) -> Dossier:
    """Everything recorded about one party, as one document.

    ``today`` is supplied rather than read from a clock, so the document is
    reproducible: the same log and the same date give the same document,
    which is the property that makes it worth handing to anybody.
    """
    today = str(today)[:10]
    graph = engine.state.graph
    entity = graph.entities.get(entity_id)

    if entity is None:
        return Dossier(
            title="No such party",
            kind="", workspace=workspace, printed=f"Printed {_date(today)}.",
            confidential="", summary=(), parts=(),
            back="Back", print_label="Print",
            refusal="Nothing on this workspace has that reference. Look the "
                    "party up by name and open the record from there.",
            entity_id=entity_id)

    events = sorted(
        (event for event in engine.log if event.subject == entity_id),
        key=lambda event: (event.occurred_at, event.seq))
    cases = sorted(
        (case for case in engine.state.casebook.cases.values()
         if case.subject == entity_id),
        key=lambda case: case.opened_at)

    parts = [_who(engine, entity_id, events)]
    missing = _missing(engine, entity_id)
    if missing:
        parts.append(missing)
    control = _control(engine, entity_id)
    if control:
        parts.append(control)
    parts.append(_judged(engine, entity_id, today))
    parts.append(_checked(engine, entity_id, events))
    parts.append(_found(engine, entity_id, cases, today))
    parts.append(_decided(engine, entity_id, cases))
    movements = _movements(engine, entity_id, events)
    if movements:
        parts.append(movements)
    still_open = _open(engine, entity_id, cases, today)
    if still_open:
        parts.append(still_open)
    parts.append(_seal(engine, entity_id, events))

    name = qualified_name(graph, entity_id, shared_names(graph))
    open_now = sum(1 for case in cases if case.is_open)
    settled = sum(1 for case in cases if not case.is_open)

    summary = [
        f"Everything recorded about {name} on this workspace, read from the "
        f"permanent log and nothing else.",
    ]
    if cases:
        summary.append(
            f"The rules have opened {_counted(len(cases), 'file', 'files')} "
            f"on this party: {settled} settled, {open_now} still open.")
    else:
        summary.append("No rule has ever opened a file on this party.")

    # Written last, from the sections rather than from the projections, so
    # the assistant is given exactly what the reader is given. A summary
    # drawn from richer material than the page shows would describe a
    # document nobody else can see.
    #
    # Written once and read thereafter. It used to be regenerated on every
    # page view and every print, and recorded nowhere: three consecutive
    # views of an identical record produced three materially different
    # paragraphs, one of which printed the raw address, email, date of birth
    # and identifying number that the other two summarised. Neither the
    # paragraph nor the ``withheld`` sentence reached the log, while every
    # withheld answer at the ask boundary is recorded -- on the stated
    # ground that a guard which fires silently is a guard nobody can audit.
    #
    # ``record=False`` keeps the old behaviour for a caller that only wants
    # to look, and every test that builds a dossier by hand.
    opening = ""
    withheld = ""
    from .narrative import opening_for, record_opening, recorded_opening

    already = recorded_opening(engine, entity_id)
    if already is not None:
        opening, withheld = already.summary, already.withheld
    elif transport is not None:
        draft = Dossier(
            title=f"The record on {name}",
            kind=PARTY_KINDS.get(str(graph.kind_of(entity_id) or ""), ""),
            workspace=workspace, printed="", confidential="",
            summary=(), parts=tuple(parts), back="", print_label="")
        written = opening_for(draft, transport)
        opening, withheld = written.summary, written.withheld
        if record and (opening or withheld):
            record_opening(engine, entity_id, written, written_at=today,
                           model=str(getattr(transport, "model", "") or ""),
                           region=str(getattr(transport, "region", "") or ""))

    return Dossier(
        opening=opening,
        opening_withheld=withheld,
        title=f"The record on {name}",
        kind=PARTY_KINDS.get(str(graph.kind_of(entity_id) or ""), ""),
        workspace=workspace,
        printed=f"Printed {_date(today)}.",
        confidential=CONFIDENTIAL,
        summary=tuple(summary),
        parts=tuple(parts),
        back="Back to the party",
        print_label="Print this record",
        entity_id=entity_id)
