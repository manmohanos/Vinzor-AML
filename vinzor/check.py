"""One check on one party, told step by step as it actually happened.

The queue answers "what needs me" and a file answers "why". Neither shows the
officer the check *happening* -- the question put to the watchlist, what came
back, how the two records compare, what the assistant made of it -- and that
gap is what makes screening feel like a verdict handed down rather than work
they can stand behind.

Every step below is real. The demonstration systems this competes with show a
"thinking" timeline whose entries all carry the same timestamp, because the
narration is written after the fact and replayed as theatre. Here the timeline
*is* the work: the query shown is the query sent, the candidates shown are the
candidates returned (including the ones that did not qualify -- refusing to
show near-misses would make every clean result look effortless), the elapsed
times are measured, and every event named at the end is on the hash-chained
log with a sequence number.

Two rules carry over from everywhere else and matter most here.

The check ends with a handoff, never a decision. A clean result says the
record now exists; a match says a file is open and names it. The buttons that
settle a file live on the file, behind the same human gate as always -- this
view adds no second path to a decision, because a second path is a second
place to get the gate wrong.

The assistant's reading, where one is prepared, is one step among several and
is labelled as a suggestion. It arrives through the existing drafting
boundary -- same guard against invented figures, same DRAFT_PREPARED record --
so nothing about putting it on this screen makes it more authoritative than
it was on the file.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .briefing import (FileRow, Suggestion, TONE, TRAITS_CAVEAT, KIND, _date,
                       _plural, _traits, item_for, describer, side_by_side,
                       suggestion_for)
from .compare import Comparison, compare
from .countries import name_of as country_name
from .screening import (ScreeningUnavailable, WatchlistClient,
                        leaves_this_machine, screen)

#: Watchlist dataset codes, as a person would name them. Only the lists that
#: actually appear in the index this product ships against; anything unlisted
#: falls back to the code spelled as words, which is ugly and honest.
LIST_NAMES: Mapping[str, str] = {
    "us_ofac_sdn": "the US Treasury sanctions list",
    "us_ofac_cons": "the US Treasury consolidated list",
    "eu_fsf": "the EU financial sanctions list",
    "eu_journal_sanctions": "the EU Official Journal sanctions",
    "un_sc_sanctions": "the UN Security Council list",
    "gb_hmt_sanctions": "the UK Treasury sanctions list",
    "ch_seco_sanctions": "the Swiss SECO sanctions list",
    "nz_russia_sanctions": "the New Zealand Russia sanctions",
    "ua_nsdc_sanctions": "the Ukrainian sanctions list",
    "ua_sfms_blacklist": "the Ukrainian financial monitoring list",
    "ru_mfa_sanctions": "the Russian foreign ministry sanctions list",
    "ru_acf_bribetakers": "the Anti-Corruption Foundation bribetakers list",
    "peps": "a register of politically exposed persons",
    "wd_peps": "a register of politically exposed persons",
}


def list_name(code: str) -> str:
    return LIST_NAMES.get(code, f"the {code.replace('_', ' ')} list")


@dataclass(frozen=True)
class Fact:
    """One label and value inside a step."""

    label: str
    value: str


@dataclass(frozen=True)
class Candidate:
    """One name the index offered, whether or not it qualified."""

    name: str
    closeness: str
    standing: str
    tone: str


@dataclass(frozen=True)
class Step:
    """One thing that happened, in the order it happened."""

    #: Machine hint for the marker. Never shown as text.
    kind: str
    title: str
    body: tuple
    facts: tuple = ()
    candidates: tuple = ()
    side_by_side: tuple = ()
    ours_label: str = ""
    theirs_label: str = ""
    suggestion: Optional[Suggestion] = None
    took: str = ""


@dataclass(frozen=True)
class Investigation:
    """The whole check, for one reader, in one piece."""

    who: str
    heading: str
    steps: tuple
    outcome: str
    verdict: str
    explanation: tuple
    next_heading: str
    files: tuple
    tone: str
    back: str
    #: A machine address, like ``Party.entity_id``. Never displayed.
    entity_id: str = ""


def _took(seconds: float) -> str:
    if seconds < 0.95:
        return f"took {seconds:.1f} seconds"
    return f"took {seconds:.0f} {_plural(round(seconds), 'second')}"


def _closeness(score: float) -> str:
    return f"{score:.0%} alike"


def run_check(engine, entity_id: str, *, client: WatchlistClient,
              today: str, drafter=None) -> Investigation:
    """Check one party against the watchlists, and narrate only what happened.

    Writes exactly what ``screen()`` has always written -- the screening
    record, any files the rules open, and any draft the assistant prepares.
    The narration is assembled from those facts, never alongside them.
    """
    graph = engine.state.graph
    entity = graph.entities.get(entity_id)
    if entity is None:
        raise KeyError(f"nothing is known about {entity_id!r}")
    who = graph.name_of(entity_id)
    describe = describer(graph)
    #: Where the log stood before this check wrote anything, so the sentence
    #: at the end counts what was actually appended.
    started_with = len(engine.log)
    steps: list = []

    # -- what we hold -------------------------------------------------------
    traits = _traits(entity)
    steps.append(Step(
        kind="record",
        title="The record this firm holds",
        body=((TRAITS_CAVEAT,) if traits else
              ("Nothing beyond a name has been recorded for this party, so a "
               "name is all the lists can be asked about.",)),
        facts=tuple(Fact(label=t.label, value=t.value) for t in traits),
    ))

    # -- the question, asked ------------------------------------------------
    started = time.perf_counter()
    try:
        results = screen(engine, entity_id, screened_at=today, client=client)
    except ScreeningUnavailable as problem:
        steps.append(Step(
            kind="asked", title="The lists could not be reached",
            body=(str(problem),),
        ))
        return Investigation(
            who=who, heading=f"Checking {who} against the watchlists",
            steps=tuple(steps), outcome="not performed",
            verdict="This check was not performed.",
            explanation=("Nothing was written to the record, so nothing "
                         "claims a check happened when it did not. Try again "
                         "once the screening service is reachable.",),
            next_heading="", files=(), tone="stop",
            back=f"Back to {who}", entity_id=entity_id,
        )
    elapsed = time.perf_counter() - started

    first = results[0].event.payload if results else {}
    basis = first.get("basis") or {}
    query = basis.get("query") or {}
    properties = query.get("properties") or {}
    asked_facts = [Fact(label="The name asked about",
                        value="; ".join(properties.get("name") or [who]))]
    for key, label in (("nationality", "Nationality given"),
                       ("jurisdiction", "Jurisdiction given")):
        if properties.get(key):
            # The wire carries ISO codes; the reader gets countries. "CA" on
            # a screen is a small leak the jargon sweep cannot catch, because
            # two letters match no pattern -- only an eye catches it.
            asked_facts.append(Fact(label=label, value="; ".join(
                country_name(value) for value in properties[key])))
    threshold = basis.get("threshold")
    if isinstance(threshold, (int, float)):
        asked_facts.append(Fact(
            label="The bar for a possible match",
            value=f"names {_closeness(float(threshold))} or more"))
    where_body = ("The question stayed on this machine: the index is "
                  "self-hosted, and no name left it.",)
    service = str(basis.get("service") or "")
    if service and leaves_this_machine(service):
        where_body = (f"The question was sent to an outside service, so this "
                      f"party's name left this machine.",)
    asked_twice = basis.get("asked_twice") or {}
    if asked_twice:
        where_body = where_body + (
            f"The name on file is abbreviated, so the lists were asked twice "
            f"— once as written, and once as "
            f"“{asked_twice.get('also_asked', '')}” — because "
            f"an abbreviated name is not found by asking once.",)
    steps.append(Step(
        kind="asked", title="What the watchlists were asked",
        body=where_body, facts=tuple(asked_facts), took=_took(elapsed),
    ))

    # -- what came back -----------------------------------------------------
    matched = [r for r in results if (r.event.payload or {}).get("matched")]
    considered = basis.get("considered") or []
    candidates = []
    matched_names = {(r.event.payload.get("basis") or {}).get("caption")
                     for r in matched}
    for row in considered:
        qualifies = row.get("name") in matched_names
        candidates.append(Candidate(
            name=str(row.get("name") or ""),
            closeness=_closeness(float(row.get("score") or 0.0)),
            standing=("close enough to need a person" if qualifies
                      else "not close enough to matter"),
            tone="today" if qualifies else "settled",
        ))
    if not considered and not matched:
        returned_body = ("No name on any list resembles this party.",)
    elif not matched:
        returned_body = (
            f"{len(considered)} similar {_plural(len(considered), 'name')} "
            f"came back, and none was close enough to be the same party.",)
    else:
        lists = sorted({code
                        for r in matched
                        for code in (r.event.payload.get("basis") or {})
                        .get("datasets", [])})
        named = ", ".join(list_name(code) for code in lists[:3])
        returned_body = (
            f"{len(matched)} {_plural(len(matched), 'name is', 'names are')} "
            f"close enough to need a person"
            + (f", appearing on {named}." if named else "."),)
    steps.append(Step(
        kind="returned", title="What came back", body=returned_body,
        candidates=tuple(candidates),
    ))

    # -- the two records, side by side --------------------------------------
    comparison: Optional[Comparison] = None
    if matched:
        best_basis = (matched[0].event.payload or {}).get("basis") or {}
        comparison = compare(subject=entity_id, our_name=who,
                             our_attributes=entity.attributes,
                             listed=best_basis)
        recorded_shape = {
            "fields": [
                {"field": f.field, "ours": f.ours, "theirs": f.theirs,
                 "verdict": str(f.verdict), "note": f.note}
                for f in comparison.fields
            ]
        }
        steps.append(Step(
            kind="compared", title="The two records, side by side",
            body=("Same facts, both sources, one row each. A difference "
                  "here is what tells two people apart.",),
            side_by_side=side_by_side(recorded_shape),
            ours_label="What we hold",
            theirs_label="What the list holds",
        ))

    # -- the assistant's reading --------------------------------------------
    opened = [case for result in results for case in result.cases]
    if matched and drafter is not None and opened:
        drafting_started = time.perf_counter()
        try:
            from .assist import prepare_drafts

            prepare_drafts(engine, prepared_at=today, drafter=drafter,
                           limit=len(opened))
        except Exception:
            pass  # no draft is the ordinary case, and the file says nothing
        drafted = None
        for case in opened:
            refreshed = engine.state.casebook.cases.get(case.case_id)
            if refreshed is not None:
                drafted = suggestion_for(refreshed)
                if drafted:
                    break
        if drafted:
            steps.append(Step(
                kind="assistant", title="The assistant read both records",
                body=(), suggestion=drafted,
                took=_took(time.perf_counter() - drafting_started),
            ))

    # -- what is now on the record ------------------------------------------
    intact, why = engine.verify()
    # Counted off the log, not rebuilt from the results. The old sum missed
    # whatever another writer in this flow had appended -- and one had been
    # added: the assistant's step runs before this one, so a check on which
    # the model drafted said "2 records were written" over a log that had
    # grown by three. Counting the thing itself cannot drift again when the
    # next writer joins.
    written = len(engine.log) - started_with
    logged_body = [
        f"{written} {_plural(written, 'record was', 'records were')} written "
        # Not "None can be edited": the jargon sweep cannot tell the English
        # word from a Python value that failed to fill in, and it has caught
        # that exact leak before. A sweep with carve-outs stops being a sweep.
        f"on {_date(today)}, each chained to the one before it. Not one can "
        f"be edited or removed — a correction is a new record.",
    ]
    logged_body.append(
        "The chain verifies." if intact else
        f"THE CHAIN DOES NOT VERIFY — stop and investigate: {why}"
    )
    steps.append(Step(kind="logged", title="Now on the permanent record",
                      body=tuple(logged_body)))

    # -- the verdict, and the handoff ---------------------------------------
    files = []
    for case in opened:
        refreshed = engine.state.casebook.cases.get(case.case_id) or case
        item = item_for(refreshed, describe,
                        KIND.get(refreshed.case_type, "Review"))
        files.append(FileRow(reference=item.reference, headline=item.headline,
                             urgency=item.urgency,
                             tone=TONE[refreshed.severity],
                             case_id=refreshed.case_id))

    if matched:
        return Investigation(
            who=who, heading=f"Checking {who} against the watchlists",
            steps=tuple(steps), outcome="match",
            verdict="A possible match needs your decision.",
            explanation=(
                "Nothing about this party should move until it is settled. "
                "The assistant cannot settle it — no machine here can — "
                "so the file below is yours, and whatever you decide will "
                "carry your name and your reason.",),
            next_heading="The file this opened",
            files=tuple(files), tone="stop",
            back=f"Back to {who}", entity_id=entity_id,
        )
    return Investigation(
        who=who, heading=f"Checking {who} against the watchlists",
        steps=tuple(steps), outcome="clean",
        verdict="Nothing found.",
        explanation=(
            "The record that this check happened — what was asked, of "
            "which lists, on which day, and that nothing came back — is "
            "now on file. That record is what an inspector asks for, because "
            "it is the only evidence the check was ever performed.",),
        next_heading="", files=(), tone="settled",
        back=f"Back to {who}", entity_id=entity_id,
    )
