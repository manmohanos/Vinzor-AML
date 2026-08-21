"""Value types for the Vinzor core.

Everything in this module is data: no I/O, no clock, no globals, no network.
That is deliberate. If a value cannot be derived from its inputs alone, it does
not belong here.

Design notes worth knowing before you edit:

* **No wall clock, anywhere.** Every timestamp is supplied by the caller. A core
  that reads ``datetime.now()`` cannot be replayed, and a system that cannot be
  replayed cannot be audited.
* **No numeric risk score.** Cases carry a ``Severity`` that comes from the
  policy that opened them, because the policy is the thing that knows *why*.
  A composite 0-100 score is a lossy summary of the evidence that already
  exists on the Case, and it invents precision a regulator would ask you to
  defend. If a customer ever needs a configurable scoring methodology, it is
  additive -- it is not needed to make the system correct.
"""

from __future__ import annotations

import hashlib
import re
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

GENESIS_HASH = "0" * 64


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class StrEnum(str, Enum):
    """A string enum whose ``str()`` is its value.

    ``class X(str, Enum)`` alone inherits ``Enum.__str__``, so ``str(X.A)`` is
    ``"X.A"`` rather than ``"A"`` -- which silently poisons anything serialised
    or hashed. Every enum below derives from this instead.
    (``enum.StrEnum`` does the same thing but only exists on Python 3.11+.)
    """

    def __str__(self) -> str:
        return str(self.value)


class EventType(StrEnum):
    """The complete event vocabulary.

    Add a member only when a real producer exists for it. An event type with no
    producer is an unused code path that still has to be maintained.
    """

    ENTITY_REGISTERED = "ENTITY_REGISTERED"
    OWNERSHIP_DECLARED = "OWNERSHIP_DECLARED"
    COMMITMENT_MADE = "COMMITMENT_MADE"
    SCREENING_COMPLETED = "SCREENING_COMPLETED"
    #: The press, searched for a party's name alongside financial-crime
    #: coverage, on a given day. An event rather than a lookup because the
    #: news is not the same tomorrow: the finding rests on the articles that
    #: were actually seen, and replay reads them back rather than asking
    #: again. Recorded when nothing was found too -- an absent record is
    #: indistinguishable from an absent check.
    ADVERSE_MEDIA_CHECKED = "ADVERSE_MEDIA_CHECKED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    CASE_DECIDED = "CASE_DECIDED"

    # The FME's own standing. Added after reading IFSCA's enforcement orders:
    # what most often costs a registration is the entity's own licence and
    # staffing, not its investors.
    LICENCE_GRANTED = "LICENCE_GRANTED"
    OFFICE_APPOINTED = "OFFICE_APPOINTED"
    OFFICE_VACATED = "OFFICE_VACATED"
    ACTIVITY_UNDERTAKEN = "ACTIVITY_UNDERTAKEN"
    AUM_REPORTED = "AUM_REPORTED"

    # What the entity owes the regulator. FILING_OVERDUE is observed at a
    # boundary, which is the only place that knows what day it is.
    FILING_SUBMITTED = "FILING_SUBMITTED"
    FILING_OVERDUE = "FILING_OVERDUE"

    # A letter from the regulator, and the answer to it. Both are facts
    # about the world -- one arrived, one was sent -- so both are events.
    # Whether an answer is late is computed from the two and the date, and
    # is never stored: the whole difficulty of this obligation is that
    # silence is the breach, and a stored "overdue" flag would have to be
    # set by something, at some moment, which is exactly the thing nobody
    # does when a notice is being ignored.
    NOTICE_RECEIVED = "NOTICE_RECEIVED"
    NOTICE_ANSWERED = "NOTICE_ANSWERED"
    #: Observed at a boundary, like FILING_OVERDUE and for the same reason:
    #: nothing happens when a letter goes unanswered, so the passing of the
    #: date has to be looked for rather than waited for.
    NOTICE_OVERDUE = "NOTICE_OVERDUE"

    #: A document filed against a party, and what a person said it
    #: evidences. The fingerprint of the file goes in the record; the
    #: bytes do not -- a log carrying twenty-megabyte scans stops being
    #: something anybody can replay.
    DOCUMENT_FILED = "DOCUMENT_FILED"

    #: What the firm is worth, and the minimum somebody confirmed applies.
    #: Both are facts about the firm rather than about a customer, which is
    #: why they are events and not settings.
    NET_WORTH_REPORTED = "NET_WORTH_REPORTED"
    MINIMUM_CONFIRMED = "MINIMUM_CONFIRMED"

    #: Work a person delegated, and each thing an agent did about it. The
    #: progress somebody watches is a projection of these, so what they saw
    #: was true when they saw it and replays the same a year later.
    TASK_GIVEN = "TASK_GIVEN"
    TASK_STEP = "TASK_STEP"
    TASK_FINISHED = "TASK_FINISHED"

    # What the system and its operators did -- facts about the running of
    # the workspace, in the same log as the facts of the world. Findings
    # are recorded rather than derived so that no later change to any rule
    # can rewrite what the system said (see DESIGN.md).
    CASE_OPENED = "CASE_OPENED"
    EVIDENCE_RECORDED = "EVIDENCE_RECORDED"
    # A spreadsheet was brought in: which file, its digest, what mapped,
    # what was written. The import is itself a record -- the first question
    # about any surprising party is "where did this row come from", and the
    # digest is what makes "this exact file, again" a checkable claim.
    SHEET_IMPORTED = "SHEET_IMPORTED"
    ACTOR_ENROLLED = "ACTOR_ENROLLED"
    ACTOR_REVOKED = "ACTOR_REVOKED"

    # A qualified person confirming that a clause in the register really says
    # what this system quotes. Recorded rather than configured, because "who
    # checked our rules, and when" is the first thing an inspector asks about
    # a system that applies them -- and because a claim nobody signed is a
    # claim nobody can be held to.
    CLAUSE_VERIFIED = "CLAUSE_VERIFIED"

    # A person's judgement of how risky a customer is, under clause 4.2,
    # with the factors they took into account. Recorded rather than
    # computed: clause 4.2 says in terms that the presence of one or more
    # factors "may not always indicate a high risk", so the category is a
    # judgement somebody made and must be attributable to them.
    RISK_ASSESSED = "RISK_ASSESSED"

    # What the assistant suggested. A fact about the system, recorded like
    # any other -- so an inspector can see what was put in front of the
    # officer, not merely what the officer concluded.
    DRAFT_PREPARED = "DRAFT_PREPARED"

    # A question the officer put to the assistant, and what it told them.
    # Recorded for the same reason as a prepared suggestion: an inspector
    # asking "what did this system tell you about that investor, and when"
    # needs somewhere to look, and a guard that fires silently is a guard
    # nobody can audit.
    ASSISTANT_ASKED = "ASSISTANT_ASKED"
    RECORD_OPENING_WRITTEN = "RECORD_OPENING_WRITTEN"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        """Sort key for the case queue. Higher is more urgent."""
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


class Role(StrEnum):
    """Who is acting.

    ``AI`` is a first-class role precisely so that it can be denied. An AI actor
    that is merely "not given a token" is a configuration accident; an AI actor
    that is explicitly outside ``DECIDING_ROLES`` is a structural guarantee.
    """

    COMPLIANCE = "COMPLIANCE"
    AML_OFFICER = "AML_OFFICER"
    SENIOR_MGMT = "SENIOR_MGMT"
    VIEWER = "VIEWER"
    AI = "AI"
    SYSTEM = "SYSTEM"


#: The only roles permitted to close a Case. Enforced on write *and* on replay.
DECIDING_ROLES = frozenset({Role.COMPLIANCE, Role.AML_OFFICER, Role.SENIOR_MGMT})


class Outcome(StrEnum):
    APPROVE = "APPROVE"
    ESCALATE = "ESCALATE"
    REJECT = "REJECT"


class CaseStatus(StrEnum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    ESCALATED = "ESCALATED"
    REJECTED = "REJECTED"


#: A decision outcome maps to exactly one terminal status.
OUTCOME_STATUS = {
    Outcome.APPROVE: CaseStatus.APPROVED,
    Outcome.ESCALATE: CaseStatus.ESCALATED,
    Outcome.REJECT: CaseStatus.REJECTED,
}


class EvidenceKind(StrEnum):
    RULE = "RULE"          # a policy fired
    FACT = "FACT"          # something observed in the data
    DECISION = "DECISION"  # a human ruled
    SUGGESTION = "SUGGESTION"  # the assistant drafted something


class DraftUse(StrEnum):
    """What the officer did with a draft that was on screen.

    ``CONTRADICTED`` is the number that matters. A draft recommending the
    parties are probably different, on a file the officer escalates, is
    the failure mode that could cost a licence -- so it is measured from
    the first day rather than discovered later.
    """

    ACCEPTED = "ACCEPTED"        # used the wording unchanged
    EDITED = "EDITED"            # used it and changed the words
    REJECTED = "REJECTED"        # wrote their own instead
    CONTRADICTED = "CONTRADICTED"  # decided against the recommendation
    NONE = "NONE"                # there was no draft to use


class Relation(StrEnum):
    """Graph relations.

    ``OWNS`` reads *source owns target* -- ``per_0001 OWNS cmp_0004 (100%)``
    means the person holds the company. The direction is stated here once so
    that no traversal has to guess it.

    ``SETTLOR_OF`` and ``TRUSTEE_OF`` exist because IFSCA 1.3.3(d) requires the
    author and the trustee of a trust to be identified as beneficial owners
    regardless of any percentage. Nothing in the current dataset produces a
    ``SETTLOR_OF`` edge -- which is itself the finding: the party is
    undeclared, and the Case says so.
    """

    OWNS = "OWNS"
    TRUSTEE_OF = "TRUSTEE_OF"
    SETTLOR_OF = "SETTLOR_OF"
    BENEFICIARY_OF = "BENEFICIARY_OF"


class EntityKind(StrEnum):
    """Customer types.

    The non-person members are the categories IFSCA 1.3.3 distinguishes, each
    of which carries its own beneficial-ownership test. They are all listed
    because the clause lists them: a partial transcription of a legal test is
    more dangerous than none.
    """

    PERSON = "PERSON"
    COMPANY = "COMPANY"
    PARTNERSHIP = "PARTNERSHIP"
    UNINCORPORATED_BODY = "UNINCORPORATED_BODY"
    TRUST = "TRUST"
    FUND = "FUND"
    #: A party whose type nobody has recorded -- the remitter on a bank
    #: statement, known only by name. Not one of the 1.3.3 customer
    #: categories: recording "person" or "company" for a name on a statement
    #: would put a fact on the record that nobody asserted. Screening still
    #: works (the watchlist query widens to cover either), and if such a
    #: party ever acquires owners, the strictest threshold applies.
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


class NotRecordable(ValueError):
    """A payload holding something JSON cannot represent."""


def canonical_json(value: Any) -> str:
    """Stable JSON: sorted keys, no incidental whitespace.

    Two structurally equal payloads must produce byte-identical output or the
    hash chain is not reproducible across processes.

    ``allow_nan`` is off, and it is the reason this raises. Python's default
    happily writes ``NaN`` and ``Infinity``, which are *not* JSON: the file
    stops being readable by a strict parser, the hash covers something no
    other implementation would agree with, and the record a regulator is
    handed cannot be opened by their tools. A division that produced a
    not-a-number is a defect upstream, and the place to find out is the
    moment somebody tries to write it down -- not eighteen months later when
    somebody else tries to read it.
    """
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            default=str, allow_nan=False,
        )
    except ValueError as why:
        raise NotRecordable(
            "this cannot go on the record: it holds a value JSON has no way "
            "to write (a not-a-number or an infinity). Something that "
            "computed it went wrong; the record is not the place to hide it."
        ) from why


def event_digest(
    *,
    prev_hash: str,
    seq: int,
    event_type: str,
    subject: str,
    occurred_at: str,
    actor: str,
    payload: Mapping[str, Any],
) -> str:
    """SHA-256 over the previous hash plus every field of this event.

    Because ``prev_hash`` is an input, altering any historical event
    invalidates every hash after it -- the log is tamper-evident, not merely
    tamper-discouraged.
    """
    body = canonical_json(
        {
            "seq": seq,
            "event_type": str(event_type),
            "subject": subject,
            "occurred_at": occurred_at,
            "actor": actor,
            "payload": payload,
        }
    )
    return hashlib.sha256(f"{prev_hash}|{body}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Event:
    """One immutable fact, as recorded in the log.

    ``seq`` is assigned by the log and is dense and monotonic from 1.
    """

    seq: int
    event_type: EventType
    subject: str
    occurred_at: str
    actor: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    prev_hash: str = GENESIS_HASH
    event_hash: str = ""

    def recompute_hash(self) -> str:
        return event_digest(
            prev_hash=self.prev_hash,
            seq=self.seq,
            event_type=self.event_type,
            subject=self.subject,
            occurred_at=self.occurred_at,
            actor=self.actor,
            payload=self.payload,
        )


@dataclass(frozen=True)
class Evidence:
    """An atomic, self-explanatory unit attached to a Case.

    ``source_seq`` is mandatory. Every piece of evidence points back at the
    event that produced it, so "why does this Case say that?" is always
    answerable by reading one row of the log.
    """

    kind: EvidenceKind
    summary: str
    source_seq: int
    policy_id: Optional[str] = None
    detail: Mapping[str, Any] = field(default_factory=dict)
    #: The clause(s) this evidence rests on, copied from the Finding so the
    #: Case is self-contained: it can be read without the policy registry.
    citations: Sequence[Mapping[str, Any]] = ()


@dataclass(frozen=True)
class Decision:
    """A human ruling. The only thing that can close a Case."""

    outcome: Outcome
    actor: str
    role: Role
    rationale: str
    decided_at: str
    seq: int
    #: What the officer did with the draft in front of them.
    draft_use: str = "NONE"
    #: A short slug naming the kind of reason, from a fixed plain-word list
    #: ("different-birth", "same-party"). Optional; the written rationale is
    #: still required. Exists because a free-text box alone permits the
    #: one-word closures examiners name as evidence of a paper control, and
    #: because reasons that cannot be counted cannot be reviewed.
    reason_code: str = ""


@dataclass
class Case:
    """The primitive: a unit of accountability with its own decision history."""

    case_id: str
    case_type: str
    subject: str
    severity: Severity
    opened_seq: int
    opened_at: str
    evidence: list[Evidence] = field(default_factory=list)
    status: CaseStatus = CaseStatus.OPEN
    decision: Optional[Decision] = None
    #: Who has passed this file up, when, and why. Rebuilt by the fold; the
    #: same names are what the four-eyes rule checks a settling officer
    #: against.
    escalations: list = field(default_factory=list)
    #: The assistant's suggestion, if one was prepared. Never authoritative.
    draft: Optional[Mapping[str, Any]] = None

    @property
    def is_open(self) -> bool:
        """Escalated counts as open. An escalation is a handover, not an
        answer: the file leaves one desk for another, and a queue that files
        it as finished is how a passed-up question is never settled."""
        return self.status in (CaseStatus.OPEN, CaseStatus.ESCALATED)

    @property
    def queue_key(self) -> tuple:
        """Most severe first, then oldest first.

        Oldest by the day it happened, not by the order it was written down.
        Those are the same thing only for a workspace that has always been
        live: a firm importing two years of history, or a dataset seeded in
        whatever order it was authored, gets a sequence that has nothing to
        do with the calendar -- and this list promised "oldest first" while
        putting a file from 2018 fiftieth. The sequence stays as the
        tie-breaker so two files opened on one day always order the same
        way, on this machine and on a replay of it.
        """
        return (-self.severity.rank, str(self.opened_at), self.opened_seq)


def check_date(value: str, field: str = "occurred_at") -> str:
    """A real calendar date, or a refusal that says which one was not.

    Validated at the boundary rather than trusted, because everything
    downstream does arithmetic on it: a payment dated 2026-13-45 reached the
    payment window and came back as "tuple index out of range", which tells an
    operator loading a client file precisely nothing. Worse, event types that
    happen to do no date arithmetic accepted the same value quietly, so a
    workspace could carry a date that only failed years later when something
    finally tried to read it.

    Uses ``date`` for the calendar rules rather than restating them: February
    has 29 days in 2024 and 28 in 2026, and nobody should be maintaining a
    second opinion about that.
    """
    from datetime import date as _date

    text = (value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError(
            f"{field} must be a date written as YYYY-MM-DD, not {value!r}"
        )
    year, month, day = (int(part) for part in text.split("-"))
    try:
        _date(year, month, day)
    except ValueError as wrong:
        raise ValueError(f"{field} {value!r} is not a real date: {wrong}") from None
    return text


def check_amount(payload: Mapping[str, Any]) -> dict:
    """A payment with money on it that can actually be read.

    Every amount rule guards with ``isinstance(amount, (int, float))``, so a
    feed that sends "1000" as text -- and plenty do -- turned overpayment and
    structuring off silently. No error, no finding, no sign at all: the queue
    simply stopped mentioning that investor. Silence is the one failure this
    system must never produce, so an amount is coerced where it plainly is a
    number and refused where it is not.
    """
    out = dict(payload)
    for field in ("amount", "called_amount"):
        value = out.get(field)
        if value is None or isinstance(value, (int, float)):
            continue
        text = str(value).strip().replace(",", "")
        try:
            out[field] = float(text)
        except ValueError:
            raise ValueError(
                f"{field} {value!r} is not an amount; a payment whose money "
                f"cannot be read would silently switch off every rule that "
                f"looks at it"
            ) from None
    amount = out.get("amount")
    if isinstance(amount, (int, float)) and amount < 0:
        raise ValueError(
            f"amount {amount!r} is negative; money moving the other way is a "
            f"reversal and needs its own record, not a payment with a minus "
            f"sign"
        )
    return out


def check_reported(payload: Mapping[str, Any]) -> dict:
    """The figures on a regulatory return, read as figures.

    Nothing coerced or refused them, and all three ways it could go wrong
    went wrong.

    * ``{"capital_received_usd": "44000000"}`` was accepted and then failed
      every ``isinstance(..., (int, float))`` downstream, so it opened a HIGH
      case whose own permanent record read *"reported: nothing recorded"* --
      a case that exists because a figure was filed, stating that no figure
      was filed.
    * ``{"investors": "twelve"}`` and ``{"investors": [1, 2, 3]}`` raised a
      raw ``ValueError``/``TypeError`` out of a policy and out of ``ingest``.
      The caller got a Python message where the design says a sentence, and
      because ``disclosure.compare`` runs on every render of the regulatory
      page, a value of that shape recorded by an actor whose findings are
      gated off would have taken the page down permanently.
    * A key nobody reports on -- ``{"aum": 48_000_000}``, one letter short of
      ``aum_usd`` -- produced no rows and no complaint at all.

    Coerced where it plainly is a number, refused with a sentence where it is
    not. Same shape as ``check_amount``, for the same reason.
    """
    from .disclosure import CLAIMS

    out = dict(payload)
    reported = out.get("reported")
    if reported is None:
        return out
    if not isinstance(reported, Mapping):
        raise ValueError(
            "the figures on a return have to be given as a set of named "
            "figures; this was "
            f"{type(reported).__name__}"
        )

    read: dict = {}
    for key, value in reported.items():
        if key not in CLAIMS:
            raise ValueError(
                f"there is nothing on a return called {key!r}. The figures "
                f"this system compares are: {', '.join(sorted(CLAIMS))}"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError(
                f"a reported figure has to be a number; {key!r} was "
                f"{value!r}"
            )
        try:
            number = float(str(value).replace(",", "").strip())
        except ValueError:
            raise ValueError(
                f"a reported figure has to be a number; {key!r} was "
                f"{value!r}"
            ) from None
        if number < 0:
            raise ValueError(
                f"a reported figure cannot be negative; {key!r} was {value!r}"
            )
        read[key] = number if key.endswith("_usd") else int(number)
    out["reported"] = read
    return out


def check_share(payload: Mapping[str, Any]) -> dict:
    """A percentage somebody could actually hold.

    A declaration of 150% was accepted and reported as an identified
    beneficial owner, which is a fact about nothing. A negative one was read
    as being under the threshold and quietly turned into a senior managing
    official instead.
    """
    out = dict(payload)
    share = out.get("percentage")
    if share is None:
        return out
    try:
        share = float(share)
    except (TypeError, ValueError):
        raise ValueError(
            f"percentage {out.get('percentage')!r} is not a number"
        ) from None
    if not 0.0 <= share <= 100.0:
        raise ValueError(
            f"percentage {share!r} is not a share anybody can hold; a "
            f"holding runs from 0 to 100"
        )
    out["percentage"] = share
    return out


def make_case_id(policy_id: str, subject: str, dedupe_key: str) -> str:
    """Deterministic Case identity.

    Derived from content rather than a counter or a UUID, so that replaying the
    same log always produces the same Case IDs. That is what lets a
    ``CASE_DECIDED`` event keep pointing at the right Case after a rebuild.

    ``dedupe_key`` decides the grain: pass the triggering record's id for
    "one Case per occurrence", or an empty string for "one Case per subject".
    """
    raw = f"{policy_id}|{subject}|{dedupe_key}"
    return "case_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class Finding:
    """A policy's verdict on one event: open (or extend) this Case.

    ``citations`` is not optional in practice. A finding that cannot name the
    clause it enforces is an opinion, and this system does not trade in
    opinions -- see ``policies.py``, where the registry refuses to run a policy
    that produces an uncited finding.
    """

    policy_id: str
    case_type: str
    severity: Severity
    summary: str
    dedupe_key: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)
    citations: Sequence[Mapping[str, Any]] = ()

    def case_id(self, subject: str) -> str:
        return make_case_id(self.policy_id, subject, self.dedupe_key)
