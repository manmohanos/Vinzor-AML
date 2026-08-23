"""The engine: facts in, findings recorded, decisions gated, folds everywhere.

Two kinds of record flow through one log. *Facts* arrive from outside — an
ownership declaration, a payment, a deadline observed at a boundary.
*Findings* are what the rulepack made of a fact, written down at the moment it
was made: policy, severity, the clause text as it then stood, the pack
version. And *decisions* are what an enrolled human ruled.

Evaluation therefore happens exactly once, at the write boundary, inside
``ingest``. ``apply_event`` — used identically by the live path and by replay —
is a pure fold: it runs no policies. That is the property the design rests on
(DESIGN.md, decision 2): no change to any rule can rewrite what the system
said last month, and a decision can never dangle against a Case that today's
rules would no longer open. ``test_replay_never_runs_policies`` and
``test_history_survives_the_deletion_of_every_policy`` hold it in place.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from .calendar import Calendar, Status, outstanding
from .cases import (LONGEST_REASON, CaseBook, DecisionDenied,
                    EscalationNeedsAnotherOfficer,
                    SeniorManagementMustApprove, TheFileIsAboutThem,
                    check_can_decide, finding_specs, is_pep, names,
                    thin_reason)
from .eventlog import EventLog
from .graph import OwnershipGraph
from .licence import Licence
from .conversation import Talk
from .agents import Runs


def _Found_failed(why: str):
    """A step that broke, as a result rather than an exception.

    The reason goes in the details, not the headline. The headline is what a
    compliance officer reads on a task card and what goes on the permanent
    record, and it used to be the exception text: ``could not finish: type
    object 'WatchlistClient' has no attribute 'from_environment'`` is on
    live.db today. A raw Python error is not a sentence for that reader, and
    the log cannot be rewritten.
    """
    from .agents import FAILED, Found

    return Found(
        headline="this step could not be completed, so nothing was checked",
        how=FAILED,
        details=(f"What went wrong: {why}",),
    )


def _outcome_sentence(found: int, broke: int, steps: int) -> str:
    """How a finished run reads on the card that summarises it.

    A run with a step that failed never closes on a sentence shaped like
    success, because that sentence is all a busy officer reads.
    """
    parts = []
    if found:
        parts.append(f"{found} of {steps} steps found something worth a "
                     f"person's time")
    if broke:
        parts.append(f"{broke} {'step' if broke == 1 else 'steps'} could not "
                     f"be run, so nothing was checked there")
    if not parts:
        return "nothing needing attention was found"
    return "; ".join(parts)
from .capital import Capital
from .disclosure import Book
from .correspondence import Correspondence
from .documents import Papers
from .duplicates import Resemblances
from .model import (DECIDING_ROLES, Case, Event, EventType, Outcome, Role,
                    canonical_json, check_amount, check_reported,
                    check_date, check_share)
from .policies import POLICIES, RULEPACK, Policy, PolicyContext, evaluate

#: Events that carry a recorded finding for the casebook to fold.
_FINDING_EVENTS = frozenset({EventType.CASE_OPENED, EventType.EVIDENCE_RECORDED})


#: Event types a model authors.
#:
#: ``TASK_STEP`` and ``TASK_FINISHED`` belong here and were missing, which is
#: the same defect that put ``DRAFT_PREPARED`` here in the first place: inert
#: only because none of the shipped policies happens to name the type. Adding
#: one policy that named ``TASK_STEP`` opened three real Cases from
#: agent-authored events -- word for word the scenario ``test_engine.py``
#: writes down in its own docstring.
MODEL_AUTHORED = frozenset({
    EventType.DRAFT_PREPARED,
    EventType.TASK_STEP,
    EventType.TASK_FINISHED,
    EventType.RECORD_OPENING_WRITTEN,
})


def may_produce_findings(state: "State", event: Event) -> bool:
    """Whether the rulepack may run over this event at all.

    DESIGN.md decision 11: a model may judge, never establish. A Finding *is*
    establishing -- it opens a Case, asserts a severity and cites a clause, on
    a permanent record. So nothing a model wrote may produce one.

    This was open. ``ingest`` evaluated every event identically, including the
    assistant's own ``DRAFT_PREPARED``, and was inert only because none of the
    seven shipped policies happens to name that type. One future policy that
    did -- or one agent given a write-capable tool -- and a model would have
    established a finding, which is the single thing the whole AI design
    exists to prevent. The human gate does not cover this: it stops a model
    *closing* a Case, not a model *opening* one.

    Two independent checks, because either alone could be circumvented by an
    honest mistake: the event type, and whether the actor is enrolled as AI.
    Actors like ``"system"`` are not caught -- deadlines and screening results
    are legitimate machine-minted facts about the world, not model judgement.
    """
    if event.event_type in MODEL_AUTHORED:
        return False
    enrolled = state.actors.get(event.actor)
    return not (enrolled is not None and enrolled["role"] is Role.AI)


def rulepack_of(policies: Sequence[Policy]) -> str:
    """The version stamp for whichever pack is actually running.

    The shipped pack gets its declared version. Anything else gets a
    fingerprint of the policy names it contains -- honest about being a
    different pack, and stable enough that the same custom pack always
    stamps the same way on replay. Saying nothing, or borrowing the shipped
    pack's version, would both be worse: a finding must be able to name the
    rules that made it.
    """
    if tuple(policies) == tuple(POLICIES):
        return RULEPACK
    names = "|".join(getattr(p, "__name__", repr(p)) for p in policies)
    return "custom." + hashlib.sha256(names.encode("utf-8")).hexdigest()[:8]


@dataclass
class State:
    """Everything derived from the log. Disposable by design."""

    graph: OwnershipGraph = field(default_factory=OwnershipGraph)
    licence: Licence = field(default_factory=Licence)
    calendar: Calendar = field(default_factory=Calendar)
    casebook: CaseBook = field(default_factory=CaseBook)
    #: Where to look for a party who may already be on the book.
    resemblances: Resemblances = field(default_factory=Resemblances)
    #: Letters from the regulator, and the answers to them.
    correspondence: Correspondence = field(
        default_factory=Correspondence)
    #: The papers behind the facts, and what each supports.
    papers: Papers = field(default_factory=Papers)
    #: The firm's own money, and the minimum it must keep.
    capital: Capital = field(default_factory=Capital)
    #: What the book holds, for a reported figure to be read
    #: against.
    book: Book = field(default_factory=Book)
    #: Work people have delegated, and how far it has got.
    runs: Runs = field(default_factory=Runs)
    #: The thread, read out of the questions and the tasks.
    talk: Talk = field(default_factory=Talk)
    #: Who may act in this workspace, by name: {"role": Role, "title": str}.
    #: Fed only by enrolment events, so "who could decide" is itself on the
    #: record — a forged decision needs a forged enrolment too.
    actors: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Clause sign-offs, by clause id. Each carries the digest of the wording
    #: that was actually read, so a sign-off cannot outlive the text it was
    #: given -- see ``citations.verified_now``.
    verifications: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Risk assessments by customer, each carrying the factors that were
    #: taken into account. Confidential under clause 4.1(d): never rendered
    #: on anything a customer could see.
    risk: dict[str, Any] = field(default_factory=dict)
    #: ``entity_id|due_on`` for every lapsed review already reported, so the
    #: sweep records that lateness was observed rather than that it is still
    #: true every time somebody loads a page. The due date is part of the key
    #: on purpose: refreshing the diligence writes a new assessment, which
    #: moves the next date, so a later lapse is a new fact and reports again.
    reviews_reported: frozenset = frozenset()
    #: Sheets already brought in, by file digest -- what "this exact file
    #: was already imported" is checked against.
    imports: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_seq: int = 0


def apply_event(state: State, event: Event) -> list[Case]:
    """Fold one recorded event into state. Runs no policies, ever.

    The single interpreter of the log, shared byte-for-byte by the live path
    and replay. Returns any Case the event opened or touched.
    """
    kind = event.event_type
    touched: list[Case] = []

    if kind in _FINDING_EVENTS:
        touched.append(state.casebook.fold_finding(event))
    elif kind is EventType.DRAFT_PREPARED:
        state.casebook.fold_draft(event)
    elif kind is EventType.CASE_DECIDED:
        _verify_decider(state, event)
        state.casebook.apply_decision(event)
    elif kind is EventType.ACTOR_ENROLLED:
        # Replace the dict rather than mutate it in place. server.py runs
        # under ThreadingHTTPServer -- one thread per request -- and several
        # modules read ``engine.state.actors`` directly rather than through
        # the lock-guarded ``Vinzor.actors()``. A reader that fetched the
        # dict and is mid ``.items()`` when an enrolment lands on another
        # thread must keep iterating the snapshot it already has, not a dict
        # that just changed size underneath it -- the same crash ``queue()``
        # was fixed against, for a caller this engine cannot make take a lock.
        state.actors = {
            **state.actors,
            event.subject: {
                "role": Role(event.payload["role"]),
                "title": event.payload.get("title", ""),
            },
        }
    elif kind is EventType.CLAUSE_VERIFIED:
        _verify_reviewer(state, event)
        state.verifications = {
            **state.verifications,
            event.subject: {
                "reviewer": event.actor,
                "qualification": event.payload.get("qualification", ""),
                "note": event.payload.get("note", ""),
                "verified_at": event.occurred_at,
                "wording": event.payload["wording"],
                "seq": event.seq,
            },
        }
    elif kind is EventType.ACTOR_REVOKED:
        state.actors = {
            name: entry for name, entry in state.actors.items() if name != event.subject
        }
    elif kind is EventType.RISK_ASSESSED:
        _verify_decider(state, event)
        from .risk import Assessment, Observation

        payload = event.payload
        observations = {
            ref: Observation(ref=ref, present=entry.get("present"),
                             because=entry.get("because", ""),
                             answered_by=entry.get("answered_by", ""))
            for ref, entry in (payload.get("factors") or {}).items()
        }
        state.risk = {
            **state.risk,
            event.subject: Assessment(
                entity_id=event.subject,
                observations=observations,
                category=payload.get("category", ""),
                reason=payload.get("reason", ""),
                by=event.actor,
                on=event.occurred_at,
                seq=event.seq,
            ),
        }
    elif kind is EventType.REVIEW_OVERDUE:
        state.reviews_reported = state.reviews_reported | {
            f"{event.subject}|{event.payload.get('due_on', '')}"
        }
    elif kind is EventType.SHEET_IMPORTED:
        state.imports = {
            **state.imports,
            event.payload["digest"]: {
                "file": event.payload.get("file", ""),
                "sheet": event.payload.get("sheet", ""),
                "by": event.actor,
                "on": event.occurred_at,
                "seq": event.seq,
            },
        }
    else:
        state.graph.apply(event)
        state.licence.apply(event)
        state.calendar.apply(event)
        state.resemblances.apply(event)
        state.correspondence.apply(event)
        state.papers.apply(event)
        state.capital.apply(event)
        state.book.apply(event)
        state.runs.apply(event)
        state.talk.apply(event)

    state.last_seq = event.seq
    return touched


def _verify_decider(state: State, event: Event) -> None:
    """The fold half of the human gate: the decider must be enrolled.

    The role named in the payload must match an enrolment earlier in the
    stream. A forged ``CASE_DECIDED`` claiming a deciding role therefore fails
    on replay unless a forged enrolment was written too — and that one is
    sitting in the audit trail with a hash over it.
    """
    enrolled = state.actors.get(event.actor)
    claimed = Role(event.payload["role"])
    if enrolled is None or enrolled["role"] is not claimed:
        raise DecisionDenied(
            f"{event.actor} is not enrolled as {claimed.value} in this "
            f"workspace (seq {event.seq})"
        )


def _verify_reviewer(state: State, event: Event) -> None:
    """The fold half of the gate on sign-off.

    Same shape as the gate on deciding a Case, and for the same reason: a
    forged ``CLAUSE_VERIFIED`` has to be accompanied by a forged enrolment,
    which is itself sitting in the audit trail under a hash. A machine cannot
    sign off a clause, because a machine is never enrolled.
    """
    enrolled = state.actors.get(event.actor)
    claimed = Role(event.payload["role"])
    if enrolled is None or enrolled["role"] is not claimed:
        raise DecisionDenied(
            f"{event.actor} is not enrolled as {claimed.value} in this "
            f"workspace, so cannot confirm a clause (seq {event.seq})"
        )
    if claimed not in DECIDING_ROLES:
        raise DecisionDenied(
            f"{claimed.value} may read the register but not confirm it "
            f"(seq {event.seq})"
        )


def project(events: Iterable[Event]) -> State:
    """Rebuild state from the log. A pure fold; policies never run here."""
    state = State()
    for event in events:
        apply_event(state, event)
    return state


@dataclass
class IngestResult:
    event: Event
    cases: list[Case]


class Vinzor:
    """One workspace: its log, and the state derived from it."""

    def __init__(
        self, log: Optional[EventLog] = None, policies: Sequence[Policy] = POLICIES
    ) -> None:
        self.log = log if log is not None else EventLog()
        self.policies = policies
        # Which rules actually ran, stamped on every finding they produce.
        # This used to read the module-level RULEPACK unconditionally, so a
        # workspace running an injected pack -- a test, a customer pack, a
        # re-assessment under different rules -- wrote the *shipped* pack's
        # version onto findings the shipped pack never made. In an append-only
        # log that mislabelling cannot be corrected later, and it is exactly
        # the question an inspector asks: which rules produced this?
        self.rulepack = rulepack_of(policies)
        # Appending and folding is a read-modify-write, so one critical
        # section. The log has its own lock for its own consistency; this one
        # keeps the projection in step with it.
        self._lock = threading.RLock()
        self.state = project(self.log)

    # -- writing ----------------------------------------------------------

    def ingest(
        self,
        *,
        event_type: EventType,
        subject: str,
        occurred_at: str,
        actor: str = "system",
        payload: Optional[Mapping[str, Any]] = None,
    ) -> IngestResult:
        """Record one fact, evaluate it once, and record what the rules said.

        The fact and its findings are appended as a single transaction; the
        log never holds half a thought. If anything fails after state was
        touched, state is rebuilt from the log — the log is the truth, state
        is disposable.
        """
        # Refused here, before the lock and before anything is written: every
        # projection downstream does arithmetic on this, and a date that is not
        # a date should fail as a sentence an operator can act on rather than
        # as an IndexError from inside a payment window.
        occurred_at = check_date(occurred_at)

        # Normalise up front so the object folded live is byte-identical to
        # the one a replay will read back from JSON.
        payload = json.loads(canonical_json(dict(payload or {})))
        if event_type is EventType.PAYMENT_RECEIVED:
            payload = check_amount(payload)
        elif event_type is EventType.OWNERSHIP_DECLARED:
            payload = check_share(payload)
        elif event_type is EventType.FILING_SUBMITTED:
            payload = check_reported(payload)

        with self._lock:
            try:
                fact = Event(
                    seq=len(self.log) + 1,
                    event_type=EventType(event_type),
                    subject=subject,
                    occurred_at=occurred_at,
                    actor=actor,
                    payload=payload,
                )
                apply_event(self.state, fact)
                findings = (
                    evaluate(
                        PolicyContext(
                            event=fact,
                            graph=self.state.graph,
                            licence=self.state.licence,
                            calendar=self.state.calendar,
                            resemblances=self.state.resemblances,
                            correspondence=self.state.correspondence,
                            papers=self.state.papers,
                            capital=self.state.capital,
                            book=self.state.book,
                            risk=self.state.risk,
                        ),
                        self.policies,
                    )
                    if may_produce_findings(self.state, fact)
                    else []
                )
                specs = [{
                    "event_type": fact.event_type,
                    "subject": fact.subject,
                    "occurred_at": fact.occurred_at,
                    "actor": fact.actor,
                    "payload": fact.payload,
                }]
                specs.extend(
                    finding_specs(self.state.casebook, findings, fact,
                                  self.rulepack)
                )
                events = self.log.append_batch(specs)
                cases: list[Case] = []
                for recorded in events[1:]:
                    cases.extend(apply_event(self.state, recorded))
            except Exception:
                # State may be ahead of the log; the log is the truth.
                self.state = project(self.log)
                raise
        return IngestResult(event=events[0], cases=cases)

    def enroll(
        self, *, name: str, role: Role, title: str = "", enrolled_at: str,
        actor: str = "system",
    ) -> IngestResult:
        """Record that a person may act in this workspace, and as what."""
        return self.ingest(
            event_type=EventType.ACTOR_ENROLLED,
            subject=name,
            occurred_at=enrolled_at,
            actor=actor,
            payload={"role": str(role), "title": title},
        )

    def decide(
        self,
        *,
        case_id: str,
        outcome: Outcome,
        actor: str,
        role: Role,
        rationale: str,
        decided_at: str,
        draft_use: str = "NONE",
        reason_code: str = "",
    ) -> Case:
        """Record a human ruling on a Case.

        Everything is validated before anything is written, so the log never
        contains an event that its own fold would refuse.
        """
        with self._lock:
            enrolled = self.state.actors.get(actor)
            if enrolled is None or enrolled["role"] is not role:
                raise DecisionDenied(
                    f"{actor} is not enrolled as {role.value} in this workspace"
                )
            check_can_decide(role)
            case = self.state.casebook.get(case_id)
            if not case.is_open:
                raise ValueError(
                    f"{case_id} is already {case.status.value}; Cases are decided once"
                )
            if not rationale.strip():
                raise ValueError("a decision requires a rationale")
            if len(rationale) > LONGEST_REASON:
                # A stated limit rather than one the size of an HTTP request
                # body happens to impose. This goes on a permanent event and
                # into every export of it.
                raise ValueError(
                    f"this reason is {len(rationale):,} characters; the most "
                    f"that goes on the record is {LONGEST_REASON:,}. Put the "
                    f"detail in the file and the conclusion here."
                )
            if thin_reason(rationale):
                raise ValueError(
                    "this reason says nothing an inspector could read; write "
                    "what was compared or concluded, not just that it was"
                )
            # A reason code is one of the ones the screen offered, or it is
            # nothing. Nothing checked, and nothing tied it to the outcome:
            # ``same-party`` -- the REJECT-only code captioned "Confirmed as
            # the same party" -- was accepted and recorded against an
            # APPROVE, and so was ``i-invented-this-code``, and so was a
            # 200-character string, silently cut to forty. A code nobody
            # chose is worse than no code: the point of the codes is that
            # reasons can be counted, and a count over invented values is
            # not a count of anything.
            code = str(reason_code or "").strip()
            if code:
                from .briefing import REASON_CODES

                allowed = REASON_CODES.get(str(outcome).split(".")[-1], set())
                if code not in allowed:
                    raise ValueError(
                        f"{code!r} is not a reason this system offers for "
                        f"{str(outcome).split('.')[-1].lower()}. Pick one "
                        f"from the list, or leave it blank and write the "
                        f"reason."
                    )
            # Pre-validated here because the event is appended before the
            # fold runs: a guard that lived only in the fold would let the
            # command write an event its own replay refuses forever.
            if names(case, actor):
                raise TheFileIsAboutThem(
                    f"this file is about {actor}; another officer has to "
                    f"settle it. If nobody else is enrolled who could, that "
                    f"is itself worth recording."
                )
            if any(entry["by"] == actor for entry in case.escalations):
                raise EscalationNeedsAnotherOfficer(
                    f"{actor} escalated this Case; a different officer has "
                    f"to settle it"
                )
            if outcome is Outcome.ESCALATE:
                # Passing a file up when nobody would be left to answer it
                # leaves it open forever, waiting on nobody, with no marker on
                # any screen -- and the period report then states of it that
                # it "is waiting for a second officer after being passed up".
                # Three officers, three clicks, and the escalations are
                # permanent events with no way back. A refusal here is a
                # remedy; the dead end is not.
                from .whosework import who_could_settle

                if not who_could_settle(case, self.state.actors,
                                        also_passing_up=actor):
                    raise EscalationNeedsAnotherOfficer(
                        f"{actor} cannot pass this file up: nobody else "
                        f"enrolled could settle it afterwards, so it would "
                        f"stay open with no one to answer it. Enrol another "
                        f"officer, or settle it yourself and record why."
                    )

            # Clause 5.5(b)(iii). Pre-validated here for the same reason as
            # four eyes: the event is appended before the fold runs, so a
            # guard that lived only in the fold would let the command write
            # an event its own replay refuses forever.
            if (outcome is Outcome.APPROVE and is_pep(case)
                    and role is not Role.SENIOR_MGMT):
                raise SeniorManagementMustApprove(
                    f"{actor} cannot clear a politically exposed person; "
                    f"clause 5.5(b)(iii) requires senior management to "
                    f"approve one"
                )

            event = self.log.append(
                event_type=EventType.CASE_DECIDED,
                subject=case.subject,
                occurred_at=decided_at,
                actor=actor,
                payload={
                    "case_id": case_id,
                    "outcome": str(outcome),
                    "role": str(role),
                    "rationale": rationale,
                    "draft_use": str(draft_use),
                    # Whole, never cut. It is one of a closed set now, and
                    # truncating a value nobody chose was how ``[:40]``
                    # wrote a code that never existed onto a permanent
                    # record.
                    "reason_code": code,
                },
            )
            apply_event(self.state, event)
        return case

    def confirm_clause(self, *, clause_id: str, reviewer: str, role: Role,
                       qualification: str, note: str, confirmed_at: str):
        """Record that a qualified person has read a clause and stands by it.

        The wording they were shown is stored with the sign-off. If the
        extract is later corrected, the digest stops matching and the clause
        silently reverts to unconfirmed rather than carrying a signature
        forward onto words nobody signed.
        """
        from .citations import CLAUSES, wording_digest

        clause = CLAUSES.get(clause_id)
        if clause is None:
            raise KeyError(f"no registered clause {clause_id!r}")
        if not (qualification or "").strip():
            raise ValueError(
                "a sign-off has to name what qualifies the person making it"
            )
        if not (note or "").strip():
            raise ValueError(
                "a sign-off has to say what was checked; it goes on the record"
            )
        return self.ingest(
            event_type=EventType.CLAUSE_VERIFIED,
            subject=clause_id,
            occurred_at=confirmed_at,
            actor=reviewer,
            payload={
                "role": role.value if isinstance(role, Role) else str(role),
                "qualification": qualification.strip(),
                "note": note.strip(),
                "wording": wording_digest(clause),
            },
        )

    #: What a customer's risk may be called. Three bands, because clause
    #: 5.11 sets a different re-check interval for each and there is no
    #: fourth interval to name.
    RISK_CATEGORIES = ("HIGH", "MEDIUM", "LOW")

    def give_asked_task(self, *, asked: str, actor: str, given_at: str,
                        transport=None, **inputs):
        """Delegate a job somebody described in their own words.

        The model chooses which tools to run and says so; it never states
        what they found. Its plan and its sentence both go in the record,
        so what an inspector reads later includes what the machine was
        asked and what it decided to do about it -- not just the results.
        """
        from .planning import plan_from

        plan = plan_from(asked, transport)
        if plan.refused or not plan.steps:
            return None, plan

        # Under the lock. ``len(self.log)`` was read outside it, so twelve
        # threads released together all computed the same id: twelve
        # delegations collapsed onto one card, permanently, with 48 step
        # events folded into a four-step plan. ``_lock`` is re-entrant, so
        # the ingest below is safe inside it.
        with self._lock:
            task_id = "task_" + hashlib.sha256(
                f"{asked}|{actor}|{given_at}|{len(self.log)}".encode()
            ).hexdigest()[:12]
            self.ingest(
                event_type=EventType.TASK_GIVEN,
                subject=task_id,
                occurred_at=given_at,
                actor=actor,
                payload={
                    "asked": asked[:400], "recipe": "asked",
                    "about": plan.said,
                    "planned_by": ("keywords" if plan.guessed
                                   else "the assistant"),
                    "plan": list(plan.steps),
                    "dropped": list(plan.invented),
                    "inputs": {k: str(v)[:200] for k, v in inputs.items()},
                },
            )
        return task_id, plan

    def give_task(self, *, recipe_key: str, actor: str, given_at: str,
                  about: str = "", **inputs):
        """Delegate a job. Returns the task's reference at once.

        The plan is recorded before any of it runs, which is what lets a
        person see what was undertaken rather than only what has finished.
        """
        from .agents import RECIPES, plan_for

        recipe = RECIPES.get(recipe_key)
        if recipe is None:
            raise ValueError(
                f"there is no job called {recipe_key!r}. The ones this "
                f"understands are: {', '.join(sorted(RECIPES))}"
            )
        with self._lock:
            task_id = "task_" + hashlib.sha256(
                f"{recipe_key}|{actor}|{given_at}|{len(self.log)}".encode()
            ).hexdigest()[:12]
            self.ingest(
                event_type=EventType.TASK_GIVEN,
                subject=task_id,
                occurred_at=given_at,
                actor=actor,
                payload={
                    "asked": recipe.asked, "recipe": recipe_key,
                    "about": about or recipe.about,
                    "plan": list(plan_for(recipe)),
                    "inputs": {k: str(v)[:200] for k, v in inputs.items()},
                },
            )
        return task_id

    def run_task(self, task_id: str, when: str, **inputs) -> None:
        """Do the work, recording each step as it finishes.

        Deliberately not one transaction. A step that has run is a thing
        that happened, and it belongs in the record whether or not the ones
        after it succeed -- which is also what makes the progress somebody
        is watching real rather than a bar that fills at the end.
        """
        from .agents import FOUND_SOMETHING, FAILED, TOOLS, ReadOnly

        task = self.state.runs.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        found_something = 0
        could_not_run = 0
        for step in task.plan:
            tool = TOOLS.get(step.tool)
            if tool is None:
                continue
            try:
                # A read-only view, never the engine. What stops a tool
                # settling a file is that it has no way to, not that
                # somebody remembered not to write one.
                found = tool.run(ReadOnly(self), today=when, **inputs)
            except Exception as broke:
                # Recorded rather than raised. A job that fails halfway
                # has still done the half, and hiding the failure would
                # leave a task that simply stopped with no reason on it.
                found = _Found_failed(str(broke)[:200])
            # Counted by what it *is*, not by what it is not. The test used
            # to be "anything that is not done and not skipped", and FAILED is
            # neither -- so a step that crashed was counted as a step that
            # found something worth a person's time. It is on the shipped
            # workspace's own log: seq 1568/1569 of live.db record a screening
            # step that broke outright and a summary reading "2 of 3 steps
            # found something worth a person's time". A run where the
            # watchlist never answered and a run that found two sanctioned
            # investors closed on the same reassuring sentence -- and that
            # sentence is the whole of a collapsed task card.
            if found.how == FOUND_SOMETHING:
                found_something += 1
            elif found.how == FAILED:
                could_not_run += 1
            self.ingest(
                event_type=EventType.TASK_STEP,
                subject=task_id,
                occurred_at=when,
                # "the agents", the same fixed author ``TASK_FINISHED``
                # already uses -- never ``step.agent``, which is a string the
                # *model* wrote. Two things went wrong with that. The audit
                # trail could attribute an agent's work to a named human: a
                # transport answering {"agent": "Meera Nair"} put an enrolled
                # AML officer's name on a hash-chained event she had nothing
                # to do with, permanently. And that same model-chosen string
                # was the input to ``may_produce_findings``, so whether the
                # rulepack ran over an agent's event was decided by untrusted
                # model output. The label is decorative; it travels as data.
                actor="the agents",
                payload={"number": step.number, "tool": step.tool,
                         "labelled": step.agent,
                         "headline": found.headline, "how": found.how,
                         "details": list(found.details)[:10]},
            )
        self.ingest(
            event_type=EventType.TASK_FINISHED,
            subject=task_id,
            occurred_at=when,
            actor="the agents",
            payload={"outcome": _outcome_sentence(
                found_something, could_not_run, len(task.plan))},
        )

    def report_net_worth(self, *, amount_usd: float, as_at: str, actor: str,
                         note: str = ""):
        """Record what the firm is worth, as at a date.

        Not gated to a deciding role: this is bookkeeping about the firm
        rather than a judgement about a customer, and a system where
        recording a number needs an officer's authority is a system where
        the number goes unrecorded.
        """
        if not isinstance(amount_usd, (int, float)):
            raise ValueError("a net worth has to be a number of US dollars")
        if float(amount_usd) < 0:
            raise ValueError(
                "a negative net worth is a going-concern question rather "
                "than a capital one, and this is not the place to record it"
            )
        return self.ingest(
            event_type=EventType.NET_WORTH_REPORTED,
            subject=self.state.licence.number or "the entity",
            occurred_at=str(as_at)[:10],
            actor=actor,
            payload={"amount_usd": float(amount_usd),
                     "note": str(note or "")[:400]},
        )

    def confirm_minimum(self, *, minimum_usd: float, actor: str, role: Role,
                        confirmed_on: str, note: str = ""):
        """Record the minimum this firm accepts as applying to it.

        Gated like a decision, and this is the whole reason the command
        exists. The figures this product ships with came from law-firm
        summaries rather than the regulations, and were measured to be a
        weaker source than it accepts anywhere else -- twelve of twenty-one
        clauses checked against IFSCA's own text had a real problem. So the
        number is offered and a person accountable for it confirms, which
        is the same shape as signing off a clause.
        """
        if not isinstance(minimum_usd, (int, float)) or minimum_usd < 0:
            raise ValueError("a minimum has to be a number of US dollars")
        entry = self.state.actors.get(actor)
        if entry is None or entry["role"] is not role:
            raise DecisionDenied(
                f"{actor} is not enrolled as {getattr(role, 'value', role)} "
                f"in this workspace"
            )
        check_can_decide(role)
        if not str(note or "").strip():
            raise ValueError(
                "confirming a minimum requires saying where the figure "
                "came from; a number with no source is what this replaces"
            )
        return self.ingest(
            event_type=EventType.MINIMUM_CONFIRMED,
            subject=self.state.licence.number or "the entity",
            occurred_at=str(confirmed_on)[:10],
            actor=actor,
            payload={"minimum_usd": float(minimum_usd),
                     "role": getattr(role, "value", str(role)),
                     # Which licence this figure was confirmed *for*. A
                     # minimum with no category on it outlives the
                     # registration it belonged to.
                     "category": getattr(self.state.licence.category, "value",
                                         "") or "",
                     "note": str(note)[:400]},
        )

    def file_document(self, *, entity_id: str, kind: str, filename: str,
                      data: bytes, supports, actor: str, filed_on: str,
                      expires_on: str = "", note: str = "", cabinet=None):
        """Put a document on a party's record, and say what it evidences.

        The bytes go to the cabinet and their fingerprint goes in the log.
        A twenty-megabyte scan in an append-only record is a record nobody
        can replay; a fingerprint is enough to prove the file has not
        changed and enough to notice the same file filed twice.

        What it supports is asserted by a person and checked against what
        that kind of document *can* support. A utility bill may be said to
        evidence an address; it may not be promoted into evidence of a
        nationality because somebody was in a hurry.
        """
        from .documents import fingerprint, refuse, shape_of

        if entity_id not in self.state.graph.entities:
            raise KeyError(entity_id)
        problem = refuse(kind, data, supports, expires_on)
        if problem:
            raise ValueError(problem)

        digest = fingerprint(data)
        if cabinet is not None:
            cabinet.keep(digest, data, filed_on)
        return self.ingest(
            event_type=EventType.DOCUMENT_FILED,
            subject=entity_id,
            occurred_at=str(filed_on)[:10],
            actor=actor,
            payload={
                "digest": digest,
                "kind": kind,
                "filename": str(filename)[:200],
                "size": len(data),
                "shape": shape_of(data),
                "supports": sorted(set(supports or ())),
                "expires_on": str(expires_on or "")[:10],
                "note": str(note or "")[:400],
            },
        )

    def record_filing(self, *, obligation: str, period: str,
                      submitted_on: str, actor: str,
                      reported: Optional[Mapping] = None, note: str = ""):
        """Record that a return or a fee was filed.

        **Nothing in the product could do this**, and the asymmetry was
        expensive. ``FILING_SUBMITTED`` appeared in six files and no command,
        no HTTP route and no import produced one; ``FILING_OVERDUE`` was
        produced by a sweep that runs on every briefing load. So a firm
        licensed in April 2023, opened here for the first time in August
        2026, had **19 files opened in a single call** -- 13 quarterly
        reports, 3 flat fees, 3 turnover fees, USD 24,700 of computed late
        charges -- and a firm that had filed every one of them on time had no
        way to say so and no way to take them off, because the log is
        append-only.

        It also left the disclosure comparison with nothing to compare: the
        "what the last return claimed" panel returned nothing on every
        workspace, and the block's middle claim was unreachable.

        Not gated to a deciding role, for the same reason as
        ``notice_received``: recording that a return went in is bookkeeping,
        not judgement, and a system where it needs an officer's authority is
        a system where it goes unrecorded.

        ``reported`` carries the figures on the return, if it had any. They
        go through ``check_reported`` at ingest, so a figure that is not a
        number is refused with a sentence rather than opening a case whose
        own record says no figure was filed.
        """
        from .calendar import Obligation

        try:
            kind = Obligation(str(obligation or "").strip().upper())
        except ValueError:
            raise ValueError(
                f"there is nothing filed called {obligation!r}. The ones "
                f"this system tracks are: "
                f"{', '.join(o.value for o in Obligation)}"
            ) from None

        period = str(period or "").strip()
        if not period:
            raise ValueError(
                "a filing needs the period it covers, so that it can be tied "
                "to the deadline it answers"
            )
        submitted_on = check_date(submitted_on, field="submitted_on")

        already = self.state.calendar.submitted.get(f"{kind.value}|{period}")
        if already:
            raise ValueError(
                f"the {kind.value} for {period} is already recorded as filed "
                f"on {already}; a correction is a new record, not a second "
                f"copy of this one"
            )

        payload: dict = {"obligation": kind.value, "period": period,
                         "submitted_on": submitted_on}
        if reported:
            payload["reported"] = dict(reported)
        if str(note or "").strip():
            payload["note"] = str(note)[:400]

        return self.ingest(
            event_type=EventType.FILING_SUBMITTED,
            subject=self.state.licence.number or "the entity",
            occurred_at=submitted_on,
            actor=actor,
            payload=payload,
        )

    def notice_received(self, *, reference: str, from_whom: str, about: str,
                        received_on: str, actor: str, answer_by: str = ""):
        """Record a letter from a regulator that expects an answer.

        Not gated to a deciding role. Whoever opens the post can put a
        letter on the record, and a system where recording that a regulator
        wrote to you needs an officer's authority is a system where letters
        sit in an inbox until somebody senior has a free afternoon. Nothing
        about the letter is decided here -- only that it arrived.

        ``answer_by`` may be empty, and no date is invented when it is. A
        date this product wrote would be repeated in every later report as
        though the Authority had set it.
        """
        reference = str(reference or "").strip()
        if not reference:
            raise ValueError(
                "a notice needs the reference the regulator put on it, so "
                "that an answer can be tied to the letter it answers"
            )
        if reference in self.state.correspondence.notices:
            raise ValueError(
                f"a notice with reference {reference} is already on this "
                f"record; a second letter needs its own reference"
            )
        if not str(about or "").strip():
            raise ValueError(
                "a notice needs a line saying what was asked for; a "
                "reference on its own tells the next reader nothing"
            )
        # The deadline the Authority set, read the way a person writes one.
        #
        # This was the only date a person can type that nothing checked.
        # Every event's ``occurred_at`` goes through ``check_date``; this
        # went into the log as whatever arrived, cut to ten characters. So
        # "31-07-2026", which is how a date is written in India, was stored
        # untouched and read back as no date at all -- the letter was
        # nineteen days overdue and the screen said "no date was set". And
        # a date pasted out of a PDF with a leading space became
        # " 2026-07-3", which is a real date twenty-eight days earlier than
        # the one the regulator gave.
        #
        # Read through the importer's parser, which already accepts the
        # forms a person uses and already refuses the genuinely ambiguous
        # ones: 07-08-2026 is either August or July depending on who typed
        # it, and guessing on a regulator's deadline is not this product's
        # to do.
        from .importing import _date as _read_date

        wanted = str(answer_by or "").strip()
        if wanted:
            deadline = _read_date(wanted)
            if deadline is None:
                raise ValueError(
                    f"{wanted!r} is not a date this can read without "
                    f"guessing. Write it as YYYY-MM-DD -- a deadline read "
                    f"the wrong way round is a letter answered a month "
                    f"late.")
            if deadline < str(received_on)[:10]:
                raise ValueError(
                    f"the answer is due on {deadline}, before the letter "
                    f"arrived on {str(received_on)[:10]}. Check the year.")
        else:
            deadline = ""
        return self.ingest(
            event_type=EventType.NOTICE_RECEIVED,
            subject=reference,
            occurred_at=str(received_on)[:10],
            actor=actor,
            payload={"reference": reference,
                     "from_whom": str(from_whom or "").strip(),
                     "about": str(about).strip()[:800],
                     "answer_by": deadline},
        )

    def notice_answered(self, *, reference: str, answer: str, actor: str,
                        answered_on: str):
        """Record that an answer went back, and what it said.

        A person's act with their name on it, like every other conclusion in
        this product. What was sent is recorded in their words rather than
        summarised, because the question an inspector asks is not whether
        you replied but what you told them.
        """
        reference = str(reference or "").strip()
        standing = self.state.correspondence.notices.get(reference)
        if standing is None:
            raise KeyError(
                f"no notice with reference {reference} is on this record"
            )
        if not standing.is_open:
            raise ValueError(
                f"the notice {reference} was already answered on "
                f"{standing.answered_on}; a further reply needs its own "
                f"record"
            )
        if not str(answer or "").strip():
            raise ValueError("recording an answer requires what was sent")
        if thin_reason(answer):
            raise ValueError(
                "this says nothing an inspector could read; write what was "
                "sent, not that something was"
            )
        return self.ingest(
            event_type=EventType.NOTICE_ANSWERED,
            subject=reference,
            occurred_at=str(answered_on)[:10],
            actor=actor,
            payload={"reference": reference, "answer": str(answer)[:2000]},
        )

    def assess_risk(self, *, entity_id: str, category: str, actor: str,
                    role: Role, reason: str, assessed_at: str,
                    answers: Optional[dict] = None):
        """Record a person's judgement of how risky a customer is.

        Clause 4.2 lists the factors and then says that the presence of one
        or more of them "may not always indicate a high risk". So there is
        no formula here and no automatic category: the observations our own
        records can make are gathered, a person weighs them against the
        factors nobody can see from data, and the category is theirs.

        Gated exactly as a decision is. A risk category sets how often the
        customer must be looked at again under clause 5.11, so an automated
        actor setting it would be an automated actor deciding how much
        scrutiny a customer gets.
        """
        from .risk import observe

        category = str(category or "").strip().upper()
        if category not in self.RISK_CATEGORIES:
            raise ValueError(
                f"a customer is high, medium or low risk; {category!r} is "
                f"none of those"
            )
        entry = self.state.actors.get(actor)
        if entry is None or entry["role"] is not role:
            raise DecisionDenied(
                f"{actor} is not enrolled as {getattr(role, 'value', role)} "
                f"in this workspace"
            )
        check_can_decide(role)
        if entity_id not in self.state.graph.entities:
            raise KeyError(entity_id)
        if not (reason or "").strip():
            raise ValueError("a risk category requires a reason")
        if len(reason) > LONGEST_REASON:
            raise ValueError(
                f"this reason is {len(reason):,} characters; the most that "
                f"goes on the record is {LONGEST_REASON:,}. Put the detail in "
                f"the file and the conclusion here."
            )
        if thin_reason(reason):
            raise ValueError(
                "this reason says nothing an inspector could read; write "
                "what was weighed, not just that it was"
            )

        # What the records can see is gathered here rather than trusted from
        # the caller: a browser that could assert "no factor is present"
        # could hide a sanctioned jurisdiction from the permanent record.
        factors = {
            ref: {"present": found.present, "because": found.because}
            for ref, found in observe(self, entity_id).items()
        }
        # A person may answer the factors no record can speak to, and may
        # also disagree with what we found -- their answer is recorded as
        # theirs, alongside what the records said, never instead of it.
        for ref, given in (answers or {}).items():
            said = given.get("present") if isinstance(given, dict) else given
            because = (given.get("because", "")
                       if isinstance(given, dict) else "")
            entry_for = factors.setdefault(ref, {})
            entry_for["present"] = bool(said) if said is not None else None
            entry_for["because"] = str(because)[:400]
            entry_for["answered_by"] = actor

        return self.ingest(
            event_type=EventType.RISK_ASSESSED,
            subject=entity_id,
            occurred_at=assessed_at,
            actor=actor,
            payload={
                "role": role.value if isinstance(role, Role) else str(role),
                "category": category,
                "reason": reason.strip(),
                "factors": factors,
            },
        )

    def observe_deadlines(self, today: str) -> list[Case]:
        """Record any filing that has become late as of ``today``.

        Called from a boundary, which is the only place that knows the date.
        The engine still never reads a clock — it is told one. Each instance
        is reported once: the log records that the lateness was observed, not
        that it is still true every time someone looks.
        """
        # Deciding what is newly late and recording it must be one indivisible
        # act. Two threads that each read ``reported_late`` before either wrote
        # to it would both conclude the same filing is newly late, and the log
        # would carry the same breach twice -- permanently, because nothing can
        # be removed from it. ``_lock`` is re-entrant, so the nested ingest()
        # below is safe.
        with self._lock:
            opened: list[Case] = []

            # Letters from the regulator first, and outside the licence
            # check below. A letter is late because a date passed, which
            # has nothing to do with when the licence was granted -- and
            # nesting this inside that guard meant a workspace with no
            # licence date recorded silently never reported an unanswered
            # notice at all. The one obligation with the most enforcement
            # against it, invisible for a reason that has nothing to do
            # with it.
            for notice in self.state.correspondence.overdue(today):
                if notice.reference in self.state.correspondence.reported_late:
                    continue
                result = self.ingest(
                    event_type=EventType.NOTICE_OVERDUE,
                    subject=notice.reference,
                    occurred_at=today,
                    actor="system",
                    payload={
                        "reference": notice.reference,
                        "from_whom": notice.from_whom,
                        "about": notice.about,
                        "answer_by": notice.answer_by,
                        "received_on": notice.received_on,
                        "days_late": -(notice.days_left(today) or 0),
                    },
                )
                opened.extend(result.cases)

            # Customer reviews next, and -- like the letters above -- outside
            # the licence guard below. Clause 5.11 measures from the day the
            # diligence was last refreshed, which has nothing to do with when
            # this firm's licence was granted. Nesting it inside that guard
            # would mean a workspace with no licence date recorded silently
            # never reported a lapsed review at all: the same defect the
            # notices carry a comment about, and the reason it is written
            # twice is that the guard is easy to drift back inside.
            from .risk import days_late, due_for_review

            for entity_id, assessment, due in due_for_review(self, today):
                if f"{entity_id}|{due.on}" in self.state.reviews_reported:
                    continue
                entity = self.state.graph.entities.get(entity_id)
                result = self.ingest(
                    event_type=EventType.REVIEW_OVERDUE,
                    subject=entity_id,
                    occurred_at=today,
                    actor="system",
                    payload={
                        "name": getattr(entity, "name", "") or entity_id,
                        "category": due.category,
                        "due_on": due.on,
                        "last_assessed_on": assessment.on,
                        "because": due.because,
                        "days_late": days_late(due.on, today),
                    },
                )
                opened.extend(result.cases)

            licence = self.state.licence
            if not licence.granted_on:
                return opened
            calendar = self.state.calendar
            from .licence import principal_officers

            late = [
                i for i in outstanding(licence.granted_on, today,
                                       calendar.submitted,
                                       principal_officers(licence))
                if i.status(today) is Status.OVERDUE
                and i.key not in calendar.reported_late
            ]
            # How many times this *kind* of filing has been missed, counting
            # what the log already shows plus what this sweep is about to add.
            # It is deliberately not the item's position in the batch: the
            # policy escalates HIGH -> CRITICAL on repeat failure, and reading
            # the position made a finding's severity depend on how often
            # somebody happened to open the page rather than on the filing
            # record. Two quarters missed is two, whether they are noticed
            # together or a month apart.
            missed: dict[str, int] = {}
            for key in calendar.reported_late:
                missed[key.split("|", 1)[0]] = missed.get(key.split("|", 1)[0], 0) + 1

            for item in late:
                obligation = item.obligation.value
                missed[obligation] = missed.get(obligation, 0) + 1
                result = self.ingest(
                    event_type=EventType.FILING_OVERDUE,
                    subject=self.state.licence.number or "the entity",
                    occurred_at=today,
                    actor="system",
                    payload={
                        "obligation": obligation,
                        "period": item.period,
                        "due_on": item.due_on,
                        "days_late": item.days_late(today),
                        "late_charge_usd": item.late_charge_usd(today),
                        "outstanding_count": missed[obligation],
                    },
                )
                opened.extend(result.cases)

            return opened

    # -- reading ----------------------------------------------------------

    def queue(self, open_only: bool = True) -> list[Case]:
        # Readers take the same lock as the fold that mutates the casebook.
        # Without it, a queue() running while an ingest() inserts a Case raises
        # "dictionary changed size during iteration" -- a crash for one user
        # caused by another user's unrelated work.
        with self._lock:
            return self.state.casebook.queue(open_only=open_only)

    def actors(self) -> dict[str, dict[str, Any]]:
        """Who may act here. A copy, so callers cannot read a mutating dict."""
        with self._lock:
            return {name: dict(entry) for name, entry in self.state.actors.items()}

    def case(self, case_id: str) -> Case:
        with self._lock:
            return self.state.casebook.get(case_id)

    def rebuild(self) -> State:
        """Re-derive state from the log. Must equal the live state."""
        with self._lock:
            return project(self.log)

    def verify(self) -> tuple[bool, Optional[str]]:
        return self.log.verify()
