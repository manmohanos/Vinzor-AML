"""Policy-as-Code: the rules that turn events into Cases.

Policies are plain Python functions. There is no YAML dialect and no ``eval``.

That is a deliberate reversal of the previous build, which shipped a YAML rule
DSL *and* a second engine that ran Python expressions from a config file
through ``eval``. Both existed to let a non-engineer edit rules without a
deploy -- a feature bought on credit for a customer who does not exist yet. The
costs were immediate: two engines pointed at one filename, a config file the
engine that claimed it could no longer parse, and an arbitrary-code-execution
path in compliance logic. Functions are typed, testable, greppable and
reviewable in a diff, which is what a regulator asks of a control.

**Every finding cites the clause it enforces.** ``evaluate`` refuses to accept
an uncited finding, so a rule cannot reach a Case on nothing but this author's
opinion of good practice. The obligation text on each Case is the regulator's,
not mine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from .calendar import BY_OBLIGATION, Calendar, Obligation
from .citations import cite
from .graph import Conclusion, OwnershipGraph
from .licence import Activity, Licence, Office, UNOBSERVABLE
from .payments import anomalies
from .capital import Capital
from .disclosure import Book
from .correspondence import Correspondence
from .documents import Papers
from .duplicates import Resemblances, look
from .model import EntityKind, Event, EventType, Finding, Severity

#: Stamped into every finding the pack produces. Bump on any change to a
#: policy, a severity, a dedupe key or the clause register: findings are
#: permanent, and this is how a Case says which rules wrote it.
RULEPACK = "2026-08-21.1"

CASE_SCREENING_HIT = "SCREENING_HIT"
CASE_UBO_REVIEW = "UBO_REVIEW"
CASE_PAYMENT_MISMATCH = "PAYMENT_MISMATCH"
CASE_LICENCE_SCOPE = "LICENCE_SCOPE"
CASE_GOVERNANCE = "GOVERNANCE"
CASE_FILING = "FILING"
CASE_SAME_PARTY = "SAME_PARTY"
CASE_NOTICE = "NOTICE"
CASE_DOCUMENT = "DOCUMENT"
CASE_CAPITAL = "CAPITAL"
CASE_DISCLOSURE = "DISCLOSURE"
CASE_REVIEW = "REVIEW"


@dataclass(frozen=True)
class PolicyContext:
    """Everything a policy is allowed to see: one event and the graph."""

    event: Event
    graph: OwnershipGraph
    licence: Licence = field(default_factory=Licence)
    calendar: Calendar = field(default_factory=Calendar)
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


Policy = Callable[[PolicyContext], Iterable[Finding]]


class UncitedFinding(RuntimeError):
    """A policy produced a finding with no clause behind it."""


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

#: watchlist type -> (policy id, severity, clauses)
_SCREENING_RULES = {
    "SANCTIONS": ("POL_SANCTIONS_HIT", Severity.CRITICAL, ("5.9", "11.2")),
    # 5.5(b)(iii) as well as 5.5: the file this opens is the one only senior
    # management may clear, and until the register held that limb the officer
    # was shown the clause about *identifying* a PEP and never the one the
    # gate on their screen actually enforces.
    "PEP": ("POL_PEP_HIT", Severity.HIGH, ("5.5", "5.5(b)(iii)", "5.6")),
    "ADVERSE_MEDIA": ("POL_ADVERSE_MEDIA", Severity.MEDIUM, ("4.2", "5.6")),
    # Clause 5.5 Guidance Note (3) puts a close associate under the same
    # measures as the PEP themselves, so the citation and the severity are
    # the PEP ones. What differs is the wording an officer reads.
    "PEP_ASSOCIATE": ("POL_PEP_ASSOCIATE", Severity.HIGH,
                      ("5.5", "5.5(b)(iii)", "5.6")),
    # No clause names a wanted or criminal register. The honest citation is
    # the one already used for adverse media and for the unclassified
    # fallback: the chapeau obligation that a risk-based assessment happens
    # at all, with enhanced diligence. Naming the kind is still worth
    # doing -- "wanted by a law-enforcement agency" is something an officer
    # can act on, and "a watchlist we do not yet classify" is not.
    "CRIMINAL": ("POL_CRIMINAL_HIT", Severity.HIGH, ("4.2", "5.6")),
    "DEBARRED": ("POL_DEBARRED", Severity.MEDIUM, ("4.2", "5.6")),
}

#: A qualifying match against a watchlist category this register has no
#: specific rule for. This is not a hypothetical: OpenSanctions' own topic
#: taxonomy (the live provider behind ``screening.py``) includes categories
#: such as ``role.rca`` (close associate of a PEP), ``debarment``,
#: ``reg.warn``, ``crime.*``, ``wanted`` and ``asset.frozen`` that are none
#: of SANCTIONS, PEP or ADVERSE_MEDIA -- ``screening.py``'s ``Hit.list_type``
#: returns ``None`` for every one of them, and the boundary records the fact
#: as ``"WATCHLIST"`` rather than inventing a category. Before this rule
#: existed, that meant a real match a provider returned was written to the
#: log with ``matched: true`` and then reached no Case, no queue and no
#: briefing line -- recorded, but invisible to the officer who needed to see
#: it, which is worse than an unrecognised list producing nothing at all.
#:
#: Asserting a specific severity or a specific enumerated clause for a
#: category this file cannot name would be exactly the guessing the
#: uncited-finding guard exists to prevent. The honest citation is the one
#: this file already uses for the same problem at ADVERSE_MEDIA: the chapeau
#: obligation that a risk-based assessment happens at all (4.2), with EDD
#: (5.6) -- see clause 4.2's own note in citations.py. Severity is MEDIUM for
#: the same reason: enough to reach a human, not a claim about how serious an
#: unclassified match is.
_UNCLASSIFIED_WATCHLIST_RULE = (
    "POL_WATCHLIST_HIT_UNCLASSIFIED", Severity.MEDIUM, ("4.2", "5.6"),
)


def screening_hit(ctx: PolicyContext) -> Iterable[Finding]:
    if ctx.event.event_type is not EventType.SCREENING_COMPLETED:
        return ()
    payload = ctx.event.payload
    if not payload.get("matched"):
        return ()
    list_type = payload.get("list_type", "")
    policy_id, severity, clauses = _SCREENING_RULES.get(
        list_type, _UNCLASSIFIED_WATCHLIST_RULE
    )
    name = ctx.graph.name_of(ctx.event.subject)
    return (
        Finding(
            policy_id=policy_id,
            case_type=CASE_SCREENING_HIT,
            severity=severity,
            summary=f"{list_type or 'watchlist'} match for {name}",
            dedupe_key=str(payload.get("alert_id", ctx.event.seq)),
            detail={
                "entity": ctx.event.subject,
                "list_type": payload.get("list_type"),
                # Carried onto the finding so the gate on clause 5.5(b)(iii)
                # can read every kind this match is, not only the one it is
                # filed under.
                "list_types": list(payload.get("list_types")
                                   or ([payload["list_type"]]
                                       if payload.get("list_type") else [])),
                "matched_rule": payload.get("rule"),
                "alert_id": payload.get("alert_id"),
            },
            citations=cite(*clauses),
        ),
    )


# ---------------------------------------------------------------------------
# Beneficial ownership
# ---------------------------------------------------------------------------

#: Resolver conclusion -> (policy id, severity, extra clauses).
#: ``IDENTIFIED`` is absent: a satisfied obligation is not a finding.
_UBO_RULES = {
    Conclusion.SENIOR_MANAGING_OFFICIAL_REQUIRED: (
        "POL_UBO_SENIOR_OFFICIAL_REQUIRED",
        Severity.HIGH,
        ("1.3.3(c)", "5.4.5"),
    ),
    Conclusion.INCOMPLETE: ("POL_UBO_INCOMPLETE", Severity.HIGH, ("5.4.5",)),
    Conclusion.NOT_DECLARED: ("POL_UBO_NOT_DECLARED", Severity.MEDIUM, ("5.4.5",)),
}


def ubo_must_be_identified(ctx: PolicyContext) -> Iterable[Finding]:
    """IFSCA 1.3.3 / 5.4.5, applied when capital is committed.

    Triggered by ``COMMITMENT_MADE`` rather than by every ownership edge: an
    incomplete graph mid-ingest is not a compliance failure, an unidentified
    beneficial owner at the moment money is promised is.
    """
    if ctx.event.event_type is not EventType.COMMITMENT_MADE:
        return ()
    investor = ctx.event.payload.get("investor", ctx.event.subject)
    if ctx.graph.kind_of(investor) is EntityKind.PERSON:
        return ()  # a natural person is their own beneficial owner

    result = ctx.graph.resolve_ubo(investor)
    rule = _UBO_RULES.get(result.conclusion)
    if rule is None:
        return ()
    policy_id, severity, clauses = rule
    return (
        Finding(
            policy_id=policy_id,
            case_type=CASE_UBO_REVIEW,
            severity=severity,
            summary=result.explain(),
            dedupe_key="",  # one open ownership question per investor
            detail={
                "investor": investor,
                "investor_kind": result.subject_kind.value if result.subject_kind else None,
                "conclusion": result.conclusion.value,
                "test": {
                    "threshold_pct": result.test.threshold,
                    "inclusive": result.test.inclusive,
                    "clause": result.test.clause,
                },
                "owners": [_owner(o) for o in result.owners],
                "below_threshold": [_owner(o) for o in result.below_threshold],
                "mandatory_parties": [
                    {"party": p.party_id, "name": p.name, "role": p.role}
                    for p in result.mandatory_parties
                ],
                "missing_roles": list(result.missing_roles),
                "cycles": [list(c) for c in result.cycles],
                "dead_ends": list(result.dead_ends),
                "limbs_not_evaluated": list(result.limbs_not_evaluated),
            },
            citations=cite(*sorted({result.test.clause, *clauses})),
        ),
    )


def _owner(owner) -> dict:
    return {
        "person": owner.person_id,
        "name": owner.name,
        "effective_pct": owner.effective_percentage,
        "paths": [list(p) for p in owner.paths],
    }


def ownership_cycle(ctx: PolicyContext) -> Iterable[Finding]:
    """A loop prevents the ownership limb of 1.3.3 from ever terminating."""
    if ctx.event.event_type is not EventType.OWNERSHIP_DECLARED:
        return ()
    payload = ctx.event.payload
    cycle = ctx.graph.cycle_through(payload["owner"], payload["owned"])
    if cycle is None:
        return ()
    ring = tuple(sorted(set(cycle)))
    return (
        Finding(
            policy_id="POL_UBO_CYCLE",
            case_type=CASE_UBO_REVIEW,
            severity=Severity.MEDIUM,
            summary=f"circular ownership: {' -> '.join(cycle)}",
            dedupe_key="|".join(ring),
            detail={
                "cycle": list(cycle),
                "declared_edge": {
                    "owner": payload["owner"],
                    "owned": payload["owned"],
                    "percentage": payload.get("percentage"),
                },
            },
            citations=cite("5.4.5", "1.3.3(a)"),
        ),
    )


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

#: anomaly class -> (policy id, severity, clauses)
_PAYMENT_RULES = {
    "SANCTIONED_PAYER": ("POL_PAY_SANCTIONED_PAYER", Severity.CRITICAL, ("5.9", "11.2")),
    "THIRD_PARTY": ("POL_PAY_THIRD_PARTY", Severity.MEDIUM, ("10.2", "5.4.5")),
}


def payment_anomaly(ctx: PolicyContext) -> Iterable[Finding]:
    """What is wrong with this payment, worked out rather than read off it.

    Two things can be said about a payment here, and only one of them is
    worked out: the money came from someone other than the investor. The
    other, a payer on a sanctions list, is a declared input, because it needs
    a screening record a policy cannot reach.

    Nine further rules were removed on 21 August 2026 and the list of what is
    no longer examined is in ``payments.py``'s own docstring, written out
    there so no reader has to infer it from an absence. The reasoning still
    lives in that module; this turns what it returns into a citable finding.
    """
    if ctx.event.event_type is not EventType.PAYMENT_RECEIVED:
        return ()
    payload = ctx.event.payload
    findings = []
    for name, because in anomalies(ctx.event, ctx.graph):
        rule = _PAYMENT_RULES.get(name)
        if rule is None:
            continue
        policy_id, severity, clauses = rule
        detail = {
            "payment_id": payload.get("payment_id"),
            "payment_ref": payload.get("payment_ref"),
            "amount": payload.get("amount"),
            "currency": payload.get("currency"),
            "payer": payload.get("payer"),
            "fund": payload.get("fund"),
            "because": because,
        }
        findings.append(Finding(
            policy_id=policy_id,
            case_type=CASE_PAYMENT_MISMATCH,
            severity=severity,
            summary=(f"{name} on "
                     f"{payload.get('payment_ref', ctx.event.subject)}: "
                     f"{because}"),
            dedupe_key=f"{payload.get('payment_id', ctx.event.seq)}|{name}",
            detail=detail,
            citations=cite(*clauses),
        ))
    return tuple(findings)


def activity_within_licence(ctx: PolicyContext) -> Iterable[Finding]:
    """Regulation 137 with 3(4): nothing outside the category, without approval.

    IFSCA has penalised entities under this heading for distribution services
    provided without registration and for unauthorised trading access.
    """
    if ctx.event.event_type is not EventType.ACTIVITY_UNDERTAKEN:
        return ()
    activity = Activity(ctx.event.payload["activity"])
    if ctx.licence.permits(activity):
        return ()
    category = ctx.licence.category
    return (
        Finding(
            policy_id="POL_ACTIVITY_OUTSIDE_LICENCE",
            case_type=CASE_LICENCE_SCOPE,
            severity=Severity.CRITICAL,
            summary=(
                f"{activity.value.replace('_', ' ').lower()} is outside the "
                f"{'unregistered' if category is None else category.value.replace('_', ' ').lower()} "
                f"licence"
            ),
            dedupe_key=activity.value,
            detail={
                "activity": activity.value,
                "category": category.value if category else None,
                "licence_number": ctx.licence.number,
                "detail": ctx.event.payload.get("detail"),
            },
            citations=cite("137", "3(4)"),
        ),
    )


#: Any of these can change whether Regulation 7 is satisfied.
_GOVERNANCE_TRIGGERS = (
    EventType.LICENCE_GRANTED,
    EventType.OFFICE_APPOINTED,
    EventType.OFFICE_VACATED,
    EventType.ACTIVITY_UNDERTAKEN,
    EventType.AUM_REPORTED,
)


def offices_must_be_filled(ctx: PolicyContext) -> Iterable[Finding]:
    """Regulation 7: the required posts, held, by people based in the IFSC.

    Re-evaluated whenever something could have changed the answer -- a seat
    vacated, a retail scheme launched, AUM reported. This is the precondition
    for what IFSCA found at Neo Asset Management: it cannot see an empty office,
    but it can see an empty seat.
    """
    if ctx.event.event_type not in _GOVERNANCE_TRIGGERS:
        return ()
    findings = []
    # A seat that has just been refilled attaches to the Case already open
    # for it -- same policy, same key -- so the file reads as the whole
    # story instead of continuing to say nobody is there. It stays open:
    # a person still confirms the appointment and closes it.
    for filled in ctx.licence.just_filled:
        findings.append(
            Finding(
                policy_id="POL_OFFICE_VACANT",
                case_type=CASE_GOVERNANCE,
                severity=Severity.LOW,
                summary=(
                    f"{filled.office.value.replace('_', ' ').lower()} filled by "
                    f"{filled.person} on {filled.filled_on} "
                    f"(vacant since {filled.vacated_on})"
                ),
                dedupe_key=f"{filled.office.value}|vacant",
                detail={
                    "office": filled.office.value,
                    "person": filled.person,
                    "vacated_on": filled.vacated_on,
                    "filled_on": filled.filled_on,
                    "resolved": True,
                    "not_evaluated": [UNOBSERVABLE],
                },
                citations=cite(ctx.licence._clause_for(filled.office), "10(1)"),
            )
        )
    for gap in ctx.licence.gaps():
        vacant = gap.reason == "vacant"
        findings.append(
            Finding(
                policy_id=("POL_OFFICE_VACANT" if vacant
                           else "POL_OFFICE_NOT_BASED_IN_IFSC"),
                case_type=CASE_GOVERNANCE,
                severity=Severity.HIGH,
                summary=(
                    f"no {gap.office.value.replace('_', ' ').lower()} is in post"
                    if vacant else
                    f"the {gap.office.value.replace('_', ' ').lower()} "
                    f"({gap.person}) is not recorded as based in the IFSC"
                ),
                dedupe_key=f"{gap.office.value}|{gap.reason}",
                detail={
                    "office": gap.office.value,
                    "person": gap.person,
                    "due_by": gap.due_by,
                    "category": ctx.licence.category.value if ctx.licence.category else None,
                    "aum_usd": ctx.licence.aum_usd,
                    "not_evaluated": [UNOBSERVABLE],
                },
                citations=cite(gap.clause, "10(1)"),
            )
        )
    return findings


def review_overdue(ctx: PolicyContext) -> Iterable[Finding]:
    """A customer whose diligence was due to be looked at again, and was not.

    Clause 5.11 sets the interval by risk category, and the interval is the
    whole point of the category: it is what a firm does with the judgement,
    not merely a label it files. So a lapsed review is not an administrative
    slip -- it is the customer sitting outside the scrutiny the firm itself
    decided they needed.

    The arithmetic for this has existed since the risk register was built and
    nothing read it. ``due_for_review`` was called by tests and by nothing
    else, which meant a customer whose refresh date passed a year ago was
    correctly computed as overdue and silently never mentioned. A check that
    did not happen must never be reported as a check that found nothing, and
    a system that knows a review is owed and tells nobody is the same defect
    with the answer already in hand.

    Severity follows the category rather than the delay. Clause 5.11 gives
    high-risk customers the shortest interval precisely because they need the
    most scrutiny, so a high-risk review lapsing is the more serious failure
    on the day it lapses -- not after some number of days chosen here. There
    is deliberately no escalation ladder for repeat lapses: unlike a filing,
    where each missed quarter is a separate breach, a review that stays
    undone is one review still undone, and re-reporting it as though it were
    a worsening series would inflate one failure into several.
    """
    if ctx.event.event_type is not EventType.REVIEW_OVERDUE:
        return ()
    payload = ctx.event.payload
    category = str(payload.get("category", "")).upper()
    name = payload.get("name") or ctx.event.subject
    late = int(payload.get("days_late", 0))
    return (
        Finding(
            policy_id="POL_REVIEW_OVERDUE",
            case_type=CASE_REVIEW,
            severity=Severity.HIGH if category == "HIGH" else Severity.MEDIUM,
            summary=(
                f"{name} is rated {category.lower()} risk and was due to be "
                f"reviewed again on {payload.get('due_on')}"
            ),
            dedupe_key=f"{ctx.event.subject}|{payload.get('due_on', '')}",
            detail={
                "name": name,
                "category": category,
                "due_on": payload.get("due_on"),
                "last_assessed_on": payload.get("last_assessed_on"),
                "days_late": late,
                "because": payload.get("because", ""),
            },
            citations=cite("5.11"),
        ),
    )


def filing_overdue(ctx: PolicyContext) -> Iterable[Finding]:
    """A return that is late. Karvy Broking lost its registration this way.

    The lateness is observed at a boundary and arrives as an event, so the
    Case rests on a dated fact rather than on whatever the clock said when
    someone happened to open the page. Repeat failure escalates: the
    enforcement record is not about one missed return, it is about a
    warning ignored and then another quarter missed.
    """
    if ctx.event.event_type is not EventType.FILING_OVERDUE:
        return ()
    payload = ctx.event.payload
    obligation = Obligation(payload["obligation"])
    schedule = BY_OBLIGATION[obligation]
    outstanding = int(payload.get("outstanding_count", 1))
    repeat = outstanding > 1
    charge = int(payload.get("late_charge_usd", 0))
    return (
        Finding(
            policy_id=("POL_FILING_REPEATEDLY_LATE" if repeat
                       else "POL_FILING_OVERDUE"),
            case_type=CASE_FILING,
            severity=Severity.CRITICAL if repeat else Severity.HIGH,
            summary=(
                f"{schedule.label} for {payload['period']} was due "
                f"{payload['due_on']} and has not been {schedule.verb}"
            ),
            dedupe_key=f"{obligation.value}|{payload['period']}",
            detail={
                "obligation": obligation.value,
                "period": payload.get("period"),
                "due_on": payload.get("due_on"),
                "days_late": payload.get("days_late"),
                "late_charge_usd": charge,
                "outstanding_count": outstanding,
                "authority": schedule.authority,
            },
            # KNOWN WRONG for the two fee obligations, and left wrong on
            # purpose. Regulation 120 is "Information to the Authority" -- the
            # authority for *returns*. It says nothing about fees, so an unpaid
            # fee Case currently points an officer at a clause that does not
            # support it.
            #
            # The fix is not a code change: ``Schedule.clause`` already names
            # "fee-4" and "fee-5", and neither is in the clause register
            # because nobody has transcribed the fee circular
            # (IFSCA-DTFA/1/2026) from its primary source. Writing an extract
            # from memory would put a fabricated legal quotation into a
            # compliance record, which is worse than the wrong pointer it
            # replaced. Registering them belongs with the clause-verification
            # work in BACKLOG.md, with the document in front of a person.
            citations=cite("120"),
        ),
    )


def notice_answered(ctx: PolicyContext) -> Iterable[Finding]:
    """The answer, attached to the file that says none arrived.

    The same shape as a refilled seat attaching to the vacancy it fills,
    and for the same reason. A letter answered on 12 August left the open
    file saying, in as many words, "that date passed 19 days ago and
    nothing has been recorded as sent" -- on the queue, on the case page,
    and in the evidence pack an inspector reads. The projection knew
    otherwise the whole time; the file was reading the finding frozen at
    the moment the rule fired.

    The file stays open, because a person settles files here and answering
    a regulator is not the same act as closing the record of having been
    asked. What changes is that it stops saying nothing was sent.
    """
    if ctx.event.event_type is not EventType.NOTICE_ANSWERED:
        return ()
    payload = ctx.event.payload or {}
    reference = str(payload.get("reference") or "")
    notice = ctx.correspondence.notices.get(reference) if ctx.correspondence else None
    if notice is None:
        return ()
    return (
        Finding(
            # The same policy id and the same key as the finding that
            # opened the file, because a case id is made of both: land on
            # the letter's own file rather than opening a second one about
            # the same letter.
            policy_id="POL_NOTICE_UNANSWERED",
            case_type=CASE_NOTICE,
            severity=Severity.LOW,
            summary=f"notice {reference} was answered",
            dedupe_key=f"notice|{reference}",
            detail={
                "reference": reference,
                "from_whom": notice.from_whom,
                "about": notice.about,
                "answer_by": notice.answer_by,
                "received_on": notice.received_on,
                "answered_on": str(ctx.event.occurred_at)[:10],
                "answered_by": str(ctx.event.actor or ""),
                "answer": str(payload.get("answer") or "")[:800],
                "days_late": notice.was_late(),
            },
            citations=cite("120"),
        ),
    )


#: The registry. Order is fixed so replaying a log always produces Cases in the
#: same order.
def already_on_the_book(ctx: PolicyContext) -> Iterable[Finding]:
    """A party who may already be here under another record.

    Found by perturbing shapes we detect: entering an investor twice was the
    cheapest evasion measured, because three payments then landed on two
    records and neither reached a threshold. That rule was removed on
    21 August 2026 and this one was kept: what a second record splits is
    everything held about a party, not only what a counting rule adds up.
    It is mostly not evasion -- registrars export a customer under two
    folios, people marry and change surnames -- and the book is watched
    less closely than it looks either way.

    Raised when the second record arrives rather than swept for later,
    because that is the moment somebody can still say which one is right.
    Nothing is merged: a wrong merge in a log with no undo puts two
    people's payments, screenings and decisions on one record, and no later
    correction can unpick whose was whose.
    """
    if ctx.event.event_type is not EventType.ENTITY_REGISTERED:
        return ()
    found = []
    for pair in look(ctx.graph, ctx.resemblances, ctx.event.subject):
        found.append(Finding(
            policy_id="POL_SAME_PARTY_TWICE",
            case_type=CASE_SAME_PARTY,
            # An authority-issued identifier shared by two records is as
            # near certain as this product gets. A resembling name with
            # something else agreeing is worth a look and no more.
            severity=Severity.HIGH if pair.identified else Severity.MEDIUM,
            summary=f"{pair.left} may already be on the book as {pair.right}",
            dedupe_key="same-party:" + ":".join(sorted((pair.left,
                                                        pair.right))),
            detail={
                "entity": ctx.event.subject,
                "other": pair.right,
                "agrees": list(pair.agrees),
                "disagrees": list(pair.disagrees),
                "identified": pair.identified,
                "because": pair.because,
            },
            citations=cite("10.2", "5.4.5"),
        ))
    return found


def notice_unanswered(ctx: PolicyContext) -> Iterable[Finding]:
    """A letter from the regulator whose date has passed.

    The most severe thing this product opens, and deliberately. A missed
    payment query is a question about a customer; this is a question about
    the firm, asked by the body that licenses it, and left unanswered.
    Regulation 120 requires what is asked to be furnished timely, and the
    published enforcement record has more orders on this ground than on any
    other we had not built for.
    """
    if ctx.event.event_type is not EventType.NOTICE_OVERDUE:
        return ()
    payload = ctx.event.payload or {}
    reference = str(payload.get("reference") or "")
    return (
        Finding(
            policy_id="POL_NOTICE_UNANSWERED",
            case_type=CASE_NOTICE,
            severity=Severity.CRITICAL,
            summary=f"notice {reference} is past the date set for an answer",
            dedupe_key=f"notice|{reference}",
            detail={
                "reference": reference,
                "from_whom": payload.get("from_whom"),
                "about": payload.get("about"),
                "answer_by": payload.get("answer_by"),
                "received_on": payload.get("received_on"),
                "days_late": payload.get("days_late"),
            },
            citations=cite("120"),
        ),
    )


def one_document_two_parties(ctx: PolicyContext) -> Iterable[Finding]:
    """The same file filed against more than one party.

    Free, because the fingerprint was already there to notice a re-upload.
    It is not a clerical slip: the same passport image cannot evidence two
    people, so either one of the records is wrong or the same identity is
    being used twice -- and both are worth an officer's morning.
    """
    if ctx.event.event_type is not EventType.DOCUMENT_FILED:
        return ()
    payload = ctx.event.payload or {}
    digest = str(payload.get("digest") or "")
    others = ctx.papers.parties_sharing(digest) - {ctx.event.subject}
    if not others:
        return ()
    return (
        Finding(
            policy_id="POL_ONE_DOCUMENT_TWO_PARTIES",
            case_type=CASE_DOCUMENT,
            severity=Severity.HIGH,
            summary=f"the same file is filed against {len(others) + 1} parties",
            dedupe_key=f"shared-document|{digest}",
            detail={
                "entity": ctx.event.subject,
                "others": sorted(others),
                "kind": payload.get("kind"),
                "filename": payload.get("filename"),
            },
            citations=cite("5.4.5"),
        ),
    )


#: Every fact that can change the answer to "is this firm short of capital".
#: Both halves of the comparison, not just the firm's own figure: the licence
#: category sets the minimum, a third-party activity adds to it, and a
#: confirmation replaces it outright.
_CHANGES_THE_CAPITAL_ANSWER = frozenset({
    EventType.NET_WORTH_REPORTED,
    EventType.LICENCE_GRANTED,
    EventType.ACTIVITY_UNDERTAKEN,
    EventType.MINIMUM_CONFIRMED,
})


def capital_short(ctx: PolicyContext) -> Iterable[Finding]:
    """The firm is worth less than its licence requires.

    Darwin Platform Aircraft Leasing lost its registration for capital
    never infused. Nothing about this obligation moves, which is exactly
    why it stops being noticed: a licence is granted, a figure is required
    from that day, and the only way anybody finds out it is not there is
    when somebody looks.

    Raised on the facts that change the answer rather than swept for. It
    used to raise on the report alone, justified as "the only moment the
    answer can change with it" -- and that was simply not true. The answer
    is *held against required*, and three ordinary orderings moved the other
    half with nothing on anyone's queue:

    * Net worth recorded before the licence, which is the order a fresh
      workspace fills up in. USD 310,000 reported, then a REGISTERED
      (NON-RETAIL) licence granted: **short by USD 190,000, no file opened.**
    * A third-party activity recorded afterwards -- the very mechanism this
      module chose, "read from what the firm has actually been recorded as
      doing". USD 600,000 against a 500,000 minimum, then portfolio
      management raises it to 1,000,000: **short by USD 400,000, no file.**
    * An officer confirming a higher minimum: same 400,000, same nothing.

    The regulatory page said the firm was short in all three cases. Nothing
    that reaches a queue did. The minimum is in the dedupe key, so a minimum
    that moves raises the question once more rather than every page load.
    """
    if ctx.event.event_type not in _CHANGES_THE_CAPITAL_ANSWER:
        return ()
    from .capital import (NOT_CONFIRMED, THIRD_PARTY_ACTIVITIES, required,
                          shortfall)

    short = shortfall(ctx.licence, ctx.capital)
    if short is None:
        return ()
    minimum, confirmed, why = required(ctx.licence, ctx.capital)
    standing = ctx.capital.latest
    # What the figure was actually built from. This used to cite 3(4)
    # alone -- the clause about which category to register under -- so a
    # firm told it was short of capital was shown everything except the
    # schedule that sets the amount.
    relied_on = ["3(4)", "8(1)", "Second Schedule"]
    if any(activity in THIRD_PARTY_ACTIVITIES
           for activity in getattr(ctx.licence, "activities", {})):
        relied_on.append("107F")
    return (
        Finding(
            policy_id="POL_CAPITAL_SHORT",
            case_type=CASE_CAPITAL,
            severity=Severity.CRITICAL,
            summary=(f"net worth is {short:,.0f} below the minimum "
                     f"of {minimum:,.0f}"),
            dedupe_key=f"capital|{standing.as_at}|{minimum:.0f}",
            detail={
                "amount_usd": standing.amount_usd,
                "minimum_usd": minimum,
                "short_usd": short,
                "as_at": standing.as_at,
                "confirmed": confirmed,
                "why": why,
                "caveat": "" if confirmed else NOT_CONFIRMED,
            },
            citations=cite(*relied_on),
        ),
    )


def reported_what_the_records_cannot_show(ctx: PolicyContext) -> Iterable[Finding]:
    """A figure filed with the regulator that the book holds nothing for.

    Not a difference of degree. Assets under management are properly not
    the sum of commitments -- capital is called in tranches and values
    move -- so a gap between a reported figure and the book is ordinary
    and explaining it is an officer's job rather than this rule's. What is
    not ordinary is a number reported against a book with nothing in it at
    all, which is the nearest thing in this data to Prowess booking
    reinsurance income as risk management fees.
    """
    if ctx.event.event_type is not EventType.FILING_SUBMITTED:
        return ()
    reported = (ctx.event.payload or {}).get("reported") or {}
    if not isinstance(reported, dict) or not reported:
        return ()
    from .disclosure import compare, nothing_behind_it

    bare = nothing_behind_it(compare(ctx.book, reported))
    if not bare:
        return ()
    return (
        Finding(
            policy_id="POL_REPORTED_WITHOUT_RECORDS",
            # Its own kind, not a filing. Sharing the filing writer made a
            # return that *was* submitted render as one that was overdue,
            # which is the opposite of what happened and exactly the sort
            # of sentence that destroys a reader's trust in the rest.
            case_type=CASE_DISCLOSURE,
            severity=Severity.HIGH,
            summary=("a figure was filed that the records hold nothing for: "
                     + ", ".join(row.what for row in bare)),
            dedupe_key=f"reported|{ctx.event.payload.get('period', '')}",
            detail={
                "period": ctx.event.payload.get("period"),
                "obligation": ctx.event.payload.get("obligation"),
                "figures": [
                    {"what": row.what, "reported": row.reported,
                     "records_show": row.records_show}
                    for row in bare
                ],
            },
            citations=cite("120"),
        ),
    )



# ---------------------------------------------------------------------------
# Adverse media
# ---------------------------------------------------------------------------

#: How many pieces of coverage make a file rather than a coincidence.
#:
#: The firm's number, not the regulator's -- IFSCA sets none, and this module
#: says so rather than implying otherwise. One article naming a person is very
#: often a namesake; a run of them from separate publications is the shape
#: worth an officer's twenty minutes. Set low deliberately: the cost of
#: reading three articles is small and the cost of not reading them is the
#: whole reason a firm does this at all.
ENOUGH_COVERAGE = 3

#: Distinct publications, not distinct articles. Twelve syndications of one
#: wire story is one story, and counting it as twelve is how a queue fills
#: with the same fact.
ENOUGH_SOURCES = 2


def adverse_media_found(ctx: PolicyContext) -> Iterable[Finding]:
    """Negative coverage of a party, put in front of a person.

    Cited to clause 4.2 and described as a risk factor, because **there is no
    IFSCA clause requiring an adverse media check** and inventing one would be
    worse than having none. What 4.2 does is list what a firm shall take into
    account when judging whether a customer is high risk, and press coverage
    of fraud or corruption is plainly something a person weighing that would
    want in front of them.

    So this opens a file that says "read these and decide", never one that
    says a party is bad. The articles are the finding; nothing here has read
    them.
    """
    if ctx.event.event_type is not EventType.ADVERSE_MEDIA_CHECKED:
        return ()
    basis = ctx.event.payload.get("basis") or {}
    articles = basis.get("articles") or []
    if len(articles) < ENOUGH_COVERAGE:
        return ()
    sources = {str(a.get("domain") or "") for a in articles if a.get("domain")}
    if len(sources) < ENOUGH_SOURCES:
        return ()

    name = ctx.graph.name_of(ctx.event.subject)
    return (
        Finding(
            policy_id="POL_ADVERSE_MEDIA",
            case_type=CASE_SCREENING_HIT,
            severity=Severity.MEDIUM,
            summary=f"press coverage naming {name} alongside financial crime",
            # One open file per party per day of checking. Re-running the
            # search on the same day extends the same file; running it next
            # month opens a new one, which is right -- new coverage is a new
            # fact about the world.
            dedupe_key=f"adverse|{ctx.event.subject}|{ctx.event.occurred_at}",
            detail={
                "entity": ctx.event.subject,
                "found": len(articles),
                "sources": sorted(sources),
                "window": basis.get("window"),
                "searched_for": basis.get("query"),
                "articles": articles[:10],
            },
            citations=cite("4.2"),
        ),
    )


POLICIES: Sequence[Policy] = (
    screening_hit,
    adverse_media_found,
    capital_short,
    reported_what_the_records_cannot_show,
    one_document_two_parties,
    notice_unanswered,
    notice_answered,
    already_on_the_book,
    ubo_must_be_identified,
    ownership_cycle,
    payment_anomaly,
    activity_within_licence,
    offices_must_be_filled,
    filing_overdue,
    review_overdue,
)


def evaluate(ctx: PolicyContext, policies: Sequence[Policy] = POLICIES) -> list[Finding]:
    findings: list[Finding] = []
    for policy in policies:
        for finding in policy(ctx):
            if not finding.citations:
                raise UncitedFinding(
                    f"{finding.policy_id} produced a finding with no clause "
                    f"citation; every rule must name the obligation it enforces"
                )
            findings.append(finding)
    return findings
