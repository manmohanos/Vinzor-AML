"""What the firm can show for itself, computed from the log alone.

Two questions get asked of a compliance function, and the product answered
neither. An inspector asks *how long has that been sitting there* -- and a
queue of two hundred files says nothing about whether the oldest is a day
old or a year old, which is the difference between a busy desk and a
finding. A board asks *what did we do last quarter* -- and the answer has
to be a document, not a screen somebody scrolled.

So this module folds the log into a period report: what arrived, what the
rules found, what people decided, how long it took them, and who has never
been checked at all. Nothing here reaches for a database or a clock; the
date is supplied and every figure comes from events, which means the
report a firm hands over in June can be reproduced exactly in December.

Two things it deliberately does not do:

* **No score.** Not for the firm, not for a customer. A number between
  nought and a hundred summarising an AML posture invents a precision
  nobody can defend to a regulator, and the evidence it was distilled from
  is already on the page.
* **No ratio without its parts.** "94% screened" hides the six per cent,
  and the six per cent is the whole question -- so every proportion here is
  written as the two counts it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .briefing import (AGE_BANDS, KIND, _counted, _date, days_between,
                       describer, qualified_name, shared_names)
from .model import CaseStatus, EventType, Outcome

#: What the events say arrived, in the words a reader would use for them.
ARRIVALS = (
    (EventType.ENTITY_REGISTERED, "party", "parties"),
    (EventType.PAYMENT_RECEIVED, "payment", "payments"),
    (EventType.OWNERSHIP_DECLARED, "ownership declaration",
     "ownership declarations"),
    (EventType.COMMITMENT_MADE, "commitment", "commitments"),
    (EventType.SCREENING_COMPLETED, "watchlist check", "watchlist checks"),
    (EventType.SHEET_IMPORTED, "spreadsheet import", "spreadsheet imports"),
)


def _median(numbers) -> Optional[float]:
    ordered = sorted(numbers)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


@dataclass(frozen=True)
class Row:
    """One ruled line: what it is, how many, and anything worth adding."""

    what: str
    count: str
    note: str = ""
    tone: str = ""


@dataclass(frozen=True)
class Section:
    heading: str
    lead: str
    rows: tuple[Row, ...] = ()
    #: A closing sentence where the numbers need one. Used sparingly: most
    #: sections are read off their rows.
    tail: str = ""


@dataclass(frozen=True)
class Report:
    title: str
    workspace: str
    covering: str
    printed: str
    summary: tuple[str, ...]
    sections: tuple[Section, ...]
    assurance: str
    back: str
    print_label: str
    ui: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# the pieces
# ---------------------------------------------------------------------------


def _within(event, since: str, today: str) -> bool:
    return since <= str(event.occurred_at)[:10] <= today


def _arrivals(engine, since: str, today: str) -> Section:
    counted = {kind: 0 for kind, _, _ in ARRIVALS}
    for event in engine.log:
        if event.event_type in counted and _within(event, since, today):
            counted[event.event_type] += 1

    rows = [
        Row(what=(many if counted[kind] != 1 else one).capitalize(),
            count=f"{counted[kind]:,}")
        for kind, one, many in ARRIVALS
    ]
    total = sum(counted.values())
    return Section(
        heading="What came in",
        lead=("Everything recorded in this period, counted from the "
              "permanent record itself." if total else
              "Nothing was recorded in this period."),
        rows=tuple(rows),
    )


def _findings(engine, since: str, today: str) -> Section:
    opened = [case for case in engine.state.casebook.cases.values()
              if since <= str(case.opened_at)[:10] <= today]
    by_kind: dict[str, int] = {}
    for case in opened:
        label = KIND.get(case.case_type, "Review")
        by_kind[label] = by_kind.get(label, 0) + 1

    urgent = sum(1 for case in opened
                 if case.severity.rank >= 3)          # CRITICAL
    rows = [Row(what=label, count=f"{count:,}")
            for label, count in sorted(by_kind.items(),
                                       key=lambda kv: -kv[1])]
    lead = (f"The rules opened {_counted(len(opened), 'file', 'files')} in "
            f"this period."
            if opened else "No rule opened a file in this period.")
    tail = ""
    if urgent:
        tail = (f"{_counted(urgent, 'of them stops', 'of them stop')} "
                f"business with that party until an officer clears it.")
    return Section(heading="What the rules found", lead=lead,
                   rows=tuple(rows), tail=tail)


def _decisions(engine, since: str, today: str) -> Section:
    settled = [case for case in engine.state.casebook.cases.values()
               if case.decision is not None
               and since <= str(case.decision.decided_at)[:10] <= today]

    by_outcome: dict[str, int] = {}
    by_person: dict[str, int] = {}
    for case in settled:
        word = {Outcome.APPROVE: "Cleared",
                Outcome.REJECT: "Stopped",
                Outcome.ESCALATE: "Passed up"}.get(
                    case.decision.outcome, "Settled")
        by_outcome[word] = by_outcome.get(word, 0) + 1
        by_person[case.decision.actor] = by_person.get(
            case.decision.actor, 0) + 1

    rows = [Row(what=word, count=f"{count:,}")
            for word, count in sorted(by_outcome.items(),
                                      key=lambda kv: -kv[1])]
    rows += [Row(what=name, count=f"{count:,}", note="settled by this person")
             for name, count in sorted(by_person.items(),
                                       key=lambda kv: -kv[1])]

    # An escalation is a handover, so a report that counts it as a decision
    # and stops there hides the question it raised. What matters is whether
    # somebody else has since answered it.
    from .whosework import stuck as _stuck

    escalated = [case for case in engine.state.casebook.cases.values()
                 if case.status is CaseStatus.ESCALATED]
    # A passed-up file that everybody who could settle it has passed up is
    # not waiting for a second officer; it is waiting for nobody, and saying
    # otherwise on a regulatory page is presenting not-knowing as knowing.
    # An unresolved alert parked in "referred" is the finding examiners
    # write, and this is the shape of it the product could once create.
    nobody = [case for case in escalated if _stuck(case, engine.state.actors)]
    waiting = [case for case in escalated if case not in nobody]

    parts = []
    if waiting:
        oldest = min(str(c.escalations[-1]["on"])[:10] for c in waiting
                     if c.escalations)
        parts.append(
            f"{_counted(len(waiting), 'file is', 'files are')} waiting "
            f"for a second officer after being passed up, the earliest "
            f"of them on {_date(oldest)}. Nobody who passed a file up "
            f"can settle it.")
    if nobody:
        oldest = min(str(c.escalations[-1]["on"])[:10] for c in nobody
                     if c.escalations)
        parts.append(
            f"{_counted(len(nobody), 'file has', 'files have')} been passed "
            f"up by everybody who could settle "
            f"{'it' if len(nobody) == 1 else 'them'}, the earliest on "
            f"{_date(oldest)}, so {'it is' if len(nobody) == 1 else 'they are'}"
            f" waiting on nobody. Enrol another officer who may decide, or "
            f"the {'file' if len(nobody) == 1 else 'files'} cannot be "
            f"settled at all.")
    tail = " ".join(parts)

    lead = (f"{_counted(len(settled), 'file was', 'files were')} settled in "
            f"this period, each by a named person with a written reason."
            if settled else
            "No file was settled in this period.")
    return Section(heading="What people decided", lead=lead,
                   rows=tuple(rows), tail=tail)


def _assistant(engine, since: str, today: str) -> Optional[Section]:
    """How the officers treated the assistant's suggestions.

    The number that matters is how often a person went the other way. A
    firm whose officers never contradict the machine is not supervising it,
    and that is exactly the finding a regulator would write.
    """
    used: dict[str, int] = {}
    for case in engine.state.casebook.cases.values():
        decision = case.decision
        if decision is None or not since <= str(
                decision.decided_at)[:10] <= today:
            continue
        if decision.draft_use and decision.draft_use != "NONE":
            used[decision.draft_use] = used.get(decision.draft_use, 0) + 1
    if not used:
        return None

    words = {
        "ACCEPTED": "Used the suggested wording as it stood",
        "EDITED": "Used the suggested wording and changed it",
        "REJECTED": "Wrote their own reason instead",
        "CONTRADICTED": "Decided against what was suggested",
    }
    rows = [Row(what=words.get(key, key.title()), count=f"{count:,}",
                tone="stop" if key == "CONTRADICTED" else "")
            for key, count in sorted(used.items(), key=lambda kv: -kv[1])]
    against = used.get("CONTRADICTED", 0)
    tail = ("No officer decided against a suggestion in this period. That "
            "is worth watching: a firm whose people never disagree with a "
            "machine is not supervising it."
            if not against else
            f"{_counted(against, 'file was', 'files were')} decided against "
            f"what was suggested, which is the supervision working.")
    return Section(
        heading="How the assistant was used",
        lead="A suggestion is never a decision. This is what people did "
             "with the ones that were put in front of them.",
        rows=tuple(rows), tail=tail)


def _ageing(engine, today: str) -> Section:
    """How long the open files have been open. The question an inspector
    asks first, and the one a count of open files cannot answer."""
    open_cases = [case for case in engine.state.casebook.cases.values() if case.is_open]

    banded = {label: 0 for _, _, label in AGE_BANDS}
    oldest_days, oldest_case = -1, None
    for case in open_cases:
        age = days_between(str(case.opened_at)[:10], today)
        if age is None or age < 0:
            age = 0
        for low, high, label in AGE_BANDS:
            if age >= low and (high is None or age < high):
                banded[label] += 1
                break
        if age > oldest_days:
            oldest_days, oldest_case = age, case

    rows = []
    for low, _, label in AGE_BANDS:
        count = banded[label]
        rows.append(Row(what=label, count=f"{count:,}",
                        tone="stop" if count and low >= 91 else ""))

    lead = (f"{_counted(len(open_cases), 'file is', 'files are')} open, "
            f"counted by how long each has been waiting."
            if open_cases else "Nothing is open.")
    tail = ""
    if oldest_case is not None and oldest_days > 0:
        describe = describer(engine.state.graph)
        who = describe(oldest_case.subject, oldest_case.case_type)
        counted = (f"{oldest_days:,} days" if oldest_days != 1
                   else "1 day")
        tail = (f"The oldest was opened on {_date(oldest_case.opened_at)}, "
                f"{counted} ago: "
                f"{KIND.get(oldest_case.case_type, 'a review').lower()} "
                f"about {who}.")
    return Section(heading="How long files have been waiting", lead=lead,
                   rows=tuple(rows), tail=tail)


def _turnaround(engine, since: str, today: str) -> Optional[Section]:
    taken = []
    for case in engine.state.casebook.cases.values():
        decision = case.decision
        if decision is None or not since <= str(
                decision.decided_at)[:10] <= today:
            continue
        days = days_between(str(case.opened_at)[:10],
                             str(decision.decided_at)[:10])
        if days is not None and days >= 0:
            taken.append(days)
    if not taken:
        return None

    middle = _median(taken)
    slowest = max(taken)
    rows = (
        Row(what="Files settled", count=f"{len(taken):,}"),
        Row(what="Half were settled within",
            count=_counted(int(middle or 0), "day", "days")),
        Row(what="The slowest took", count=_counted(slowest, "day", "days"),
            tone="stop" if slowest > 30 else ""),
    )
    return Section(
        heading="How long settling takes",
        lead="Measured from the day the rule opened the file to the day a "
             "person settled it.",
        rows=rows)


def _coverage(engine, today: str) -> Section:
    """Who has been checked against the watchlists, and who never has.

    The clean results are the point. A firm proves it screened its book by
    showing the checks it ran, not by showing the hits it found -- so a
    party nobody has ever checked is the finding here, and it is named.
    """
    graph = engine.state.graph
    parties = list(graph.entities)
    checked: dict[str, str] = {}
    for event in engine.log:
        if event.event_type is not EventType.SCREENING_COMPLETED:
            continue
        when = str(event.occurred_at)[:10]
        if when > checked.get(event.subject, ""):
            checked[event.subject] = when

    never = [entity_id for entity_id in parties if entity_id not in checked]
    stale = [entity_id for entity_id, when in checked.items()
             if (days_between(when, today) or 0) > 365]

    rows = [
        Row(what="Parties on the record", count=f"{len(parties):,}"),
        Row(what="Checked against the watchlists at least once",
            count=f"{len(checked):,}"),
        Row(what="Never checked", count=f"{len(never):,}",
            tone="stop" if never else ""),
        Row(what="Last checked more than a year ago", count=f"{len(stale):,}",
            tone="stop" if stale else ""),
    ]

    tail = ""
    if never:
        shared = shared_names(graph)
        names = [qualified_name(graph, entity_id, shared)
                 for entity_id in never[:5]]
        listed = ", ".join(names)
        more = ("" if len(never) <= 5
                else f", and {len(never) - 5} more")
        tail = (f"Nobody has run a check on {listed}{more}. A check that was "
                f"never run is the one thing this record cannot show was "
                f"done.")
    else:
        tail = ("Every party on the record has been checked at least once, "
                "and each check is on the permanent record with what it "
                "asked and what came back.")
    return Section(
        heading="Watchlist coverage",
        lead="Proof that the checking happened is the deliverable, so the "
             "clean results are counted here alongside the matches.",
        rows=tuple(rows), tail=tail)


def _handover(engine) -> Optional[Section]:
    """Whether the client book could be handed to a registration agency.

    Not a period figure like everything else on this report: it is the
    state of the book as it stands, which is why the lead says so. From
    1 September 2026 an IFSC regulated entity uploads each client's KYC to
    a registered agency within three working days, and its existing book by
    30 October.
    """
    from .readiness import FOR_A_LEGAL_PERSON, FOR_A_PERSON, measure

    result = measure(engine)
    if not result.parties:
        return None

    words = {clause: what for clause, what, _ in
             FOR_A_PERSON + FOR_A_LEGAL_PERSON}
    rows = [
        Row(what="Parties on the record", count=f"{len(result.parties):,}"),
        Row(what="Complete enough to hand over",
            count=f"{len(result.ready):,}"),
        Row(what="Short of something the guidelines require",
            count=f"{len(result.short):,}",
            tone="stop" if result.short else ""),
    ]
    for clause, count in sorted(result.by_clause.items(),
                                key=lambda kv: -kv[1]):
        rows.append(Row(
            what=words.get(clause, "what kind of party this is").capitalize(),
            count=f"{count:,}",
            note=f"clause {clause}",
        ))

    tail = (
        "This measures clause 5.4.2 — the identification information "
        "the guidelines say a Regulated Entity shall obtain at least. It is "
        "upstream of any upload: a record missing what 5.4.2 requires is not "
        "ready for anybody. It is not a check against a registration "
        "agency's own file layout, so passing it does not promise a file "
        "will be accepted."
    )
    if result.short:
        biggest = max(result.by_clause.items(), key=lambda kv: kv[1])
        tail = (
            f"Most of the shortfall is one thing: "
            f"{words.get(biggest[0], 'the party type')} is missing from "
            f"{_counted(biggest[1], 'party', 'parties')}. That is usually "
            f"one column absent from an export rather than "
            f"{biggest[1]:,} separate problems. " + tail
        )
    return Section(
        heading="Whether the book could be handed over",
        lead="As the record stands today, not for the period above.",
        rows=tuple(rows), tail=tail)


def _the_record(engine) -> Section:
    intact, why = engine.verify()
    events = len(engine.log)
    # Witness the length now, so this report and the log agree about it.
    try:
        engine.log.mark(str(getattr(engine.log, "_marked_on", "")) or "")
    except Exception:
        pass
    count, head = engine.log.head()
    rows = (
        Row(what="Records in the permanent log", count=f"{events:,}"),
        Row(what="The chain",
            count="Verifies" if intact else "Broken",
            note=("Every record still hashes to the one before it."
                  if intact else str(why)),
            tone="" if intact else "stop"),
        # The pair that makes a printed report a witness. A chain proves
        # what remains is intact; it cannot prove nothing was taken off the
        # end, because every link points backwards. A document handed over
        # in July saying the record stood at this length with this
        # fingerprint is evidence against a file that says something
        # shorter in September -- and unlike anything inside the file, a
        # printed page cannot be edited by whoever holds the database.
        Row(what="Fingerprint of the last record", count=head[:16],
            note=f"At {count:,} records. Keep this with the report: it is "
                 f"the one part of the seal that leaves the building."),
    )
    return Section(
        heading="The record behind this report",
        lead="Every figure above was counted from these records, and nothing "
             "here was typed in by hand.",
        rows=rows,
        tail=("Each record is sealed to the one before it, so a figure in "
              "this report cannot be changed without breaking the chain "
              "that proves it."))


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


class PeriodUnreadable(ValueError):
    """The period asked for is not a period. Refused rather than guessed."""


def _a_date(value, what: str) -> str:
    """An ISO date, or a refusal naming the remedy."""
    from datetime import datetime

    text = str(value or "").strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise PeriodUnreadable(
            f"{text!r} could not be read as {what}. Choose one of the periods "
            f"offered, or write the date as 2026-08-01."
        ) from None
    return text


def period_report(engine, today: str, since: str = "",
                  workspace: str = "") -> Report:
    """Everything the firm can show for itself, for a period ending today.

    ``since`` defaults to the first day of the month ``today`` falls in,
    because that is the period a compliance function actually reports on.

    **Both dates are read as dates before anything counts them.** They used to
    be truncated to ten characters and compared as text, which is right for
    an ISO date and silently wrong for anything else. Measured against the
    live book, same server, same instant:

    ==================  ====================================================
    ``since=banana``    "Covering banana to 20 August 2026", every figure
                        zero, "No file was opened or settled in this period"
                        -- while 221 files had in fact been opened.
    ``since=01-08-2026``  a date written the ordinary Indian way became
                        "Covering 2026 August 1", and a one-month report
                        quietly became an all-time one: 154 commitments
                        instead of 16, 53 ownership declarations instead of 0.
    ==================  ====================================================

    This page has the firm's name on it and a print button, and "no file was
    opened or settled in this period" is the sentence a firm would least like
    to have to defend. A period that cannot be read is refused, never guessed
    at and never echoed into the covering sentence.
    """
    today = _a_date(today, "the date the report ends")
    if not since:
        since = today[:8] + "01"
    since = _a_date(since, "the date the period starts")
    if since > today:
        raise PeriodUnreadable(
            f"the period starts on {since} and ends on {today}, which is "
            f"before it began. Choose one of the periods offered."
        )

    sections = [
        _arrivals(engine, since, today),
        _findings(engine, since, today),
        _decisions(engine, since, today),
    ]
    assistant = _assistant(engine, since, today)
    if assistant:
        sections.append(assistant)
    sections.append(_ageing(engine, today))
    turnaround = _turnaround(engine, since, today)
    if turnaround:
        sections.append(turnaround)
    sections.append(_coverage(engine, today))
    handover = _handover(engine)
    if handover:
        sections.append(handover)
    sections.append(_the_record(engine))

    open_now = sum(1 for case in engine.state.casebook.cases.values() if case.is_open)
    settled = sum(
        1 for case in engine.state.casebook.cases.values()
        if case.decision is not None
        and since <= str(case.decision.decided_at)[:10] <= today)
    opened = sum(1 for case in engine.state.casebook.cases.values()
                 if since <= str(case.opened_at)[:10] <= today)

    summary = [
        f"In this period the rules opened "
        f"{_counted(opened, 'file', 'files')} and people settled "
        f"{_counted(settled, 'of them', 'of them')}."
        if opened or settled else
        "No file was opened or settled in this period.",
    ]
    if open_now:
        summary.append(
            f"{_counted(open_now, 'file remains', 'files remain')} open "
            f"today.")
    # Said plainly rather than left to be inferred from a gap in the rows:
    # a period where more arrived than left is the thing a board is being
    # asked to notice.
    if opened > settled and opened:
        summary.append(
            "More files were opened than settled, so the list is growing.")
    elif settled and settled >= opened:
        summary.append(
            "At least as many files were settled as were opened, so the "
            "list is not growing.")

    return Report(
        title="What this firm can show for itself",
        workspace=workspace,
        covering=f"Covering {_date(since)} to {_date(today)}.",
        printed=f"Prepared on {_date(today)} from the permanent record.",
        summary=tuple(summary),
        sections=tuple(sections),
        assurance=(
            "This report is a reading of the permanent record, not a "
            "summary written beside it. Anyone with the record can produce "
            "it again and get the same figures, today or in five years."),
        back="Back to your list",
        print_label="Print or save as a document",
    )
