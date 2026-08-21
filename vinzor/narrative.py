"""A written opening to a record, from figures the record already holds.

Everything this product puts on a page is a fact with a clause behind it,
and a reader who has never met the file still has to assemble the story
themselves. A Principal Officer handed twelve sections wants a paragraph
first: what this party is, what was found, what is unresolved.

**The model writes prose. It does not supply facts.** It is handed the
figures the sections already contain and asked to join them into English.
Anything it says that is not in what it was given is a fabrication on a
compliance record, and there is no version of that which is acceptable --
so the summary is checked before it is shown and thrown away if it invents
a number. Thrown away, not corrected: a paragraph that had to be repaired
is one nobody should have been reading.

**It never concludes.** No risk rating, no recommendation, no "this
customer appears legitimate". Those are decisions, decisions belong to a
person, and a fluent sentence is the most efficient way ever devised to
make somebody agree without checking. The prose says what is on the file;
the officer says what it means.

**A record is complete without it.** Where no model is configured, or the
summary fails its check, the sections are simply shown as they always
were. Nothing downstream depends on the paragraph existing, which is the
property that lets it be thrown away without ceremony.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

#: Any run of digits worth policing. Matches what the drafting guard uses,
#: because the two are solving the same problem and drifting apart would
#: mean one of them is wrong.
_FIGURE = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: Sections the summary is not given. Not because they are secret -- they
#: are on the same page -- but because they describe the document rather
#: than the party, and a paragraph that opens a file should be about the
#: party.
SKIP = frozenset({"The record behind this document"})

INSTRUCTION = (
    "You write the opening paragraph of a compliance record for a fund "
    "manager in GIFT City, India, regulated by IFSCA. The reader is a "
    "Principal Officer who has not seen this file before.\n\n"
    "You are given every figure and finding the record contains. Join them "
    "into two or three short sentences of plain English.\n\n"
    "Rules, all absolute:\n"
    "- Use only what you are given. Never state a figure, date, name or "
    "finding that is not in the material.\n"
    "- Never conclude. No risk rating, no recommendation, no judgement "
    "about whether the party is acceptable. A person decides that.\n"
    "- Never reassure. Do not write that anything looks fine, appears "
    "legitimate, or is low risk.\n"
    "- Plain words. No jargon, no abbreviations the reader would have to "
    "look up.\n"
    "- Never repeat an identifying number, a passport or document "
    "number, a postal address or an email address. Say what kind of "
    "thing is held, and let the reader open the record for the value. "
    "Dates of birth, nationalities, names and amounts you may state.\n\n"
    'Reply as JSON: {"summary": "<your two or three sentences>"}'
)

#: Phrases that mean the model concluded something. Checked because the
#: instruction not to is the one it is most likely to drift past, and the
#: drift is always in the same direction -- toward reassurance.
CONCLUDED = (
    "low risk", "high risk", "medium risk", "appears legitimate",
    "no concerns", "no issues", "satisfactory", "acceptable",
    "recommend", "should be approved", "should be rejected",
    "can be onboarded", "appears clean", "nothing of concern",
    "no red flags", "compliant with",
)


@dataclass(frozen=True)
class Opening:
    """A written opening, or the reason there is none."""

    summary: str = ""
    #: Empty where the summary stands. Otherwise why it was thrown away,
    #: in words, so the absence is legible rather than mysterious.
    withheld: str = ""


#: A run of digits shaped like a date, which is the one case where the
#: pieces are worth keeping on their own: a summary may name the year out of
#: a date the record gives in full.
_DATE_SHAPED = re.compile(r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}")


def figures_in(text: str) -> set:
    """Every figure in this text, as values rather than as digit fragments.

    It used to split on commas, so "1,250,000" was kept as {1, 250, 000} and
    the amount itself was never held at all. Against a record reading
    "Received USD 1,797,478", a summary claiming USD 1,797,000 -- or USD
    1,000,000 -- passed as nothing invented, because every fragment of the
    invention was a fragment of the truth. Money is the thing on these
    records most worth getting right.
    """
    out = set()
    for raw in _FIGURE.findall(text or ""):
        raw = raw.strip().rstrip(".")
        if not raw:
            continue
        out.add(raw)
        if _DATE_SHAPED.fullmatch(raw):
            out.update(part for part in re.split(r"[-/]", raw) if part)
            continue
        out.add(raw.replace(",", ""))
    return out


def invented(summary: str, given: str) -> list:
    """Figures in the summary that were not in the material.

    Only digits are policed. A model paraphrasing "several investors" is
    doing its job; a model producing a passport number nobody supplied is
    fabricating a regulatory record.
    """
    allowed = figures_in(given)
    out = []
    # Walked as it was written rather than through the normalised set, so a
    # reader is shown the figure the summary actually contains and shown it
    # once -- not "1,797,000" and "1797000" as two separate inventions.
    seen: set = set()
    for raw in _FIGURE.findall(summary or ""):
        part = raw.strip().rstrip(".")
        if not part or part in seen:
            continue
        seen.add(part)
        if part in allowed or part.replace(",", "") in allowed:
            continue
        # Single digits are counting words -- "two sections" -- not figures.
        # The exemption used to run to thirty-one, and a substring rule sat
        # under it letting any fragment of a supplied figure through: "197"
        # passed on "1978", and "1,797,000" on "1,797,478". Both are gone.
        # A year still passes on its own because a date-shaped run keeps its
        # parts, which is a rule about dates rather than about any figure
        # that happens to be short.
        if len(part) == 1 and part.isdigit():
            continue
        out.append(part)
    return out


def concluded(summary: str) -> list:
    low = (summary or "").lower()
    return [phrase for phrase in CONCLUDED if phrase in low]


#: The most of one party's record that is handed to the model.
#:
#: This was a bare ``[:12000]`` at the end of the function -- no name, no
#: comment, no marker -- so a busy record was cut mid-line with nothing to
#: say it had been. Measured: one party paying a fortnightly capital call
#: reaches the cap at roughly **200 dated lines**, and what is lost is the
#: tail, which on today's section ordering is "What is still open" -- the
#: section that says the party has an unsettled sanctions file. Compare
#: ``ask.MAX_RESULT_CHARS``, which is named, explained, and appends a visible
#: marker so the model can say the record was shortened. It does say so,
#: live. This one could not.
MAX_MATERIAL_CHARS = 12_000

#: Appended when the cap bites, so the model can tell the reader.
SHORTENED = "\n\n(This record is longer than can be shown here. Sections "\
            "after this point were not included.)"


def material(doc) -> str:
    """Everything the record holds, as the model sees it.

    Assembled from the rendered sections rather than from the projections,
    so the model is given exactly what the reader is given. A summary drawn
    from richer material than the page shows would describe a document
    nobody else can see.
    """
    lines = [f"Party: {doc.title}", f"Kind: {doc.kind}"]
    for part in doc.parts:
        # The seal — how many records this was built from and whether the
        # chain verifies — is on the page already and is about the document
        # rather than the party. Given it, the model dutifully wrote it
        # into every summary: "built from 4 records within a log of 1,638".
        # Not wrong, and not what somebody opening a file wants first.
        if part.heading in SKIP:
            continue
        lines.append("")
        lines.append(part.heading + ":")
        if part.lead:
            lines.append("  " + part.lead)
        for fact in part.facts:
            lines.append(f"  - {fact.label}: {fact.value}"
                         + (f" ({fact.note})" if fact.note else ""))
        for entry in part.entries:
            lines.append(f"  - {entry.when} {entry.what}"
                         + (f" [{entry.who}]" if entry.who else ""))
    whole = "\n".join(lines)
    if len(whole) <= MAX_MATERIAL_CHARS:
        return whole
    return whole[:MAX_MATERIAL_CHARS] + SHORTENED


def recorded_opening(engine, entity_id: str) -> Optional[Opening]:
    """The opening already written for this party, if one has been.

    The paragraph used to be regenerated on every page view and every print,
    and recorded nowhere. Three consecutive views of an identical, unchanged
    record -- at temperature 0, top_p 1, seed 7 -- produced three materially
    different paragraphs, and one of them printed the raw values ("12 Marine
    Drive, Mumbai; rohan@example.com; date of birth 1978-04-12; ... K9930147")
    that the other two summarised. Nothing was written either way: not the
    paragraph, and not the ``withheld`` sentence when a guard fired -- while
    every withheld answer at the ask boundary is recorded, on the stated
    ground that a guard which fires silently is a guard nobody can audit.

    So it is written once and read thereafter, which also takes a model call
    out of the latency of every record page.
    """
    from .model import EventType

    for event in reversed(list(engine.log)):
        if (event.event_type is EventType.RECORD_OPENING_WRITTEN
                and event.subject == entity_id):
            payload = event.payload or {}
            return Opening(summary=str(payload.get("summary") or ""),
                           withheld=str(payload.get("withheld") or ""))
    return None


def record_opening(engine, entity_id: str, opening: "Opening", *,
                   written_at: str, model: str = "", region: str = "",
                   tokens_in: int = 0, tokens_out: int = 0,
                   cost_usd: float = 0.0):
    """Put the paragraph, or the reason there is none, on the log."""
    from .model import EventType

    return engine.ingest(
        event_type=EventType.RECORD_OPENING_WRITTEN,
        subject=entity_id,
        occurred_at=written_at,
        actor="assistant",
        payload={
            "summary": opening.summary,
            "withheld": opening.withheld,
            "model": model,
            "region": region,
            "prompt_version": PROMPT_VERSION,
            "input_tokens": int(tokens_in),
            "output_tokens": int(tokens_out),
            "cost_usd": round(float(cost_usd), 6),
        },
    )


def _prompt_version() -> str:
    """Derived, never typed -- the same reason ``assist._prompt_version`` is.

    An inspector asking "which prompt wrote the paragraph at the top of this
    record" gets an answer that cannot disagree with the prompt it names.
    """
    import hashlib

    return "opening." + hashlib.sha256(
        INSTRUCTION.encode("utf-8")).hexdigest()[:8]


PROMPT_VERSION = _prompt_version()


def opening_for(doc, transport=None) -> Opening:
    """Two or three sentences at the top of a record, or nothing.

    Nothing is a normal outcome and carries no apology. A record without a
    paragraph is a record; a record with a fabricated one is a liability.
    """
    if transport is None:
        return Opening()

    given = material(doc)
    try:
        reply, _in, _out = transport([
            {"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": given},
        ])
    except Exception:
        return Opening()

    summary = ""
    if isinstance(reply, dict):
        summary = str(reply.get("summary") or "").strip()
    if not summary:
        return Opening()

    made_up = invented(summary, given)
    if made_up:
        return Opening(withheld=(
            "A written summary was prepared and thrown away: it contained "
            + ("a figure" if len(made_up) == 1 else "figures")
            + " this record does not hold ("
            + ", ".join(made_up[:4]) + "). The sections below are unaffected."))

    drew = concluded(summary)
    if drew:
        return Opening(withheld=(
            "A written summary was prepared and thrown away: it drew a "
            "conclusion rather than describing the file. That is a "
            "person's to make, not the assistant's. The sections below "
            "are unaffected."))

    return Opening(summary=summary)
