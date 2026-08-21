"""The book, as a workbook an officer can actually work in.

A firm hands over a spreadsheet and gets back a website. For the person
whose job is two hundred investors that is a bad trade: they want to sort
by what is missing, filter to the ones with no document, hand a tab to a
colleague and put a column of their own next to ours. All spreadsheet
operations, none of them a web page.

**What comes back is more than what went in.** Exporting the imported
columns would be a round trip and worth nothing. Beside each party goes
what this system has since worked out about them -- whether a watchlist
matched, what clause 5.4.2 still wants, whether any of it is evidenced by
a document, how risky somebody judged them and when they are next due, and
whether they look like somebody already on the book. That is the column an
officer wanted when they asked for the file back.

**Nothing here is a judgement the system made up.** Every column is either
a fact from the log or a count of findings that are themselves on the log
with a clause behind each. Where nobody has decided something the cell
says so in words -- "nobody has categorised this party" -- rather than
being left blank, because a blank column in a spreadsheet is read as a no.
"""

from __future__ import annotations

from typing import Optional

from .spreadsheet import Sheet, workbook


def _plain(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def parties_sheet(engine, today: str) -> Sheet:
    """One row per party, with what we have since found out about them."""
    from .briefing import KIND, PARTY_KINDS
    from .documents import KINDS as DOCUMENT_KINDS
    from .readiness import measure

    graph = engine.state.graph
    papers = getattr(engine.state, "papers", None)
    risk = engine.state.risk
    measured = {s.entity_id: s for s in measure(engine, today=today).parties}

    matched: dict = {}
    for case in engine.state.casebook.cases.values():
        if case.case_type in ("SCREENING_HIT", "SAME_PARTY"):
            for evidence in case.evidence:
                kind = (evidence.detail or {}).get("list_type")
                if kind:
                    matched.setdefault(case.subject, set()).add(str(kind))

    open_files: dict = {}
    for case in engine.state.casebook.cases.values():
        if case.is_open:
            open_files[case.subject] = open_files.get(case.subject, 0) + 1

    columns = (
        "Reference", "Name", "Kind", "Nationality", "Country of residence",
        "Date of birth", "Identifying number", "Address", "Email", "Phone",
        "On a watchlist", "What matched",
        "Missing under clause 5.4.2", "Held but not evidenced",
        "Documents on file", "Risk", "Risk set by", "Risk set on",
        "Open files",
    )

    rows = []
    for entity_id, entity in sorted(graph.entities.items(),
                                    key=lambda kv: (kv[1].name or "").lower()):
        attributes = dict(entity.attributes or {})
        standing = measured.get(entity_id)
        assessed = risk.get(entity_id)
        held = papers.held_for(entity_id) if papers else ()
        hits = sorted(matched.get(entity_id, ()))

        rows.append([
            entity_id,
            entity.name or "",
            PARTY_KINDS.get(str(entity.kind), str(entity.kind)),
            _plain(attributes.get("nationality")),
            _plain(attributes.get("country_of_residence")),
            _plain(attributes.get("dob")),
            _plain(attributes.get("pan") or attributes.get("cin")
                   or attributes.get("id_document_number")
                   or attributes.get("lei")),
            _plain(attributes.get("address")),
            _plain(attributes.get("email")),
            _plain(attributes.get("phone")),
            "Yes" if hits else "No",
            ", ".join(h.replace("_", " ").lower() for h in hits),
            "; ".join(gap.what for gap in standing.gaps) if standing else "",
            "; ".join(gap.what for gap in standing.unsupported)
            if standing else "",
            "; ".join(sorted({
                DOCUMENT_KINDS.get(p.kind, ("Other", ()))[0] for p in held})),
            (str(assessed.category).capitalize() if assessed
             else "nobody has categorised this party"),
            (assessed.by if assessed else ""),
            (assessed.on if assessed else ""),
            open_files.get(entity_id, 0),
        ])

    return Sheet(
        name="Parties",
        columns=columns,
        rows=rows,
        note=(f"Every party on this book as at {today}, with what this "
              f"system has since found out about each. Figures are as the "
              f"permanent record held them when this file was written."),
    )


def findings_sheet(engine, today: str) -> Sheet:
    """One row per open file, so a queue can be worked in a spreadsheet."""
    from .briefing import KIND, describer, item_for

    describe = describer(engine.state.graph)
    rows = []
    counted: dict = {}
    for case in engine.state.casebook.queue():
        label = KIND.get(case.case_type, "Review")
        counted[label] = counted.get(label, 0) + 1
        item = item_for(case, describe, f"{label} {counted[label]}", today)
        clause = ""
        for evidence in case.evidence:
            for citation in evidence.citations or ():
                clause = str(citation.get("clause") or "")
                break
            if clause:
                break
        rows.append([
            case.case_id,
            label,
            describe(case.subject),
            str(case.severity).replace("Severity.", "").title(),
            str(case.opened_at)[:10],
            item.headline,
            " ".join(item.because),
            clause,
            str(case.status).replace("CaseStatus.", "").title(),
        ])

    return Sheet(
        name="Open files",
        columns=("Reference", "Kind", "Party", "Urgency", "Opened",
                 "What was found", "Why", "Clause", "Standing"),
        rows=rows,
        note=(f"Every file still open as at {today}. Each was written down "
              f"as a fact when it was found and is never rewritten when a "
              f"rule later changes."),
    )


def decisions_sheet(engine) -> Sheet:
    """Who settled what, in their own words. The audit tab."""
    from .briefing import KIND, describer, role_word

    describe = describer(engine.state.graph)
    rows = []
    for case in engine.state.casebook.cases.values():
        label = KIND.get(case.case_type, "Review")
        for step in case.escalations:
            rows.append([str(step.get("on", ""))[:10], case.case_id, label,
                         describe(case.subject), "Passed up",
                         str(step.get("by", "")), role_word(step.get("role")),
                         str(step.get("why", ""))])
        if case.decision is not None:
            rows.append([
                str(case.decision.decided_at)[:10], case.case_id, label,
                describe(case.subject),
                str(case.decision.outcome).replace("Outcome.", "").title(),
                str(case.decision.actor), role_word(case.decision.role),
                str(case.decision.rationale or "")])
    rows.sort(key=lambda row: row[0])

    return Sheet(
        name="Decisions",
        columns=("When", "Reference", "Kind", "Party", "What was decided",
                 "By", "Acting as", "Their reason, in their own words"),
        rows=rows,
        note=("Every decision on this book. The wording is the decider's "
              "and has not been tidied; none of it can be edited or "
              "removed."),
    )


def payments_sheet(engine) -> Sheet:
    """The money, as it was recorded."""
    from .model import EventType

    graph = engine.state.graph
    rows = []
    for event in engine.log:
        if event.event_type is not EventType.PAYMENT_RECEIVED:
            continue
        payload = event.payload or {}
        payer = str(payload.get("payer") or "")
        rows.append([
            str(event.occurred_at)[:10],
            str(payload.get("payment_ref") or payload.get("payment_id") or ""),
            graph.name_of(event.subject),
            graph.name_of(payer) if payer else "",
            payload.get("amount") if isinstance(
                payload.get("amount"), (int, float)) else "",
            str(payload.get("currency") or ""),
            payload.get("called_amount") if isinstance(
                payload.get("called_amount"), (int, float)) else "",
            str(payload.get("narration") or ""),
        ])
    return Sheet(
        name="Payments",
        columns=("Date", "Reference", "For", "From", "Amount", "Currency",
                 "Called", "Narration"),
        rows=rows,
        note="Every payment recorded, as it was recorded.",
    )


def the_book(engine, today: str) -> bytes:
    """The whole workbook: parties, open files, decisions and payments."""
    return workbook([
        parties_sheet(engine, today),
        findings_sheet(engine, today),
        decisions_sheet(engine),
        payments_sheet(engine),
    ])


def one_party(engine, entity_id: str, today: str) -> Optional[bytes]:
    """Everything on one party, as a workbook rather than a document."""
    from .dossier import dossier

    doc = dossier(engine, entity_id, today)
    if doc.refusal:
        return None

    facts = Sheet(
        name="Record",
        columns=("Section", "What", "Value", "Note"),
        rows=[[part.heading, fact.label, fact.value, fact.note]
              for part in doc.parts for fact in part.facts],
        note=f"{doc.title}. {doc.printed}",
    )
    happened = Sheet(
        name="What happened",
        columns=("When", "What", "Who", "Their words", "Clause"),
        rows=[[entry.when, entry.what, entry.who, entry.why, entry.clause]
              for part in doc.parts for entry in part.entries],
        note=("Everything recorded about this party, in order. This file is "
              "for the firm and for a regulator; it must never be given to "
              "the party it is about."),
    )
    return workbook([facts, happened])
