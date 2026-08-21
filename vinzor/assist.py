"""Assisted review — a model drafts, a person decides.

The seam the architecture was shaped around, finally filled. A drafter reads a
Case, writes what it would say, and records that as a fact. It cannot decide
anything: a model is not an enrolled actor, so the human gate refuses it
without needing a single new restraint (DESIGN.md, decision 4).

Three rules make this safe enough for a regulatory file:

1. **The model never sees the raw file.** It is handed the *computed*
   comparison from ``compare.py`` — names, dates and numbers already
   established by deterministic code. It judges significance and writes prose;
   it does not establish facts.
2. **A draft that invents a fact is destroyed, not shown.** Every date and
   number in the draft is checked against the comparison it was given. One
   invention and the officer sees "no draft available" instead. A fabricated
   passport number in a compliance record is worse than no help at all.
3. **Failure is silent and cheap.** No model, no budget, bad output — the
   officer works exactly as they do today, and nothing is written.

Drafting happens at a boundary, never in the write path. Like
``observe_deadlines``, it is a separate call: a slow model can never delay a
page or a decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from .compare import Comparison, comparison_for
from .countries import name_of as _country_name
from .model import DraftUse, EventType, Outcome

#: The date this prompt design was settled. Names the *generation*, not the
#: exact text -- the text is fingerprinted separately below, because a
#: hand-maintained constant is a promise somebody eventually forgets to keep.
PROMPT_RELEASE = "2026-08-12"

#: What a draft may recommend. Deliberately not the same words as a decision
#: outcome -- a recommendation is not a decision, and the vocabulary should not
#: let anyone confuse them.
RECOMMENDATIONS = ("LIKELY_NOT_THE_SAME", "POSSIBLY_THE_SAME", "CANNOT_TELL")

#: Spend ceiling in US dollars, across the whole workspace. Costs are events,
#: so the running total is summed from the log and cannot drift.
DEFAULT_BUDGET_USD = 50.0


class DraftingUnavailable(RuntimeError):
    """No draft could be produced. Nothing is recorded and nothing breaks."""


class DraftRejected(DraftingUnavailable):
    """The model asserted something it was not given. The draft is destroyed."""


@dataclass(frozen=True)
class Draft:
    case_id: str
    recommendation: str
    reasoning: str
    suggested_wording: str
    checks: tuple[str, ...]
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    region: str


# ---------------------------------------------------------------------------
# The instructions
# ---------------------------------------------------------------------------

INSTRUCTIONS = """\
You are helping a compliance officer at an investment fund in GIFT City, India \
review a possible sanctions or PEP match. The officer is a finance or legal \
professional, not a technologist.

You have been given a comparison that has ALREADY been computed by \
deterministic software. Every name, date and number you may use appears in it.

Rules you must follow:
- Never state a date, number, name or fact that is not in the comparison. If \
you need something you were not given, say it is not on file.
- You are not deciding anything. A human decides. Recommend, and say why.
- Absence of data is not evidence. "No date of birth on the watchlist entry" \
means unknown, not different.
- Write for a person reading quickly. Short sentences. No jargon, no bullet \
symbols, no headings, no markdown.
- Do not mention artificial intelligence, models, prompts, scores or software.

Reply with JSON only, matching this shape exactly:
{"recommendation": one of LIKELY_NOT_THE_SAME | POSSIBLY_THE_SAME | CANNOT_TELL,
 "reasoning": "two or three sentences explaining what matches and what does not, \
and what that means",
 "suggested_wording": "one or two sentences the officer could use verbatim as \
their written reason, in the first person",
 "checks": ["at most three short things to verify before deciding"]}\
"""


def _prompt_version() -> str:
    """A stamp that cannot disagree with the prompt it names.

    This was a hand-maintained constant, and the audit trail's answer to
    "which prompt wrote this recommendation" was therefore only as good as
    somebody's memory: edit ``INSTRUCTIONS`` without bumping the constant and
    every draft afterwards carries a version that never existed. In a log that
    refuses UPDATE and DELETE, that misinformation is permanent -- there is no
    later correction to make.

    So the stamp is derived from the thing it describes. The release date
    stays for readability; the digest is over the instruction text and the
    recommendation vocabulary, which together are what a change to the prompt
    would alter. Change either and the stamp changes on its own, without
    anyone remembering to do anything.
    """
    body = INSTRUCTIONS + "\n" + "|".join(RECOMMENDATIONS)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    return f"{PROMPT_RELEASE}.{digest}"


#: Recorded on every draft. Derived, never typed.
PROMPT_VERSION = _prompt_version()


#: Fields whose ``ours``/``theirs`` values are ISO country codes, not words.
#: Mirrors ``briefing._COUNTRY_ROWS`` -- the same translation the officer's
#: own screen applies, kept in step so the model is reading what a person
#: would read, not what the wire protocol happens to carry.
_COUNTRY_FIELDS = frozenset({"nationality", "country"})


def _readable(field: str, value: str) -> str:
    """A field value as a person would read it.

    A live deployment surfaced this directly: handed raw ``ours is IN;
    theirs is RU``, the model faithfully repeated the codes verbatim --
    "the nationalities, IN and RU, are different" -- straight into text an
    officer could paste as their own written reason. Nothing there was
    invented, so the figures guard had nothing to catch; the codes were
    implementation vocabulary reaching a reader through the model's mouth
    instead of a fabricated fact. Translating before the prompt is built
    closes that without touching the guard, exactly as compare.py stays
    silent about presentation and leaves it to the surface that renders for
    a reader (DESIGN.md decision 6).
    """
    if not value:
        return value
    if field in _COUNTRY_FIELDS:
        return _country_name(value)
    # And dates. ``briefing._side`` applies *two* translations and says so in
    # its own docstring -- "a date becomes a date they would say aloud, and a
    # country code becomes a country" -- and this applied only the second. So
    # the model was handed "ours is 1978-04-12; theirs is 1961-03-03" for a
    # comparison the officer was reading as "12 April 1978" against "3 March
    # 1961". Reusing briefing's own helper keeps the two in step by
    # construction rather than by comment, which is what the comment above
    # already claims.
    from .briefing import _date

    said = _date(value)
    return said if said != value else value


def build_prompt(comparison: Comparison) -> list[dict[str, str]]:
    """The two messages sent to the model. Deterministic for a given input."""
    lines = [
        f"Our investor: {comparison.our_name}",
        f"Listed party: {comparison.listed_name}",
        f"Appears on: {', '.join(comparison.listed_on) or 'an unnamed list'}",
        "",
        "Field by field:",
    ]
    for item in comparison.fields:
        ours = _readable(item.field, item.ours) or "not on file"
        theirs = _readable(item.field, item.theirs) or "not on the watchlist entry"
        lines.append(
            f"- {item.field}: ours is {ours}; theirs is {theirs}. "
            f"{item.verdict.value.lower()} — {item.note}"
        )
    return [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": "\n".join(lines)},
    ]


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

#: Anything that looks like a figure a regulator would care about.
#:
#: Deliberately **not** anchored on word boundaries. It was, once, and that made
#: the guard blind to exactly the shape it most needed to catch: an Indian
#: passport is a letter followed by seven digits, so ``K9930147`` has no word
#: boundary before its digits and sailed straight through. A model could invent
#: a passport number and have it written permanently to a compliance record.
#: A PAN (``ABCDE1234F``) had the same hole. Digits are policed wherever they
#: appear, attached to letters or not.
_FIGURE = re.compile(r"\d[\d,\-/]*")

#: Vocabulary that means the draft has started talking about itself, or about
#: software, instead of about the file. The instructions forbid it; instructions
#: are not a control, so this is. A regulator reading "as an AI language model"
#: in a compliance file learns something about the firm, not about the investor.
_OFF_LIMITS = re.compile(
    r"as an ai\b|\ban ai\b|language model|artificial intelligence|machine "
    r"learning|\balgorithm|confidence score|match score|\bjson\b|\bprompt\b|"
    r"i cannot assist|i am unable to",
    re.IGNORECASE,
)

#: Formatting characters, not facts. Stripped rather than rejected -- a good
#: draft wrapped in asterisks is still a good draft, whereas an invented
#: passport number is not repairable.
_MARKUP = re.compile(r"[*#`_]{1,}")


def _plain(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _MARKUP.sub("", text)).strip()


#: A run of digits shaped like a date. See :func:`invented_figures`.
_DATE_SHAPED = re.compile(r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}")

_MONTHS = {name.lower(): number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"), start=1)}
_MONTHS.update({name[:3]: number for name, number in list(_MONTHS.items())})

#: A date written the way a person writes one: "12 April 1978", "4 Dec 1978".
_DATE_IN_WORDS = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b")


def dates_in(text: str) -> set:
    """Every date in this text, normalised, however it was written.

    Figures alone cannot see a date, and a date is where the drafting guard
    was walked past. Both sides of a comparison say 1978-04-12; a draft
    clearing the match "because our investor was born on 12 April 1978 and
    the listed party on 4 December 1978" contains only the digits 12, 4 and
    1978, every one of them a digit of the true date. The invention is in
    the *arrangement*, and only reading it as a date can see that.
    """
    found = set()
    for day, month, year in _DATE_IN_WORDS.findall(text or ""):
        number = _MONTHS.get(month.lower()) or _MONTHS.get(month.lower()[:3])
        if number:
            found.add(f"{int(year):04d}-{number:02d}-{int(day):02d}")
    for raw in _DATE_SHAPED.findall(text or ""):
        parts = [int(one) for one in re.split(r"[-/]", raw) if one]
        if len(parts) != 3:
            continue
        if parts[0] > 31:                       # year first
            year, month, day = parts
        else:                                   # day first, as India writes it
            day, month, year = parts
        if 1 <= month <= 12 and 1 <= day <= 31 and year > 1000:
            found.add(f"{year:04d}-{month:02d}-{day:02d}")
    return found


def invented_figures(text: str, comparison: Comparison) -> list[str]:
    """Figures in ``text`` that were not in the comparison it was given.

    Only digits are policed. Words are left alone: a model paraphrasing
    "different countries" is doing its job, but a model producing a passport
    number nobody supplied is fabricating a regulatory record.

    **A figure is compared as a value, not as a bag of digits.** This split
    every run on commas, hyphens and slashes and checked the pieces, so a
    date was never checked as a date: given a record and a listing that both
    say 1978-04-12, a draft clearing the match because "our investor was
    born on 12 April 1978 and the listed party on 4 December 1978" passed
    with nothing invented -- every digit of the fabricated date is a digit
    of the true one. The same split let an amount through: 1,797,000 is
    three fragments of 1,797,478.
    """
    allowed = set(comparison.facts)
    # The parts of a date on their own, because a draft may name the year
    # out of a date the comparison gives in full. Only for date-shaped runs:
    # this is a rule about dates, not a licence for any short figure.
    for fact in comparison.facts:
        if _DATE_SHAPED.fullmatch(str(fact).strip()):
            allowed.update(part for part in re.split(r"[-/]", str(fact).strip())
                           if part)
        allowed.add(str(fact).replace(",", ""))

    invented = []

    # Dates first, read as dates. A date the comparison never gave is an
    # invention however its digits happen to overlap with one it did.
    # Read from the field values themselves, not from ``facts`` -- ``facts``
    # is already atomised into digit runs, so no whole date survives in it
    # and there would be nothing for a date to match against.
    given_dates = set()
    for item in getattr(comparison, "fields", ()):
        for side in (item.ours, item.theirs, item.note):
            given_dates |= dates_in(str(side or ""))
    for written in sorted(dates_in(text)):
        if written not in given_dates:
            invented.append(written)

    seen: set = set()
    for raw in _FIGURE.findall(text):
        part = raw.strip().rstrip(".")
        if not part or part in seen:
            continue
        seen.add(part)
        if part in allowed or part.replace(",", "") in allowed:
            continue
        if _DATE_SHAPED.fullmatch(part) and all(
                piece in allowed for piece in re.split(r"[-/]", part) if piece):
            continue
        # Single digits are counting words ("two documents"), not figures.
        # The exemption used to run to thirty-one, which is every day of a
        # month and every small count a fabricated sentence needs.
        if len(part) == 1 and part.isdigit():
            continue
        invented.append(part)
    return sorted(set(invented))


def parse_reply(payload: Mapping[str, Any], comparison: Comparison) -> dict[str, Any]:
    """Validate a model reply, or raise. Never returns something unchecked."""
    recommendation = str(payload.get("recommendation", "")).strip().upper()
    if recommendation not in RECOMMENDATIONS:
        raise DraftRejected(f"unrecognised recommendation {recommendation!r}")

    reasoning = _plain(str(payload.get("reasoning", "")))
    wording = _plain(str(payload.get("suggested_wording", "")))
    if len(reasoning) < 20 or len(wording) < 20:
        raise DraftRejected("the draft was too short to be useful")

    checks = tuple(
        _plain(str(c)) for c in (payload.get("checks") or []) if _plain(str(c))
    )

    whole = " ".join([reasoning, wording, *checks])
    invented = invented_figures(whole, comparison)
    if invented:
        raise DraftRejected(
            f"the draft asserted figures it was not given: {', '.join(invented)}"
        )
    talking_about_itself = _OFF_LIMITS.search(whole)
    if talking_about_itself:
        raise DraftRejected(
            f"the draft used words that do not belong in a compliance file: "
            f"{talking_about_itself.group(0)!r}"
        )
    return {"recommendation": recommendation, "reasoning": reasoning,
            "suggested_wording": wording, "checks": checks[:3]}


# ---------------------------------------------------------------------------
# The drafter
# ---------------------------------------------------------------------------

#: Takes the messages, returns (reply dict, input tokens, output tokens).
Transport = Callable[[Sequence[Mapping[str, str]]], tuple[Mapping[str, Any], int, int]]


@dataclass(frozen=True)
class Drafter:
    """A model behind a transport. The transport is injected, so every test
    runs offline against canned replies and none touches the network."""

    transport: Transport
    model: str
    region: str
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0

    def draft(self, case_id: str, comparison: Comparison) -> Draft:
        reply, tokens_in, tokens_out = self.transport(build_prompt(comparison))
        checked = parse_reply(reply, comparison)
        cost = (tokens_in / 1000 * self.cost_per_1k_input
                + tokens_out / 1000 * self.cost_per_1k_output)
        return Draft(
            case_id=case_id,
            model=self.model,
            region=self.region,
            prompt_version=PROMPT_VERSION,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=round(cost, 6),
            **checked,
        )


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


#: Every event that can carry a model bill. Both halves of the assistant are
#: here on purpose: the ceiling is described as covering the workspace, and
#: for a while it covered only the drafting half -- the half no officer
#: drives -- while the ask box on every screen spent against nothing.
_COSTS_MONEY = (EventType.DRAFT_PREPARED, EventType.ASSISTANT_ASKED,
                EventType.RECORD_OPENING_WRITTEN)


def spent_so_far(engine) -> float:
    """Total model spend in this workspace, summed from the log."""
    return round(sum(
        float(event.payload.get("cost_usd") or 0.0)
        for event in engine.log
        if event.event_type in _COSTS_MONEY
    ), 6)


def already_drafted(engine) -> set[str]:
    return {
        str(event.payload.get("case_id"))
        for event in engine.log
        if event.event_type is EventType.DRAFT_PREPARED
    }


def prepare_drafts(
    engine,
    *,
    prepared_at: str,
    drafter: Drafter,
    limit: int = 10,
    budget_usd: float = DEFAULT_BUDGET_USD,
) -> list[Draft]:
    """Draft for open screening files that do not have one yet.

    A boundary call, like ``observe_deadlines``: the caller supplies the date,
    nothing here reads a clock. Returns the drafts written. One failure does
    not stop the others, and a failed draft records nothing at all.
    """
    done = already_drafted(engine)
    written: list[Draft] = []

    for case in engine.queue():
        if len(written) >= limit:
            break
        if case.case_id in done or case.case_type != "SCREENING_HIT":
            continue
        if spent_so_far(engine) >= budget_usd:
            break
        comparison = comparison_for(engine, case)
        if comparison is None:
            continue
        try:
            draft = drafter.draft(case.case_id, comparison)
        except DraftingUnavailable:
            continue  # nothing recorded; the officer simply gets no draft
        record(engine, draft, comparison, prepared_at=prepared_at)
        written.append(draft)
    return written


# ---------------------------------------------------------------------------
# What the officer did with it
# ---------------------------------------------------------------------------

#: The decisions that are *consistent* with each recommendation. ``CANNOT_TELL``
#: recommends nothing, so nothing can contradict it.
AGREES_WITH: Mapping[str, frozenset] = {
    "LIKELY_NOT_THE_SAME": frozenset({Outcome.APPROVE}),
    "POSSIBLY_THE_SAME": frozenset({Outcome.ESCALATE, Outcome.REJECT}),
    "CANNOT_TELL": frozenset({Outcome.APPROVE, Outcome.ESCALATE, Outcome.REJECT}),
}


def draft_use(case, outcome: Outcome, reported: str = "NONE") -> DraftUse:
    """Classify what happened to the draft on this Case.

    ``reported`` is what the screen says the officer did with the wording, and
    is taken at face value -- only they know whether they rewrote it. But
    *contradiction* is computed here from the record, not reported, because it
    is the number that would embarrass the firm and a client should not be the
    one deciding whether to admit it.
    """
    draft = getattr(case, "draft", None)
    if not draft:
        return DraftUse.NONE

    recommendation = str(draft.get("recommendation") or "")
    agreeable = AGREES_WITH.get(recommendation)
    if agreeable is not None and Outcome(outcome) not in agreeable:
        return DraftUse.CONTRADICTED

    try:
        used = DraftUse(str(reported).upper())
    except ValueError:
        used = DraftUse.NONE
    # A draft was on screen. "None" is not one of the things that can have
    # happened to it: they read it and wrote their own.
    return DraftUse.REJECTED if used is DraftUse.NONE else used


def record(engine, draft: Draft, comparison: Comparison, *, prepared_at: str):
    """Write the draft to the log as a fact about what the system said."""
    return engine.ingest(
        event_type=EventType.DRAFT_PREPARED,
        subject=comparison.subject,
        occurred_at=prepared_at,
        actor="assistant",
        payload={
            "case_id": draft.case_id,
            "recommendation": draft.recommendation,
            "reasoning": draft.reasoning,
            "suggested_wording": draft.suggested_wording,
            "checks": list(draft.checks),
            "model": draft.model,
            "region": draft.region,
            "prompt_version": draft.prompt_version,
            "input_tokens": draft.input_tokens,
            "output_tokens": draft.output_tokens,
            "cost_usd": draft.cost_usd,
            "comparison": comparison.as_dict(),
        },
    )
