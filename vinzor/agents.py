"""Work a person delegates, done by agents, visible while it happens.

The product could show what it had found and let somebody decide about it.
It could not be *given a job*. "Run a deep review on these fifty investors"
had no home: an officer did it a file at a time, and the system watched.

**What makes this honest rather than theatre.** Every step an agent takes
is a real call to a real tool -- the same screening the queue uses, the
same duplicate resolver, the same ownership walk, the same report writer.
Nothing here animates a progress bar over a sleep. A step that says it
screened forty-one parties screened forty-one parties, and the finding it
reports is the finding that went into the log.

That matters more here than in most products. A compliance officer who
learns that the moving bar is decoration has learned that the whole screen
might be, and the next thing they stop trusting is a sanctions match.

**Why the event log is the right substrate.** An agent run is a sequence of
things that happened, which is what this log already holds. So a run is not
a job queue with a status column; it is events. Three consequences fall
out, and they are the reason for the design:

* The progress a person watches is a projection of the record, so what
  they saw was true when they saw it and is still true a year later.
* A run replays. An inspector asking what the machine did on 3 March gets
  the same answer as the officer who watched it happen.
* It composes with the human gate already built. An agent can look, count,
  compare and draft. It cannot settle a file, because settling is a
  decision and the fold refuses decisions from anything not enrolled as a
  person. That refusal is not new code; the agent simply runs into it.

**On the model.** Most of what an agent does here needs no language model:
screening, resolution, ownership, document checks and report assembly are
deterministic and already built. A model is wanted for two things -- turning
a sentence into a plan, and writing narrative -- and where none is
configured those degrade to a fixed menu of recipes and to figures without
prose. What does not happen is a plan that pretends to have been reasoned.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from .model import EventType

#: How a step ended. ``looking`` is not stored -- it is what a step in the
#: plan with no result yet *is*, which keeps the record to things that
#: happened rather than to things that are still going on.
DONE = "done"
FOUND_SOMETHING = "found"
FAILED = "failed"

#: How many names one step may list before it says how many it left out.
#: A stated limit rather than a hidden one: the screening step used to cut
#: silently at eight, so a morning check that found twelve matched parties
#: named eight and dropped four -- two of them debarments -- with nothing on
#: the page or the record to say anything had been left out.
MOST_NAMES = 8
SKIPPED = "skipped"


@dataclass(frozen=True)
class Tool:
    """One thing an agent can actually do.

    ``says`` is written for the person watching, in the present continuous,
    because it appears on screen while the tool is running: "Checking 41
    parties against the watchlists".
    """

    name: str
    says: str
    #: What it is for, in a sentence, shown when somebody asks what this
    #: agent can do.
    about: str
    run: Callable[..., "Found"]


@dataclass(frozen=True)
class Found:
    """What a tool came back with."""

    #: One line for the activity panel: "41 checked, 3 possible matches".
    headline: str
    #: How it ended.
    how: str = DONE
    #: Anything a later step needs. Never shown raw.
    carried: Mapping[str, Any] = field(default_factory=dict)
    #: Lines a reader can act on, if the tool has any.
    details: tuple = ()


@dataclass(frozen=True)
class Step:
    """One planned thing, and what came of it once it ran."""

    number: int
    agent: str
    tool: str
    says: str
    #: Empty while this step has not run.
    headline: str = ""
    how: str = ""
    details: tuple = ()

    @property
    def finished(self) -> bool:
        return bool(self.how)


@dataclass(frozen=True)
class Task:
    """A job somebody gave the machine."""

    task_id: str
    asked: str
    asked_by: str
    given_at: str
    plan: tuple
    about: str = ""
    finished_at: str = ""
    outcome: str = ""
    #: Where it sits in the log. A task's ``occurred_at`` is a *date* -- the
    #: ledger checks dates, not timestamps -- so every job delegated on one
    #: day sorted equal, and Python's stable sort with ``reverse=True`` left
    #: same-day tasks in insertion order, oldest first. See :meth:`Runs.recent`.
    at: int = 0

    @property
    def running(self) -> bool:
        """No record of this ending. Not the same as "happening now".

        See :meth:`stopped`. This is the raw fact and stays the raw fact;
        what a screen says needs the date as well.
        """
        return not self.finished_at

    def stopped(self, today: str) -> bool:
        """Given on an earlier day and never finished, so it is not running.

        The work runs on a daemon thread. An ordinary clean shutdown kills
        it, and nothing records that it stopped -- so the projection turned
        "we have no record of this ending" into the present tense, for ever.
        Simulated with a normal interpreter exit one second into a morning
        check::

            after restart:  running True  how_far 0%
                            now doing "Checking parties against the
                            watchlists"

        The card sat under "Working now", the bar at 0%, and the browser
        re-fetched every 1,200 ms waiting for a thread that no longer
        existed. It survived restarts, so a workspace collected permanent
        phantom jobs an officer could not tell from live ones.

        This is the Ledger block's own lesson -- a chain cannot see its own
        tail, absence read as a positive state -- turning up again in the
        agent projection. The day is the evidence of life: a job given today
        may well still be running; one given before today, with nothing
        recorded since, is not.
        """
        return self.running and str(self.given_at)[:10] < str(today)[:10]

    @property
    def done_count(self) -> int:
        return sum(1 for step in self.plan if step.finished)

    @property
    def how_far(self) -> float:
        if not self.plan:
            return 1.0
        return self.done_count / len(self.plan)

    @property
    def now_doing(self) -> Optional[Step]:
        for step in self.plan:
            if not step.finished:
                return step
        return None


class ToolsCannotWrite(PermissionError):
    """A tool reached for a way of changing the workspace."""


class _ReadOnlyLog:
    """The log, readable and not appendable."""

    __slots__ = ("_log",)

    def __init__(self, log):
        object.__setattr__(self, "_log", log)

    def __iter__(self):
        return iter(self._log)

    def __len__(self):
        return len(self._log)

    def __getitem__(self, at):
        return self._log[at]

    def __getattr__(self, name):
        if name in ("append", "close"):
            raise ToolsCannotWrite(
                f"a tool tried to {name} on the log. Tools read; people and "
                f"the rules write."
            )
        return getattr(self._log, name)


class ReadOnly:
    """The workspace as a tool may see it: everything, changeable by nothing.

    **"An agent cannot settle a file" used to rest on nothing.** ``run_task``
    handed each tool the whole engine, and ``decide``'s ``actor`` is a free
    string the fold checks against the *payload*, never against the caller.
    So a tenth tool dropped into ``TOOLS`` that called
    ``engine.decide(actor="Meera Nair", role=Role.AML_OFFICER, ...)`` settled
    three files from inside a run::

        CASE_DECIDED events 4 -> 7
          actor='Meera Nair'  case_619146146fae  APPROVE
          actor='Meera Nair'  case_abc72aec015d  APPROVE
          actor='Meera Nair'  case_1091aad0e972  APPROVE
        chain verifies: True   replay agrees the file is settled: True

    Three files permanently approved, attributed to an officer who never
    touched them. And the guard the product cited against exactly this
    iterates ``ask.TOOLS`` -- the *assistant's* registry -- so a
    write-capable tool inserted into ``agents.TOOLS`` passed both of its
    tests untouched.

    The safety was real and it was a coincidence: nine hand-written functions
    happening not to write. It is structural now. An allowlist rather than a
    blocklist, because a blocklist has to be remembered every time the engine
    grows a method and this does not.
    """

    #: Everything a read needs. Measured across every module the tools reach
    #: through -- reporting, dossier, readiness, duplicates, evidence,
    #: quality, briefing, screening -- which touch exactly these and
    #: ``ingest``, the one deliberately absent.
    MAY_READ = frozenset({"state", "queue", "verify", "log"})

    __slots__ = ("_engine",)

    def __init__(self, engine):
        object.__setattr__(self, "_engine", engine)

    def __getattr__(self, name):
        if name not in self.MAY_READ:
            raise ToolsCannotWrite(
                f"a tool reached for {name!r}, which is not one of the things "
                f"a tool may use. Tools read the workspace; people and the "
                f"rules change it."
            )
        if name == "log":
            return _ReadOnlyLog(self._engine.log)
        return getattr(self._engine, name)

    def __setattr__(self, name, value):
        raise ToolsCannotWrite(
            f"a tool tried to set {name!r} on the workspace")


@dataclass
class Runs:
    """Every task given, and how far each has got."""

    tasks: dict = field(default_factory=dict)

    def apply(self, event) -> None:
        payload = event.payload or {}
        if event.event_type is EventType.TASK_GIVEN:
            plan = tuple(
                Step(number=index, agent=str(one.get("agent") or ""),
                     tool=str(one.get("tool") or ""),
                     says=str(one.get("says") or ""))
                for index, one in enumerate(payload.get("plan") or ())
            )
            self.tasks = {**self.tasks, event.subject: Task(
                task_id=event.subject,
                asked=str(payload.get("asked") or ""),
                asked_by=str(event.actor or ""),
                given_at=str(event.occurred_at)[:19],
                at=int(getattr(event, "seq", 0) or 0),
                about=str(payload.get("about") or ""),
                plan=plan,
            )}
            return

        standing = self.tasks.get(event.subject)
        if standing is None:
            return

        if event.event_type is EventType.TASK_STEP:
            number = int(payload.get("number", -1))
            plan = tuple(
                step if step.number != number else Step(
                    number=step.number, agent=step.agent, tool=step.tool,
                    says=step.says,
                    headline=str(payload.get("headline") or ""),
                    how=str(payload.get("how") or DONE),
                    details=tuple(payload.get("details") or ()),
                )
                for step in standing.plan
            )
            self.tasks = {**self.tasks,
                          event.subject: _with(standing, plan=plan)}
        elif event.event_type is EventType.TASK_FINISHED:
            self.tasks = {**self.tasks, event.subject: _with(
                standing,
                finished_at=str(event.occurred_at)[:19],
                outcome=str(payload.get("outcome") or ""))}

    def running(self) -> tuple:
        return tuple(t for t in self.tasks.values() if t.running)

    def stopped(self, today: str) -> tuple:
        """Jobs that were left mid-flight by a restart or a shutdown."""
        return tuple(t for t in self.tasks.values() if t.stopped(today))

    def recent(self, most: int = 20) -> tuple:
        """The newest first, and never dropping one that is still running.

        Both halves were wrong. The sort key was the day alone, so every job
        delegated today tied; a stable sort does not reverse equal elements,
        so among same-day tasks the "newest first" order was **insertion
        order, oldest first**, and the cap then cut the newest away. On a copy
        of the shipped workspace, starting 30 jobs in one day::

            of the 30 just started, 18 are not on the page at all
            last three cards shown: run 10, run 11, run 12

        The sharper version needs one click: at 24 same-day tasks, an officer
        pressing "Run the morning check" got a page with the new job missing,
        no running panel, and therefore no polling -- ``keepWatching()`` stops
        the moment no running card is in the document. The job ran to
        completion, landed on the log, and was never shown.

        The tie now breaks on the sequence number, which is what "newest"
        actually means in a log; and a running job is never cut, because a
        cap that hides work in progress is worse than a longer page.
        """
        newest = sorted(self.tasks.values(),
                        key=lambda t: (t.given_at, t.at), reverse=True)
        shown = list(newest[:most])
        seen = {t.task_id for t in shown}
        shown.extend(t for t in newest[most:]
                     if t.running and t.task_id not in seen)
        return tuple(sorted(shown, key=lambda t: (t.given_at, t.at),
                            reverse=True))


def _with(task: Task, **changes) -> Task:
    from dataclasses import replace
    return replace(task, **changes)


# ---------------------------------------------------------------------------
# what agents can actually do
# ---------------------------------------------------------------------------


def _screen_everyone(engine, **rest) -> Found:
    """Check parties on the book against the live watchlists.

    Bounded, and the bound is reported. Screening four million entities
    for every party takes real time, so a run does a slice and says how
    big the slice was -- a step that quietly stopped at forty would be
    read as "the book is clean".
    """
    import os

    from .model import EntityKind
    from .screening import WatchlistClient

    # A caller may hand one in. The step used to build its own and only its
    # own, which made every claim about what it records untestable without a
    # watchlist on the other end -- so the counting defect below sat in the
    # one step that talks to the outside world, unexamined.
    client = rest.get("client")
    if client is None:
        url = os.environ.get("VINZOR_SCREENING_URL", "")
        if not url:
            return Found(
                headline="no watchlist service is configured, so nothing was "
                         "checked",
                how=SKIPPED)
        client = WatchlistClient(
            url=url,
            api_key=os.environ.get("VINZOR_SCREENING_KEY", ""),
            scope=os.environ.get("VINZOR_SCREENING_SCOPE", "default"),
        )
    graph = engine.state.graph
    cap = int(rest.get("cap", 40))
    checked = matched = refused = 0
    why = ""
    lines = []
    for entity_id, entity in list(graph.entities.items()):
        if checked + refused >= cap:
            break
        name = (entity.name or "").strip()
        if not name:
            continue
        try:
            kind = entity.kind if isinstance(entity.kind, EntityKind)                 else EntityKind.UNKNOWN
            hits, _how = client.match(name=name, kind=kind)
        except Exception as broke:
            # Counted apart from the checks. This used to increment
            # ``checked`` before the call and swallow the failure, so a run
            # in which the watchlist refused every single request recorded
            # "40 of 218 checked, 0 worth a look" -- permanently, on the
            # log, in the words a clean pass uses. One character wrong in
            # an environment variable produced exactly that.
            refused += 1
            if not why:
                why = str(broke)
            continue
        checked += 1
        if hits:
            matched += 1
            said = str(getattr(hits[0], "list_type", "")).lower()
            lines.append(f"{name} — {said.replace('_', ' ') or 'a watchlist'}")
    total = len(graph.entities)
    said = f"{checked} of {total} checked, {matched} worth a look"
    if refused:
        said += f", {refused} could not be checked"
    if not checked and not refused:
        said = "nothing to check"
    elif not checked:
        said = f"none of {total} could be checked"

    kept = list(lines[:MOST_NAMES])
    if len(lines) > MOST_NAMES:
        # Said out loud. Twelve parties matched and eight were named, two of
        # the four dropped being debarments -- a silent cut in the one list
        # the step exists to produce.
        kept.append(f"and {len(lines) - MOST_NAMES} more that matched, "
                    f"not named here")
    if refused and why:
        kept.append(f"why the checks failed: {why}")
    if total > cap:
        kept.append(f"stopped at {cap} — a full pass of {total} is a longer job")

    return Found(
        headline=said,
        # A step that reached nothing has established nothing, whatever it
        # counted on the way.
        how=(FAILED if refused and not checked
             else FOUND_SOMETHING if matched else DONE),
        carried={"checked": checked, "matched": matched, "refused": refused},
        details=tuple(kept),
    )


def _find_duplicates(engine, **rest) -> Found:
    from .duplicates import over_the_book

    pairs = over_the_book(engine)
    return Found(
        headline=(f"{len(pairs)} pair may be the same party" if len(pairs) == 1
                  else f"{len(pairs)} pairs may be the same party" if pairs
                  else "no duplicates found"),
        how=FOUND_SOMETHING if pairs else DONE,
        carried={"pairs": len(pairs)},
        details=tuple(pair.because for pair in pairs[:6]),
    )


def _measure_readiness(engine, today: str = "", **rest) -> Found:
    from .readiness import measure

    found = measure(engine, today=today)
    short = len(found.short)
    # Across the whole book, not only the parties that are otherwise
    # complete. Counting only the complete ones reported zero on a book
    # where nobody is complete yet, which reads as "nothing to do".
    unevidenced = sum(1 for p in found.parties if p.unsupported)
    return Found(
        headline=f"{len(found.ready)} of {len(found.parties)} complete, "
                 f"{unevidenced} held without a document behind it",
        how=FOUND_SOMETHING if short or unevidenced else DONE,
        carried={"ready": len(found.ready), "short": short},
        details=tuple(
            f"{clause}: {count} parties"
            for clause, count in sorted(found.by_clause.items(),
                                        key=lambda kv: -kv[1])[:6]),
    )


#: How many ownership structures one pass follows. A stated limit: the walk
#: used to take the first sixty entities of *any* kind, in registration
#: order, and call them structures. On a real book that was one structure
#: and fifty-nine natural people -- who have no ownership chain, so nothing
#: could be incomplete -- and the step recorded "60 structures followed,
#: none could not be completed" while eighty-three structures it never
#: looked at held eighteen broken chains.
MOST_STRUCTURES = 60

#: The kinds that have an ownership chain at all. A natural person is their
#: own beneficial owner; walking one and counting it as a structure followed
#: is how the count above came to mean nothing.
#:
#: Named rather than imported, because ``model`` is imported inside the
#: functions here to keep this module's import graph shallow.
_STRUCTURAL = frozenset({"COMPANY", "PARTNERSHIP", "TRUST", "FUND",
                         "UNINCORPORATED_BODY"})


def _walk_ownership(engine, **rest) -> Found:
    graph = engine.state.graph
    looked = trouble = 0
    lines = []
    cap = int(rest.get("cap", MOST_STRUCTURES))
    structures = [eid for eid, one in graph.entities.items()
                  if str(getattr(one.kind, "value", one.kind)) in _STRUCTURAL]
    for entity_id in structures[:cap]:
        try:
            found = graph.resolve_ubo(entity_id)
        except Exception:
            continue
        looked += 1
        if found.missing_roles or found.cycles or found.dead_ends:
            trouble += 1
            name = graph.name_of(entity_id)
            if found.missing_roles:
                lines.append(f"{name}: nobody named as "
                             + ", ".join(found.missing_roles))
            elif found.cycles:
                lines.append(f"{name}: the ownership chain loops")
            else:
                lines.append(f"{name}: the chain runs out before a person")
    kept = list(lines[:MOST_NAMES])
    if len(lines) > MOST_NAMES:
        kept.append(f"and {len(lines) - MOST_NAMES} more with the same "
                    f"trouble, not named here")
    if len(structures) > cap:
        kept.append(f"stopped at {cap} — this book holds "
                    f"{len(structures)} structures")
    return Found(
        headline=(f"{looked} of {len(structures)} structures followed, "
                  + ("none could not be completed" if not trouble
                     else "1 could not be completed" if trouble == 1
                     else f"{trouble} could not be completed")),
        how=FOUND_SOMETHING if trouble else DONE,
        carried={"looked": looked, "trouble": trouble,
                 "structures": len(structures)},
        details=tuple(kept),
    )


def _check_payments(engine, **rest) -> Found:
    counted: dict = {}
    for case in engine.state.casebook.cases.values():
        if case.case_type != "PAYMENT_MISMATCH" or not case.is_open:
            continue
        for evidence in case.evidence:
            because = (evidence.detail or {}).get("because", "")
            if because:
                counted[because.split(" on this book")[0][:70]] = \
                    counted.get(because.split(" on this book")[0][:70], 0) + 1
    total = sum(counted.values())
    return Found(
        headline=(f"{total} payment findings still open"
                  if total else "nothing open on payments"),
        how=FOUND_SOMETHING if total else DONE,
        carried={"open": total},
        details=tuple(f"{what} ({count})" for what, count
                      in sorted(counted.items(), key=lambda kv: -kv[1])[:6]),
    )


def _check_letters(engine, today: str = "", **rest) -> Found:
    letters = engine.state.correspondence
    late = letters.overdue(today) if today else ()
    soon = letters.due_soon(today) if today else ()
    open_now = letters.open_notices()
    return Found(
        headline=(f"{len(open_now)} waiting, {len(late)} past the date set"
                  if open_now else "nothing from a regulator is waiting"),
        how=FOUND_SOMETHING if late else DONE,
        carried={"open": len(open_now), "late": len(late)},
        details=tuple(f"{n.reference} — {n.about[:60]}"
                      for n in (late + soon)[:6]),
    )


def _check_the_firm(engine, today: str = "", **rest) -> Found:
    from .capital import in_words, shortfall

    short = shortfall(engine.state.licence, engine.state.capital)
    return Found(
        headline=in_words(engine.state.licence, engine.state.capital),
        how=FOUND_SOMETHING if short else DONE,
        carried={"short": short or 0},
    )


def _write_the_report(engine, today: str = "", **rest) -> Found:
    from .reporting import period_report

    report = period_report(engine, today or "2026-08-19")
    rows = sum(len(section.rows) for section in report.sections)
    return Found(
        headline=f"report assembled: {len(report.sections)} sections, "
                 f"{rows} figures",
        carried={"sections": len(report.sections)},
        details=tuple(section.heading for section in report.sections[:8]),
    )


def _one_party_record(engine, party: str = "", today: str = "", **rest) -> Found:
    from .dossier import dossier

    if not party:
        return Found(headline="no party was named", how=SKIPPED)
    doc = dossier(engine, party, today or "2026-08-19")
    if doc.refusal:
        return Found(headline=doc.refusal, how=FAILED)
    return Found(
        headline=f"{doc.title}: {len(doc.parts)} sections",
        carried={"party": party},
        details=tuple(part.heading for part in doc.parts),
    )


#: Everything an agent may do, and who does it. The agent names are the
#: ones a reader sees, so they say what the agent is for rather than what
#: it is called in the code.
TOOLS: Mapping[str, Tool] = {
    "screen": Tool(
        name="screen", says="Checking parties against the watchlists",
        about="Searches every party on the book against nearly 4 million "
              "sanctioned, politically exposed and wanted entities.",
        run=_screen_everyone),
    "duplicates": Tool(
        name="duplicates", says="Looking for the same party entered twice",
        about="Compares parties by identifier and by how their names "
              "sound, and reports pairs that may be one person.",
        run=_find_duplicates),
    "readiness": Tool(
        name="readiness", says="Measuring the book against clause 5.4.2",
        about="Checks what identification data each party is missing, and "
              "what is held without a document behind it.",
        run=_measure_readiness),
    "ownership": Tool(
        name="ownership", says="Following ownership through to the people",
        about="Walks each structure to its beneficial owners and reports "
              "where the chain loops, runs out, or names nobody.",
        run=_walk_ownership),
    "payments": Tool(
        name="payments", says="Reading the payment findings",
        about="Gathers the payment files still waiting on a person: a payer "
              "named on a sanctions list, and money sent by someone other "
              "than the investor. Nothing else about a payment is checked.",
        run=_check_payments),
    "letters": Tool(
        name="letters", says="Checking letters from the regulator",
        about="Reports what a regulator has asked for and whether the "
              "date they set has passed.",
        run=_check_letters),
    "firm": Tool(
        name="firm", says="Checking the firm's own position",
        about="Compares the firm's reported net worth against the minimum "
              "its licence requires.",
        run=_check_the_firm),
    "report": Tool(
        name="report", says="Assembling the report",
        about="Builds the period report from the log.",
        run=_write_the_report),
    "record": Tool(
        name="record", says="Assembling one party's full record",
        about="Builds the handover document for a single party.",
        run=_one_party_record),
}


@dataclass(frozen=True)
class Recipe:
    """A job somebody can ask for, and the steps it takes.

    Fixed plans rather than a model's, and stated as such. When a model is
    configured it can compose these; until then a person picks a job from a
    menu and the steps are the ones written here. A plan that pretended to
    have been reasoned would be the first lie on the screen.
    """

    key: str
    asked: str
    about: str
    steps: tuple


RECIPES: Mapping[str, Recipe] = {
    "morning": Recipe(
        key="morning", asked="Run the morning check across the whole book",
        about="What an officer would look at first: who is on a watchlist, "
              "who is on the book twice, what the regulator is waiting for, "
              "and where the firm itself stands.",
        steps=(("Screening", "screen"), ("Resolution", "duplicates"),
               ("Correspondence", "letters"), ("The firm", "firm"))),
    "onboarding": Recipe(
        key="onboarding", asked="Check the book is fit to hand over",
        about="Everything an inspector asks for: what identification data "
              "is missing, what is held with no document behind it, and "
              "whether ownership resolves to real people.",
        steps=(("Readiness", "readiness"), ("Ownership", "ownership"),
               ("Screening", "screen"))),
    "monitoring": Recipe(
        key="monitoring", asked="Review who the money came from",
        about="Who paid: a payer named on a sanctions list, and money sent "
              "by someone other than the investor. Nothing about the amount "
              "or the timing of a payment is examined. Then ownership, and "
              "the firm's own position beside it.",
        steps=(("Monitoring", "payments"), ("Ownership", "ownership"),
               ("The firm", "firm"))),
    "quarter": Recipe(
        key="quarter", asked="Prepare the quarterly picture",
        about="The report a board or a regulator gets, with the checks "
              "behind it run first so the figures are current.",
        steps=(("Screening", "screen"), ("Readiness", "readiness"),
               ("Correspondence", "letters"), ("Reporting", "report"))),
    "party": Recipe(
        key="party", asked="Build the full record on one party",
        about="Everything held on a single investor, assembled as the "
              "document you would hand an inspector.",
        steps=(("Resolution", "duplicates"), ("Ownership", "ownership"),
               ("Reporting", "record"))),
}


def plan_for(recipe: Recipe) -> tuple:
    """The plan a person sees before anything runs.

    Shown up front on purpose. Somebody watching work they delegated needs
    to know what was undertaken, not just what has finished -- the
    difference between a checklist and a spinner.
    """
    return tuple(
        {"agent": agent, "tool": tool,
         "says": TOOLS[tool].says if tool in TOOLS else tool}
        for agent, tool in recipe.steps
    )
