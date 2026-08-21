"""Whose work this is, and what each job should be looking at first.

Four people signed in and saw the same list in the same order. The AML
officer's morning and senior management's morning are not the same morning
-- one is a hundred name checks, the other is four things nobody else may
settle -- and a screen that cannot tell them apart is a screen both of them
scroll past.

**Ordered, never hidden.** Every role sees every file. A compliance system
that shows senior management a shorter list has decided on their behalf
what is beneath them, and the one time that judgement is wrong is the time
it matters. So this changes the order and says why a thing is near the top;
it never removes anything.

**The order is a stated list, not a score.** Each role has an ordered set of
what it puts first, written out below and readable by the person it applies
to. A weighting nobody can inspect is how a queue quietly stops reflecting
what a firm actually cares about, and the officer who notices is the one
who has already stopped trusting it.

**One rule outranks all four lists: work that is waiting for you.** A file
somebody passed up is not merely urgent, it is *blocked* -- it sits until a
particular person settles it, and the four-eyes rule means that person is
never the one who passed it up. Anything waiting on the signed-in reader
goes to the top of their screen whatever it is about, because for everybody
else on the book it is simply not their problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from .model import CaseStatus, Role

#: What each role's screen puts first, most important first. The strings
#: are policy identifiers and case types; anything not named here keeps its
#: ordinary place below, ordered by severity and age as before.
#:
#: Written as a list rather than computed so that the person it applies to
#: can read it and disagree. Disagreement is the point: no two firms divide
#: this work the same way, and a firm that wants its compliance officer
#: looking at payments first should be able to see that it currently does
#: not.
FIRST_FOR: Mapping[Role, tuple] = {
    # The day-to-day desk. This used to read names and money, in that
    # order. Since the counterparty and multi-hop payment rules were removed
    # on 21 August 2026 there is no money left in the middle of it: one
    # payment rule at the top, because a sanctions match stops the money, and
    # then names. The one remaining derived payment rule -- the sender is not
    # the investor -- is deliberately not promoted here, and takes its
    # ordinary place below by severity and age.
    Role.AML_OFFICER: (
        "POL_PAY_SANCTIONED_PAYER",
        "POL_SANCTIONS_HIT",
        "POL_PEP_HIT",
        "POL_PEP_ASSOCIATE",
        "POL_CRIMINAL_HIT",
        "POL_DEBARRED",
        "POL_SAME_PARTY_TWICE",
        "POL_ONE_DOCUMENT_TWO_PARTIES",
        "POL_ADVERSE_MEDIA",
    ),
    # The person who answers for whether the firm is in order, rather than
    # for any one customer. Their morning is what an inspection would open
    # with.
    Role.COMPLIANCE: (
        "POL_NOTICE_UNANSWERED",
        "POL_FILING_REPEATEDLY_LATE",
        "POL_FILING_OVERDUE",
        "POL_GOVERNANCE_POST_VACANT",
        "POL_ACTIVITY_OUTSIDE_LICENCE",
        "POL_REPORTED_WITHOUT_RECORDS",
        "POL_UBO_INCOMPLETE",
        "POL_SAME_PARTY_TWICE",
        "POL_ONE_DOCUMENT_TWO_PARTIES",
    ),
    # Things that reach this desk because nobody else may settle them, and
    # things that are about the firm itself rather than a customer.
    Role.SENIOR_MGMT: (
        "POL_CAPITAL_SHORT",
        "POL_PEP_HIT",
        "POL_PEP_ASSOCIATE",
        "POL_NOTICE_UNANSWERED",
        "POL_ACTIVITY_OUTSIDE_LICENCE",
        "POL_PAY_SANCTIONED_PAYER",
        "POL_SANCTIONS_HIT",
        "POL_REPORTED_WITHOUT_RECORDS",
    ),
    # No actions, so nothing is waiting on them. Ordered like the working
    # desk, because that is the view somebody reading over a shoulder is
    # trying to follow.
    Role.VIEWER: (
        "POL_PAY_SANCTIONED_PAYER",
        "POL_SANCTIONS_HIT",
        "POL_PEP_HIT",
        "POL_SAME_PARTY_TWICE",
    ),
}

#: What each role's screen is for, said on the screen itself so nobody has
#: to guess why their list differs from a colleague's.
WHAT_YOURS_IS_FOR: Mapping[Role, str] = {
    Role.AML_OFFICER: (
        "Ordered for the AML officer's desk: a payment from a sanctioned "
        "party first, because that one stops the money, then the name "
        "checks. Everything else on the book is still below, in the usual "
        "order."
    ),
    Role.COMPLIANCE: (
        "Ordered for the compliance officer: what an inspection opens with "
        "— the regulator, filings, posts and licence scope. Customer files "
        "are still below, in the usual order."
    ),
    Role.SENIOR_MGMT: (
        "Ordered for senior management: the firm's own position, and the "
        "files nobody else may settle. Everything else is still below."
    ),
    Role.VIEWER: (
        "Ordered as the AML officer's desk is, which is the view most "
        "people are trying to follow. You can open anything and settle "
        "nothing."
    ),
}

#: Only these three PEP-shaped kinds may be settled by senior management
#: alone. Kept here rather than re-derived so this file and ``cases.py``
#: cannot come to disagree about who a file is waiting for.
ONLY_SENIOR = frozenset({"PEP", "PEP_ASSOCIATE"})


#: The group work-waiting-on-you goes in. A key rather than a policy, like
#: the aged group, because it is about who is blocked rather than what the
#: rule found.
WAITING = "__waiting_on_you__"

#: The group for a file that has been passed up by everybody who could have
#: settled it. It sits above even work waiting on this reader, because
#: nothing about it can move until somebody is enrolled -- and because until
#: this group existed such a file sat in the ordinary band with no marker on
#: it, open forever, while the period report described it as waiting for a
#: second officer. New files cannot reach this state any more: ``engine``
#: refuses the escalation that would create one. A log written before that
#: guard can still hold one, and the log cannot be rewritten.
STUCK = "__nobody_can_settle__"


def rank_of(group_key: str, role: Optional[Role], aged_key: str = "") -> int:
    """Where a group of files sits on this role's screen.

    Four bands. Work blocked on this reader, then the things this
    particular job exists to look at, then files that have sat for months,
    then everything else in the order the queue already used.

    Aged files sitting above the role's own priorities was the first
    version, and it undid the whole change: eighty-nine old files were the
    top of all four screens, so senior management still had to scroll past
    them to find the capital shortfall only they can act on. Age is a
    reason to look at something. It is not a reason to look at it before
    the one thing on the screen that is yours.

    Group keys carry a suffix where one policy covers two things -- fees
    and returns share a rule -- so the base policy is what is ranked.
    """
    if group_key == STUCK:
        return -1
    if group_key == WAITING:
        return 0
    wanted = FIRST_FOR.get(role, ()) if role is not None else ()
    base = str(group_key).split("|", 1)[0]
    if base in wanted:
        return 1 + wanted.index(base)
    if aged_key and group_key == aged_key:
        return 1 + len(wanted)
    return 2 + len(wanted)


@dataclass(frozen=True)
class Placed:
    """One file, and why it sits where it does."""

    case_id: str
    #: Lower sorts earlier.
    rank: int
    #: Empty unless there is something worth saying about the position.
    because: str = ""
    waiting_on_you: bool = False


def _list_types(case) -> set:
    """Every kind of watchlist this file's evidence names.

    It used to read one value, the one the file is *filed under*, which is
    the most serious thing the match is. A sanctioned head of state is
    filed under sanctions and is also politically exposed, so an escalated
    file about one was routed to whichever officer was free rather than
    reserved for senior management -- the same single-value mistake that
    let the gate in ``cases.is_pep`` be walked past.
    """
    found: set = set()
    for evidence in case.evidence:
        detail = evidence.detail or {}
        kinds = detail.get("list_types") or [detail.get("list_type")]
        found |= {str(kind) for kind in kinds if kind}
    return found


def waiting_on(case, person: str, role: Role) -> bool:
    """Whether this file is blocked on this particular reader.

    Three things have to hold, and leaving any one out makes the top of
    somebody's screen wrong. It has to have been passed up. It cannot have
    been passed up by them -- that is the whole of the four-eyes rule. And
    where it is a public-office file, only senior management may settle it,
    so it is not waiting on anybody else however senior they feel.
    """
    if case.status is not CaseStatus.ESCALATED:
        return False
    if any(step.get("by") == person for step in case.escalations):
        return False
    if role not in (Role.AML_OFFICER, Role.COMPLIANCE, Role.SENIOR_MGMT):
        return False
    if _list_types(case) & ONLY_SENIOR:
        return role is Role.SENIOR_MGMT
    return True


def who_could_settle(case, actors, also_passing_up: str = "") -> list[str]:
    """Everybody enrolled who could settle this file once it is passed up.

    ``also_passing_up`` asks the question one step ahead: if this person
    passes it up too, who would be left? That is the question worth
    asking, because the answer can be nobody.

    Empty on a file already passed up means it is stuck: everybody who
    could have settled it has passed it up, and four eyes locks each of
    them out permanently.

    This was reachable in three clicks. The screen offers "pass it up" to
    every deciding role and goes on offering it on a file that has already
    been passed up, so with three officers enrolled::

        status ESCALATED | open True | passed up by Meera, Aarav, Devika
        Meera   AML officer        waiting on you: no   can settle: no
        Aarav   Compliance officer waiting on you: no   can settle: no
        Devika  Senior management  waiting on you: no   can settle: no

    A file open forever, waiting on nobody, sitting in the ordinary band of
    every screen with no marker on it -- while the period report said of it
    "1 file is waiting for a second officer after being passed up". On a
    politically exposed file it takes one click, because only senior
    management may clear one.
    """
    passed_up = {step.get("by") for step in case.escalations}
    if also_passing_up:
        passed_up.add(also_passing_up)
    only_senior = bool(_list_types(case) & ONLY_SENIOR)

    able = []
    for name, entry in (actors or {}).items():
        role = entry.get("role")
        if name in passed_up:
            continue
        if role not in (Role.AML_OFFICER, Role.COMPLIANCE, Role.SENIOR_MGMT):
            continue
        if only_senior and role is not Role.SENIOR_MGMT:
            continue
        able.append(name)
    return sorted(able)


def stuck(case, actors) -> bool:
    """A passed-up file nobody left can settle."""
    return (case.status is CaseStatus.ESCALATED
            and not who_could_settle(case, actors))


def place(case, person: str, role: Role) -> Placed:
    """Where this file sits on this reader's screen, and why."""
    if waiting_on(case, person, role):
        who = next((step.get("by") for step in case.escalations
                    if step.get("by") != person), "")
        return Placed(
            case_id=case.case_id, rank=0, waiting_on_you=True,
            because=(f"{who} passed this up and cannot settle it themselves."
                     if who else "This was passed up and is waiting for you."))

    wanted = FIRST_FOR.get(role, ())
    policy = ""
    for evidence in case.evidence:
        if evidence.policy_id:
            policy = evidence.policy_id
            break
    if policy in wanted:
        return Placed(case_id=case.case_id, rank=1 + wanted.index(policy))
    # Everything not named for this role keeps its ordinary place, below
    # what is. Nothing is removed.
    return Placed(case_id=case.case_id, rank=1 + len(wanted))


def sort_key(case, person: str, role: Role):
    """A key that puts this reader's work first and keeps the rest as it was.

    The second half of the key is the ordinary queue order -- severity then
    age -- so within a band the list a firm already knows is unchanged.
    """
    return (place(case, person, role).rank, case.queue_key)


def order(cases: Sequence, person: str, role: Role) -> list:
    return sorted(cases, key=lambda case: sort_key(case, person, role))
