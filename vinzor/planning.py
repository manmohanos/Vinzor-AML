"""Turning what somebody typed into a plan the agents can actually run.

The piece that makes this a system you can talk to rather than a menu you
pick from. An officer writes "check whether anyone on the book is on a
sanctions list and whether we have papers for them", and the model turns it
into steps: screen, then readiness.

**The model chooses which tools to run. It never says what they found.**
That division is the whole design and it is not a matter of taste. A
language model asked to assess a customer will produce a fluent assessment
whether or not the evidence supports one, and a fluent wrong answer on a
compliance record is worse than no answer -- it is the failure this product
was built to prevent. So the model is given a job it is genuinely good at,
which is reading intent and picking from a fixed list, and kept away from
the one it is bad at, which is deciding facts.

Everything downstream of the plan is deterministic. Screening is the same
screening the queue runs, resolution the same resolver, ownership the same
walk. If the model picks the wrong tools, the worst case is a person
watching work they did not want and saying so. It cannot be the case that
the model invents a sanctions hit, because nothing it returns is ever
treated as a finding.

**A tool it made up is dropped and the drop is reported.** Models
occasionally answer with a plausible tool that does not exist. Quietly
skipping it would leave a plan that looks shorter than what was asked for,
with no way to tell why, so anything unrecognised is named on screen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from .agents import TOOLS

#: Kept short deliberately. Every extra instruction is another thing the
#: model can weigh against the one rule that matters, which is that it
#: chooses tools and reports nothing.
INSTRUCTION = (
    "You route requests at a compliance system for a fund manager in GIFT "
    "City, India, regulated by IFSCA. An officer has typed something. Your "
    "only decision is which of two things should happen.\n\n"
    "THE READER answers from what the workspace already holds. It can look "
    "up a party, read an open file, list what is overdue, quote a clause "
    "and explain why something was flagged. It replies in seconds and runs "
    "nothing. Choose it with kind=\"answer\" whenever the officer is "
    "*asking about* something: what, who, why, when, how many, is there, "
    "show me, explain.\n\n"
    "THE AGENTS do work that takes real time and that the officer watches: "
    "screening every party against four million watchlist entries, "
    "measuring the whole book, assembling a report. Choose them with "
    "kind=\"work\" only when the officer is *asking for something to "
    "be done*: run, check all, screen everyone, prepare, build.\n\n"
    "The reader is the default and by a wide margin. Reading is instant "
    "and costs nothing; starting a job nobody asked for costs an officer "
    "their attention and makes them wait. \"What am I late on\" and "
    "\"who is on a watchlist\" are questions about what is already "
    "known, and the reader answers both. Choose work only when the request "
    "cannot be answered without something being run first.\n\n"
    "When you choose work, pick tools from the list and put them in a "
    "sensible order. You never state findings, never assess a customer and "
    "never invent figures: the reader and the tools do all of that.\n\n"
    "Reply as JSON only:\n"
    '{"kind": "answer" | "work", ' 
    '"steps": [{"tool": "<name from the list>", ' 
    '"agent": "<two or three words naming what this step is for>"}], ' 
    '"said": "<one sentence to the officer saying what you are about to ' 
    'do; empty when kind is answer>", ' 
    '"refused": "<empty, or one sentence if neither can help>"}' + "\n\n"

    "Give steps only when kind is \"work\". Never invent a tool."
)


@dataclass(frozen=True)
class Plan:
    """What the model made of a request."""

    steps: tuple = ()
    #: One sentence back to the officer, in the model's words.
    said: str = ""
    #: Set where the request cannot be answered with the tools there are.
    refused: str = ""
    #: Tools the model asked for that do not exist. Named rather than
    #: silently dropped.
    invented: tuple = ()
    #: True where no model was reachable and this came from the fallback.
    guessed: bool = False
    #: "answer" where the officer asked about something already known and
    #: the record can simply be read, "work" where something has to be
    #: run. Routing rather than planning, and it is one call with the
    #: planning because the model has to read the request either way.
    kind: str = "work"


def _short(label: str, most: int = 26) -> str:
    """A label cut at a word rather than mid-syllable.

    "Check regulator corresponden" is what cutting on a character count
    produces, and a screen that does that once is a screen somebody stops
    reading carefully.
    """
    label = " ".join(label.split())
    if len(label) <= most:
        return label
    cut = label[:most].rsplit(" ", 1)[0]
    return cut or label[:most]


def tool_menu() -> str:
    """The tools, as the model sees them."""
    return "\n".join(f"- {name}: {tool.about}"
                     for name, tool in TOOLS.items())


#: The most steps a model-composed plan may have.
#:
#: There was no bound at all, and the whole plan goes into one permanent
#: event. A transport returning 2,000 steps produced a 155 KB TASK_GIVEN
#: payload, 2,002 permanent events, and a workspace file that grew by a
#: megabyte -- with the cheapest tool. With the screening tool each of those
#: steps is 3.5-7.7 seconds and forty watchlist round trips, and there is no
#: way to stop a run once it has started. The discipline already exists one
#: file over: ``agents._screen_everyone`` caps at forty and says so in words.
#: Twelve is more steps than any of the five shipped recipes has.
MOST_STEPS = 12


def _from_reply(reply: Mapping) -> Plan:
    wanted = reply.get("steps")
    steps, invented, dropped = [], [], 0
    for one in (wanted if isinstance(wanted, list) else []):
        if not isinstance(one, dict):
            continue
        name = str(one.get("tool") or "").strip()
        if name not in TOOLS:
            if name:
                invented.append(name)
            continue
        if len(steps) >= MOST_STEPS:
            dropped += 1
            continue
        agent = str(one.get("agent") or "").strip() or name.title()
        steps.append({"tool": name, "agent": _short(agent),
                      "says": TOOLS[name].says})
    kind = str(reply.get("kind") or "").strip().lower()
    if kind not in ("answer", "work"):
        # An unrecognised kind is treated as a question, which is the
        # cheaper mistake: reading the record and replying costs seconds,
        # and starting work nobody asked for costs their attention.
        kind = "answer" if not steps else "work"
    said = str(reply.get("said") or "")[:400]
    if dropped:
        # Said on screen, the way an invented tool is said on screen. A cap
        # that is not mentioned is a hidden limit.
        said = (f"{said} This job was cut to the first {MOST_STEPS} steps; "
                f"{dropped} more were left out.").strip()
    return Plan(
        steps=tuple(steps),
        said=said[:400],
        refused=str(reply.get("refused") or "")[:400],
        invented=tuple(invented),
        kind=kind,
    )


#: Words that suggest a tool when there is no model to ask. Not clever and
#: not pretending to be: it is a keyword match, and a plan built this way
#: says so on screen so nobody mistakes it for reasoning.
HINTS: Mapping[str, tuple] = {
    "screen": ("screen", "sanction", "watchlist", "pep", "politically",
               "check the names", "list"),
    "duplicates": ("duplicate", "same party", "twice", "resolve", "match"),
    "readiness": ("ready", "5.4.2", "missing", "complete", "hand over",
                  "kyc", "identification", "document"),
    "ownership": ("owner", "ubo", "beneficial", "structure", "control"),
    "payments": ("payment", "transaction", "monitoring", "money", "transfer"),
    "letters": ("letter", "notice", "regulator wrote", "correspondence",
                "ifsca asked"),
    "firm": ("capital", "net worth", "our own", "the firm"),
    "report": ("report", "quarter", "board", "summary of the book"),
}


def without_a_model(asked: str) -> Plan:
    """A plan from keywords, clearly labelled as one.

    The honest fallback. It is not reasoning and does not claim to be --
    ``guessed`` is set and the screen says the request was matched on words
    rather than understood.
    """
    text = (asked or "").lower()
    steps = []
    for name, words in HINTS.items():
        if any(word in text for word in words):
            steps.append({"tool": name, "agent": name.title(),
                          "says": TOOLS[name].says})
    if not steps:
        return Plan(
            refused="Nothing in that matched a job this can do. Try naming "
                    "what you want looked at — screening, ownership, "
                    "documents, payments, letters from the regulator, or "
                    "the firm's own position.",
            guessed=True)
    return Plan(
        steps=tuple(steps),
        said="Matched on the words in your request rather than understood, "
             "because no assistant is configured. These are the tools that "
             "seem to fit.",
        guessed=True, kind="work")


def plan_from(asked: str, transport=None) -> Plan:
    """A plan for what somebody typed.

    ``transport`` is the model. Where none is given or it cannot be
    reached, the keyword fallback answers and says that is what happened --
    a system that silently degrades from reasoning to string matching is
    one nobody can calibrate their trust against.
    """
    asked = (asked or "").strip()
    if not asked:
        return Plan(refused="Nothing was asked.")

    if transport is None:
        return without_a_model(asked)

    try:
        reply, _tokens_in, _tokens_out = transport([
            {"role": "system", "content": INSTRUCTION + "\n\nTools:\n"
                                          + tool_menu()},
            {"role": "user", "content": asked[:2000]},
        ])
    except Exception:
        return without_a_model(asked)

    plan = _from_reply(reply if isinstance(reply, dict) else {})
    if plan.kind == "answer":
        return plan
    if not plan.steps and not plan.refused:
        return Plan(
            refused="The assistant did not choose any of the available "
                    "tools for that. Try naming what you want looked at.",
            invented=plan.invented)
    return plan
