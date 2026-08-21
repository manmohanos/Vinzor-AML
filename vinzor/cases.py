"""Cases: the primitive, the fold that builds them, and the human gate.

A Case is built entirely from recorded events. ``CASE_OPENED`` and
``EVIDENCE_RECORDED`` carry everything the rulepack concluded at the moment it
concluded it — severity, summary, the clause text as it then stood, the
rulepack version. The fold never recomputes any of that, which is why no later
change to any rule can rewrite what the system said (DESIGN.md, decision 2).

The human gate is enforced twice on purpose. Once on the command side, in
``engine.decide``, where a request becomes an event. And once here on the fold,
when a ``CASE_DECIDED`` event is replayed — so "an AI cannot approve a Case" is
true of the code that *reads* the log as well as the code that writes it. A
guarantee that holds in only one direction is a guarantee someone will
eventually route around.

The two sides drifted, which is the failure mode that sentence predicts.
``engine.decide`` applied six checks and the fold applied four; the two it did
not apply were *decide once* and *a decision has a reason*. Appending a second
``CASE_DECIDED`` straight to the log turned a written rejection of a sanctions
match into an approval with an empty reason, permanently and on every machine.
The fold now applies all of them but ``thin_reason``, which stays on the
command side alone on purpose: it is a calibration of what counts as saying
something, and hardening a calibration into the fold would make a log written
under yesterday's wording unreplayable tomorrow.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional, Sequence

from .model import (
    DECIDING_ROLES,
    OUTCOME_STATUS,
    Case,
    CaseStatus,
    Decision,
    Event,
    EventType,
    Evidence,
    EvidenceKind,
    Finding,
    Outcome,
    Role,
    Severity,
    make_case_id,
)


class DecisionDenied(PermissionError):
    """Raised when a non-human actor, or a read-only role, tries to decide."""


class SeniorManagementMustApprove(DecisionDenied):
    """A politically exposed person is being accepted by somebody too junior.

    Clause 5.5(b)(iii) is not a recommendation: a Regulated Entity shall
    "obtain approval from its Senior Management before opening an account of
    a PEP", and 5.5(b)(iv) says the same where an existing customer becomes
    one. Clearing a PEP match is that approval in practice, so an officer
    below senior management cannot give it.

    Only clearing is gated. Stopping a PEP, or passing the question up,
    needs no seniority -- a rule that made refusing business harder than
    accepting it would have the incentive exactly backwards.
    """


class DecisionAlreadyRecorded(DecisionDenied):
    """A settled file is being settled again.

    ``engine.decide`` has always refused this, and for a while that was
    mistaken for a guarantee. It is not: the command side is one way into the
    log, and the log is the thing that is authoritative. Appending a second
    ``CASE_DECIDED`` directly replaced a written rejection with an approval
    on every replay afterwards, and the audit sheet -- headed "every decision
    on this book" -- showed only the second one. There is no undo in an
    append-only log, so the fold refuses instead.

    Escalation is not settling: an escalated file is still open, and the
    officer it was passed to still has to answer it.
    """


class DecisionNeedsAReason(DecisionDenied):
    """A decision arrived with nothing written in it.

    The reason is the decision, as far as an inspector is concerned: a
    cleared sanctions match with an empty box is indistinguishable from one
    nobody looked at. The command side refuses it; so does the fold, because
    only one of the two is the record.
    """


class TheFileIsAboutThem(DecisionDenied):
    """The person settling this file is the person it is about.

    Four eyes was scoped to escalation alone: both guards compared the actor
    against ``case.escalations`` and against nothing else. Nothing compared
    the decider to the *subject*. A governance file names its subject in as
    many words -- "the compliance officer (Aarav Sharma) is not recorded as
    based in the IFSC" -- and Aarav Sharma could settle it::

        settled by the person it is about: APPROVED by Aarav Sharma

    No refusal, no marker, on a permanent record. Customer files are not
    reachable this way, because their subject is an entity id rather than a
    person's name; the entity-level governance and licence files are, and
    those are exactly the files about a named office holder.

    Where a firm has only one eligible officer, the refusal is itself the
    finding worth showing.
    """


class EscalationNeedsAnotherOfficer(DecisionDenied):
    """The officer who passed a file up is trying to settle it themselves.

    Four eyes, enforced rather than hoped for: escalating means handing the
    question to somebody else, and a rule that lets the same person answer
    their own escalation is a rule that does not exist.
    """


#: What people type when they want the box to go away. The FCA has named
#: one-word closures as evidence of a paper control, and a reason that says
#: nothing cannot be read by the inspector it exists for.
STOCK_NON_REASONS = frozenset({
    "ok", "okay", "checked", "reviewed", "fine", "done", "cleared",
    "approved", "rejected", "verified", "confirmed", "yes", "agreed",
    "noted", "na", "n a", "none", "good", "all good", "no issues",
    "no issues found", "looks fine", "looks ok", "looks good",
    "as discussed", "see notes", "per above", "as above",
    "self explanatory", "reviewed and cleared", "checked and cleared",
    "reviewed and approved", "checked and approved", "all looks good",
    # Found by measuring the gate rather than by imagining it: each of these
    # cleared a three-word floor while saying nothing that could be checked.
    "fine by me", "this is fine", "closed as agreed", "as agreed",
    "no further action", "nothing to add", "happy with this",
    "content with this", "asdf", "test", "aaa", "xxx", "abc",
})


#: The kinds clause 5.5 reserves to senior management. A close associate
#: is here because Guidance Note (3) says relationships with relatives and
#: close associates "involve similar risks", and the measures applied to
#: PEPs "should also apply" to them -- and 5.5(b)(iii) is one of those
#: measures.
_SENIOR_APPROVAL_KINDS = frozenset({"PEP", "PEP_ASSOCIATE"})


def is_pep(case) -> bool:
    """Whether this file is about somebody in public office, or a relative
    or close associate of one.

    Read off the evidence the policy recorded rather than recomputed, so a
    later change to how screening classifies lists cannot retrospectively
    make somebody a PEP who was not one when the officer decided.

    **It read one value, and one value was the wrong question.** A match is
    filed under the most serious thing it is, so a sanctioned head of state
    is a SANCTIONS match -- correct for triage, because that is the one
    that stops the money. This gate then asked that same label whether the
    party was politically exposed, and was told no. Vladimir Putin, Bashar
    Assad and Kim Jong-un all classify as SANCTIONS against the watchlist
    this product ships with, and all three carry ``role.pep``; a sanctioned
    politically exposed person could be cleared by any officer. Of 847
    sanctioned persons sampled from that index, 21.4% were also politically
    exposed or a close associate of somebody who is.

    So it reads every kind the match carried. ``list_types`` is written by
    the screening boundary; ``list_type`` is still read for evidence
    recorded before that existed, which keeps this a reading of what the
    policy wrote rather than a recomputation.
    """
    for evidence in case.evidence:
        detail = evidence.detail or {}
        kinds = detail.get("list_types")
        if not kinds:
            kinds = [detail.get("list_type") or ""]
        if any(str(kind) in _SENIOR_APPROVAL_KINDS for kind in kinds):
            return True
    return False


#: The longest reason that goes on the record. Named because it is on a
#: permanent event and in every export of it: a reason nobody can read is
#: not evidence, and an unbounded one turns one careless paste into a row
#: that breaks the spreadsheet an inspector opens. Generous -- a full page
#: of typing clears it -- and stated, so a reason cut short says so rather
#: than being decided by the size of an HTTP request body.
LONGEST_REASON = 4_000

#: Tokens: letters in any script, and digits. Both parts were wrong before.
#: ``[a-z']+`` counted ASCII letters only, so **every reason written in an
#: Indian script was refused outright** -- the product could not be used in a
#: language it was built for, and the officer was told their reason said
#: nothing. And ignoring digits refused "DOB 1971 vs 1985", which is the
#: single commonest true reason on a name match and is item one on OFAC's own
#: checklist, quoted in ``SCREENING_REASONS``.
_A_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _said_once(words: Sequence[str]) -> str:
    """The distinct words, in order, for comparing against the stock list.

    "ok ok ok" and "n/a n/a n/a" cleared a three-word floor and meant exactly
    what "ok" means. Repeating a non-reason does not make it a reason.
    """
    seen: list[str] = []
    for word in words:
        if word not in seen:
            seen.append(word)
    return " ".join(seen)


def names(case, person: str) -> bool:
    """Whether this file is about this person, by name.

    Read off the evidence the rules recorded, because that is where a
    governance finding puts the office holder it is about. Compared without
    regard to case or surrounding space, and never on an empty name -- an
    unnamed actor is not everybody.
    """
    who = str(person or "").strip().casefold()
    if not who:
        return False
    for piece in case.evidence:
        named = str((piece.detail or {}).get("person") or "").strip()
        if named and named.casefold() == who:
            return True
    return False


def thin_reason(text: str) -> bool:
    """Whether a rationale says anything at all.

    Three words is a low bar on purpose: "Different birth dates" clears it,
    and the point is not to grade prose but to refuse the click-through.

    Measured on 12 reasons a screening officer would really type and 13
    one-line closures, the previous version refused **5 of the 12 genuine
    ones** -- including all three written in a non-Latin script -- and let
    **10 of the 13 closures** through. It was catching the wrong side.
    """
    words = _A_WORD.findall((text or "").lower())
    if len(words) < 3:
        return True
    return _said_once(words) in STOCK_NON_REASONS


class UnknownCase(KeyError):
    pass


def _reopened_case_id(finding: Finding, subject: str, closed: Case) -> str:
    """The id for a fresh Case reopening one that is no longer open.

    Chained off the seq of the decision that closed the prior Case rather
    than a counter or the triggering record's id: the same closed Case
    always derives the same successor, so replaying the log reaches the
    same chain of ids every time, on any machine.
    """
    assert closed.decision is not None, "a non-open Case always has a decision"
    dedupe_key = f"{finding.dedupe_key}|reopened-after:{closed.decision.seq}"
    return make_case_id(finding.policy_id, subject, dedupe_key)


def finding_specs(
    casebook: "CaseBook",
    findings: Iterable[Finding],
    fact: Event,
    rulepack: str,
) -> list[dict[str, Any]]:
    """Turn the rulepack's conclusions about one fact into event specs.

    Whether a finding opens a Case or extends one is decided *now* and
    recorded — so the case id a decision will later reference is a fact in the
    log, never something a future version of the dedupe logic has to
    recompute.

    A case id that already names a Case is only "existing" while that Case is
    still open. A breach that recurs after the Case was decided must not fold
    onto the closed Case as more evidence for a question that is settled — it
    reopens as a new Case, with a fresh id derived from the closed one so
    replay always lands on the same chain of ids.
    """
    specs: list[dict[str, Any]] = []
    opened: set[str] = set()
    for finding in findings:
        case_id = finding.case_id(fact.subject)
        while case_id not in opened:
            case = casebook.cases.get(case_id)
            if case is None or case.is_open:
                break
            case_id = _reopened_case_id(finding, fact.subject, case)
        exists = case_id in casebook.cases or case_id in opened
        opened.add(case_id)
        specs.append({
            "event_type": (EventType.EVIDENCE_RECORDED if exists
                           else EventType.CASE_OPENED),
            "subject": fact.subject,
            "occurred_at": fact.occurred_at,
            "actor": "system",
            "payload": {
                "case_id": case_id,
                "case_type": finding.case_type,
                "severity": str(finding.severity),
                "summary": finding.summary,
                "policy_id": finding.policy_id,
                "detail": dict(finding.detail),
                "citations": list(finding.citations),
                "source_seq": fact.seq,
                "rulepack": rulepack,
            },
        })
    return specs


class CaseBook:
    """All Cases, folded from the log. Rebuildable at any time."""

    def __init__(self) -> None:
        self.cases: dict[str, Case] = {}

    # -- folding ------------------------------------------------------------

    def fold_finding(self, event: Event) -> Case:
        """Fold one recorded finding. Everything comes from the payload."""
        payload = event.payload
        severity = Severity(payload["severity"])
        evidence = Evidence(
            kind=EvidenceKind.RULE,
            summary=payload["summary"],
            source_seq=payload["source_seq"],
            policy_id=payload["policy_id"],
            detail=payload["detail"],
            citations=tuple(payload["citations"]),
        )

        case = self.cases.get(payload["case_id"])
        if case is None:
            case = Case(
                case_id=payload["case_id"],
                case_type=payload["case_type"],
                subject=event.subject,
                severity=severity,
                opened_seq=payload["source_seq"],
                opened_at=event.occurred_at,
                evidence=[evidence],
            )
            self.cases[case.case_id] = case
            return case

        # The same finding folded twice (a defensive guard, not an expected
        # path) must not duplicate evidence.
        already = any(
            e.policy_id == evidence.policy_id and e.source_seq == evidence.source_seq
            for e in case.evidence
        )
        if not already:
            case.evidence.append(evidence)
        if severity.rank > case.severity.rank:
            case.severity = severity
        return case

    def fold_draft(self, event: Event) -> Case:
        """Attach a recorded suggestion to its Case.

        Kept strictly separate from evidence that carries weight: a draft is
        what the system said, not a finding, and the Case is decided exactly
        as it would have been without one.
        """
        payload = event.payload
        case = self.cases.get(payload["case_id"])
        if case is None:
            raise UnknownCase(payload["case_id"])
        case.draft = dict(payload)
        case.evidence.append(
            Evidence(
                kind=EvidenceKind.SUGGESTION,
                summary=f"A suggestion was prepared: {payload['recommendation']}",
                source_seq=event.seq,
                detail={"model": payload.get("model"),
                        "prompt_version": payload.get("prompt_version"),
                        "cost_usd": payload.get("cost_usd")},
            )
        )
        return case

    def apply_decision(self, event: Event) -> Case:
        """Fold a ``CASE_DECIDED`` event.

        The role check lives here; the enrolment check lives in the engine's
        fold, which can see who was enrolled earlier in the stream.
        """
        payload = event.payload
        case = self.cases.get(payload["case_id"])
        if case is None:
            raise UnknownCase(payload["case_id"])

        if not case.is_open:
            raise DecisionAlreadyRecorded(
                f"{case.case_id} was already settled as {case.status.value} "
                f"and cannot be settled again (seq {event.seq})"
            )

        role = Role(payload["role"])
        if role not in DECIDING_ROLES:
            raise DecisionDenied(
                f"role {role.value} cannot decide a Case (seq {event.seq})"
            )

        if not str(payload.get("rationale", "")).strip():
            raise DecisionNeedsAReason(
                f"{event.actor} settled {case.case_id} with nothing written "
                f"in it (seq {event.seq})"
            )

        outcome = Outcome(payload["outcome"])

        # Four eyes: whoever passed this file up can neither settle it nor
        # push it up again. Enforced on the fold as well as on the command,
        # so a decision written straight into the log by the escalating
        # officer fails on every replay.
        if any(entry["by"] == event.actor for entry in case.escalations):
            raise EscalationNeedsAnotherOfficer(
                f"{event.actor} escalated this Case and cannot also settle "
                f"it (seq {event.seq})"
            )

        if names(case, event.actor):
            raise TheFileIsAboutThem(
                f"{event.actor} settled a file that is about them "
                f"(seq {event.seq})"
            )

        # Clause 5.5(b)(iii): senior management approves a PEP, or nobody
        # does. Enforced on the fold as well as the command, so a clearance
        # written straight into the log by a junior officer fails on every
        # replay rather than standing because nobody looked again.
        if (outcome is Outcome.APPROVE and is_pep(case)
                and role is not Role.SENIOR_MGMT):
            raise SeniorManagementMustApprove(
                f"{event.actor} cleared a politically exposed person "
                f"without senior management approval (seq {event.seq})"
            )

        if outcome is Outcome.ESCALATE:
            # A handover, not an answer: the file stays open, now needing a
            # different officer, and the handover itself goes on the record.
            case.escalations.append({
                "by": event.actor,
                "role": role.value,
                "on": event.occurred_at,
                "why": payload.get("rationale", ""),
            })
            case.status = CaseStatus.ESCALATED
            case.evidence.append(
                Evidence(
                    kind=EvidenceKind.DECISION,
                    summary=f"ESCALATE by {event.actor} ({role.value})",
                    source_seq=event.seq,
                    detail={"rationale": payload.get("rationale", "")},
                )
            )
            return case

        decision = Decision(
            outcome=outcome,
            actor=event.actor,
            role=role,
            rationale=payload.get("rationale", ""),
            decided_at=event.occurred_at,
            seq=event.seq,
            draft_use=str(payload.get("draft_use", "NONE")),
            reason_code=str(payload.get("reason_code", "")),
        )
        case.decision = decision
        case.status = OUTCOME_STATUS[outcome]
        case.evidence.append(
            Evidence(
                kind=EvidenceKind.DECISION,
                summary=f"{outcome.value} by {event.actor} ({role.value})",
                source_seq=event.seq,
                detail={"rationale": decision.rationale},
            )
        )
        return case

    # -- reading --------------------------------------------------------------

    def queue(self, open_only: bool = True) -> list[Case]:
        """The work list: most severe first, then oldest first."""
        cases = self.cases.values()
        if open_only:
            cases = [c for c in cases if c.is_open]
        return sorted(cases, key=lambda c: c.queue_key)

    def for_subject(self, subject: str) -> list[Case]:
        return sorted(
            (c for c in self.cases.values() if c.subject == subject),
            key=lambda c: c.opened_seq,
        )

    def get(self, case_id: str) -> Case:
        case = self.cases.get(case_id)
        if case is None:
            raise UnknownCase(case_id)
        return case

    def __len__(self) -> int:
        return len(self.cases)


def check_can_decide(role: Role) -> None:
    """Command-side gate. Call before writing a decision to the log."""
    if role not in DECIDING_ROLES:
        raise DecisionDenied(
            f"role {role.value} cannot decide a Case; "
            f"permitted roles are {sorted(r.value for r in DECIDING_ROLES)}"
        )
