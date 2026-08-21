"""The evidence pack: everything this workspace can prove, in one folder.

The product's claim is not that it finds things. It is that what it found, and
what a person decided about it, can be shown to someone else afterwards. Until
now that claim could only be checked by opening the application on the machine
that holds the database, which is no use to an inspector, an auditor, a board,
or a fund administrator being asked a question about last March.

Two files, deliberately:

``record.jsonl`` is the log itself, one event per line, with the hash chain
intact. It is the evidence. Anyone can re-verify it without this software --
the rule is stated in the pack and is four lines of any language.

``evidence.html`` is a reading of that log for a person. It is *not* the
evidence and says so: every figure in it is derived from the same lines, and
where the two ever disagreed the JSONL would be right.

The pack renders from the log and from nothing else. It holds no opinion the
application does not already hold, and it repeats every caveat the screens
carry -- an export that quietly drops the "no qualified person has checked
these clauses" line would be the most dangerous document this system produces.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from .briefing import _date, regulatory, screening
from .citations import CLAUSES, DOCUMENTS, SOURCE_CHECK_NOTE
from .model import Event

#: How to re-verify the chain without this software. Stated in the pack so the
#: recipient is not asked to trust the tool that produced it.
CHAIN_RULE = (
    "Each line carries the SHA-256 of the line before it. For any line, let "
    "body be the JSON text of {seq, event_type, subject, occurred_at, actor, "
    "payload} with keys sorted, no whitespace between tokens, and non-ASCII "
    "characters written as themselves rather than escaped. Then event_hash "
    "must equal the SHA-256 of prev_hash + \"|\" + body, and prev_hash must "
    "equal the previous line's event_hash. Note that prev_hash is joined on "
    "outside the JSON, not carried inside it. Alter, remove or insert any "
    "line and every hash after it stops matching. "
    "A chain proves that, and only that: nothing has been altered or "
    "removed *between* the first line and the last. It cannot speak about "
    "what was taken off either end, because what remains still follows "
    "itself — cut the first ten lines away and every surviving link "
    "checks. So verify.py also holds two anchors, written into it when this "
    "pack was made: the first line must be record 1 following the opening "
    "hash of sixty-four zeroes, and the last line must be the record this "
    "log ended at, with the count that was in it. Those are what make "
    "\"none missing\" a claim about the whole log rather than about the "
    "file in front of you."
)

#: Shipped inside the pack. Stdlib only, no Vinzor import, no network: a
#: recipient who does not trust the tool that produced the pack should not have
#: to run that tool to check it. Written out rather than described because a
#: rule stated in prose is a rule someone has to reimplement, and the first
#: version of this file described the hash wrongly -- it would have made an
#: honest pack look forged.
VERIFIER = '''"""Check record.jsonl. Usage: python verify.py [record.jsonl]

Exits 0 if the chain is intact, 1 if it is not. Reads nothing but the file.
"""
import hashlib
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "record.jsonl"
with open(path, encoding="utf-8") as handle:
    events = [json.loads(line) for line in handle if line.strip()]

if not events:
    print("no events in", path)
    raise SystemExit(1)


def digest(event):
    body = json.dumps(
        {k: event[k] for k in
         ("seq", "event_type", "subject", "occurred_at", "actor", "payload")},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
    )
    return hashlib.sha256(
        (event["prev_hash"] + "|" + body).encode("utf-8")
    ).hexdigest()


# What this file was when it left the firm. Written in as literals at the
# moment the pack was made, so the checks below do not have to take the
# file's own word for where it begins and ends.
#
# Without them a chain proves only that the records still here follow one
# another. Cut the first ten lines off and every remaining link still
# matches; cut the last ten off and the same. This verifier said "INTACT:
# 30 records, none altered, none missing" to both.
FIRST_SEQ = 1
GENESIS = "0" * 64
EXPECTED_COUNT = __COUNT__
EXPECTED_HEAD = "__HEAD__"

if events[0]["seq"] != FIRST_SEQ or events[0]["prev_hash"] != GENESIS:
    print("BROKEN: this file does not begin at the first record of the log, "
          "so records have been removed from the front of it")
    raise SystemExit(1)

previous = GENESIS
for position, event in enumerate(events):
    if event["prev_hash"] != previous:
        print(f"BROKEN at seq {event['seq']}: it follows a different record "
              f"than the one before it in this file")
        raise SystemExit(1)
    if digest(event) != event["event_hash"]:
        print(f"BROKEN at seq {event['seq']}: this record has been altered "
              f"since it was written")
        raise SystemExit(1)
    if position and event["seq"] != events[position - 1]["seq"] + 1:
        print(f"BROKEN at seq {event['seq']}: a record is missing before it")
        raise SystemExit(1)
    previous = event["event_hash"]

if len(events) != EXPECTED_COUNT or events[-1]["event_hash"] != EXPECTED_HEAD:
    print(f"BROKEN: this file held {EXPECTED_COUNT} records when it was made "
          f"and holds {len(events)} now, so records have been removed from "
          f"the end of it")
    raise SystemExit(1)

print(f"INTACT: records {events[0]['seq']} to {events[-1]['seq']}, "
      f"{len(events)} of them, none altered, none missing from either end.")
print(f"first {events[0]['occurred_at']}  last {events[-1]['occurred_at']}")
'''


def _event_dict(event: Event) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "event_type": str(event.event_type),
        "subject": event.subject,
        "occurred_at": event.occurred_at,
        "actor": event.actor,
        "payload": event.payload,
        "prev_hash": event.prev_hash,
        "event_hash": event.event_hash,
    }


def _esc(value: Any) -> str:
    """HTML-escape. The pack embeds names and free-typed decision reasons."""
    return (
        str(value)
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def decisions(engine) -> list[dict[str, str]]:
    """Every settled file: who settled it, in what capacity, when, and the
    reason they gave.

    Read off the Cases rather than the raw events so that the reason shown is
    the one the fold accepted, which is the one the application acted on.

    **The capacity is the point of half these rows.** The table carried a name
    and no role, so the one thing an inspector opens this pack to check --
    that a politically exposed person was cleared by senior management, as
    clause 5.5(b)(iii) requires -- was the one thing it could not show. The
    product enforces that rule twice and then printed a pack that could not
    evidence it.
    """
    from .briefing import role_word

    rows = []
    graph = engine.state.graph
    for case in engine.state.casebook.cases.values():
        decision = case.decision
        if decision is None:
            continue
        rows.append({
            "case": case.case_id,
            "about": graph.name_of(case.subject),
            "kind": case.case_type,
            "outcome": str(decision.outcome),
            "who": decision.actor,
            "as": role_word(decision.role),
            "when": decision.decided_at,
            "why": decision.rationale,
            "clauses": ", ".join(sorted({
                citation["clause"]
                for piece in case.evidence
                for citation in (piece.citations or ())
            })),
        })
    rows.sort(key=lambda row: (row["when"], row["case"]))
    return rows


def pack(engine, workspace: str = "", today: Optional[str] = None) -> dict[str, str]:
    """Build the pack. Returns {filename: contents}."""
    events = list(engine.log)
    intact, why = engine.verify()

    lines = [json.dumps(_event_dict(e), sort_keys=True, separators=(",", ":"))
             for e in events]
    record = "\n".join(lines) + ("\n" if lines else "")

    settled = decisions(engine)
    checks = screening(engine, today, per_list=10_000)
    standing = regulatory(engine, today)

    #: A fingerprint of the pack itself, so two copies can be compared without
    #: reading them. Not a signature: it proves the file did not change in
    #: transit, not who produced it.
    digest = hashlib.sha256(record.encode("utf-8")).hexdigest()

    html = _render(
        workspace=workspace or "this workspace",
        events=events,
        intact=intact,
        why=why,
        digest=digest,
        settled=settled,
        checks=checks,
        standing=standing,
        today=today or "",
    )
    # The anchors are written into the verifier rather than left for it to
    # infer, because a file cannot testify to what has been taken off its
    # own ends.
    verifier = (VERIFIER
                .replace("__COUNT__", str(len(events)))
                .replace("__HEAD__",
                         events[-1].event_hash if events else ""))
    return {"record.jsonl": record, "evidence.html": html,
            "verify.py": verifier}


def write(engine, out: Path, workspace: str = "",
          today: Optional[str] = None) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, body in pack(engine, workspace, today).items():
        path = out / name
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written


def _render(*, workspace, events, intact, why, digest, settled, checks,
            standing, today) -> str:
    genesis = events[0].prev_hash if events else ""
    head = events[-1].event_hash if events else ""
    first = events[0].occurred_at if events else ""
    last = max((e.occurred_at for e in events), default="")

    chain_line = (
        "The chain verifies. Every record is intact and in order."
        if intact else
        f"THE CHAIN DOES NOT VERIFY. {_esc(why or '')} Treat nothing in this "
        f"pack as reliable until that is explained."
    )

    rows = "".join(
        f"<tr><td>{_esc(_date(row['when']))}</td>"
        f"<td>{_esc(row['about'])}</td>"
        f"<td>{_esc(row['outcome'].replace('_', ' ').lower())}</td>"
        f"<td>{_esc(row['who'])}</td>"
        f"<td>{_esc(row['as'])}</td>"
        f"<td>{_esc(row['clauses'])}</td>"
        f"<td>{_esc(row['why'])}</td></tr>"
        for row in settled
    ) or ("<tr><td colspan='6' class='none'>No file in this workspace has "
          "been settled by a person.</td></tr>")

    screened = "".join(
        f"<tr><td>{_esc(c.who)}</td><td>{_esc(c.kind)}</td>"
        f"<td>{_esc(c.when)}</td><td>{_esc(c.result)}</td></tr>"
        for c in list(checks.checked) + list(checks.unchecked)
    ) or "<tr><td colspan='4' class='none'>No party has been checked.</td></tr>"

    clauses = "".join(
        f"<tr><td>{_esc(c.clause_id)}</td>"
        f"<td>{_esc(DOCUMENTS[c.doc_id].title)}</td>"
        f"<td>p.{_esc(c.page)}</td>"
        f"<td>{'a person has confirmed this' if c.verified else 'not confirmed by a person'}</td>"
        f"</tr>"
        for c in sorted(CLAUSES.values(), key=lambda c: (c.doc_id, c.clause_id))
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Evidence pack — {_esc(workspace)}</title>
<style>
 :root{{color-scheme:light}}
 body{{margin:0;background:#fff;color:#0b1c2e;
   font:16px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}}
 .wrap{{max-width:60rem;margin:0 auto;padding:3rem 1.5rem 5rem}}
 h1{{font-size:2rem;letter-spacing:-.02em;margin:0 0 .4rem}}
 h2{{font-size:1.25rem;margin:2.75rem 0 .6rem;letter-spacing:-.01em}}
 p{{max-width:68ch}}
 .sub{{color:#4a586e;margin:0 0 2rem}}
 .box{{border:1px solid #e2e5ee;border-radius:8px;padding:1rem 1.2rem;
   background:#fafbfd;margin:0 0 1rem}}
 .ok{{border-left:3px solid #1c6b4c}} .bad{{border-left:3px solid #b91c4f}}
 .bad strong{{color:#b91c4f}}
 table{{border-collapse:collapse;width:100%;font-size:.92rem;margin-top:.5rem}}
 th,td{{text-align:left;padding:.5rem .6rem;border-bottom:1px solid #eceef4;
   vertical-align:top}}
 th{{font-size:.78rem;text-transform:uppercase;letter-spacing:.07em;color:#64748d}}
 td.none{{color:#64748d;font-style:italic}}
 code,.mono{{font-family:ui-monospace,Consolas,monospace;font-size:.85em;
   word-break:break-all}}
 .caveat{{border-left:3px solid #96610b;background:#fffaf2}}
 .scroll{{overflow-x:auto}}
 footer{{margin-top:3rem;padding-top:1rem;border-top:1px solid #e2e5ee;
   color:#64748d;font-size:.88rem}}
</style></head><body><div class="wrap">

<h1>Evidence pack</h1>
<p class="sub">{_esc(workspace)}{' &middot; ' + _esc(_date(today)) if today else ''}</p>

<div class="box {'ok' if intact else 'bad'}">
  <p style="margin:0"><strong>{chain_line}</strong></p>
</div>

<p><strong>This page is a reading of the record, not the record.</strong>
The evidence is <code>record.jsonl</code> beside this file: {len(events)} events
covering {_esc(_date(first)) if first else 'no period'} to
{_esc(_date(last)) if last else ''}. Every figure below is derived from those
lines, and if the two ever disagree the lines are right.</p>

<h2>Checking this pack yourself</h2>
<div class="box"><p style="margin:0 0 .6rem">{_esc(CHAIN_RULE)}</p>
<p class="mono" style="margin:0">genesis prev_hash: {_esc(genesis)}<br>
final event_hash: {_esc(head)}<br>
sha256(record.jsonl): {_esc(digest)}</p></div>

<h2>Decisions a person recorded</h2>
<p>Every file settled in this workspace, with the reason given at the time.
No decision can be edited once written; a correction is a new record.</p>
<div class="scroll"><table>
<thead><tr><th>When</th><th>About</th><th>Outcome</th><th>Who</th>
<th>Acting as</th><th>Clauses</th><th>Reason given</th></tr></thead>
<tbody>{rows}</tbody></table></div>

<h2>Watchlist screening</h2>
<p>{_esc(checks.coverage_summary)} {_esc(checks.scope_note)}</p>
<div class="box caveat"><p style="margin:0">{_esc(checks.rule_caveat)}</p></div>
<div class="scroll"><table>
<thead><tr><th>Party</th><th>Type</th><th>Last checked</th><th>Result</th></tr></thead>
<tbody>{screened}</tbody></table></div>

<h2>Standing with the regulator</h2>
<p>{_esc(standing.licence_summary or standing.unlicensed)}</p>
<p>{_esc(standing.owed_summary)}</p>

<h2>The rules this system applied</h2>
<p>{_esc(standing.register_summary)}</p>
<div class="box caveat"><p style="margin:0 0 .6rem">{_esc(SOURCE_CHECK_NOTE)}</p>
<p style="margin:0">{_esc(standing.register_caveat)}</p></div>
<div class="scroll"><table>
<thead><tr><th>Clause</th><th>Document</th><th>Page</th><th>Standing</th></tr></thead>
<tbody>{clauses}</tbody></table></div>

<footer>Produced by Vinzor from the workspace log. It asserts nothing that is
not in <code>record.jsonl</code>, and it is not a legal opinion.</footer>
</div></body></html>"""
