"""Every sentence this system says to a person.

Read this file if you want to know what the product tells a Principal Officer.
Nothing user-facing is written anywhere else -- not in the web app, not in the
audit export, not in an email template. One place, so a compliance
professional can review the whole of it without reading code, and so the
screen and the file handed to a regulator cannot say different things.

**The reader.** A Principal Officer or Compliance Officer at a GIFT City FME.
A finance or legal professional -- CA, CS, lawyer, ex-banker. Personally named
on the FME's registration and personally accountable to IFSCA. They are not
optimising for speed. They are optimising for being able to show, later, that
they did the right thing for a defensible reason.

**The line between their language and ours.** Their vocabulary stays: beneficial
owner, PEP, sanctions, enhanced due diligence, source of funds, clause 1.3.3(a).
That is not jargon to them, it is their profession, and a clause reference is
their strongest defence. Ours goes, all of it: case ids, policy ids, entity ids,
enum values, sequence numbers, hashes, JSON, the word "event". If it exists
because of how the software is built, it does not reach the reader.
``tests/test_briefing.py`` fails the build if any of it leaks.

**Every item answers the six questions they actually have:** what is this about,
what is wrong, why does it matter, what do I have to do, what happens when I
decide, and how is this recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Optional, Sequence

from .calendar import BY_OBLIGATION, Obligation, Status, instances
from .citations import CLAUSES, SOURCES, SOURCE_CHECKED_ON
from .countries import name_of as country_name
from .model import Case, CaseStatus, Outcome, Severity

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: Severity is an internal grading. A person needs to know when to do it.
URGENCY = {
    Severity.CRITICAL: "Stop — do not let this proceed until it is cleared",
    Severity.HIGH: "Needs you today",
    Severity.MEDIUM: "Needs you this week",
    Severity.LOW: "When you have time",
}

TONE = {
    Severity.CRITICAL: "stop",
    Severity.HIGH: "today",
    Severity.MEDIUM: "week",
    Severity.LOW: "later",
}

#: Roles, as a person would say them. Written down once because a role is
#: not decoration on a decision: clause 5.5(b)(iii) reserves the clearing of a
#: politically exposed person for senior management, and a decision table that
#: shows only a name cannot show that the rule was kept. The reader must never
#: meet ``SENIOR_MGMT``.
ROLE_WORDS = {
    "COMPLIANCE": "Compliance officer",
    "AML_OFFICER": "AML officer",
    "SENIOR_MGMT": "Senior management",
    "PRINCIPAL_OFFICER": "Principal Officer",
    "VIEWER": "Read-only",
    "AI": "The assistant",
}


def role_word(role) -> str:
    """A role in words. An unknown one is shown as it came, tidied, rather
    than dropped -- a role nobody has a word for is still evidence."""
    raw = str(getattr(role, "value", role) or "").strip()
    if not raw:
        return ""
    return ROLE_WORDS.get(raw.upper(), raw.replace("_", " ").capitalize())


#: Case types, as a file would be labelled on a desk.
KIND = {
    "SCREENING_HIT": "Name check",
    "UBO_REVIEW": "Ownership review",
    "PAYMENT_MISMATCH": "Payment query",
    "LICENCE_SCOPE": "Licence check",
    "GOVERNANCE": "Key personnel",
    "FILING": "Filing due",
    "SAME_PARTY": "Duplicate record",
    "NOTICE": "Regulator's letter",
    "DOCUMENT": "Document check",
    "CAPITAL": "Capital",
    "DISCLOSURE": "What was reported",
}

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


def _d(iso: str):
    from datetime import date

    year, month, day = (int(p) for p in iso.split("-")[:3])
    return date(year, month, day)


def _date(iso: str) -> str:
    """2025-05-01 -> 1 May 2025."""
    try:
        year, month, day = (int(p) for p in iso.split("-")[:3])
        return f"{day} {MONTHS[month - 1]} {year}"
    except (ValueError, IndexError):
        return iso


def _money(amount: Optional[float], currency: Optional[str]) -> str:
    """An amount exactly as it stands on the record.

    Rounding to whole units misstates the figure an officer will be quoted,
    and it could print an overpayment as two identical numbers -- "we called
    USD 2,000,000 and received USD 2,000,000" -- which reads as no discrepancy
    at all. Whole amounts still print whole; only the fraction survives.
    """
    if amount is None:
        return "an unstated amount"
    shown = f"{amount:,.2f}".rstrip("0").rstrip(".") if amount % 1 else f"{amount:,.0f}"
    return f"{currency or ''} {shown}".strip()


def _pct(value: float) -> str:
    return f"{value:.10g}%"


def _plural(count: int, singular: str, plural: Optional[str] = None) -> str:
    return singular if count == 1 else (plural or singular + "s")


def _join(names: Sequence[str]) -> str:
    names = list(names)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


# ---------------------------------------------------------------------------
# What a person sees
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """The obligation behind an item, in their language and the regulator's."""

    clause: str
    document: str
    says: str
    quote: str
    #: Where the destination goes. A machine address, never shown as text --
    #: the reader sees ``link_text``.
    link: str
    link_text: str
    checked_by_a_person: bool
    caution: Optional[str] = None


@dataclass(frozen=True)
class Choice:
    label: str
    means: str
    outcome: Outcome


@dataclass(frozen=True)
class Line:
    """One detail, both sides, and what can be said about the difference.

    Computed by software that does arithmetic, not by anything that writes
    prose. This is the part of a name check an officer can rely on, so it is
    shown whether or not a suggestion was prepared.
    """

    what: str
    ours: str
    theirs: str
    says: str
    #: Machine hint for colour: same, close, differs, unknown. Never shown.
    tone: str


@dataclass(frozen=True)
class Suggestion:
    """A prepared starting point. Deliberately framed as help, not an answer.

    The order of the fields is the order they are read, and it is not the
    order a model would choose. The caveat comes before the conclusion, and
    the officer's own two choices — take these words, or write their own —
    sit at the end, equally weighted. An officer who agrees with everything
    the assistant says has stopped being a control.
    """

    heading: str
    caveat: str
    verdict: str
    reasoning: str
    wording_label: str
    wording: str
    checks_label: str
    checks: tuple[str, ...]
    use_label: str
    own_label: str
    recorded_as: str


@dataclass(frozen=True)
class Item:
    reference: str
    #: The single line shown when this sits inside a group of like items.
    line: str
    kind: str
    urgency: str
    who: str
    about: str
    headline: str
    because: tuple[str, ...]
    to_close_this: tuple[str, ...]
    rules: tuple[Rule, ...]
    choices: tuple[Choice, ...]
    recorded_as: str
    #: The factual comparison, when there is one. Always trustworthy.
    side_by_side: tuple[Line, ...] = ()
    #: Column headings for it, so the screen holds no wording of its own.
    ours_label: str = ""
    theirs_label: str = ""
    #: The strongest single agreement in the comparison, where there is
    #: one. Set apart from the ruled lines because it is worth more than
    #: any of them, and toned the same as the rest it read as one more row.
    corroboration: str = ""
    #: The reasons an officer may pick from when settling this file. Empty
    #: for files whose closure has no standard checklist.
    reasons: tuple = ()
    #: How long this file has been waiting, where that has become the
    #: point. Empty for anything opened in the last few days, because a
    #: number on every row would make the number mean nothing.
    waiting: str = ""
    #: The prepared draft, when one exists. Often there is none, and the item
    #: reads exactly as it did before this feature existed.
    suggestion: Optional[Suggestion] = None
    #: Kept so a screen can post a decision. Never displayed.
    case_id: str = ""


@dataclass(frozen=True)
class Due:
    """Something owed to IFSCA that is not late yet."""

    what: str
    when: str
    pressing: bool


@dataclass(frozen=True)
class Group:
    """Work that shares an obligation, and therefore shares an explanation.

    A flat list of 180 items is a spreadsheet with extra steps. Items that
    raise the *same* question -- four payments held for the same reason under
    the same clause -- are one piece of work with four instances, and are read
    that way: explain once, list the four, decide each.
    """

    title: str
    urgency: str
    #: Machine hint for how urgently this should read on screen. Drives colour,
    #: never shown as text -- ``urgency`` is the sentence a person reads.
    tone: str
    because: tuple[str, ...]
    to_close_this: tuple[str, ...]
    rules: tuple[Rule, ...]
    items: tuple[Item, ...]
    #: True number in this group, which may exceed the items shown.
    total: int
    #: An accurate statement of how much of the group is on screen. Empty when
    #: all of it is.
    more: str = ""
    #: The label on the control that fetches the rest. Empty when there is no
    #: rest to fetch.
    show_all: str = ""
    #: Which bucket this is, so a screen can ask for the whole of *this* group
    #: rather than the whole queue. A machine address, never displayed --
    #: skipped by the jargon sweep for the same reason ``Item.case_id`` is.
    ref: str = ""


@dataclass(frozen=True)
class Stat:
    """One number on the dashboard, with the words that make it a fact."""

    label: str
    value: str
    #: Machine hint for colour. Never shown as text.
    tone: str = "plain"


@dataclass(frozen=True)
class Workload:
    """How many open files ask one kind of question."""

    label: str
    count: int
    #: This row's count against the largest row, 0..1. Drives a bar width on
    #: screen; never shown as text.
    share: float


#: How open files are banded by age, and what each band is called. The
#: bands are not arbitrary: a file opened today is work in hand, a file
#: over a month old is the one an inspector asks about by name, and three
#: months is where a firm stops being able to call it a backlog.
AGE_BANDS = (
    (0, 1, "Opened today"),
    (1, 8, "Within the last week"),
    (8, 31, "One week to one month"),
    (31, 91, "One to three months"),
    (91, None, "More than three months"),
)


def days_between(earlier: str, later: str) -> Optional[int]:
    """Whole days from one ISO date to another, or nothing where either is
    not a date. Dates come off the log already checked, but a screen that
    raised on one bad character would be a screen nobody could open."""
    from datetime import date as _day

    try:
        return (_day.fromisoformat(str(later)[:10])
                - _day.fromisoformat(str(earlier)[:10])).days
    except (TypeError, ValueError):
        return None


def band_by_age(cases, today: str) -> "list[tuple[str, int, int]]":
    """(label, count, days of the oldest in the band) for each age band."""
    counted = {label: [0, 0] for _, _, label in AGE_BANDS}
    for case in cases:
        age = days_between(str(case.opened_at)[:10], today)
        if age is None or age < 0:
            age = 0
        for low, high, label in AGE_BANDS:
            if age >= low and (high is None or age < high):
                counted[label][0] += 1
                counted[label][1] = max(counted[label][1], age)
                break
    return [(label, counted[label][0], counted[label][1])
            for _, _, label in AGE_BANDS]


@dataclass(frozen=True)
class Ageing:
    """One age band on the dashboard: how many files, and how old."""

    label: str
    count: int
    share: float
    #: Set where a band is one nobody should be looking at with anything
    #: in it. Never shown as text.
    tone: str = "plain"


@dataclass(frozen=True)
class Waiting:
    """One letter from a regulator that has not been answered."""

    reference: str
    who: str
    about: str
    clock: str
    #: Never shown as text.
    tone: str = "plain"


@dataclass(frozen=True)
class Dashboard:
    """The morning at a glance, before a single file is opened.

    Every label here is a sentence fragment a person reads, so it lives in
    this module with everything else user-facing, and the jargon sweep walks
    it like any other text.
    """

    stats: tuple[Stat, ...]
    workload_heading: str
    workload: tuple[Workload, ...]
    deadlines_heading: str
    #: How long the open files have been waiting. A count of open files
    #: cannot answer the first question an inspector asks, which is how
    #: long the oldest one has been sitting there.
    ageing_heading: str = ""
    ageing: tuple[Ageing, ...] = ()
    ageing_note: str = ""
    #: Letters from the regulator still waiting for an answer. On the
    #: dashboard rather than in the queue on purpose: a letter due in three
    #: days is not a decision anybody has to make, it is work somebody has
    #: to do, and a file that opens before any breach would have to be
    #: settled even when the answer went out on time. A file opens only
    #: once the date has passed, which is the point it becomes a breach.
    waiting_heading: str = ""
    waiting: tuple[Waiting, ...] = ()
    waiting_note: str = ""


@dataclass(frozen=True)
class Briefing:
    greeting: str
    headlines: tuple[str, ...]
    nothing_needed: str
    coming_up: tuple[Due, ...]
    groups: tuple[Group, ...]
    assurance: str
    dashboard: Optional[Dashboard] = None
    #: Why this reader's order differs from a colleague's. Said on the
    #: screen so nobody has to guess, and so a firm that disagrees with
    #: the order can see what it currently is.
    ordered_for: str = ""

    @property
    def items(self) -> tuple[Item, ...]:
        return tuple(i for g in self.groups for i in g.items)


CHOICES = (
    Choice(
        "Clear it",
        "You are satisfied this is in order. The file closes and the investor "
        "can proceed. Your reason is kept with it.",
        Outcome.APPROVE,
    ),
    Choice(
        "Refer upwards",
        "You want senior management or the Principal Officer to look at this "
        "before anything happens. The file stays open to them, with your note.",
        Outcome.ESCALATE,
    ),
    Choice(
        "Do not proceed",
        "This should not go ahead. The file closes as refused and your reason "
        "is kept with it.",
        Outcome.REJECT,
    ),
)

RECORDED = (
    "Your name, your decision and your reason are written into the permanent "
    "record. It cannot be edited or deleted afterwards, by anyone, including us."
)

#: What a person is told when they cannot act, or when an action fails. A
#: stack trace is not an error message; neither is "400 Bad Request".
MESSAGES = {
    #: This used to end "Set VINZOR_SCREENING_URL to your watchlist index",
    #: which is an instruction to whoever installed the software printed on
    #: the screen of somebody who cannot act on it -- and it is what every
    #: user saw the first time they pressed "Check the watchlists now". The
    #: remedy an officer can actually carry out is to ask. The variable name
    #: still appears, in the console, to the person starting the server.
    "no_screening_service": (
        "No watchlist is connected to this workspace, so the check was not "
        "run and this party's name did not leave the machine. Ask whoever "
        "set up this system to connect one, then try again."
    ),
    "run_stopped": (
        "This run stopped before it finished, so the steps after the last "
        "one recorded were never carried out. Start it again when you need "
        "it."
    ),
    "filing_recorded": (
        "Recorded as filed. Any figures on it now sit beside what the records "
        "hold, on \"Where you stand with IFSCA\"."
    ),
    "period_unreadable": (
        "That period could not be read, so no report was made rather than a "
        "report covering the wrong dates. Choose one of the periods offered, "
        "or write the date as 2026-08-01."
    ),
    "upload_expired": (
        "That upload is no longer held here. Choose the file again."
    ),
    "viewer_import": (
        "You are signed in with read-only access. Importing writes to the "
        "permanent record, so it has to be done by a compliance officer, "
        "the AML officer, or senior management."
    ),
    "viewer_check": (
        "You are signed in with read-only access. Running a check writes to "
        "the permanent record, so it has to be done by a compliance officer, "
        "the AML officer, or senior management."
    ),
    "viewer": (
        "You are signed in with read-only access. You can open these files and "
        "read everything in them, but settling one has to be done by a "
        "compliance officer, the AML officer, or senior management."
    ),
    "risk_recorded": (
        "Recorded. The categorisation, the factors and your reason are now "
        "part of the permanent file."
    ),
    "risk_needs_reason": (
        "A categorisation needs a reason that says what you weighed. It is "
        "what an inspector reads to understand the judgement."
    ),
    "risk_bad_category": (
        "A customer is high, medium or low risk. Clause 5.11 sets a "
        "different review interval for each, and there is no fourth."
    ),
    "senior_only": (
        "Clearing a politically exposed person is senior management's to "
        "give — clause 5.5(b)(iii). You can stop this one, or pass it "
        "up to somebody who can approve it."
    ),
    "four_eyes": (
        "You passed this file up, so a different officer has to settle it "
        "— that is what escalating means."
    ),
    "reason_too_thin": (
        "That reason says nothing an inspector could read. Write what you "
        "compared or concluded — one word is a click, not a reason."
    ),
    "needs_reason": (
        "Write a short reason first. It goes into the permanent record and is "
        "what shows an auditor why you decided as you did."
    ),
    "already_settled": (
        "This file has already been settled. Files are decided once, so that "
        "the record cannot be quietly rewritten later."
    ),
    "needs_question": "Type a question first.",
    "question_too_long": (
        "That is longer than this can take in one go. Ask the shorter version "
        "and follow up."
    ),
    "confirmed": (
        "Recorded. Your name, your qualification and what you checked are now "
        "part of the permanent record, against this exact wording."
    ),
    "needs_confirmation_detail": (
        "A confirmation has to say who you are qualified as, and what you "
        "checked. Both go on the record and are what make it worth anything."
    ),
    "no_party": (
        "Nobody on record matches “{query}”. Try part of the name, "
        "or check the spelling against the file you are working from."
    ),
    "not_found": (
        "That file could not be found. It may have been settled by a colleague "
        "since this page was loaded — reload to see the current list."
    ),
    "not_allowed": (
        "Your access does not permit settling files. Ask the AML officer or "
        "senior management to review this one."
    ),
    "sign_in_first": (
        "You are not signed in, or your session has ended. Nothing was "
        "recorded. Sign in again and repeat what you were doing."
    ),
    "unavailable": (
        "The system could not complete that just now and nothing was recorded. "
        "Reload the page and try again; if it keeps happening, tell your "
        "administrator before relying on this list."
    ),
    "settled": "Recorded. Your name and reason are now part of the permanent file.",
    "all_clear": (
        "Nothing needs you right now. Every open file has been dealt with."
    ),
}

#: Interface furniture: headings, button labels, the sentence above the reason
#: box. Not prose about a Case, but words a person reads all the same, so they
#: belong here with everything else they read rather than in the browser.
#:
#: These lived in ``app.js`` as string literals, which broke decision 6 twice
#: over: the jargon sweep never walked them, and a second surface would have
#: had to either duplicate them or drift. Every screen now asks the server
#: what to call things.
UI = {
    "wordmark": "Vinzor",
    "switch_user": "switch",
    "loading": "Opening your files…",
    "load_failed": (
        "The list could not be loaded. Reload the page to try again."
    ),
    "no_password": (
        "This is a demonstration running on this machine. Choose who you are — "
        "there is no password, and your identity is not checked. Nothing here "
        "should be treated as a live compliance record."
    ),
    "record_heading": "The record",
    "to_close_heading": "What you need to do",
    "rule_heading": "The rule behind this",
    "rules_heading": "The rules behind this",
    "clause_prefix": "Clause",
    "why": "Why? This goes into the permanent record.",
    "reason_pick": "The reason that fits best",
    "confirm_prefix": "Record:",
    "confirm_plain": "Record it",
    "cancel": "Cancel",
    "record_failed": (
        "That could not be recorded and nothing was saved. Try again."
    ),
    "open_file": "Open this file",
    "back_to_queue": "Back to your list",
    "evidence_heading": "Everything on this file, in order",
    "open_regulatory": "Where you stand with IFSCA",
    "find_party": "Look up a party",
    #: The regulatory page. Every sentence on it is already a field of
    #: Regulatory; these are the two pieces of furniture around them.
    "nav_standing": "IFSCA",
    "standing_clauses_show": "Show all the rules",
    "standing_clauses_hide": "Hide the rules",
    "ask_open": "Ask about this",
    "ask_about": "About:",
    "ask_here_queue": "your list of open files",
    "ask_here_regulator": "where you stand with IFSCA",
    "ask_here_screening": "watchlist screening",
    "ask_heading": "Ask about your records",
    "ask_lead": (
        "Ask anything about this workspace and it will read the records to "
        "answer. It can look at everything and change nothing — when the "
        "answer is that a file needs settling, that stays yours."
    ),
    "ask_placeholder": "Ask about this, or anything else…",
    "ask_go": "Ask",
    "ask_thinking": "Reading your records…",
    "ask_looked_at": "It read:",
    # The report's own assistant. The eight checks decide what is true;
    # this reads what they decided. The lead says so plainly, because an
    # officer who thinks the sentence below it *is* the check has been
    # misled about which part of this product is deterministic.
    "report_ask_lead": (
        "The eight checks above decide what is true. This reads them back "
        "and tells you what they mean together — it can look at "
        "everything on this party and change nothing, and it settles no file."
    ),
    "report_ask_try_one": "What matters most here, and what should I do next?",
    "report_ask_try_two": "What is stopping this file from being settled?",
    "ask_failed": (
        "The assistant could not be reached. Every finding above was read "
        "from the record and is unaffected."
    ),
    # What a document turned out to say. The field names are the record's
    # own and are not words an officer uses, so each is given one here.
    # The state an officer read as "my upload did nothing". It is not that:
    # a document is held, and nobody has yet said what it proves. Clause
    # 5.4.5 asks a firm to verify identity from a document, not merely to
    # possess one, and the difference was being carried by a dot colour.
    "onboard_held_unevidenced": (
        "You have filed a document for this. It is on the record as held — "
        "nobody has yet confirmed what it proves, which is what the rule "
        "asks for separately."
    ),
    "onboard_held_badge": "Filed",
    "onboard_why_asked": "Why is this asked for?",
    "report_download_kind": (
        "PDF — the format to attach to an email"
    ),
    # Who the watchlist returned. Screening gives back candidates and the
    # officer eliminates them; a caption and a score is not enough to do
    # that with, and the identifying detail was recorded all along.
    "candidates_heading": "Who the watchlist returned",
    "candidates_one": (
        "One entry on a watchlist came back for this name. It may not be "
        "your investor. Compare what the entry says about itself against "
        "what you hold."
    ),
    "candidates_many": (
        "{n} entries on the watchlists came back for this name. Most of them "
        "will not be your investor — a name match is a question, not an "
        "answer. Compare what each entry says about itself against what you "
        "hold."
    ),
    "candidates_caveat": (
        "A difference here is not a clearance. People change nationality, "
        "records carry the wrong year, and somebody under sanction is not "
        "obliged to have given anybody an accurate date of birth. This is "
        "what you need to make the judgement; it does not make it."
    ),
    "candidates_theirs": "The listed entry",
    "candidates_ours": "Your investor",
    "candidates_silent": "not stated",
    "candidates_score": "match",
    "candidates_also_known": "Also known as:",
    "candidates_unnamed": "An unnamed entry",
    "candidates_differs": (
        "At least one identifying detail differs. That is the usual reason "
        "an alert like this is closed — record which detail, and why it "
        "satisfied you."
    ),
    # Naming a document. This was not asked at all: every upload went up
    # with no kind on it, arrived as "other", and "other" may evidence
    # nothing -- so the reader answered every document filed through the
    # screen with "this system does not know what a document of that kind
    # is allowed to evidence". It read as a broken product and it was a
    # missing question.
    "onboard_name_the_kind": (
        "Say what each of these is before it is filed. What a document is "
        "decides what it is allowed to prove — a utility bill may evidence "
        "an address and may not evidence a nationality, however clearly it "
        "prints one — so this is your assertion about the paper, not ours."
    ),
    "onboard_kind_label": "What kind of document is this?",
    "onboard_kind_choose": "Choose…",
    "onboard_kind_evidences": "Can evidence:",
    "onboard_file_them": "File these",
    "onboard_forget_them": "Not these",
    # What an officer can answer before any document arrives. An investor
    # sitting opposite knows their own date of birth; there was nowhere to
    # put it, so the checks ran against a name and a party kind.
    "onboard_known_heading": "What do you already know about them?",
    "onboard_known_lead": (
        "All of this is optional. Anything you leave blank is reported as "
        "still needed, which is the true statement about it — and "
        "anything you fill in is what a document will later be checked "
        "against."
    ),
    "onboard_known_more": "Anything else you know",
    "onboard_known_country": "Two letters, e.g. IN",
    # The clause is the authority and it is not the explanation. An officer
    # who has never read Annexure II Part B(a) cannot act on being shown its
    # number, and an inspector cannot act on a paraphrase -- so both are on
    # the screen, the citation first and the plain sentence behind it.
    "onboard_explain": "Put this in plain words",
    "onboard_explain_asks": (
        "In two or three sentences, and without citing clause numbers: what "
        "is {what}, why is this party being asked for it, and what is the "
        "risk of taking them on without it? Write for a compliance officer "
        "who has not read the rulebook."
    ),
    # Said above the list of what this system does not check. It was a bare
    # list of seven caveats, which reads as a disclaimer rather than as the
    # useful thing it is.
    "onboard_not_modelled_lead": (
        "These are things the rules ask for that this system does not look "
        "at, listed rather than left to be discovered. Each needs a person, "
        "or a record the product does not hold. Nothing below has been "
        "checked either way."
    ),
    # The wait, made visible. Everything an officer waits for during a run
    # happens at these two boundaries; the eight checks themselves are pure
    # functions over the log and land in milliseconds.
    "gather_watchlist": "The watchlist",
    "gather_press": "The press",
    "gather_looking": "asking…",
    "gather_done": "answered",
    "gather_failed": "did not answer",
    "read_field_name": "Name",
    "read_field_dob": "Date of birth",
    "read_field_nationality": "Nationality",
    "read_field_id_document_number": "Document number",
    "read_field_address": "Address",
    "read_field_expires": "Expires",
    "read_field_pan": "Permanent account number",
    "read_field_cin": "Corporate identity number",
    "read_field_date_of_incorporation": "Date of incorporation",
    "read_field_country_of_incorporation": "Country of incorporation",
    "read_agrees": "agrees with the record",
    "read_differs": "the record says",
    "ask_examples_heading": "Try",
    "ask_examples": [
        "What needs my attention most urgently today?",
        "Is anyone who committed money still unscreened?",
        "What do we owe IFSCA, and how late are we?",
        "What does the rule say about beneficial owners of a trust?",
    ],
    "open_screening": "Watchlist screening",
    "open_reports": "What you can show",
    "open_agents": "Agents",
    "agents_heading": "Give the agents a job",
    "agents_lead": (
        "Every step below is a real call to a real tool — the same "
        "screening the queue uses, the same resolver, the same ownership "
        "walk. Nothing here is a progress bar over a wait. What you watch "
        "is the permanent record being written."
    ),
    "agents_running": "Working now",
    "agents_recent": "Already done",
    "agents_none": "Nothing has been delegated yet.",
    "agents_start": "Start",
    "agents_watching": "Working…",
    "agents_placeholder": (
        "Ask for something — “check whether anyone on the book "
        "is on a sanctions list and whether we hold papers for them”"
    ),
    "agents_send": "Ask",
    "open_chat": "Assistant",
    "chat_heading": "Ask, or set the agents working",
    "chat_lead": (
        "Type a sentence. A question about what is already on the record "
        "is read and answered; a job is planned and run in front of you. "
        "You do not have to know which it will be."
    ),
    "chat_placeholder": "Ask anything, or ask for something to be done…",
    "chat_send": "Send",
    "chat_thinking": "Reading…",
    "chat_read": "Read from",
    "chat_again": "You asked recently",
    "chat_activity": "What the agents are doing",
    "chat_quiet": "Nothing is running.",
    "export_book": "Export to Excel",
    "export_party": "Export this record to Excel",
    "export_note": (
        "Four tabs: every party with what has since been found out about "
        "them, every open file, every decision in the decider's own words, "
        "and every payment. Figures are as the record held them when the "
        "file was written."
    ),
    "risk_set": "Set how risky this customer is",
    "risk_high": "High risk",
    "risk_medium": "Medium risk",
    "risk_low": "Low risk",
    "risk_why": "Why this category? This goes into the permanent record.",
    "risk_record": "Record this categorisation",
    "risk_open_heading": "Factors only a person can answer",
    "risk_yes": "Yes",
    "risk_no": "No",
    "risk_unknown": "Not established",
    "risk_note": "What you saw (optional)",
    "report_period_heading": "The period this covers",
    "report_this_month": "This month",
    "report_last_month": "Last month",
    "report_this_quarter": "This quarter",
    "report_this_year": "This year",
    "report_everything": "Everything on the record",
    "import_button": "Import a spreadsheet",
    "import_heading": "Import a spreadsheet",
    "import_lead": (
        "Bring in a spreadsheet of parties -- customers, investors, account "
        "holders -- or of payments, straight from a statement export. CSV "
        "and Excel both work. The file is read first and you see exactly "
        "what it says; nothing is written until you confirm."
    ),
    "import_choose": "Choose a file",
    "import_reading": "Reading the file…",
    "import_templates": "Start from a template if the export is awkward:",
    "import_template_parties": "Parties template",
    "import_template_payments": "Payments template",
    "import_notes_heading": "Reading this file",
    "import_columns_heading": "Columns being used",
    "import_ignored_heading": (
        "Columns left alone, because nothing here recognises them"
    ),
    "import_rejected_heading": "Rows that would be left out",
    "import_refused_heading": "This sheet was refused",
    "import_refused_lead": (
        "Nothing was written. Fix what is named below and choose the file "
        "again."
    ),
    "import_working": "Writing the records…",
    "import_another": "Import another file",
    "import_as_parties": "It is a list of parties",
    "import_as_payments": "It is a list of payments",
    "import_row": "Row",
    "import_drop": "…or drop it here",
    "import_failed": (
        "That file could not be read. Choose it again, or try a different "
        "export of it."
    ),
    "import_lost_progress": (
        "The screening run can no longer be followed from this page. It "
        "keeps running, and any match will appear in your list."
    ),
    "find_heading": "Look up a party",
    "find_placeholder": "Part of a name",
    "find_go": "Search",
    "read_clause": "Read this clause in the published guidelines",
    "confirm_clause": "I have checked this wording",
    "check_party": "Check the watchlists now",
    "sign_in_heading": "Sign in",
    "sign_in_name": "Your name",
    "sign_in_password": "Password",
    "sign_in_button": "Sign in",
    "sign_in_working": "Checking…",
    "sign_out": "Sign out",
    "signed_out": "You are signed out. Nothing on this screen is live any more.",
    "no_password_yet": (
        "No password has been set for this workspace, so anyone who can "
        "reach this page can act as anyone. That is a demonstration, not a "
        "compliance record. Set one before any real customer data goes in: "
        "python -m vinzor password --name \"Their Name\" --workspace live.db"
    ),
    # The one artefact that leaves the building. Named for what a reader
    # would ask for -- nobody asks for an export.
    "open_record": "The full record",
    "record_confidential": "Who may read this",
    "check_wait": (
        "Asking the lists… if a suggestion is prepared it can take "
        "half a minute."
    ),
    "check_steps_heading": "What happened, in order",
    "confirm_lead": (
        "Read the wording above against the published document at the page "
        "shown, then put your name to it. This is recorded against this exact "
        "wording: if the text is ever corrected, your confirmation stops "
        "applying rather than carrying over."
    ),
    "confirm_who": "What qualifies you to confirm this",
    "confirm_who_hint": "Company Secretary, ICSI membership 12345",
    "confirm_note": "What you checked",
    "confirm_note_hint": "Read against page 34 of the master; wording matches.",
    "confirm_go": "Record my confirmation",
    "confirm_needs_both": (
        "Both are needed. They are what makes the confirmation worth anything "
        "to whoever reads it later."
    ),
    "decided_heading": "How this was settled",
}

ASSURANCE = (
    "Every document, check and decision on these files is recorded permanently "
    "and in order. If IFSCA or your auditor asks what happened and why, the "
    "answer can be produced in full."
)


# ---------------------------------------------------------------------------
# The words for each finding
# ---------------------------------------------------------------------------


def _screening(case: Case, detail: Mapping[str, Any], who: str, policy: str, describe):
    if policy == "POL_SANCTIONS_HIT":
        return (
            f"{who} may be on a sanctions list",
            (
                f"A name check against United Nations and other sanctions lists "
                f"returned a possible match for {who}.",
                "A possible match is not proof. Lists hold names, not people, and "
                "common names collide. Establishing whether this is the same party "
                "is the work.",
            ),
            (
                f"Compare the date of birth, nationality and identity document "
                f"number on the listed party against the documents {who} gave us.",
                "If it is the same party: do not accept money or proceed, and "
                "follow the asset-freezing procedure.",
                "If it is not: write down exactly which details you compared and "
                "why you are satisfied, then clear it.",
            ),
        )
    if policy == "POL_PEP_HIT":
        return (
            f"{who} may hold or be close to senior public office",
            (
                f"{who} appears on a list of politically exposed persons.",
                "This is not an allegation of wrongdoing. It means there is a "
                "higher risk that funds could come from bribery or misuse of "
                "public money, so the file needs deeper checks than usual.",
            ),
            (
                "Establish how this person built their wealth, and separately "
                "where the money for this particular investment came from. Get "
                "documents, not assertions.",
                "Obtain senior management approval before accepting the "
                "investment, and record who gave it.",
                "Set this relationship to be reviewed more often than a "
                "standard one.",
            ),
        )
    if policy == "POL_PEP_ASSOCIATE":
        return (
            f"{who} may be a relative or close associate of somebody in "
            f"public office",
            (
                f"{who} appears on a list as a family member or close "
                f"associate of a politically exposed person.",
                "This is not an allegation of wrongdoing. The guidelines say "
                "relationships with relatives and close associates carry "
                "similar risks to the office-holder themselves, so the same "
                "measures apply here as would apply to them.",
            ),
            (
                "Establish who the office-holder is and how this party is "
                "connected to them.",
                "Establish how this party built their wealth, and separately "
                "where the money for this investment came from.",
                "Obtain senior management approval before accepting, and "
                "record who gave it.",
            ),
        )
    if policy == "POL_CRIMINAL_HIT":
        return (
            f"{who} may be wanted, or named in a criminal matter",
            (
                f"{who} matched an entry on a wanted list or a register of "
                f"criminal proceedings.",
                "A match is not proof, and these lists carry people at every "
                "stage from accusation to conviction. Establishing whether "
                "this is the same party, and what the entry actually says, "
                "is the work.",
            ),
            (
                "Read the entry itself and establish what it alleges and "
                "who issued it.",
                "Compare the identifying details against the documents this "
                "party gave you, and write down which matched.",
                "If it is the same party, do not proceed without senior "
                "management deciding, and consider whether a report is owed.",
            ),
        )
    if policy == "POL_DEBARRED":
        return (
            f"{who} may be barred from public contracts or regulated work",
            (
                f"{who} matched a debarment or exclusion register.",
                "Debarment is a decision by an authority that a party may "
                "not be awarded certain work. It is not itself a money "
                "laundering finding, but it is a fact about their standing "
                "that belongs on the file.",
            ),
            (
                "Read the entry and establish which authority barred them, "
                "for what, and for how long.",
                "Establish whether it is the same party, and record which "
                "details you compared.",
            ),
        )
    if policy == "POL_WATCHLIST_HIT_UNCLASSIFIED":
        # Written to say exactly what is known and no more. The provider
        # returned a match on a list this system has no specific rule for --
        # a debarment register, a wanted list, a close associate of a PEP --
        # and naming it as something it might not be would be a guess on a
        # regulatory file. The officer is told what happened, told plainly
        # that the kind is unestablished, and pointed at the entry itself.
        return (
            f"{who} matched a watchlist we do not yet classify",
            (
                f"A name check returned a match for {who} on a list this "
                f"system does not yet have a specific rule for.",
                "We are not able to tell you what kind of list it is, so this "
                "needs a person to look at the entry itself and decide what "
                "it means.",
            ),
            (
                "Open the watchlist entry and establish what the list is and "
                "why this party is on it.",
                "Establish whether it is genuinely the same party, comparing "
                "the date of birth, nationality and identity document against "
                "the documents we hold.",
                "Record what you found and what you concluded, either way.",
            ),
        )
    return (
        f"There is adverse media about {who}",
        (
            f"Press or public reporting about {who} was flagged during checks.",
            "Not every negative article matters. What matters is whether it "
            "concerns financial crime, fraud, corruption or similar, and whether "
            "it is credible and about this same party.",
        ),
        (
            "Read the reporting and decide whether it concerns this same party "
            "and whether it is credible.",
            "If it is material, treat the relationship as higher risk and apply "
            "enhanced due diligence.",
            "Record your conclusion either way — including a decision that it "
            "is not material.",
        ),
    )


def _ownership(case: Case, detail: Mapping[str, Any], who: str, policy: str, describe):
    threshold = _pct((detail.get("test") or {}).get("threshold_pct", 10))
    owners = detail.get("owners") or []
    below = detail.get("below_threshold") or []
    cycles = detail.get("cycles") or []
    dead_ends = detail.get("dead_ends") or []
    missing = detail.get("missing_roles") or []

    if policy == "POL_UBO_CYCLE" or cycles:
        ring = list(cycles[0] if cycles else detail.get("cycle", []))
        # Two shapes reach here. graph.resolve_ubo repeats the first company at
        # the end to close the loop; policies.ownership_cycle stores distinct
        # ids. Slicing the last element off unconditionally dropped a real
        # company from the sentence, and with only two in the loop it named
        # nobody but the subject -- while the other branch described the same
        # loop correctly, so one screen could explain one loop two ways.
        if len(ring) > 1 and ring[0] == ring[-1]:
            ring = ring[:-1]
        named = [describe(node) for node in ring]
        if named and named[0] != who:
            # Start the loop at the company the officer is looking at, so the
            # sentence begins where their eye already is.
            named = (named[named.index(who):] + named[:named.index(who)]
                     if who in named else [who] + named)
        # The chain closes on itself, which is what makes it a circle a person
        # can see. It used to stop short and add "and that last company owns
        # the first one again" -- which, once the chain was complete, described
        # the first company as though it were a different one.
        chain = (
            f"{named[0]} is owned by "
            + ", which is owned by ".join(named[1:] + [f"{named[0]} again"])
            if len(named) > 1 else who
        )
        because = [
            f"The ownership of {who} runs in a circle: {chain}.",
            "Because the chain loops, it never arrives at a real person, so we "
            "cannot tell you who ultimately benefits from this investment.",
        ]
        if owners:
            found = _join([f"{o['name']} ({_pct(o['effective_pct'])})" for o in owners])
            because.append(
                f"We did find {found} along the way, but while the loop is there "
                f"we cannot be sure that is everyone."
            )
        return (
            f"We cannot work out who really owns {who}",
            tuple(because),
            (
                f"Ask {who} for a signed ownership declaration naming every "
                f"individual who owns more than {threshold} of the company, "
                f"directly or through any other company.",
                "Ask them to explain the circular shareholding — there is "
                "sometimes a legitimate reason, and it should be on file.",
                "Support it with a register of members or a shareholding chart, "
                "not just the declaration.",
            ),
        )

    if missing:
        return (
            f"{who} has not named everyone the rules require",
            (
                f"For a trust, the rules require you to identify the person who "
                f"set it up and the trustee, whatever their share of it.",
                f"We have not been given: {_join(list(missing))}.",
            ),
            (
                f"Request the trust deed for {who}.",
                "From it, record the settlor, the trustee, and any protector or "
                "other person who can direct how the trust is run.",
                "Collect identity documents for each of them.",
            ),
        )

    if policy == "POL_UBO_SENIOR_OFFICIAL_REQUIRED":
        largest = (
            f"The largest single holding is {below[0]['name']} with "
            f"{_pct(below[0]['effective_pct'])}."
            if below
            else "No individual holds a stake at all."
        )
        return (
            f"No one owns enough of {who} to count as its beneficial owner",
            (
                f"We traced everyone with a stake in {who}. {largest}",
                f"That is below the {threshold} the rules use for this kind of "
                f"customer, so on ownership alone there is no beneficial owner "
                f"to name.",
                "The rules are clear about what happens then: the beneficial "
                "owner is the most senior person actually running the business.",
            ),
            (
                f"Ask {who} who their senior managing official is.",
                "Collect that person's identity documents and record them as the "
                "beneficial owner, noting that this is the fallback position "
                "rather than an ownership finding.",
            ),
        )

    if dead_ends:
        return (
            f"The ownership trail for {who} stops before it reaches a person",
            (
                f"{who} is owned by another company, but nobody has told us who "
                f"owns that company in turn.",
                f"The trail stops at: {_join([describe(d) for d in dead_ends])}.",
                "Until it reaches named individuals, we cannot say who "
                "ultimately benefits.",
            ),
            (
                "Ask for the ownership of each company in the chain, until every "
                "branch ends at a named individual.",
                "A group structure chart is usually the fastest way to get this.",
            ),
        )

    return (
        f"Nobody has told us who owns {who}",
        (
            f"We hold no ownership information for {who} at all.",
            "Money must not be accepted from a customer whose beneficial "
            "owners have not been identified.",
        ),
        (
            f"Request an ownership declaration from {who} naming every "
            f"individual holding more than {threshold}.",
            "Ask for supporting evidence — register of members, shareholding "
            "chart, or the trust deed if it is a trust.",
        ),
    )


def _disclosure(case: Case, detail: Mapping[str, Any], who: str,
                policy: str, describe):
    """A return that claimed something the book holds nothing for."""
    figures = detail.get("figures") or []
    period = str(detail.get("period") or "")

    lines = [
        f"The return for {period} was filed claiming "
        + _join([f"{row.get('what')} of {row.get('reported')}"
                 for row in figures])
        + ", and the records hold "
        + _join([str(row.get("records_show")) for row in figures])
        + ".",
        "A gap between a reported figure and the book is ordinary. Capital "
        "is called in tranches, values move, and a fund can properly be "
        "worth more or less than was promised to it — none of that is "
        "raised here and none of it should be.",
        "This is different. There is nothing behind the figure at all, "
        "which is the nearest thing in these records to the misstatement "
        "that cost an IFSC broker its authorisation: income booked under "
        "the wrong name.",
    ]
    return (
        f"A figure was reported to IFSCA that this book cannot show",
        tuple(lines),
        (
            "Find where the reported figure came from — it may be held "
            "somewhere this system has never been given.",
            "If it came from somewhere real, get that into the records so "
            "the return and the book agree.",
            "If it did not, the return needs correcting with the "
            "Authority, and that is not something to settle quietly here.",
        ),
    )


def _capital(case: Case, detail: Mapping[str, Any], who: str,
             policy: str, describe):
    """The firm is worth less than its licence requires."""
    short = detail.get("short_usd") or 0
    minimum = detail.get("minimum_usd") or 0
    held = detail.get("amount_usd") or 0
    caveat = str(detail.get("caveat") or "")

    because = [
        f"The last figure recorded for this firm is "
        f"USD {held:,.0f} as at {_date(detail.get('as_at'))}. The minimum "
        f"is USD {minimum:,.0f}, so it is USD {short:,.0f} short.",
        "This is the obligation that cost an IFSC lessor its registration, "
        "and nothing about it moves. A licence is granted, a figure is "
        "required from that day, and the only way anybody finds out it is "
        "not there is when somebody looks.",
    ]
    if caveat:
        because.append(caveat)

    return (
        "This firm is below the capital its licence requires",
        tuple(because),
        (
            "Establish the current position with whoever keeps the accounts, "
            "and record it here.",
            ("Confirm the minimum that actually applies to this firm, so "
             "this stops resting on an unchecked figure."
             if caveat else
             "If the position has changed, record the new figure."),
            "If it is genuinely short, that is a conversation with the "
            "Authority rather than a file to settle here.",
        ),
    )


def _document(case: Case, detail: Mapping[str, Any], who: str,
              policy: str, describe):
    """One file standing as evidence for more than one party."""
    from .documents import KINDS

    others = [describe(other) for other in (detail.get("others") or ())]
    called = KINDS.get(str(detail.get("kind") or ""),
                       ("A document", ()))[0].lower()
    named = str(detail.get("filename") or "")

    return (
        f"The same {called} is on file for {_join(others)} as well",
        (
            f"The file filed here{f' ({named})' if named else ''} is byte for "
            f"byte the file already on record for {_join(others)}.",
            "The same scan cannot be evidence of two people. Either one of "
            "these records has somebody else's document attached to it, or "
            "one identity is being used twice — and the two are answered "
            "very differently.",
            "Nothing has been assumed either way. Both records still stand "
            "and both still cite this file.",
        ),
        (
            "Open both records and establish which party this document "
            "actually belongs to.",
            "Get the right document for the other one, file it, and record "
            "what happened to this one.",
            "If the same person really is on the book twice, that is a "
            "separate thing to settle and this file does not settle it.",
        ),
    )


def _notice(case: Case, detail: Mapping[str, Any], who: str,
            policy: str, describe):
    """A regulator's letter nobody has answered.

    Written to be read by whoever can actually fix it, which for this one
    is usually the Principal Officer rather than the AML officer. So it
    says what was asked, when, by whom, and how long ago -- and nothing
    about analysis, because there is nothing to analyse. Somebody has to
    write a letter.
    """
    from .correspondence import who_sent_it

    sender = who_sent_it(str(detail.get("from_whom") or ""))
    late = detail.get("days_late")
    late_words = (f"{late} {_plural(int(late), 'day')}"
                  if isinstance(late, int) and late > 0 else "some days")
    asked = str(detail.get("about") or "").strip()

    answered_on = str(detail.get("answered_on") or "")
    if answered_on:
        late = detail.get("days_late")
        when = (f", {late} {_plural(int(late), 'day')} after the date they "
                f"set" if isinstance(late, int) and late > 0
                else ", within the time they gave")
        because = [
            f"{sender} wrote on {_date(detail.get('received_on'))} asking for "
            f"an answer by {_date(detail.get('answer_by'))}. "
            f"{str(detail.get('answered_by') or 'Somebody')} recorded an "
            f"answer on {_date(answered_on)}{when}.",
        ]
        said = str(detail.get("answer") or "").strip()
        if said:
            because.append(f"What was sent: {said}")
    else:
        because = [
            f"{sender} wrote on {_date(detail.get('received_on'))} asking for "
            f"an answer by {_date(detail.get('answer_by'))}. That date passed "
            f"{late_words} ago and nothing has been recorded as sent.",
        ]
    if asked:
        because.append(f"What they asked for: {asked}")
    because.append(
        "This is the ground the Authority has acted on most often. Not "
        "because the answer was wrong, but because none arrived — an "
        "unanswered letter is a breach in itself, and it goes on being one "
        "every day nobody writes back.")

    if answered_on:
        return (
            f"{sender} was answered, and this file is still open",
            tuple(because),
            (
                "Read what was sent and settle this file, or say what is "
                "still outstanding.",
                "If the answer was late, the lateness is the thing to note: "
                "it is on the record above and an inspector will ask.",
            ),
        )

    return (
        f"{sender} is waiting for an answer",
        tuple(because),
        (
            "Send the answer, then record here what was sent and when.",
            "If the answer needs more time, ask them for it in writing — an "
            "extension they agreed to is a different record from silence.",
            "If it was already answered, record that now, so the next "
            "person is not chasing something already done.",
        ),
    )


def _same_party(case: Case, detail: Mapping[str, Any], who: str,
                policy: str, describe):
    """Two records that may be one party.

    The point is not that a duplicate is suspicious. It is that every rule
    in the product that counts something -- how many investors one sender
    funds, how many senders fund one investor -- counts these two
    separately, so a book with duplicates in it is quietly under-monitored.
    Saying that plainly is what makes the file worth opening.
    """
    other = describe(str(detail.get("other") or ""))
    identified = bool(detail.get("identified"))
    disagrees = tuple(detail.get("disagrees") or ())

    because = [str(detail.get("because") or "")]
    if identified:
        because.append(
            "The number they share is issued to one holder, so two records "
            "carrying it are either the same party or a mistake in the "
            "records.")
    because.append(
        "While both records stand, everything this product counts is "
        "counted twice: payments funding one investor, senders funding "
        "several, and how risky each is judged to be. Three payments "
        "across two records reach no threshold that three payments "
        "across one would.")
    if disagrees:
        because.append(
            "This is not settled. Against it, the records disagree on "
            f"{_join(disagrees)} — which is worth explaining either "
            f"way, because one of the two is wrong.")

    return (
        f"This party may already be on the book as {other}",
        tuple(because),
        (
            "Establish whether these are one party or two.",
            "If they are one, decide which record is the surviving one and "
            "record why — nothing here merges them for you, because a "
            "wrong merge cannot be undone.",
            "If they are two, record what distinguishes them, so the next "
            "person does not ask again.",
        ),
    )


def _payment(case: Case, detail: Mapping[str, Any], who: str, policy: str, describe):
    amount = _money(detail.get("amount"), detail.get("currency"))
    called = _money(detail.get("called_amount"), detail.get("currency"))
    words = {
        "POL_PAY_SANCTIONED_PAYER": (
            "Money arrived from a party that may be on a sanctions list",
            (
                f"A payment of {amount} arrived, and the sender resembles a name "
                f"on a sanctions list.",
                "Handling funds from a sanctioned party is an offence in itself, "
                "so nothing must move until this is settled.",
            ),
            (
                "Do not apply this money to the investor's account or move it on.",
                "Establish whether the sender is genuinely the listed party.",
                "If it is, follow the freezing procedure and report it. If it is "
                "not, record what you compared.",
            ),
        ),
        "POL_PAY_STRUCTURING": (
            "Payments look deliberately split to stay under a threshold",
            (
                f"Several payments arrived on the same day, each below the level "
                f"that would trigger a report, together making up {amount}.",
                "That pattern is one of the recognised signs of layering. There "
                "can be innocent explanations — banking limits, for example.",
            ),
            (
                "Ask the investor why the payment was split.",
                "Check whether the same pattern has happened before with this "
                "investor.",
                "If no ordinary explanation holds up, prepare this for reporting.",
            ),
        ),
        "POL_PAY_SHARED_PAYER": (
            "One sender is funding several investors on this book",
            (
                f"A payment of {amount} arrived from a sender who has also "
                f"paid other investors here.",
                "One account funding several supposedly unrelated investors "
                "is a recognised way of moving one person's money in under "
                "several names. There can be ordinary explanations — a "
                "family office, a feeder arrangement, one adviser settling "
                "for several clients.",
            ),
            (
                "List which investors this sender has paid, and ask each of "
                "them what their relationship to the sender is.",
                "Establish whether the answers agree with one another.",
                "If the investors are genuinely connected, record how; if "
                "they are not, ask why one account is paying for all of "
                "them.",
            ),
        ),
        "POL_PAY_CAME_BACK": (
            "Money from this investor has come back to them",
            (
                f"A payment of {amount} arrived from a sender who had "
                f"already been paid, directly or through others, by this "
                f"same investor.",
                "Money that leaves a party and returns to them has bought "
                "nothing and settled nothing. The only thing that changed "
                "is the history it now carries, which is what makes the "
                "round trip worth an explanation rather than the amount.",
            ),
            (
                "Ask what each step in the round trip was for, and get the "
                "answer in writing before any of it is accepted.",
                "Establish whether the parties in between are connected to "
                "this investor; if they are, record how.",
                "Where no commercial purpose can be shown for the round "
                "trip, consider whether this needs reporting.",
            ),
        ),
        "POL_PAY_PASSED_THROUGH": (
            "This money was passed along a chain before it arrived",
            (
                f"A payment of {amount} arrived from a sender who had "
                f"themselves been paid shortly before, by somebody who had "
                f"also been paid shortly before that.",
                "One party passing money on is ordinary -- a feeder, a "
                "nominee, an agent. A chain of them separates the money "
                "from whoever first sent it, which is the point of doing "
                "it.",
            ),
            (
                "Follow the chain to whoever started it and establish where "
                "their money came from.",
                "Ask each party in the chain what their part in it was.",
                "Check whether your fund documents permit payment from "
                "anyone other than the investor.",
            ),
        ),
        "POL_PAY_MANY_PAYERS": (
            "This investor is being funded from several different accounts",
            (
                f"A payment of {amount} arrived, and this investor has now "
                f"been funded from several different senders.",
                "A capital call is normally met from the investor's own "
                "account. Money arriving from several sources is worth an "
                "explanation before it is accepted.",
            ),
            (
                "Ask the investor to account for each sender and their "
                "relationship to it.",
                "Check whether your fund documents permit payment from "
                "anyone other than the investor.",
            ),
        ),
        "POL_PAY_THIRD_PARTY": (
            "The money came from someone other than the investor",
            (
                f"A payment of {amount} arrived, but the sender is not the "
                f"investor who committed the capital.",
                "Third-party funding hides the real source of money, so it needs "
                "an explanation and usually documentary support.",
            ),
            (
                "Ask the investor who sent the money and what their relationship "
                "to it is.",
                "Check whether your fund documents permit third-party payments "
                "at all.",
                "If accepted, apply the same checks to the sender as you would "
                "to an investor.",
            ),
        ),
        "POL_PAY_UNKNOWN_SOURCE": (
            "Money arrived that we cannot match to any investor",
            (
                # Capitalised explicitly: when no amount is on file, _money()
                # returns "an unstated amount", and a sentence starting with a
                # lower-case word reads as a typo to the reader, not a
                # deliberate word choice.
                _sentence(
                    f"{amount} was received with nothing tying it to a known "
                    f"investor or capital call."
                ),
                "Unattributed money should not sit in the fund unexplained.",
            ),
            (
                "Ask the bank for the full payment details including the sender.",
                "If it cannot be attributed, consider returning it to source "
                "rather than holding it.",
            ),
        ),
        "POL_PAY_OVERPAYMENT": (
            "More money arrived than was asked for",
            (
                _sentence(f"{amount} was received against a call for {called}."),
                "Usually this is an error or an early payment. Occasionally it "
                "is an attempt to place funds that need somewhere to sit.",
            ),
            (
                "Ask the investor to confirm the intended amount in writing.",
                "Agree whether to refund the excess or hold it against the next "
                "call, and record which.",
            ),
        ),
        "POL_PAY_UNEXPECTED_CURRENCY": (
            "The money arrived in a different currency than expected",
            (
                _sentence(
                    f"{amount} was received where "
                    f"{detail.get('expected_currency') or 'another currency'} "
                    f"was expected."
                ),
                "Often administrative. Worth a note either way, since a change "
                "in payment route can be an early sign of something else.",
            ),
            (
                "Confirm with the investor that their payment arrangements have "
                "changed, and update their record.",
                "Check the converted amount still satisfies what was called.",
            ),
        ),
    }
    return words.get(policy, (f"A payment from {who} needs review", (), ()))


def _licence(case: Case, detail: Mapping[str, Any], who: str, policy: str, describe):
    activity = str(detail.get("activity", "")).replace("_", " ").lower()
    category = str(detail.get("category") or "").replace("_", " ").lower()
    return (
        f"{who} may be doing something its licence does not cover",
        (
            f"Records show {who} undertaking {activity}.",
            f"Its registration is as a {category} fund management entity, "
            f"and that category does not include this activity."
            if category else
            f"No registration category is on file, so nothing can be confirmed as permitted.",
            "An entity may not carry on business outside its category without "
            "the Authority's prior approval. IFSCA has cancelled registrations "
            "and imposed penalties on this ground.",
        ),
        (
            "Confirm whether this activity is actually being carried on, or "
            "whether the record is wrong.",
            "If it is being carried on, establish whether prior approval was "
            "obtained from IFSCA and put a copy on file.",
            "If there is no approval, stop the activity and take advice before "
            "resuming — this is the kind of thing that costs a registration.",
        ),
    )


def _governance(case: Case, detail: Mapping[str, Any], who: str, policy: str, describe):
    post = str(detail.get("office", "")).replace("_", " ").lower()
    due = detail.get("due_by")
    if detail.get("resolved"):
        # The seat is filled. The Case stays open because a person still
        # confirms the appointment, but the file must stop saying nobody is
        # there -- the log says somebody is.
        person = detail.get("person") or "someone"
        filled_on = detail.get("filled_on")
        vacated_on = detail.get("vacated_on")
        since = (f" The post had been empty since {_date(vacated_on)}."
                 if vacated_on else "")
        return (
            f"Your {post} post has been filled",
            (
                f"{person} is recorded as holding the post of {post} for {who}"
                + (f", appointed {_date(filled_on)}." if filled_on else ".")
                + since,
                "This is still on your list because an appointment is not "
                "complete until it is confirmed and IFSCA is told.",
            ),
            (
                f"Confirm that {person} has taken up the post and meets the "
                f"qualification and experience requirements.",
                "Notify IFSCA of the appointment in the manner they specify — "
                "the appointment itself is not enough.",
                f"Check that {person} is based in GIFT City, which an "
                f"unannounced inspection will look for.",
            ),
        )
    if policy == "POL_OFFICE_NOT_BASED_IN_IFSC":
        person = detail.get("person") or "the holder"
        return (
            f"Your {post} is not recorded as based in GIFT City",
            (
                f"{person} holds the post of {post}, but our records do not "
                f"show them as based in the IFSC.",
                "The rules require the principal officer and every key "
                "managerial person to be based out of the IFSC — not merely "
                "appointed, but there.",
                "IFSCA checks this by turning up unannounced. It has issued a "
                "warning to a fund management entity whose principal officer "
                "and key managerial personnel were absent on four such visits.",
            ),
            (
                f"Confirm where {person} is actually based and correct the "
                f"record.",
                "If they are not based in GIFT City, either relocate them or "
                "appoint someone who is.",
                "Make sure the office is staffed and open during business "
                "hours — an inspection can happen on any working day.",
            ),
        )
    deadline = f" You have until {_date(due)} to fill it." if due else ""
    return (
        f"You have no {post} in post",
        (
            f"The post of {post} is required for {who} and nobody currently "
            f"holds it.",
            "A required post left empty is one of the most common reasons an "
            "entity in GIFT City loses its registration. It is also the first "
            "thing an unannounced inspection looks for."
            + deadline,
        ),
        (
            f"Appoint a {post} who meets the qualification and experience "
            f"requirements and is based in GIFT City.",
            "Notify IFSCA of the appointment in the manner they specify — the "
            "appointment itself is not enough.",
            "Until the post is filled, make sure someone senior is present at "
            "the office and able to answer for the entity.",
        ),
    )


def _filing(case: Case, detail: Mapping[str, Any], who: str, policy: str, describe):
    period = detail.get("period", "")
    days = detail.get("days_late") or 0
    charge = detail.get("late_charge_usd") or 0
    repeat = int(detail.get("outstanding_count") or 1) > 1
    schedule = BY_OBLIGATION[Obligation(detail["obligation"])]
    # A return is filed; a fee is paid. calendar.py says so where the verb is
    # defined, and the first sentence below honours it -- but every sentence
    # after it used to say "return" regardless, so an officer holding an unpaid
    # fee was told to file a document in the IFSCA Downloads format. There is
    # no such document. They would have filed nothing and still owed the money.
    money = not schedule.late_charge and schedule.verb == "paid"
    thing = "payment" if money else "return"
    because = [
        f"The {schedule.label} for {period} was due on "
        f"{_date(detail.get('due_on', ''))} and has not been {schedule.verb}. "
        f"That is {days} {_plural(days, 'day')} ago.",
    ]
    if charge:
        because.append(
            f"A late-submission charge of USD {charge:,} has accrued on this "
            f"return — USD 100 for every month or part of a month, for each "
            f"return. Paying it does not settle the matter."
        )
    if repeat:
        because.append(
            f"This is not the only {thing} outstanding. A single lapse draws a "
            f"warning; a pattern of them is what has cost entities in GIFT "
            f"City their registration outright."
        )
    else:
        because.append(
            f"Late {thing}s are among the most common reasons IFSCA takes "
            f"action. It usually begins with a warning letter."
        )
    if money:
        return (
            f"Your {schedule.label} for {period} is unpaid",
            tuple(because),
            (
                f"Pay the {schedule.label} for {period} to IFSCA and keep the "
                f"confirmation on file.",
                "If anything is blocking it, write to IFSCA and say so before "
                "they write to you. Silence is treated as non-cooperation and "
                "counts against you separately.",
                "Check whether any earlier year's fee is also unpaid and "
                "settle those at the same time.",
            ),
        )
    return (
        f"Your {schedule.label} for {period} is overdue",
        tuple(because),
        (
            f"File the {period} return in the current format from the "
            f"Downloads section of the IFSCA website — the formats were "
            f"revised on 3 April 2025.",
            "If anything is blocking it, write to IFSCA and say so before "
            "they write to you. Silence is treated as non-cooperation and "
            "counts against you separately.",
            "Check whether any earlier period is also outstanding and file "
            "those at the same time.",
        ),
    )


WRITERS = {
    "FILING": _filing,
    "LICENCE_SCOPE": _licence,
    "GOVERNANCE": _governance,
    "SCREENING_HIT": _screening,
    "UBO_REVIEW": _ownership,
    "PAYMENT_MISMATCH": _payment,
    "SAME_PARTY": _same_party,
    "NOTICE": _notice,
    "DOCUMENT": _document,
    "CAPITAL": _capital,
    "DISCLOSURE": _disclosure,
}


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

#: How each clause reads once it is put in plain words. Kept beside the
#: verbatim quote so a reader can check the restatement against the source.
PLAIN_RULES = {
    "1.3.3(a)": "For a company customer, anyone holding more than 10% of the "
                "shares, capital or profits is a beneficial owner — and so is "
                "anyone who controls it by other means, such as being able to "
                "appoint most of the board.",
    "1.3.3(b)": "For a partnership, anyone holding more than 10% of the capital "
                "or profits is a beneficial owner.",
    "1.3.3(c)": "For an unincorporated body the figure is 15%. And where no "
                "individual meets the test at all, the beneficial owner is the "
                "senior managing official.",
    "1.3.3(d)": "For a trust you must identify the person who created it, the "
                "trustee, any beneficiary with 10% or more, and anyone who "
                "effectively controls it.",
    "5.4.5": "You must identify every beneficial owner and take reasonable "
             "steps to verify who they are using reliable, independent sources.",
    "5.9": "You must check customers, their business and their transactions "
           "against the United Nations sanctions lists and any other list that "
           "applies to you.",
    "11.2": "Where a party is listed, the asset-freezing procedure under the "
            "Unlawful Activities (Prevention) Act must be followed exactly.",
    "5.5": "You must have a way of working out whether a customer, anyone "
           "acting for them, or any of their beneficial owners is a "
           "politically exposed person.",
    "5.5(b)(iii)": "Before a politically exposed person is taken on, senior "
                   "management has to approve it. Nobody more junior can.",
    "5.5(b)(iv)": "Where somebody already on the book becomes a politically "
                  "exposed person, senior management has to approve carrying "
                  "on with them.",
    "5.6": "Where the risk of money laundering or terrorist financing is high, "
           "you must carry out enhanced due diligence proportionate to it.",
    "4.2": "When judging whether a situation is high risk, you must weigh "
           "factors including the customer, their business and whether any "
           "country involved is under sanctions.",
    "10.2": "A suspicious transaction is identified by spotting an indicator, "
            "questioning the customer, reviewing their records, and then "
            "weighing it all up.",
    "10.1": "Suspicions must be reported internally, escalated to the Principal "
            "Officer, and reported onward to FIU-IND where required.",
    "3(4)": "Every fund management entity is registered in one of three "
            "categories, and each category fixes what it may do. The "
            "categories build on each other: a retail FME may do everything "
            "the other two may.",
    "137": "You may not carry on any business activity outside what your "
           "registration covers without IFSCA's prior approval.",
    "7(1)": "You must have a principal officer, responsible for the whole of "
            "the entity's activity including fund management, risk and "
            "compliance.",
    "7(2)": "A registered FME must also have a compliance officer, responsible "
            "for compliance and for putting risk management into practice.",
    "7(3)": "A retail FME must appoint an additional fund-management KMP "
            "before it files the offer document for its first retail scheme "
            "or ETF — before, not after.",
    "7(4)": "Once you manage USD 1 billion or more at the close of a financial "
            "year, you must appoint an additional fund-management KMP within "
            "six months of that year end.",
    "7(5)": "Your principal officer and every KMP must be based out of the "
            "IFSC, and must meet the stated qualification and experience "
            "requirements.",
    "10(1)": "You must have office space, equipment, communications and staff "
             "sufficient for what you actually do — judged against the size of "
             "your operation, not a minimum.",
    "120": "You must file the returns IFSCA asks for, in the form and at the "
           "interval it specifies. For fund management entities that means a "
           "quarterly report, due within 21 calendar days of the quarter end.",
    "5.5 Guidance Note (4)":
        "Holding public office does not by itself make somebody high risk. "
        "You assess each one and decide the category yourself — and "
        "whatever you decide, the extra measures under 5.5(b) still apply.",
    "5.4.2": "For a person you must hold their full name and any aliases, an "
             "identifying number, date of birth, nationality, domicile, a "
             "residential address that is not a post office box, and contact "
             "details. For a company or a trust: its full name and any trading "
             "name, an identifying number, its registered and business "
             "addresses, and when and where it was set up — plus its legal "
             "form and who its connected parties are.",
    "5.11": "How often you must look at a customer again: every year if they "
            "are high risk, every three years if medium, every five if low. "
            "For a resident Indian customer already known to your group in "
            "India the cycle is longer — two, eight and ten years.",
    "8(1)": "You must be worth at least the amount set for your registration "
            "category, at all times — not on the day you registered, and "
            "not on average. IFSCA may set a different amount for you.",
    "Second Schedule": "The amounts. An authorised FME must be worth USD "
                       "75,000; a non-retail registered FME, USD 500,000; a "
                       "retail registered FME, USD 1,000,000.",
    "107F": "If you are authorised to manage somebody else's money as a "
            "third-party fund manager, you must hold a further USD 500,000 on "
            "top of your category amount, not instead of it.",
}

UNVERIFIED_CAUTION = (
    "We have not yet had a compliance professional confirm this wording against "
    "the published guidelines. Read the source before relying on it."
)


#: The heading for a group of like items. ``{n}`` is the count, ``{is}`` the
#: verb, so one item reads as naturally as forty.
GROUP_TITLE = {
    "POL_SANCTIONS_HIT": "{n} {party} may be on a sanctions list",
    "POL_PEP_HIT": "{n} {party} may hold or be close to public office",
    "POL_ADVERSE_MEDIA": "There is adverse media about {n} {party}",
    "POL_PEP_ASSOCIATE":
        "{n} {party} may be a relative or close associate of somebody in "
        "public office",
    "POL_CRIMINAL_HIT":
        "{n} {party} may be wanted, or named in a criminal matter",
    "POL_DEBARRED":
        "{n} {party} may be barred from public contracts or regulated work",
    "POL_WATCHLIST_HIT_UNCLASSIFIED":
        "{n} {party} matched a watchlist we do not yet classify",
    "POL_UBO_CYCLE": "{n} {structure} {contain} circular ownership",
    "POL_UBO_INCOMPLETE": "{n} {investor} cannot be cleared until you establish who owns them",
    "POL_UBO_SENIOR_OFFICIAL_REQUIRED": "{n} {investor} {have} no owner large enough to name",
    "POL_UBO_NOT_DECLARED": "{n} {investor} {have} told us nothing about who owns them",
    "POL_PAY_SANCTIONED_PAYER": "{n} {payment} arrived from a party that may be sanctioned",
    "POL_PAY_STRUCTURING": "{n} {payment} {look} deliberately split to stay under a threshold",
    "POL_PAY_THIRD_PARTY": "{n} {payment} came from someone other than the investor",
    "POL_PAY_SHARED_PAYER":
        "{n} {payment} came from a sender who is funding several investors",
    "POL_PAY_MANY_PAYERS":
        "{n} {payment} went to an investor funded from several accounts",
    "POL_CAPITAL_SHORT":
        "This firm is below the capital its licence requires",
    "POL_REPORTED_WITHOUT_RECORDS":
        "{n} {filing} claimed something the records hold nothing for",
    "POL_ONE_DOCUMENT_TWO_PARTIES":
        "{n} {document} {isare} on file for more than one party",
    "POL_NOTICE_UNANSWERED":
        "{n} {letter} from a regulator {were} never answered",
    "POL_SAME_PARTY_TWICE":
        "{n} {party} may already be on the book under another record",
    "POL_PAY_CAME_BACK":
        "{n} {payment} came back to the investor who sent it out",
    "POL_PAY_PASSED_THROUGH":
        "{n} {payment} {were} passed along a chain before arriving",
    "POL_PAY_UNKNOWN_SOURCE": "{n} {payment} cannot be matched to any investor",
    "POL_PAY_OVERPAYMENT": "{n} {payment} {were} larger than the amount called",
    "POL_PAY_UNEXPECTED_CURRENCY": "{n} {payment} arrived in an unexpected currency",
    "POL_ACTIVITY_OUTSIDE_LICENCE":
        "{n} {activity} may be outside what your licence permits",
    "POL_OFFICE_VACANT": "{n} required {post} {isare} unfilled",
    # A filled seat is not an unfilled one. It stays on the list until a person
    # confirms the appointment, but counting it among the vacancies told an
    # officer two posts were empty when one of them had somebody in it.
    "POL_OFFICE_VACANT|FILLED": "{n} filled {post} {isare} awaiting confirmation with IFSCA",
    "POL_OFFICE_NOT_BASED_IN_IFSC":
        "{n} required {post} {has} someone not based in GIFT City",
    "POL_REVIEW_OVERDUE": "{n} {customer} overdue for review",
    "POL_OWNERSHIP_CHANGED_AFTER_DILIGENCE":
        "{n} {customer} changed hands since {were} checked",
    "POL_FILING_OVERDUE": "{n} {filing} overdue with IFSCA",
    "POL_FILING_REPEATEDLY_LATE":
        "{n} {filing} overdue — this is not the first",
    # A fee is money owed, not paperwork missing. Counting an unpaid fee among
    # "filings overdue" tells an officer to produce a document that does not
    # exist, and understates what IFSCA is actually waiting for.
    "POL_FILING_OVERDUE|FEE": "{n} {fee} unpaid",
    "POL_FILING_REPEATEDLY_LATE|FEE":
        "{n} {fee} unpaid — this is not the first",
}

#: The obligations that are settled with money rather than a document.
_FEE_OBLIGATIONS = frozenset({
    Obligation.FLAT_RECURRING_FEE.value,
    Obligation.CONDITIONAL_RECURRING_FEE.value,
})

#: A group's shared "why this matters" and "what to do", written once per
#: policy and generically -- no party name, no amount, no single item's fact.
#: app.js renders only ``group.because``/``group.to_close_this`` for the whole
#: group and never an individual item's own text, so this is the entire
#: explanation an officer reads. Copying it from the first item used to put
#: one item's specific detail -- a named trust, a named person, one turnover
#: fee -- in front of every other item in the group, which is wrong for all
#: of them but the first.
GROUP_BECAUSE = {
    "POL_SANCTIONS_HIT": (
        "Each of these is a possible match against United Nations and other "
        "sanctions lists.",
        "A possible match is not proof. Lists hold names, not people, and "
        "common names collide. Establishing whether each is really the same "
        "party is the work.",
    ),
    "POL_PEP_HIT": (
        "Each of these appears on a list of politically exposed persons.",
        "This is not an allegation of wrongdoing. It means there is a higher "
        "risk that funds could come from bribery or misuse of public money, "
        "so each file needs deeper checks than usual.",
    ),
    "POL_ADVERSE_MEDIA": (
        "Press or public reporting was flagged during checks on each of "
        "these.",
        "Not every negative article matters. What matters is whether it "
        "concerns financial crime, fraud, corruption or similar, and whether "
        "it is credible and about the same party.",
    ),
    "POL_WATCHLIST_HIT_UNCLASSIFIED": (
        "Each of these matched a list this system does not yet have a "
        "specific rule for.",
        "We are not able to tell you what kind of list each one is, so each "
        "needs a person to look at the entry itself and decide what it means.",
    ),
    "POL_UBO_CYCLE": (
        "The ownership of each of these runs in a circle that never arrives "
        "at a real person, so we cannot tell you who ultimately benefits "
        "from the investment.",
        "A circular structure sometimes has a legitimate reason, but it has "
        "to be established, not assumed.",
    ),
    "POL_UBO_INCOMPLETE": (
        "For each of these, the ownership or control information we hold "
        "does not go far enough to identify who ultimately owns or runs the "
        "investor.",
        "Money must not be accepted from a customer whose beneficial "
        "owners have not been identified.",
    ),
    "POL_UBO_SENIOR_OFFICIAL_REQUIRED": (
        "For each of these, nobody's shareholding is large enough on its own "
        "to count as a beneficial owner under the rules.",
        "The rules are clear about what happens then: the beneficial owner "
        "is the most senior person actually running the business.",
    ),
    "POL_UBO_NOT_DECLARED": (
        "We hold no ownership information at all for each of these.",
        "Money must not be accepted from a customer whose beneficial "
        "owners have not been identified.",
    ),
    "POL_PAY_SANCTIONED_PAYER": (
        "Each of these payments arrived from a sender that resembles a name "
        "on a sanctions list.",
        "Handling funds from a sanctioned party is an offence in itself, so "
        "nothing must move until each is settled.",
    ),
    "POL_PAY_STRUCTURING": (
        "For each of these, several payments arrived on the same day, each "
        "below the level that would trigger a report.",
        "That pattern is one of the recognised signs of layering. There can "
        "be innocent explanations — banking limits, for example.",
    ),
    "POL_PAY_SHARED_PAYER": (
        "For each of these, one sender has paid several different investors "
        "on this book.",
        "One account funding several supposedly unrelated investors is a "
        "recognised way of moving one person's money in under several "
        "names. A family office or a feeder arrangement explains it; "
        "nothing explaining it does not.",
    ),
    "POL_PAY_MANY_PAYERS": (
        "Each of these investors has been funded from several different "
        "accounts.",
        "A capital call is normally met from the investor's own account.",
    ),
    "POL_CAPITAL_SHORT": (
        "The firm's own money is below what its licence requires it to "
        "keep.",
        "Nothing about this obligation moves, which is why it stops being "
        "noticed until somebody looks.",
    ),
    "POL_REPORTED_WITHOUT_RECORDS": (
        "Each of these returns claimed a figure the book holds nothing at "
        "all for.",
        "A gap between a reported figure and the records is ordinary — "
        "capital is called in tranches and values move. A figure with "
        "nothing behind it is not a gap, it is a number from nowhere.",
    ),
    "POL_ONE_DOCUMENT_TWO_PARTIES": (
        "Each of these files is byte for byte a file already on record "
        "for somebody else.",
        "The same scan cannot be evidence of two people. Either a record "
        "has the wrong document attached, or one identity is being used "
        "twice.",
    ),
    "POL_NOTICE_UNANSWERED": (
        "A regulator asked each of these questions and set a date. The "
        "date has passed and no answer is recorded.",
        "Nothing here needs analysing. Somebody has to write back, and "
        "every day nobody does is another day of the breach.",
    ),
    "POL_SAME_PARTY_TWICE": (
        "Each of these looks like a party the book already holds under "
        "another record.",
        "Nothing is merged for you. While both stand, every rule that "
        "counts something counts them separately, so the book is watched "
        "less closely than it appears to be.",
    ),
    "POL_PAY_CAME_BACK": (
        "In each of these the money has completed a round trip: it left "
        "the investor, passed through other hands, and came back.",
        "Nothing was bought and nothing was settled. What changed is the "
        "history the money carries, which is usually the reason for it.",
    ),
    "POL_PAY_PASSED_THROUGH": (
        "Each of these arrived from somebody who had just been paid by "
        "somebody who had just been paid.",
        "One party passing money on is ordinary. A chain of them puts "
        "distance between the money and whoever first sent it.",
    ),
    "POL_PAY_THIRD_PARTY": (
        "For each of these, the sender is not the investor who committed "
        "the capital.",
        "Third-party funding hides the real source of money, so it needs an "
        "explanation and usually documentary support.",
    ),
    "POL_PAY_UNKNOWN_SOURCE": (
        "Each of these arrived with nothing tying it to a known investor or "
        "capital call.",
        "Unattributed money should not sit in the fund unexplained.",
    ),
    "POL_PAY_OVERPAYMENT": (
        "Each of these payments is larger than the amount that was called.",
        "Usually this is an error or an early payment. Occasionally it is an "
        "attempt to place funds that need somewhere to sit.",
    ),
    "POL_PAY_UNEXPECTED_CURRENCY": (
        "Each of these arrived in a different currency than expected.",
        "Often administrative. Worth a note either way, since a change in "
        "payment route can be an early sign of something else.",
    ),
    "POL_ACTIVITY_OUTSIDE_LICENCE": (
        "Records show each of these carrying on an activity that its "
        "registration category may not cover.",
        "An entity may not carry on business outside its category without "
        "the Authority's prior approval. IFSCA has cancelled registrations "
        "and imposed penalties on this ground.",
    ),
    "POL_OFFICE_VACANT": (
        "Each of these is a required post that nobody currently holds.",
        "A required post left empty is one of the most common reasons an "
        "entity in GIFT City loses its registration. It is also the first "
        "thing an unannounced inspection looks for.",
    ),
    "POL_OFFICE_VACANT|FILLED": (
        "Each of these posts is recorded as filled, but the appointment has "
        "not yet been confirmed and reported to IFSCA.",
        "A post stays on this list until an appointment is complete — "
        "filled is not the same as confirmed.",
    ),
    "POL_OFFICE_NOT_BASED_IN_IFSC": (
        "For each of these, our records do not show the post holder as "
        "based in the IFSC.",
        "The rules require the principal officer and every key managerial "
        "person to be based out of the IFSC — not merely appointed, but "
        "there. IFSCA checks this by turning up unannounced, and has issued "
        "a warning to a fund management entity whose principal officer and "
        "key managerial personnel were absent on four such visits.",
    ),
    "POL_OWNERSHIP_CHANGED_AFTER_DILIGENCE": (
        "The ownership of each of these customers has changed since you "
        "finished checking them and set their risk category.",
        "A customer whose owners have changed is, for anti-money-laundering "
        "purposes, a different customer: the people you identified may no "
        "longer be there, and the category you set was against a structure "
        "that has since moved. Waiting for the scheduled review can mean "
        "waiting up to five years.",
    ),
    "POL_REVIEW_OVERDUE": (
        "Each of these customers was due to have their due diligence looked "
        "at again, and has not been.",
        "How often a customer must be reviewed is set by the risk category "
        "you gave them — every year for high risk, less often for the rest. "
        "A review that has lapsed means the customer is outside the "
        "scrutiny your own firm decided they needed, which is the first "
        "thing an inspection asks to see the record of.",
    ),
    "POL_FILING_OVERDUE": (
        "Each of these returns was due and has not been filed.",
        "Late returns are among the most common reasons IFSCA takes action. "
        "It usually begins with a warning letter.",
    ),
    "POL_FILING_REPEATEDLY_LATE": (
        "Each of these returns was due and has not been filed, and it is "
        "not the only one outstanding for that entity.",
        "A single lapse draws a warning; a pattern of them is what has cost "
        "entities in GIFT City their registration outright.",
    ),
    "POL_FILING_OVERDUE|FEE": (
        "Each of these fees was due and has not been paid.",
        "Late payments are among the most common reasons IFSCA takes "
        "action. It usually begins with a warning letter.",
    ),
    "POL_FILING_REPEATEDLY_LATE|FEE": (
        "Each of these fees was due and has not been paid, and it is not "
        "the only one outstanding for that entity.",
        "A single lapse draws a warning; a pattern of them is what has cost "
        "entities in GIFT City their registration outright.",
    ),
}

_ASK_INVESTOR = (
    "Ask each investor for a signed ownership declaration naming every "
    "individual who owns more than the threshold that applies to them, "
    "directly or through any other company.",
    "Ask for supporting evidence for whatever is provided — a register of "
    "members, a shareholding chart, or a trust deed.",
)

_FILE_THE_RETURN = (
    "File each return in the current format from the Downloads section of "
    "the IFSCA website — the formats were revised on 3 April 2025.",
    "If anything is blocking it, write to IFSCA and say so before they "
    "write to you. Silence is treated as non-cooperation and counts against "
    "you separately.",
    "Check whether any earlier period is also outstanding and file those at "
    "the same time.",
)

_PAY_THE_FEE = (
    "Pay the fee for each of these to IFSCA and keep the confirmation on "
    "file.",
    "If anything is blocking it, write to IFSCA and say so before they "
    "write to you. Silence is treated as non-cooperation and counts against "
    "you separately.",
    "Check whether any earlier year's fee is also unpaid and settle those "
    "at the same time.",
)

GROUP_ACTIONS = {
    "POL_SANCTIONS_HIT": (
        "Compare the date of birth, nationality and identity document "
        "number on each listed party against the documents the investor "
        "gave us.",
        "If it is the same party: do not accept money or proceed, and "
        "follow the asset-freezing procedure.",
        "If it is not: write down exactly which details you compared and "
        "why you are satisfied, then clear it.",
    ),
    "POL_PEP_HIT": (
        "Establish how each person built their wealth, and separately "
        "where the money for their investment came from. Get documents, "
        "not assertions.",
        "Obtain senior management approval before accepting the "
        "investment, and record who gave it.",
        "Set each relationship to be reviewed more often than a standard "
        "one.",
    ),
    "POL_ADVERSE_MEDIA": (
        "Read the reporting for each and decide whether it concerns that "
        "party and whether it is credible.",
        "If it is material, treat the relationship as higher risk and "
        "apply enhanced due diligence.",
        "Record your conclusion either way — including a decision that it "
        "is not material.",
    ),
    "POL_WATCHLIST_HIT_UNCLASSIFIED": (
        "Open each watchlist entry and establish what the list is and why "
        "the party is on it.",
        "Establish whether each is genuinely the same party, comparing the "
        "date of birth, nationality and identity document against the "
        "documents we hold.",
        "Record what you found and what you concluded, either way.",
    ),
    "POL_UBO_CYCLE": _ASK_INVESTOR + (
        "Ask each investor to explain the circular shareholding — there is "
        "sometimes a legitimate reason, and it should be on file.",
    ),
    "POL_UBO_INCOMPLETE": (
        "Work out, case by case, what is missing — a named party, the next "
        "link in an ownership chain, or the declaration itself — and "
        "request exactly that from the investor.",
        "Support whatever is provided with documentary evidence: a trust "
        "deed, a register of members, or a shareholding chart, not just a "
        "declaration.",
        "Continue until every branch ends at a named individual.",
    ),
    "POL_UBO_SENIOR_OFFICIAL_REQUIRED": (
        "Ask each investor who their senior managing official is.",
        "Collect that person's identity documents and record them as the "
        "beneficial owner, noting that this is the fallback position "
        "rather than an ownership finding.",
    ),
    "POL_UBO_NOT_DECLARED": _ASK_INVESTOR,
    "POL_PAY_SANCTIONED_PAYER": (
        "Do not apply this money to any investor's account or move it on.",
        "Establish whether the sender is genuinely the listed party.",
        "If it is, follow the freezing procedure and report it. If it is "
        "not, record what you compared.",
    ),
    "POL_PAY_STRUCTURING": (
        "Ask the investor why the payment was split.",
        "Check whether the same pattern has happened before with that "
        "investor.",
        "If no ordinary explanation holds up, prepare it for reporting.",
    ),
    "POL_PAY_THIRD_PARTY": (
        "Ask the investor who sent the money and what their relationship "
        "to it is.",
        "Check whether your fund documents permit third-party payments at "
        "all.",
        "If accepted, apply the same checks to the sender as you would to "
        "an investor.",
    ),
    "POL_PAY_UNKNOWN_SOURCE": (
        "Ask the bank for the full payment details including the sender.",
        "If it cannot be attributed, consider returning it to source "
        "rather than holding it.",
    ),
    "POL_PAY_OVERPAYMENT": (
        "Ask the investor to confirm the intended amount in writing.",
        "Agree whether to refund the excess or hold it against the next "
        "call, and record which.",
    ),
    "POL_PAY_UNEXPECTED_CURRENCY": (
        "Confirm with the investor that their payment arrangements have "
        "changed, and update their record.",
        "Check the converted amount still satisfies what was called.",
    ),
    "POL_ACTIVITY_OUTSIDE_LICENCE": (
        "Confirm whether the activity is actually being carried on, or "
        "whether the record is wrong.",
        "If it is being carried on, establish whether prior approval was "
        "obtained from IFSCA and put a copy on file.",
        "If there is no approval, stop the activity and take advice before "
        "resuming — this is the kind of thing that costs a registration.",
    ),
    "POL_OFFICE_VACANT": (
        "Appoint someone who meets the qualification and experience "
        "requirements and is based in GIFT City.",
        "Notify IFSCA of the appointment in the manner they specify — the "
        "appointment itself is not enough.",
        "Until each post is filled, make sure someone senior is present at "
        "the office and able to answer for the entity.",
    ),
    "POL_OFFICE_VACANT|FILLED": (
        "Confirm that each person has taken up the post and meets the "
        "qualification and experience requirements.",
        "Notify IFSCA of the appointment in the manner they specify — the "
        "appointment itself is not enough.",
        "Check that each of them is based in GIFT City, which an "
        "unannounced inspection will look for.",
    ),
    "POL_OFFICE_NOT_BASED_IN_IFSC": (
        "Confirm where each post holder is actually based and correct the "
        "record.",
        "If they are not based in GIFT City, either relocate them or "
        "appoint someone who is.",
        "Make sure the office is staffed and open during business hours — "
        "an inspection can happen on any working day.",
    ),
    "POL_OWNERSHIP_CHANGED_AFTER_DILIGENCE": (
        "Identify whoever now holds more than 10% of the customer, and "
        "confirm the people you identified before are still there.",
        "Set the risk category again once you have. The structure it was "
        "set against is not the structure the customer has now.",
    ),
    "POL_REVIEW_OVERDUE": (
        "Refresh what you hold on the customer — identification, ownership, "
        "and the purpose of the relationship — and check it is still what "
        "your records say.",
        "Set the risk category again once you have. Recording the review is "
        "what moves the next date; nothing here assumes it happened.",
    ),
    "POL_FILING_OVERDUE": _FILE_THE_RETURN,
    "POL_FILING_REPEATEDLY_LATE": _FILE_THE_RETURN,
    "POL_FILING_OVERDUE|FEE": _PAY_THE_FEE,
    "POL_FILING_REPEATEDLY_LATE|FEE": _PAY_THE_FEE,
}

#: Used only when a policy has no entry above *and* the items in the group
#: did not, coincidentally, all say exactly the same thing.
_GROUP_FALLBACK_BECAUSE = (
    "These are grouped together because they raise the same question, but "
    "each needs its own detail read before you decide.",
)
_GROUP_FALLBACK_ACTIONS = (
    "Open each file for the detail that applies to it before deciding.",
)


#: What is true of every file in the long-wait group, whatever rule opened
#: it. Deliberately says nothing about what any of them is about: the one
#: thing they share is the waiting.
AGED_BECAUSE = (
    "These were opened by different rules on different days, and none of "
    "them has been settled. What they have in common is the waiting.",
    "An alert nobody answered is the finding an inspector writes up, "
    "whatever it was originally about. The longer it sits, the harder it "
    "is to reconstruct what anyone knew at the time.",
)

AGED_ACTIONS = (
    "Work down this list oldest first, and open each file to see what it "
    "is about and which rule opened it.",
    "Settle what you can settle. If a file cannot be settled, pass it up "
    "so a second officer sees it — leaving it open is not a decision.",
)


def _group_text(key: str, items: Sequence[Item]) -> tuple[
    tuple[str, ...], tuple[str, ...]
]:
    """The shared explanation and shared next step for a whole group.

    Written once per policy and true of every item in it -- never one item's
    specific fact standing in for the rest. Falling back to an item's own
    words is only safe when every item in the group produced the identical
    words: that means it is genuinely universal, not a coincidence of being
    listed first.
    """
    if key == AGED:
        return AGED_BECAUSE, AGED_ACTIONS
    because = GROUP_BECAUSE.get(key)
    actions = GROUP_ACTIONS.get(key)
    if because is None:
        first = items[0].because
        because = first if all(i.because == first for i in items) else _GROUP_FALLBACK_BECAUSE
    if actions is None:
        first = items[0].to_close_this
        actions = first if all(i.to_close_this == first for i in items) else _GROUP_FALLBACK_ACTIONS
    return because, actions


def _latest(case: Case):
    """The most recent evidence a Case carries from its own policy.

    Evidence accumulates on an open Case, so its first line is the oldest
    thing anyone said about it. For most Cases that is the right thing to
    show. For a governance seat it is not: the refill attaches to the same
    Case as the vacancy, and reading line one means telling an officer a post
    is empty after somebody has been appointed to it.
    """
    policy = case.evidence[0].policy_id or ""
    mine = [e for e in case.evidence if (e.policy_id or "") == policy]
    return mine[-1] if mine else case.evidence[0]


def _resolved(case: Case) -> bool:
    """Whether the condition that opened this Case has since been met."""
    return bool(_latest(case).detail.get("resolved"))


#: The bucket that holds work which has waited past the last age band.
#: Not a policy: no rule produced it, and no clause is true of all of it.
AGED = "|WAITING"

AGED_URGENCY = "Waiting longest — clear these before anything else"


def _group_title(policy: str, count: int) -> str:
    # The fallback agrees with itself at one: it read "1 item need your
    # review" for any policy without its own title, which is the first
    # sentence a reader would see on a rule this file has not been taught
    # to name yet.
    from .whosework import STUCK as _STUCK
    from .whosework import WAITING as _WAITING

    if policy == _STUCK:
        return (f"{count} {_plural(count, 'file has', 'files have')} been "
                f"passed up by everybody who could settle "
                f"{_plural(count, 'it', 'them')}")
    if policy == _WAITING:
        # This used to end "and nobody else can settle it", which is an
        # exclusive claim the screen has no basis for: the same sentence was
        # shown to two officers at once about one file, and either of them
        # could have settled it. What is true is that it was passed up and is
        # now waiting for this reader.
        return (f"{count} {_plural(count, 'file was', 'files were')} passed "
                f"up and {_plural(count, 'is', 'are')} waiting for you")
    if policy == AGED:
        return (f"{count} {_plural(count, 'file has', 'files have')} been "
                f"waiting more than three months")
    template = GROUP_TITLE.get(policy, "{n} {item} {need} your review")
    return template.format(
        n=count,
        party=_plural(count, "party", "parties"),
        investor=_plural(count, "investor"),
        structure=_plural(count, "structure"),
        payment=_plural(count, "payment"),
        item=_plural(count, "item"),
        activity=_plural(count, "activity", "activities"),
        post=_plural(count, "post"),
        isare=_plural(count, "is", "are"),
        has=_plural(count, "has", "have"),
        filing=_plural(count, "filing is", "filings are"),
        fee=_plural(count, "fee is", "fees are"),
        letter=_plural(count, "letter"),
        document=_plural(count, "document"),
        customer=_plural(count, "customer"),
        # Verb agreement, so a group of one reads as English too.
        have=_plural(count, "has", "have"),
        need=_plural(count, "needs", "need"),
        look=_plural(count, "looks", "look"),
        were=_plural(count, "was", "were"),
        contain=_plural(count, "contains", "contain"),
    )


#: What each recognised column means, said the way its owner would say it.
IMPORT_MEANINGS = {
    "name": "the party's name",
    "first_name": "the first part of the name",
    "middle_name": "the middle part of the name",
    "last_name": "the last part of the name",
    "kind": "what each party is",
    "nationality": "nationality",
    "country_of_residence": "country of residence",
    "country_of_incorporation": "country of incorporation",
    "jurisdiction": "jurisdiction",
    "dob": "date of birth",
    "date_of_incorporation": "date of incorporation",
    "id_document_type": "identity document type",
    "id_document_number": "identity document number",
    "pan": "PAN",
    "cin": "CIN",
    "lei": "LEI",
    "customer_reference": "your own reference for the party",
    "owner_name": "who owns the party",
    "owner_share": "the owner's share",
    "commitment_amount": "the amount committed",
    "commitment_currency": "the commitment's currency",
    "fund": "the fund committed to",
    "payer": "who each payment came from",
    "amount": "the amount",
    "debit_amount": "money going out",
    "credit_amount": "money arriving",
    "direction": "whether money came in or went out",
    "currency": "the currency",
    "date": "each payment's date",
    "value_date": "the day the money took effect",
    "reference": "the bank's reference",
    "narration": "the bank's description",
}


def import_report(plan, digest: str, filename: str,
                  screening: bool = True) -> dict:
    """One spreadsheet's understanding report, everything in words.

    This is the page a person reads before the only write: what mapped,
    what was left alone, what would be rejected and why, and the one
    sentence of consequence the confirm button restates.
    """
    payments = plan.kind == "payments"
    rejected = plan.rejected_payments if payments else plan.rejected
    usable = len(plan.usable_payments) if payments else len(plan.usable)

    counts = {"usable": usable, "rejected": len(rejected)}
    if payments:
        counts["outgoing"] = len(plan.outgoing_payments)
    else:
        counts["commitments"] = sum(
            1 for r in plan.usable if r.commitment)
        counts["owners"] = sum(1 for r in plan.usable if r.owner)

    thing = "payment" if payments else "party"
    things = "payments" if payments else "parties"
    what = things if usable != 1 else thing

    if payments:
        consequence = (
            f"{usable} {what} will be written to the permanent record. "
            f"Every payer not already known will be registered"
            + (" and screened against the watchlists" if screening else "")
            + ", and money that broke a rule opens a file in your list."
        )
    else:
        consequence = (
            f"{usable} {what} will be written to the permanent record"
            + (", and each new one screened against the watchlists. "
               "Matches open files in your list." if screening else ". ")
        )
    if not screening:
        consequence += (
            " No watchlist is connected, so nothing will be screened; the "
            "records will be written and can be screened later."
        )
    if rejected:
        rows = _counted(len(rejected), "rejected row is", "rejected rows are")
        consequence += (
            f" The {rows} written nowhere; fix "
            f"{'it' if len(rejected) == 1 else 'them'} in the file and "
            f"import it again \u2014 what was already written will not be "
            f"duplicated."
        )

    return {
        "file": filename,
        "digest": digest,
        "kind": plan.kind,
        "reads_as": (
            f"This file reads as {things}: {usable} of "
            f"{_counted(len(plan.payments) if payments else len(plan.rows), 'row', 'rows')} "
            f"would be recorded."),
        "notes": [_sentence(note) for note in plan.notes],
        # Said as a fact rather than left for the browser to infer by
        # matching on the refusal's wording: a sentence is allowed to be
        # rewritten without silently disabling a button somewhere else.
        "undecided": any("Say which it is" in r for r in plan.refusals),
        "refusals": list(plan.refusals),
        "columns": [
            {"column": column,
             "meaning": IMPORT_MEANINGS.get(target,
                                            target.replace("_", " "))}
            for target, column in sorted(plan.mapped.items(),
                                         key=lambda kv: kv[1])
        ],
        "ignored": list(plan.ignored),
        "rejected": [
            {"row": row.number, "because": _sentence("; ".join(row.problems))}
            for row in rejected[:50]
        ],
        "rejected_more": (
            f"…and "
            f"{_counted(len(rejected) - 50, 'more row', 'more rows')}, for "
            f"the same kinds of reason." if len(rejected) > 50 else ""),
        "counts": counts,
        "consequence": consequence,
        "confirm_label": f"Record {usable} {what}",
    }


def _counted(count: int, one: str, many: str) -> str:
    """"1 party is" / "4 parties are" -- a number wearing real grammar."""
    return f"{count} {one if count == 1 else many}"


def import_receipt(counts: Mapping[str, int], kind: str,
                   screening: bool) -> str:
    """What the confirm actually did, as one paragraph."""
    if kind == "payments":
        written = counts.get("payments_recorded", 0)
        if not written and counts.get("already_recorded"):
            return (f"Nothing new was written: all "
                    f"{counts['already_recorded']} of these payments were "
                    f"already on the record.")
        parts = [_counted(written, "payment is", "payments are")
                 + " on the record."]
        if counts.get("payers_registered"):
            parts.append(_counted(counts["payers_registered"],
                                  "payer was registered as a party.",
                                  "payers were registered as parties."))
        if counts.get("already_recorded"):
            parts.append(f"{counts['already_recorded']} already on the "
                         f"record were not written twice.")
    else:
        if (not counts.get("registered") and not counts.get("committed")
                and counts.get("already_known")):
            return (f"Nothing new was written: all "
                    f"{counts['already_known']} of these parties were "
                    f"already known.")
        parts = [_counted(counts.get("registered", 0),
                          "party is", "parties are") + " on the record."]
        if counts.get("committed"):
            parts.append(_counted(counts["committed"],
                                  "commitment was", "commitments were")
                         + " recorded.")
        if counts.get("ownership_declared"):
            parts.append(_counted(counts["ownership_declared"],
                                  "ownership declaration was",
                                  "ownership declarations were")
                         + " recorded.")
        if counts.get("already_known"):
            parts.append(f"{counts['already_known']} already known were "
                         f"not written twice.")
    if screening:
        parts.append("Screening against the watchlists has begun; matches "
                     "will appear in your list.")
    return " ".join(parts)


def import_progress(progress: Mapping[str, Any]) -> str:
    """The screening run so far, as the sentence a reader checks."""
    done = progress.get("done", 0)
    total = progress.get("total", 0)
    matches = progress.get("matches", 0)
    state = progress.get("state", "")
    # A payments sheet screens the payers it registered, not "parties" in
    # general, and a reader who just uploaded a statement should be told
    # which of the two they are watching.
    payments = progress.get("kind") == "payments"
    who = "payers" if payments else "parties"
    one_of_them = "payer" if payments else "party"
    hits = (_counted(matches, "possible match", "possible matches")
            if matches else "no matches")

    if not total:
        return ("Everybody in this file was already known, so there was "
                "nobody new to screen.")
    if state == "running":
        return f"Screened {done} of {total} {who} so far: {hits}."
    if state == "finished":
        tail = ""
        if matches:
            tail = (" It is in your list." if matches == 1
                    else " They are in your list.")
        opened = (f"The one new {one_of_them} was screened" if total == 1
                  else f"All {total} were screened")
        return f"{opened}: {hits}.{tail}"
    if state == "skipped":
        return ("The records were written. No watchlist is connected to "
                "this workspace, so nothing was screened \u2014 whoever "
                "set it up can connect one, and these records can be "
                "screened afterwards.")
    if state == "stopped":
        return (f"Screening stopped after {done} of {total}, because the "
                f"watchlist service stopped answering. What was screened "
                f"is on the record; the rest can be screened again later.")
    return ""


#: When money arrives that cannot be attributed, there is no name to show.
#: Printing the internal record id would be the worst of both worlds: it tells
#: the reader nothing and looks like a name.
UNKNOWN_SENDER = "An unidentified sender"
UNKNOWN_PARTY = "An unidentified party"


def describer(graph):
    """Name an entity, or say plainly that we cannot."""

    def describe(entity_id: str, case_type: str = "") -> str:
        if entity_id in graph.entities:
            return graph.name_of(entity_id)
        return UNKNOWN_SENDER if case_type == "PAYMENT_MISMATCH" else UNKNOWN_PARTY

    return describe


def _line(case: Case, detail: Mapping[str, Any], who: str) -> str:
    """The item as one line, for when the group has already explained why."""
    if case.case_type == "PAYMENT_MISMATCH":
        # The bank reference is not jargon -- it is how they will find this
        # payment in the bank portal.
        reference = detail.get("payment_ref")
        tail = f", reference {reference}" if reference else ""
        return (
            f"{who} — {_money(detail.get('amount'), detail.get('currency'))} "
            f"received {_date(case.opened_at)}{tail}"
        )
    if case.case_type == "UBO_REVIEW":
        return f"{who} — raised {_date(case.opened_at)}"
    return f"{who} — flagged {_date(case.opened_at)}"


def _rules_for(case: Case) -> tuple[Rule, ...]:
    seen: dict[str, Rule] = {}
    for evidence in case.evidence:
        for citation in evidence.citations:
            clause_id = citation["clause"]
            if clause_id in seen:
                continue
            registered = CLAUSES.get(clause_id)
            seen[clause_id] = Rule(
                clause=clause_id,
                document=citation["document"],
                says=PLAIN_RULES.get(clause_id, citation["heading"]),
                quote=citation["extract"],
                link=citation["url"],
                link_text=f"Read clause {clause_id} in the published guidelines",
                checked_by_a_person=bool(citation["verified"]),
                caution=None if citation["verified"] else UNVERIFIED_CAUTION,
            )
    return tuple(seen.values())


def _about(case: Case, detail: Mapping[str, Any], describe) -> str:
    if case.case_type == "UBO_REVIEW":
        return f"Ownership question raised on {_date(case.opened_at)}"
    if case.case_type == "PAYMENT_MISMATCH":
        fund = describe(detail["fund"]) if detail.get("fund") else None
        received = _date(case.opened_at)
        return (
            f"Payment received {received}" + (f" for {fund}" if fund else "")
        )
    return f"Raised on {_date(case.opened_at)}"


# ---------------------------------------------------------------------------
# The comparison, and the suggestion built on top of it
# ---------------------------------------------------------------------------

OURS_LABEL = "What we hold"
THEIRS_LABEL = "What the list says"

NOT_ON_FILE = "Not on file"
NOT_ON_THE_LIST = "Not on the list entry"

#: Comparison verdicts, as a colour hint. The sentence a person reads is the
#: note, which is written by the comparison itself.
TONE_OF = {
    "IDENTICAL": "same",
    "EQUIVALENT": "same",
    "PARTIAL": "close",
    "DIFFERENT": "differs",
    "UNKNOWN": "unknown",
}

#: What a recommendation means, in the only words that should appear on screen.
#: Deliberately hedged: the assistant has seen two records, not a person.
VERDICTS = {
    "LIKELY_NOT_THE_SAME": (
        "On the details we hold, these look like two different parties."
    ),
    "POSSIBLY_THE_SAME": (
        "On the details we hold, this could be the same party."
    ),
    "CANNOT_TELL": (
        "There is not enough on file to tell these apart either way."
    ),
}

SUGGESTION_HEADING = "A suggested starting point"

SUGGESTION_CAVEAT = (
    "This was prepared automatically from the two records above, before you "
    "opened the file. It is a starting point for your own review, not a "
    "decision and not advice, and it can be wrong. Nothing has been recorded "
    "and nothing happens until you decide."
)

WORDING_LABEL = "Wording you could use, if you agree with it"
CHECKS_LABEL = "It suggests confirming these before you decide"
USE_LABEL = "Use this wording"
OWN_LABEL = "Write my own"

SUGGESTION_RECORDED = (
    "Whether you used this wording, changed it, ignored it, or decided the "
    "other way is recorded with your decision — so that how much this helps, "
    "and how often it is wrong, can be shown to your auditor."
)


#: Rows whose values are country codes rather than words.
_COUNTRY_ROWS = {"nationality", "country"}


def _side(value: str, absent: str, what: str = "") -> str:
    """One side of one row, as a person reads it.

    Two translations happen here and nowhere else. A date becomes a date they
    would say aloud, and a country code becomes a country -- because a screen
    that puts ``SG`` beside ``cn`` has handed the officer a puzzle instead of
    a comparison.
    """
    value = (value or "").strip()
    if not value:
        return absent
    if what.strip().lower() in _COUNTRY_ROWS:
        return country_name(value)
    shown = _date(value)
    return shown if shown != value else value


def _sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "?", "!")) else text + "."


def side_by_side(comparison: Optional[Mapping[str, Any]]) -> tuple[Line, ...]:
    """The computed comparison, as a person reads it.

    Takes the recorded form -- a plain mapping off the log -- rather than a
    ``Comparison`` object, so that what is shown is exactly what was written
    down at the time, not a recomputation of it.
    """
    if not comparison:
        return ()
    lines = []
    for entry in comparison.get("fields") or ():
        verdict = str(entry.get("verdict") or "UNKNOWN")
        what = str(entry.get("field") or "")
        lines.append(Line(
            what=_sentence(what).rstrip("."),
            ours=_side(str(entry.get("ours") or ""), NOT_ON_FILE, what),
            theirs=_side(str(entry.get("theirs") or ""), NOT_ON_THE_LIST, what),
            says=_sentence(str(entry.get("note") or "")),
            tone=TONE_OF.get(verdict, "unknown"),
        ))
    return tuple(lines)


def suggestion_for(case: Case) -> Optional[Suggestion]:
    """The prepared draft on a Case, or nothing at all.

    Nothing at all is the ordinary case: no model configured, no budget left,
    a draft that was rejected for inventing a figure. The file reads exactly
    as it would have without any of this.
    """
    draft = case.draft
    if not draft:
        return None
    verdict = VERDICTS.get(str(draft.get("recommendation") or ""))
    reasoning = _sentence(str(draft.get("reasoning") or ""))
    wording = str(draft.get("suggested_wording") or "").strip()
    if not verdict or not reasoning or not wording:
        return None
    return Suggestion(
        heading=SUGGESTION_HEADING,
        caveat=SUGGESTION_CAVEAT,
        verdict=verdict,
        reasoning=reasoning,
        wording_label=WORDING_LABEL,
        wording=wording,
        checks_label=CHECKS_LABEL,
        checks=tuple(_sentence(str(c)) for c in (draft.get("checks") or ()) if c),
        use_label=USE_LABEL,
        own_label=OWN_LABEL,
        recorded_as=SUGGESTION_RECORDED,
    )


@dataclass(frozen=True)
class ReasonChoice:
    """One reason an officer can pick, tied to the decision it belongs to.

    ``when`` and ``code`` are machine values; ``label`` is what the reader
    sees. The codes exist because a free-text box alone permits the one-word
    closures examiners name as a paper control, and because reasons that
    cannot be counted cannot be reviewed. The written reason stays required
    regardless of what is picked.
    """

    when: str
    code: str
    label: str


#: The reasons that settle a name check, drawn from the checklist OFAC
#: publishes for exactly this decision. "Another reason" is always present:
#: a fixed list that claims to be exhaustive teaches people to pick the
#: nearest wrong answer.
SCREENING_REASONS = (
    ReasonChoice("APPROVE", "different-birth", "Different date of birth"),
    ReasonChoice("APPROVE", "different-country",
                 "Different nationality or country"),
    ReasonChoice("APPROVE", "different-papers",
                 "Different identity documents"),
    ReasonChoice("APPROVE", "partial-name", "Only part of the name matches"),
    ReasonChoice("APPROVE", "wrong-kind",
                 "The listed party is a different kind of entity"),
    ReasonChoice("APPROVE", "another-reason", "Another reason, written below"),
    ReasonChoice("REJECT", "same-party", "Confirmed as the same party"),
    ReasonChoice("REJECT", "another-reason", "Another reason, written below"),
    ReasonChoice("ESCALATE", "needs-senior", "Needs a more senior decision"),
    ReasonChoice("ESCALATE", "cannot-resolve",
                 "The record cannot resolve it either way"),
    ReasonChoice("ESCALATE", "another-reason", "Another reason, written below"),
)


#: The codes each outcome offers, by outcome. Derived from the list above
#: rather than typed again, so the server cannot come to accept a code the
#: screen never offers. It did: ``same-party`` is the REJECT-only code
#: captioned "Confirmed as the same party", and it was accepted and recorded
#: against an APPROVE; so was ``i-invented-this-code``, and so was a
#: 200-character string, silently cut to forty.
REASON_CODES = {
    outcome: frozenset(choice.code for choice in SCREENING_REASONS
                       if choice.when == outcome)
    for outcome in {choice.when for choice in SCREENING_REASONS}
}


#: Below this many days, a file is simply work in hand and saying how
#: long it has been open adds nothing. Above it, the wait is the fact.
SAY_THE_WAIT_AFTER = 7


def waited_for(case: Case, today: str) -> str:
    """"waiting 214 days" -- or nothing, for a file still in its first week."""
    if not today:
        return ""
    days = days_between(str(case.opened_at)[:10], today)
    if days is None or days < SAY_THE_WAIT_AFTER:
        return ""
    return f"waiting {days:,} days"


def item_for(case: Case, describe, reference: str, today: str = "") -> Item:
    """Render one Case as a person reads it."""
    reasons = SCREENING_REASONS if case.case_type == "SCREENING_HIT" else ()
    evidence = case.evidence[0]
    # A governance Case is read from its *latest* evidence, not its first.
    # A seat that has been refilled attaches to the Case already open for the
    # vacancy -- deliberately, so the file reads as the whole story -- but the
    # first evidence line still says the seat is empty. Rendering that line
    # told a Principal Officer they had no compliance officer while the log
    # showed one appointed, in the record that goes to IFSCA. Only the
    # governance writer distinguishes the two, so only it looks forward.
    # A regulator's letter reads the same way, and for the same reason: the
    # answer attaches to the file that says none arrived, and the first
    # evidence line goes on saying nothing was sent. That sentence reached
    # the queue, the case page and the evidence pack, twelve days after the
    # answer went.
    if case.case_type in ("GOVERNANCE", "NOTICE"):
        evidence = _latest(case)
    detail = evidence.detail
    policy = evidence.policy_id or ""
    who = describe(case.subject, case.case_type)
    writer = WRITERS.get(case.case_type)
    headline, because, actions = (
        writer(case, detail, who, policy, describe)
        if writer
        else (f"{who} needs review", (), ())
    )
    recorded = (case.draft or {}).get("comparison") or {}
    lines = side_by_side(recorded)
    return Item(
        corroboration=_sentence(str(recorded.get("corroboration") or "")),
        reference=reference,
        line=_line(case, detail, who),
        kind=KIND.get(case.case_type, "Review"),
        urgency=URGENCY[case.severity],
        who=who,
        about=_about(case, detail, describe),
        headline=headline,
        because=tuple(because),
        to_close_this=tuple(actions),
        rules=_rules_for(case),
        choices=CHOICES,
        reasons=reasons,
        waiting=waited_for(case, today) if case.is_open else "",
        recorded_as=RECORDED,
        side_by_side=lines,
        ours_label=OURS_LABEL if lines else "",
        theirs_label=THEIRS_LABEL if lines else "",
        suggestion=suggestion_for(case),
        case_id=case.case_id,
    )


#: The hours each greeting covers. Local to whoever is reading, which is the
#: only clock that matters here: the officer is looking at their own screen.
GREETINGS = ((12, "Good morning"), (17, "Good afternoon"), (24, "Good evening"))


def greet(hour: int) -> str:
    for until, words in GREETINGS:
        if hour < until:
            return words
    return "Good evening"


def brief(engine, person: str, today: Optional[str] = None,
          per_group: int = 6, expand: Optional[str] = None,
          hour: Optional[int] = None) -> Briefing:
    """The whole morning, for one person, grouped by the question being asked.

    ``hour`` arrives from the boundary alongside ``today``, for the same
    reason: the core does not read a clock. It said "Good morning" at every
    hour of the day, which is a small lie on the first line of a screen whose
    argument is that it does not tell them.
    """
    today = today or date.today().isoformat()
    hour = datetime.now().hour if hour is None else hour
    describe = describer(engine.state.graph)
    queue = engine.queue()

    # Files that have waited past the last age band come out of their rule
    # groups and into one group of their own, at the top. Left where they
    # were, a file from 2018 sat 158th inside a group that shows six -- past
    # the fold of a page nobody scrolls, under a heading about payments
    # rather than about the two years it had been waiting. Its rule has not
    # changed and neither has its severity; only where a person meets it.
    long_wait = AGE_BANDS[-1][0]

    # Whose desk this is. Four people used to see one list in one order,
    # which meant three of them were reading somebody else's morning.
    from .whosework import (STUCK, WAITING, WHAT_YOURS_IS_FOR, rank_of, stuck,
                            waiting_on)

    entry = engine.state.actors.get(person) or {}
    role = entry.get("role")

    buckets: dict[str, list[Case]] = {}
    for case in queue:
        # Work blocked on this particular reader comes first, above even
        # the oldest files. For everybody else on the book it is simply
        # not their problem, and for this reader nothing else can move
        # until they look.
        if role is not None and waiting_on(case, person, role):
            buckets.setdefault(WAITING, []).append(case)
            continue
        # Above everything, and on everybody's screen: a file passed up by
        # every person who could settle it is waiting on nobody, and until it
        # had a group of its own it sat in the ordinary band unmarked.
        if stuck(case, engine.state.actors):
            buckets.setdefault(STUCK, []).append(case)
            continue
        waited = days_between(str(case.opened_at)[:10], today)
        if waited is not None and waited >= long_wait:
            buckets.setdefault(AGED, []).append(case)
            continue
        # Money and paperwork do not belong in one group. Both overdue-filing
        # policies cover returns and fees alike, and a group shows only the
        # first item's explanation and actions -- so a fee sorted to the front
        # made "file a return in the Downloads format" the sole instruction
        # for a group of overdue returns, and vice versa. Splitting the bucket
        # keeps each group's shared text true of everything in it.
        policy = case.evidence[0].policy_id or ""
        key = policy
        if case.case_type == "FILING":
            obligation = case.evidence[0].detail.get("obligation")
            if obligation in _FEE_OBLIGATIONS:
                key = f"{policy}|FEE"
        elif case.case_type == "GOVERNANCE" and _resolved(case):
            # Same reason: the group heading and its shared text come from one
            # item, and "unfilled" is not true of a seat somebody now holds.
            key = f"{policy}|FILLED"
        buckets.setdefault(key, []).append(case)

    groups = []
    counters: dict[str, int] = {}
    for key, cases in sorted(
        buckets.items(),
        # Nothing in a compliance list outranks work that has been sitting
        # for months, so that group sorts above every rule regardless of
        # what the rules themselves say about severity.
        # Three bands, then the ordinary order inside each. Work waiting
        # on this reader, then files that have sat for months, then
        # everything else ordered by what this particular job looks at
        # first. Nothing is removed from anybody's list -- a screen that
        # showed senior management less would have decided on their behalf
        # what is beneath them.
        key=lambda kv: (rank_of(kv[0], role, AGED),
                        -kv[1][0].severity.rank, -len(kv[1]))
    ):
        lead = cases[0]
        kind = KIND.get(lead.case_type, "Review")
        # The group the reader asked to see in full is rendered in full.
        # Everything else is capped, so a queue of two hundred files does not
        # arrive as one page.
        if key == AGED:
            # Oldest first inside the group too, whatever each file is
            # about: the reader is working down a queue by age here, not
            # by rule.
            cases = sorted(cases, key=lambda c: (str(c.opened_at),
                                                 c.opened_seq))
        shown = cases if key == expand else cases[:per_group]
        items = []
        for case in shown:
            counters[kind] = counters.get(kind, 0) + 1
            items.append(item_for(case, describe, f"{kind} {counters[kind]}",
                                  today=today))
        hidden = len(cases) - len(items)
        group_because, group_actions = _group_text(key, items)
        groups.append(
            Group(
                title=_group_title(key, len(cases)),
                urgency=(AGED_URGENCY if key == AGED
                         else URGENCY[lead.severity]),
                tone="stop" if key == AGED else TONE[lead.severity],
                because=group_because,
                to_close_this=group_actions,
                # Files here were opened under different rules, so there is
                # no clause true of all of them. Each carries its own on its
                # own page, where it belongs.
                rules=() if key == AGED else items[0].rules,
                items=tuple(items),
                total=len(cases),
                # Says what is true. This read "and N more of the same, shown
                # when you open this", and opening the group showed the same
                # six -- the promise was kept nowhere in the codebase, and 120
                # of 195 open files were unreachable while the screen told the
                # officer otherwise. In a product whose whole claim is that the
                # screen and the regulator's file cannot drift apart, that
                # sentence was the most damaging thing on it.
                more=(
                    f"Showing {len(items)} of {len(cases)}."
                    if hidden
                    else ""
                ),
                show_all=f"Show all {len(cases)}" if hidden else "",
                ref=key,
            )
        )

    stopped = sum(1 for c in queue if c.severity is Severity.CRITICAL)
    headlines = []
    if stopped:
        headlines.append(
            f"{stopped} {_plural(stopped, 'thing needs', 'things need')} to stop "
            f"until you clear {'it' if stopped == 1 else 'them'}"
        )
    today_count = sum(1 for c in queue if c.severity is Severity.HIGH)
    if today_count:
        headlines.append(f"{today_count} {_plural(today_count, 'file needs', 'files need')} you today")
    week = len(queue) - stopped - today_count
    if week:
        headlines.append(f"{week} can wait until later this week")

    coming = []
    licence = engine.state.licence
    if licence.granted_on:
        from .licence import principal_officers

        for item in instances(licence.granted_on, today,
                              engine.state.calendar.submitted,
                              principal_officers(licence)):
            state = item.status(today)
            if state not in (Status.UPCOMING, Status.DUE_SOON):
                continue  # overdue items are Cases, not reminders
            days = (_d(item.due_on) - _d(today)).days
            coming.append(Due(
                what=f"{item.schedule.label} for {item.period}",
                when=(f"due {_date(item.due_on)} — "
                      f"{days} {_plural(days, 'day')} from now"),
                pressing=state is Status.DUE_SOON,
            ))

    # ``is_open`` rather than a status comparison: an escalated file has
    # left the OPEN status but not the queue, and counting it as settled
    # told an officer that a file nobody has answered was finished.
    settled = sum(
        1 for c in engine.state.casebook.cases.values() if not c.is_open
    )

    kinds: dict[str, int] = {}
    for case in queue:
        label = KIND.get(case.case_type, "Review")
        kinds[label] = kinds.get(label, 0) + 1
    busiest = max(kinds.values(), default=0)
    bands = band_by_age(queue, today)
    widest = max((count for _, count, _ in bands), default=0)
    oldest = max((age for _, count, age in bands if count), default=0)
    # Marked by the band's own lower bound, never by a word in its label:
    # "Between one and three months old" reads as urgent to a substring
    # test and is not, and colouring it claret cried wolf on the one band
    # that should mean something.
    ageing = tuple(
        Ageing(label=label, count=count,
               share=(count / widest) if widest else 0.0,
               tone=("stop" if count and low >= 91 else "plain"))
        for (low, _, _), (label, count, _) in zip(AGE_BANDS, bands)
    )
    ageing_note = ""
    if oldest > 0:
        waited = "1 day" if oldest == 1 else f"{oldest:,} days"
        ageing_note = f"The oldest open file has been waiting {waited}."
    elif queue:
        ageing_note = "Everything open was opened today."

    # Who has never been checked at all. The clean checks are the
    # deliverable, so the gap in them is the number worth a place here.
    checked = {
        event.subject for event in engine.log
        if str(event.event_type) == "SCREENING_COMPLETED"
    }
    unchecked = sum(1 for entity_id in engine.state.graph.entities
                    if entity_id not in checked)

    # Letters from the regulator. Deliberately shown whether or not any is
    # late: the failure this answers is that nothing happens when one is
    # ignored, so the only defence is that it stays in front of somebody.
    from .correspondence import how_long_left, who_sent_it

    open_letters = engine.state.correspondence.open_notices()
    waiting = tuple(
        Waiting(
            reference=notice.reference,
            who=who_sent_it(notice.from_whom),
            about=notice.about,
            clock=how_long_left(notice, today),
            tone=("stop" if (notice.days_left(today) or 0) < 0
                  else "today" if (notice.days_left(today) is not None
                                   and notice.days_left(today) <= 7)
                  else "plain"),
        )
        for notice in open_letters
    )
    waiting_heading = ("Letters from a regulator waiting for an answer"
                       if waiting else "")
    undated = sum(1 for notice in open_letters
                  if notice.days_left(today) is None)
    waiting_note = ""
    if undated:
        waiting_note = (
            f"{_counted(undated, 'letter set', 'letters set')} no date. "
            f"Nothing here can tell you when {'it is' if undated == 1 else 'they are'} "
            f"late, so somebody has to decide what is reasonable."
        )

    dashboard = Dashboard(
        stats=(
            Stat("Files open", str(len(queue))),
            Stat("Stop and clear first", str(stopped), "stop"),
            Stat("Need you today", str(today_count), "today"),
            Stat("Never checked", str(unchecked),
                 "stop" if unchecked else "good"),
            Stat("Already settled", str(settled), "good"),
        ),
        ageing_heading="How long the open files have been waiting",
        ageing=ageing,
        ageing_note=ageing_note,
        workload_heading="What the open files are about",
        workload=tuple(
            Workload(label=label, count=count, share=count / busiest)
            for label, count in sorted(kinds.items(), key=lambda kv: -kv[1])
        ),
        deadlines_heading="Coming up",
        waiting_heading=waiting_heading,
        waiting=waiting,
        waiting_note=waiting_note,
    )

    return Briefing(
        greeting=f"{greet(hour)}, {person}. Here is {_date(today)}.",
        headlines=tuple(headlines),
        coming_up=tuple(coming[:6]),
        ordered_for=WHAT_YOURS_IS_FOR.get(role, ""),
        dashboard=dashboard,
        nothing_needed=(
            f"{settled} {_plural(settled, 'file has', 'files have')} already been "
            f"settled and {_plural(settled, 'needs', 'need')} nothing further from you."
            if settled
            else "Nothing has been settled yet — this is the full list."
        ),
        groups=tuple(groups),
        assurance=ASSURANCE,
    )


# ---------------------------------------------------------------------------
# How the assistant is doing
# ---------------------------------------------------------------------------

#: Azure region identifiers, as a place a person recognises.
REGION_NAMES = {
    "centralindia": "India (Central)",
    "southindia": "India (South)",
    "westindia": "India (West)",
    "jioindiacentral": "India (Central)",
    "jioindiawest": "India (West)",
}


@dataclass(frozen=True)
class Score:
    """One number, what it is called, and what it means."""

    label: str
    value: str
    meaning: str
    #: Machine hint for colour: good, watch, bad, plain. Never shown.
    tone: str = "plain"


@dataclass(frozen=True)
class Report:
    """The assistant's own record, for the person who is accountable for it."""

    heading: str
    standing: str
    caution: str
    scores: tuple[Score, ...]
    spend: str
    prepared_where: str
    gap: str
    recorded_as: str


def _rate(value: float) -> str:
    return f"{value * 100:.0f}%"


def report(quality) -> Report:
    """Turn the counted quality numbers into sentences.

    Written for a Principal Officer who has to defend using this at all. The
    honest number goes first and the flattering one second, because the other
    way round is how a dashboard becomes a liability.
    """
    decided = quality.decided
    if not quality.prepared:
        standing = (
            "No suggestions have been prepared yet. Every file so far has been "
            "reviewed and written up entirely by your team."
        )
    elif not decided:
        standing = (
            f"{quality.prepared} "
            f"{_plural(quality.prepared, 'suggestion has', 'suggestions have')} "
            f"been prepared and "
            f"{_plural(quality.prepared, 'it has not been decided yet', 'none of them decided yet')}, "
            f"so there is nothing to judge "
            f"{_plural(quality.prepared, 'it', 'them')} by."
        )
    elif quality.contradicted:
        standing = (
            f"On {quality.contradicted} of {decided} decided "
            f"{_plural(decided, 'file', 'files')}, your officer decided the "
            f"opposite of what was suggested. Read "
            # Plural of *contradicted*, not of *decided* -- this clause is
            # about the files the officer overruled, not the whole decided
            # pool. Five decided and one contradicted must read "that file",
            # not "those files"; the earlier version pluralised on decided and
            # got it right only when the two counts happened to be equal.
            f"{_plural(quality.contradicted, 'that file', 'those files')}: "
            f"either the suggestion was wrong, or the officer was, and you "
            f"need to know which."
        )
    else:
        standing = (
            f"On {_plural(decided, 'the one', f'all {decided}')} decided "
            f"{_plural(decided, 'file', 'files')}, your officer's decision "
            f"agreed with what was suggested. No suggestion has been "
            f"overruled."
        )

    caution = (
        ""
        if quality.trustworthy or not decided
        else (
            f"These proportions rest on {decided} decided "
            f"{_plural(decided, 'file', 'files')}. That is too few to quote to "
            f"anyone as a measure of reliability; treat them as early signs."
        )
    )

    scores = (
        Score(
            "Decided against the suggestion",
            f"{quality.contradicted} of {decided}" if decided else "Nothing yet",
            "Your officer read it and went the other way. The number that "
            "matters most, and the one to explain if it grows.",
            "bad" if quality.contradicted else "good",
        ),
        Score(
            "Wording used, as written or edited",
            _rate(quality.acceptance_rate) if decided else "Nothing yet",
            "How often the suggested wording ended up in the permanent record, "
            "in your officer's own decision.",
            "plain",
        ),
        Score(
            "Wording set aside",
            f"{quality.rejected} of {decided}" if decided else "Nothing yet",
            "Your officer read it, agreed with where it landed, and still "
            "preferred their own words.",
            "plain",
        ),
        Score(
            "Waiting on a person",
            str(quality.waiting),
            "Files with a suggestion prepared that nobody has decided yet. "
            "A suggestion never closes anything on its own.",
            "watch" if quality.waiting else "plain",
        ),
    )

    spend = (
        f"US$ {quality.spend_usd:,.2f} spent of the "
        f"US$ {quality.budget_usd:,.2f} allowed, across "
        f"{quality.prepared} {_plural(quality.prepared, 'suggestion')}. "
        f"Drafting stops on its own when the allowance is used up, and the "
        f"rest of the system carries on unaffected."
    )

    places = _join(sorted({REGION_NAMES.get(r, r) for r in quality.regions}))
    prepared_where = (
        f"Every suggestion was prepared inside {places}. Investor details are "
        f"not sent outside India, and a reply served from anywhere else is "
        f"refused rather than shown."
        if places
        else "No suggestion has been prepared, so nothing has been sent anywhere."
    )

    gap = (
        "One thing this cannot tell you. When a suggestion states a date or a "
        "number it was never given, it is destroyed before anyone sees it and "
        "nothing is written down — which keeps invented details out of your "
        "permanent record, but also means the number of times that happened is "
        "not counted here yet."
    )

    return Report(
        heading="How the assistant is doing",
        standing=standing,
        caution=caution,
        scores=scores,
        spend=spend,
        prepared_where=prepared_where,
        gap=gap,
        recorded_as=(
            "Every figure on this page is counted from the same permanent "
            "record as your files. There is no separate tally that could "
            "disagree with it."
        ),
    )


# ---------------------------------------------------------------------------
# One file, in full
# ---------------------------------------------------------------------------

#: Who did a thing, as a person would say it. ``system`` and ``assistant`` are
#: actor strings on the log, not names, and printing them raw would put
#: implementation vocabulary in the one place an officer looks hardest.
ACTOR_NAMES = {
    "system": "Recorded automatically",
    "assistant": "The assistant",
}

#: Evidence kinds, as the reader meets them on a timeline.
MOMENT_KIND = {
    "RULE": "A rule fired",
    "FACT": "Something was observed",
    "DECISION": "A person decided",
    "SUGGESTION": "A suggestion was prepared",
}


@dataclass(frozen=True)
class Moment:
    """One entry on a file's timeline."""

    when: str
    kind: str
    what: str
    who: str
    #: Machine hint for colour. Never shown as text.
    tone: str


@dataclass(frozen=True)
class CaseFile:
    """Everything recorded about one file, on one page.

    The queue answers "what needs me". This answers "why does this need me,
    and what has happened to it" -- which is the question an officer is
    actually accountable for, and the one an inspector asks first. Nothing
    here is new information: it is the same Case the queue renders, with its
    evidence unrolled in the order it was recorded.
    """

    reference: str
    kind: str
    urgency: str
    tone: str
    who: str
    about: str
    headline: str
    because: tuple[str, ...]
    to_close_this: tuple[str, ...]
    rules: tuple[Rule, ...]
    side_by_side: tuple[Line, ...]
    ours_label: str
    theirs_label: str
    suggestion: Optional[Suggestion]
    timeline_heading: str
    timeline: tuple[Moment, ...]
    to_close_heading: str
    settled: str
    decided_heading: str
    choices: tuple[Choice, ...]
    recorded_as: str
    back: str
    reasons: tuple = ()
    #: The strongest single agreement in the comparison, where there is one.
    corroboration: str = ""
    #: Filled when this file has been passed up and now needs a different
    #: officer. The queue keeps the file; this sentence says why it is back.
    escalated: str = ""
    #: Machine addresses, like ``Item.case_id``. Never displayed.
    case_id: str = ""
    subject: str = ""


def _moment_who(actor: str) -> str:
    return ACTOR_NAMES.get(actor, actor)


def _moment_what(case: Case, evidence, first: bool) -> str:
    """What happened, in words, without quoting the record at the reader.

    ``Evidence.summary`` is internal record text -- "SANCTIONS match for Kavya
    Singh", "A suggestion was prepared: LIKELY_NOT_THE_SAME". It has never
    reached a screen before, because the queue renders a writer's headline
    rather than the evidence itself, and printing it here would put screaming
    constants on the one page an officer reads hardest. So the timeline says
    what kind of thing happened and under which clause, and leaves the detail
    to the headline and the panels above it.
    """
    kind = str(evidence.kind)
    what = KIND.get(case.case_type, "review").lower()
    clauses = [c["clause"] for c in (evidence.citations or ())]
    under = f" under clause {_join(clauses)}" if clauses else ""

    if kind == "SUGGESTION":
        return "A suggestion was prepared for the officer to consider."
    if kind == "DECISION":
        if str(evidence.summary or "").startswith("ESCALATE"):
            return "A person passed this file up for a more senior decision."
        return "A person settled this file."
    if kind == "RULE":
        return (f"This {what} was opened{under}." if first
                else f"More was recorded on this {what}{under}.")
    return f"Something was observed on this {what}{under}."


def _timeline(engine, case: Case) -> tuple[Moment, ...]:
    """Every piece of evidence on a Case, in the order it was recorded.

    Dates and actors come from the events the evidence points back at --
    ``source_seq`` exists for exactly this, so "why does this file say that"
    is answerable by reading one row of the log. Evidence whose source event
    cannot be found still appears, dated from the Case: a gap in the
    chronology would be a worse lie than an undated line.
    """
    wanted = {e.source_seq for e in case.evidence}
    when_by_seq = {
        event.seq: (event.occurred_at, event.actor)
        for event in engine.log if event.seq in wanted
    }

    moments = []
    for position, evidence in enumerate(case.evidence):
        occurred, actor = when_by_seq.get(
            evidence.source_seq, (case.opened_at, "system")
        )
        kind = str(evidence.kind)
        moments.append(Moment(
            when=_date(occurred),
            kind=MOMENT_KIND.get(kind, "Something happened"),
            what=_moment_what(case, evidence, position == 0),
            who=_moment_who(actor),
            tone=kind.lower(),
        ))
    return tuple(moments)


def case_file(engine, case_id: str, today: Optional[str] = None) -> CaseFile:
    """One Case, rendered in full. Raises ``UnknownCase`` if there is no such file."""
    case = engine.state.casebook.get(case_id)
    describe = describer(engine.state.graph)
    item = item_for(case, describe, KIND.get(case.case_type, "Review"),
                    today=today or "")

    decision = case.decision
    settled = ""
    if decision is not None:
        outcome = next((c for c in CHOICES if c.outcome is decision.outcome), None)
        settled = (
            f"{decision.actor} settled this on {_date(decision.decided_at)}: "
            f"{(outcome.label if outcome else str(decision.outcome)).lower()}. "
            f"Their reason: {_sentence(decision.rationale)}"
        )

    escalated = ""
    if case.status is CaseStatus.ESCALATED and case.escalations:
        latest = case.escalations[-1]
        escalated = (
            f"{latest['by']} passed this file up on {_date(latest['on'])}. "
            f"Their reason: {_sentence(latest['why'])} "
            f"A different officer has to settle it."
        )

    return CaseFile(
        reference=item.reference,
        kind=item.kind,
        urgency=item.urgency,
        tone=TONE[case.severity],
        who=item.who,
        about=item.about,
        headline=item.headline,
        because=item.because,
        to_close_this=item.to_close_this,
        rules=item.rules,
        side_by_side=item.side_by_side,
        corroboration=item.corroboration,
        ours_label=item.ours_label,
        theirs_label=item.theirs_label,
        suggestion=item.suggestion,
        timeline_heading=UI["evidence_heading"],
        timeline=_timeline(engine, case),
        to_close_heading=UI["to_close_heading"],
        settled=settled,
        decided_heading=UI["decided_heading"],
        choices=() if decision is not None else CHOICES,
        recorded_as=RECORDED,
        back=UI["back_to_queue"],
        case_id=case.case_id,
        subject=case.subject,
        reasons=item.reasons,
        escalated=escalated,
    )



@dataclass(frozen=True)
class Held:
    """One document on a party's record, as a person reads it."""

    called: str
    filename: str
    supports: str
    when: str
    who: str
    #: Empty unless it has lapsed, in which case it says so plainly.
    lapsed: str = ""
    tone: str = "plain"


@dataclass(frozen=True)
class Trait:
    """One identifying detail on record."""

    label: str
    value: str
    #: Machine hint for colour. Never shown as text.
    tone: str


@dataclass(frozen=True)
class Tie:
    """One declared ownership connection, in either direction."""

    direction: str
    who: str
    share: str
    basis: str
    #: A machine address: which party page this row leads to.
    ref: str


@dataclass(frozen=True)
class Movement:
    """One commitment or one payment."""

    when: str
    what: str
    amount: str
    note: str
    tone: str


@dataclass(frozen=True)
class FileRow:
    """One file on this party, open or settled."""

    reference: str
    headline: str
    urgency: str
    tone: str
    #: A machine address, like ``Item.case_id``. Never displayed.
    case_id: str


@dataclass(frozen=True)
class OpenFactor:
    """A clause 4.2 factor waiting on a person."""

    ref: str
    group: str
    wording: str


@dataclass(frozen=True)
class RiskFactor:
    """One clause 4.2 factor, as answered."""

    ref: str
    group: str
    wording: str
    present: bool
    because: str = ""
    #: Set where a person answered rather than the records.
    answered_by: str = ""


@dataclass(frozen=True)
class ProposedFactor:
    """One factor's part in a proposed band, and what it added.

    Separate from RiskFactor because it answers a different question. That
    one says what was found; this says what the scorecard did with it -- and
    an officer asked to agree with a band is owed the arithmetic, not just
    the total.
    """

    ref: str
    wording: str
    weight: int
    because: str = ""


@dataclass(frozen=True)
class Party:
    """Everything recorded about one party, on one page."""

    name: str
    kind: str
    heading: str
    standing: str
    unknown: str
    traits_heading: str
    traits: tuple
    traits_caveat: str
    ties_heading: str
    ties: tuple
    ties_none: str
    money_heading: str
    money_summary: str
    movements: tuple
    money_none: str
    open_heading: str
    open_files: tuple
    settled_heading: str
    settled_files: tuple
    timeline_heading: str
    timeline: tuple
    back: str
    #: A machine address. Never displayed.
    entity_id: str = ""
    #: How risky this customer was judged, the factors behind it, and when
    #: they must be looked at again. Confidential under clause 4.1(d): this
    #: is for the officer's screen and must never reach the customer.
    risk_heading: str = ""
    risk_summary: str = ""
    risk_category: str = ""
    risk_factors: tuple = ()
    risk_unanswered: str = ""
    #: What the scorecard would suggest, and its workings. Never a category:
    #: see scorecard.py, and clause 4.2's closing sentence.
    risk_proposed: str = ""
    risk_proposed_lead: str = ""
    risk_proposed_thin: str = ""
    risk_proposed_scope: str = ""
    risk_proposed_points: int = 0
    risk_proposed_from: tuple = ()
    risk_scorecard: str = ""
    risk_due: str = ""
    risk_caveat: str = ""
    #: The clause 4.2 factors nobody has answered, for the officer to
    #: settle. Only a person can: no record speaks to them.
    risk_open: tuple = ()
    #: What the watchlists found on this party, and what the clauses ask of
    #: whoever is about to categorise them. Beside the clause 4.2 factors
    #: rather than among them: none of the nineteen covers a watchlist
    #: match, and filing it under one that does not say it would be an
    #: invented citation.
    risk_screening: str = ""
    risk_guidance: tuple = ()
    #: Whether the person reading may set a category at all.
    may_assess: bool = False
    #: The papers behind the facts. Everything in ``traits`` arrived in a
    #: spreadsheet; clause 5.4.5 asks that identity be verified from
    #: reliable, independent sources, and this is where those sit.
    papers_heading: str = ""
    papers: tuple = ()
    papers_none: str = ""
    papers_note: str = ""

# ---------------------------------------------------------------------------
# What the regulator requires of this entity
# ---------------------------------------------------------------------------

#: Enforcement grounds, as a person would name them. The enum values are
#: SCREAMING_CASE and would fail the jargon sweep on sight.
GROUND_NAMES = {
    "GOVERNANCE": "People and premises",
    "REPORTING": "Filings and returns",
    "CAPITAL": "Capital and net worth",
    "SCOPE": "Activities beyond the licence",
    "COOPERATION": "Answering the regulator",
    "FEES": "Regulatory fees",
    "AML_KYC": "Money-laundering controls",
    "DISCLOSURE": "What was disclosed",
}

#: How much of a ground this system would actually catch, in plain words.
LEVEL_WORDS = {"FULL": "Covered", "PARTIAL": "Partly covered", "NONE": "Not covered"}

REQUIRED_POST_NAMES = {
    "PRINCIPAL_OFFICER": "Principal Officer",
    "COMPLIANCE_OFFICER": "Compliance Officer",
    "FUND_MANAGEMENT_KMP": "Fund management key person",
}

CATEGORY_NAMES = {
    "AUTHORISED": "Authorised",
    "REGISTERED_NON_RETAIL": "Registered (non-retail)",
    "REGISTERED_RETAIL": "Registered (retail)",
}

#: Deliberately does not open with the word "None": the jargon sweep cannot
#: tell the English word from a Python value that failed to fill in, and a
#: sweep with exceptions carved into it stops being a sweep.
UNVERIFIED_REGISTER_CAVEAT = (
    "Not one of these has been confirmed against the published guidelines by a "
    "qualified person yet. The wording was taken from the regulator's own "
    "documents by machine, and every file that cites one says so."
)

#: Two different claims, and the page must never let them blur. A machine can
#: prove the words were copied faithfully and the page numbers point where
#: they say. It cannot prove the right clause was chosen for the rule, or that
#: the clause means what this system takes it to mean. Reporting the first as
#: though it were the second is exactly how a compliance officer ends up
#: trusting a rule nobody ever read.
SOURCE_CHECK_LINE = (
    "All {clauses} clauses here are matched word for word against the "
    "regulator's own published documents. A copy of each of the {documents} "
    "is kept here, and the match is remade every time the system is built, "
    "most recently on {checked} - so neither a quotation nor a page number "
    "can drift unnoticed. That shows the wording was copied faithfully. It "
    "does not show that the right clause was picked, or that it means what "
    "this system takes it to mean."
)


@dataclass(frozen=True)
class Owed:
    """One thing this entity owes IFSCA."""

    what: str
    when: str
    status: str
    charge: str
    tone: str


@dataclass(frozen=True)
class Post:
    """A post the licence requires somebody to hold."""

    office: str
    holder: str
    tone: str


@dataclass(frozen=True)
class ClauseRow:
    clause: str
    document: str
    says: str
    checked: str
    where: str
    tone: str
    link: str
    #: Who stands behind this wording, if anyone. Empty until someone does.
    confirmed_by: str = ""


@dataclass(frozen=True)
class Exposure:
    """One thing IFSCA has actually acted on, and how much of it we catch."""

    ground: str
    actions: str
    coverage: str
    position: str
    tone: str


@dataclass(frozen=True)
class Regulatory:
    """The standing of this entity with its regulator, on one page.

    Every number here already existed; until now it printed to a terminal
    during a demo and nowhere a Principal Officer could see it. Nothing is
    computed for this page that is not already computed for a Case.
    """

    heading: str
    licence_heading: str
    licence_summary: str
    unlicensed: str
    posts_heading: str
    posts: tuple
    owed_heading: str
    owed_summary: str
    owed: tuple
    register_heading: str
    register_summary: str
    source_check: str
    register_caveat: str
    amendment: str
    clauses: tuple
    scorecard_heading: str
    scorecard_summary: str
    grounds: tuple
    back: str
    #: The book, against clause 5.11's periodic-review regime.
    customers_heading: str = ""
    customers_summary: str = ""
    #: Said where customers carry no risk category. Never omitted when it
    #: applies: "no reviews overdue" is true of a book nobody has
    #: categorised, and true in the way that matters least.
    customers_caveat: str = ""
    #: Whether an overnight run has refreshed any of this lately. Sits above
    #: the figures rather than beside them: every count on this page is a
    #: claim about the present, and a workspace nobody has swept is making
    #: those claims out of records that stopped moving.
    swept: str = ""
    #: The firm's own money against the minimum its licence requires.
    capital_heading: str = ""
    capital_summary: str = ""
    capital_caveat: str = ""
    #: What the last return claimed, beside what the book holds. Shown
    #: rather than judged: the gap between a reported figure and the
    #: records is ordinary, and explaining it is an officer's job.
    reported_heading: str = ""
    reported_summary: str = ""
    reported: tuple = ()


def _reported_rows(engine) -> tuple:
    """The last return that carried figures, beside what the book holds."""
    from .disclosure import compare
    from .model import EventType

    latest = None
    for event in engine.log:
        if event.event_type is not EventType.FILING_SUBMITTED:
            continue
        reported = (event.payload or {}).get("reported")
        if isinstance(reported, dict) and reported:
            latest = event
    if latest is None:
        return (), ""

    rows = compare(engine.state.book, (latest.payload or {}).get("reported"))
    period = str((latest.payload or {}).get("period") or "")
    summary = (
        f"The return for {period}, beside what this book holds. A "
        f"difference is ordinary — capital is called in tranches and "
        f"values move — so nothing here is a finding. It is the "
        f"comparison somebody has to be able to make before signing the "
        f"next one."
    )
    return rows, summary


def _owed_rows(engine, today: str) -> tuple:
    licence = engine.state.licence
    if not licence.granted_on:
        return ()
    rows = []
    from .licence import principal_officers

    for item in instances(licence.granted_on, today,
                          engine.state.calendar.submitted,
                          principal_officers(licence)):
        state = item.status(today)
        charge = item.late_charge_usd(today)
        if state is Status.OVERDUE:
            days = item.days_late(today)
            status = f"Overdue by {days} {_plural(days, 'day')}"
            tone = "stop"
        elif state is Status.DUE_SOON:
            status = "Due soon"
            tone = "today"
        elif state is Status.SUBMITTED:
            # The past participle of the schedule's own verb. "Filed" on a
            # registration would read as a return that went in somewhere.
            status = {"paid": "Paid", "done": "Done"}.get(
                item.schedule.verb, "Filed")
            tone = "settled"
        else:
            status = "Not due yet"
            tone = "week"
        rows.append(Owed(
            what=f"{item.schedule.label} for {item.period}",
            when=f"Due {_date(item.due_on)}",
            status=status,
            charge=(f"USD {charge:,} has accrued" if charge else ""),
            tone=tone,
        ))
    return tuple(rows)


def _grounds_by_weight():
    """Every ground IFSCA has acted on, most-acted-on first."""
    from .enforcement import ACTIONS, COVERAGE

    counts = {}
    for action in ACTIONS:
        for ground in action.grounds:
            counts[ground] = counts.get(ground, 0) + 1
    return [
        (ground, count, COVERAGE[ground])
        for ground, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


def _signed_off(engine) -> dict:
    """Clause id -> the sentence naming who stands behind that wording.

    Read from the log rather than from the register, so a sign-off is
    workspace data like an enrolment -- and so one recorded against wording
    that has since been corrected simply stops appearing.
    """
    from .citations import verified_now

    out = {}
    for clause_id in CLAUSES:
        record = verified_now(clause_id, engine.state.verifications)
        if record:
            out[clause_id] = (
                f"{record['reviewer']} ({record['qualification']}) confirmed "
                f"this on {_date(record['verified_at'])}. {record['note']}"
            )
    return out


#: Said where no overnight run has ever happened in this workspace. The
#: strongest of the three, because it is the case where every figure on the
#: page reads its best and means least: nothing is overdue, nothing has
#: matched, and nothing has looked.
NEVER_SWEPT = (
    "No overnight check has ever run here. Every figure on this page was "
    "worked out from records as they stand, and nothing has re-checked them "
    "against the watchlists or the calendar since they were entered. Treat "
    "what follows as the state of your records, not the state of the world."
)

#: Said where the last run is older than a night. Names the date rather than
#: only the gap: "3 days ago" is a number somebody argues with, and a date is
#: a thing they can go and look at.
SWEPT_STALE = (
    "The last overnight check ran on {when}, {days} days ago. Anything that "
    "has changed since — a name added to a watchlist, a date that has "
    "passed — is not in the figures below."
)

#: Said where the run is current. Short on purpose: it is the ordinary case,
#: and a reassurance repeated at length is a reassurance that gets skipped.
SWEPT_RECENTLY = "Last overnight check: {when}."

#: Appended where the run happened but could not reach the watchlist for
#: somebody. The run is not reported as clean, because it was not.
SWEPT_INCOMPLETE = (
    " {n} {party} could not be checked that night and {were} not screened."
)


def _swept(engine, today: str) -> str:
    """One sentence about whether these figures have been refreshed."""
    from .sweep import currency

    how = currency(engine, today)
    if how.never:
        return NEVER_SWEPT
    said = (SWEPT_STALE.format(when=_date(how.last.on), days=how.days_ago)
            if how.stale
            else SWEPT_RECENTLY.format(when=_date(how.last.on)))
    missed = len(how.last.unreachable)
    if missed:
        said += SWEPT_INCOMPLETE.format(
            n=missed,
            party=_plural(missed, "party", "parties"),
            were=_plural(missed, "was", "were"))
    return said


def regulatory(engine, today=None) -> Regulatory:
    """Where this entity stands with IFSCA: licence, posts, filings, rules."""
    from .citations import DOCUMENTS, coverage
    from .enforcement import scorecard

    today = today or date.today().isoformat()
    licence = engine.state.licence
    signed_off = _signed_off(engine)
    register = coverage(engine.state.verifications)

    if licence.granted_on:
        category = CATEGORY_NAMES.get(
            str(licence.category or ""), str(licence.category or "")
        )
        summary = (
            f"Registered with IFSCA as {category}, number "
            f"{licence.number or 'not recorded'}, granted "
            f"{_date(licence.granted_on)}."
        )
        unlicensed = ""
    else:
        summary = ""
        unlicensed = (
            "No registration is on file for this entity, so nothing on this "
            "page can be checked against one. Recording the licence is the "
            "first thing to do here."
        )

    gaps = {str(gap.office): gap.reason for gap in licence.gaps()}
    posts = tuple(
        Post(
            office=REQUIRED_POST_NAMES.get(str(office), str(office)),
            holder=(licence.holders[office].person if office in licence.holders
                    else "Nobody holds this post"),
            tone=("stop" if str(office) in gaps else "settled"),
        )
        for office in licence.required_offices()
    )

    owed = _owed_rows(engine, today)
    late = sum(1 for row in owed if row.tone == "stop")
    if not owed:
        owed_summary = ""
    elif late:
        owed_summary = (
            f"{late} of {len(owed)} "
            f"{_plural(len(owed), 'obligation is', 'obligations are')} overdue."
        )
    else:
        owed_summary = (
            f"Nothing is overdue. {len(owed)} "
            f"{_plural(len(owed), 'obligation', 'obligations')} tracked."
        )

    pending = register.get("pending_amendments") or []
    amendment = ""
    if pending:
        first = pending[0]
        amendment = (
            f"A circular dated {_date(first['circular_date'])} amends these "
            f"guidelines and has not been incorporated here yet. "
            f"{first['summary']}"
        )

    clauses = tuple(
        ClauseRow(
            clause=clause.clause_id,
            document=DOCUMENTS[clause.doc_id].title,
            says=PLAIN_RULES.get(clause.clause_id, clause.heading),
            checked=("Checked by a person" if signed_off.get(clause.clause_id)
                     else "Not yet checked by a person"),
            confirmed_by=signed_off.get(clause.clause_id, ""),
            where=(f"Page {clause.page}" if clause.page else ""),
            tone=("settled" if signed_off.get(clause.clause_id) else "today"),
            link=DOCUMENTS[clause.doc_id].url,
        )
        for clause in sorted(CLAUSES.values(), key=lambda c: (c.doc_id, c.clause_id))
    )

    score = scorecard()
    grounds = tuple(
        Exposure(
            ground=GROUND_NAMES.get(str(ground), str(ground)),
            actions=f"{count} {_plural(count, 'action', 'actions')}",
            coverage=LEVEL_WORDS.get(str(capability.level), str(capability.level)),
            position=(capability.position or capability.needs),
            tone=("settled" if str(capability.level) == "FULL"
                  else "today" if str(capability.level) == "PARTIAL" else "stop"),
        )
        for ground, count, capability in _grounds_by_weight()
    )

    from .capital import NOT_CONFIRMED as _NOT_CONFIRMED, in_words, required

    _capital_words = in_words(engine.state.licence, engine.state.capital)
    _minimum, _confirmed, _why = required(engine.state.licence,
                                          engine.state.capital)
    _capital_caveat = ("" if _confirmed or _minimum is None else _NOT_CONFIRMED)
    _reported, _reported_summary = _reported_rows(engine)

    # Clause 5.11's regime, as it actually stands on this book. The two
    # numbers are deliberately reported together: a customer with no risk
    # category has no review interval, so they cannot be overdue for a
    # review -- which means a book nobody has categorised shows nothing
    # overdue and is in the worst position it can be in. Showing the first
    # number without the second would be this system's oldest mistake on
    # its most important page.
    from .risk import due_for_review, never_assessed

    _on_the_book = len(engine.state.graph.entities)
    _uncategorised = len(never_assessed(engine))
    _lapsed = len(due_for_review(engine, today))
    _rated = _on_the_book - _uncategorised

    if not _on_the_book:
        _customers_summary = "No customers are on the book yet."
        _customers_caveat = ""
    else:
        _customers_summary = (
            f"{_rated} of {_on_the_book} "
            f"{_plural(_on_the_book, 'customer carries', 'customers carry')} "
            f"a risk category. "
            + (f"{_lapsed} "
               f"{_plural(_lapsed, 'is', 'are')} overdue for review."
               # Not "None of those...": a guard on this page rejects the
               # word, because a bare "None" on screen is far more often a
               # Python value that escaped than a sentence somebody wrote.
               if _lapsed else "Not one of them is overdue for review.")
        )
        _customers_caveat = ("" if not _uncategorised else (
            f"{_uncategorised} "
            f"{_plural(_uncategorised, 'customer has', 'customers have')} no "
            f"risk category, so {_plural(_uncategorised, 'it has', 'they have')} "
            f"no review date and {_plural(_uncategorised, 'cannot', 'cannot')} "
            f"appear as overdue above. Clause 5.11 sets the interval by "
            f"category, so a customer without one sits outside the review "
            f"regime rather than passing it. Categorising them is what puts "
            f"them inside it."
        ))

    return Regulatory(
        heading="Where you stand with IFSCA",
        licence_heading="Your registration",
        licence_summary=summary,
        unlicensed=unlicensed,
        customers_heading="Your customers, and when they are next reviewed",
        swept=_swept(engine, today),
        customers_summary=_customers_summary,
        customers_caveat=_customers_caveat,
        posts_heading="Posts your licence requires",
        posts=posts,
        owed_heading="What you owe IFSCA",
        owed_summary=owed_summary,
        owed=owed,
        register_heading="The rules this system enforces",
        register_summary=(
            f"{register['clauses']} clauses from {register['documents']} "
            f"published documents. {register['verified']} confirmed by a "
            f"person, {register['unverified']} not yet."
        ),
        source_check=(
            SOURCE_CHECK_LINE.format(checked=_date(SOURCE_CHECKED_ON),
                                     clauses=len(CLAUSES),
                                     documents=len(SOURCES))
            if SOURCE_CHECKED_ON else ""
        ),
        register_caveat=(UNVERIFIED_REGISTER_CAVEAT if register["unverified"] else ""),
        amendment=amendment,
        clauses=clauses,
        scorecard_heading="What IFSCA has actually acted on",
        scorecard_summary=(
            f"{score.published} enforcement actions published between July 2024 "
            f"and June 2026. {score.scored} are recorded here in enough detail "
            f"to score, and this system would surface {score.would_surface} of "
            f"those {score.scored}."
        ),
        grounds=grounds,
        capital_heading="The firm's own money",
        capital_summary=_capital_words,
        capital_caveat=_capital_caveat,
        reported_heading="What the last return claimed",
        reported_summary=_reported_summary,
        reported=_reported,
        back=UI["back_to_queue"],
    )


# ---------------------------------------------------------------------------
# Everything about one party
# ---------------------------------------------------------------------------

#: What each recorded attribute is called when a person reads it. Anything not
#: listed here is not shown at all: a label invented from a key name would be
#: guesswork printed with the same authority as a fact.
TRAIT_LABELS = {
    "nationality": "Nationality",
    "country_of_residence": "Lives in",
    "country_of_incorporation": "Incorporated in",
    "jurisdiction": "Registered in",
    "dob": "Date of birth",
    "id_document_type": "Identity document",
    "id_document_number": "Document number",
    "is_listed": "Listed on an exchange",
    "is_shell": "Shell company",
    "pep_flag": "Politically exposed person",
    "high_risk_jurisdiction": "High-risk jurisdiction",
}

#: Attributes holding an ISO country code.
_COUNTRY_TRAITS = frozenset({
    "nationality", "country_of_residence", "country_of_incorporation",
    "jurisdiction",
})

_DATE_TRAITS = frozenset({"dob"})

#: Attributes recorded as 0 or 1. Each needs its own words, because "Yes"
#: against "Shell company" and "Yes" against "Listed on an exchange" mean
#: opposite things to the officer reading them.
_FLAG_WORDS = {
    "is_listed": ("Yes", "No", ""),
    "is_shell": ("Yes — no independent operations recorded", "No", "today"),
    "pep_flag": ("Yes", "Not recorded as one", "today"),
    "high_risk_jurisdiction": ("Yes", "No", "today"),
}

#: Identity documents, spelled out.
_ID_DOCUMENTS = {
    "PASSPORT": "Passport",
    "NATIONAL_ID": "National identity card",
    "DRIVING_LICENCE": "Driving licence",
    "CERTIFICATE_OF_INCORPORATION": "Certificate of incorporation",
}

#: Customer types, as clause 1.3.3 distinguishes them, in ordinary words.
PARTY_KINDS = {
    "PERSON": "Person",
    "COMPANY": "Company",
    "PARTNERSHIP": "Partnership",
    "UNINCORPORATED_BODY": "Unincorporated body",
    "TRUST": "Trust",
    "FUND": "Fund",
    # Not a 1.3.3 category: a name off a statement, type never recorded.
    "UNKNOWN": "Type not recorded",
}

#: Ownership relations, read as a sentence about the party on the page.
_HELD_BY = {
    "OWNS": "holds a stake in",
    "TRUSTEE_OF": "is a trustee of",
    "SETTLOR_OF": "created",
    "BENEFICIARY_OF": "benefits from",
}

TRAITS_CAVEAT = (
    "These are the details as declared to this firm. Nothing here has been "
    "checked against an independent source."
)

NOTHING_RECORDED = "Nothing has been recorded about this party."

#: Not every Case has a party behind it. An unattributable payment opens a
#: Case against the payment record, and the queue already calls that sender
#: "An unidentified sender". This page has to agree with the queue the reader
#: clicked through from, and must never print the record id as though it were
#: a name -- the exact defect the queue sweep caught once already.
UNREGISTERED_SUBJECT = (
    "No party on the register matches this. Everything below is attached to "
    "the record itself, which is most often a payment that could not be "
    "traced back to a named sender."
)


def _article(word: str) -> str:
    """"a" or "an", so sentences built from a lookup table still read."""
    return "an" if word[:1].lower() in "aeiou" else "a"

#: What each kind of event was, said plainly. The payload is never quoted at
#: the reader: it holds screaming constants and internal ids.
def _party_what(event, describe) -> tuple:
    """(what happened, tone) for one event on a party's chronology."""
    kind = str(event.event_type)
    payload = event.payload or {}

    if kind == "ENTITY_REGISTERED":
        return "This party was added to the records.", "fact"
    if kind == "OWNERSHIP_DECLARED":
        owner = describe(payload.get("owner", ""))
        owned = describe(payload.get("owned", ""))
        share = payload.get("percentage")
        held = f" of {_pct(share)}" if isinstance(share, (int, float)) else ""
        return f"A holding{held} by {owner} in {owned} was declared.", "fact"
    if kind == "COMMITMENT_MADE":
        return (f"A commitment of "
                f"{_money(payload.get('amount'), payload.get('currency'))} "
                f"was made to a fund."), "fact"
    if kind == "PAYMENT_RECEIVED":
        amount = _money(payload.get("amount"), payload.get("currency"))
        if payload.get("anomaly"):
            return f"A payment of {amount} arrived and raised a query.", "rule"
        return f"A payment of {amount} arrived and matched what was called.", "fact"
    if kind == "SCREENING_COMPLETED":
        return "This party was checked against the watchlists.", "fact"
    if kind == "CASE_OPENED":
        what = KIND.get(payload.get("case_type", ""), "review").lower()
        return f"{_article(what).capitalize()} {what} was opened.", "rule"
    if kind == "EVIDENCE_RECORDED":
        what = KIND.get(payload.get("case_type", ""), "review").lower()
        return f"More was recorded on an open {what}.", "rule"
    if kind == "CASE_DECIDED":
        return "A person settled a file on this party.", "decision"
    if kind == "DRAFT_PREPARED":
        return "A suggestion was prepared for the officer to consider.", "suggestion"
    return "Something was recorded.", "fact"


def _papers_panel(engine, entity_id: str, today) -> tuple:
    """The documents held, and what is still standing on nothing.

    The point of the panel is the last line rather than the list: a party
    can have every field clause 5.4.2 asks for and not one document behind
    any of them, and until documents could be filed the two looked
    identical on every screen.
    """
    from . import readiness as _readiness
    from .documents import KINDS

    held = getattr(engine.state, "papers", None)
    if held is None:
        return (), "", ""
    day = str(today or "")[:10]
    # The list that applies to *this* party. Reading both would say "a full
    # name" twice, because clause 5.4.2 asks for one under (a) and again
    # under (b), for different kinds of customer.
    wanted = _readiness._requirements(engine.state.graph.kind_of(entity_id))
    rows = []
    for paper in held.held_for(entity_id):
        supports = _join([what for _clause, what, keys in wanted
                          if any(key in paper.supports for key in keys)])
        lapsed = ""
        tone = "plain"
        if day and paper.expired(day):
            lapsed = f"Ran out on {_date(paper.expires_on)}"
            tone = "stop"
        elif paper.expires_on:
            lapsed = f"Runs out on {_date(paper.expires_on)}"
        rows.append(Held(
            called=paper.called,
            filename=paper.filename,
            supports=supports or "nothing on the list clause 5.4.2 asks for",
            when=_date(paper.filed_on),
            who=paper.filed_by,
            lapsed=lapsed,
            tone=tone,
        ))

    none_said = ("No document has been filed for this party. Everything "
                 "above was typed in, which is what a firm holds rather "
                 "than what it has verified." if not rows else "")

    note = ""
    if day:
        measured = _readiness.measure(engine, only=(entity_id,), today=day)
        standing = next((s for s in measured.parties
                         if s.entity_id == entity_id), None)
        if standing is not None and standing.unsupported:
            note = (
                _counted(len(standing.unsupported), "thing", "things")
                + " on this record " + ("is" if len(standing.unsupported) == 1
                                        else "are")
                + " held but not evidenced: "
                + _join([gap.what for gap in standing.unsupported])
                + ". Clause 5.4.2 asks a firm to hold these; clause 5.4.5 "
                  "asks it to verify identity from reliable, independent "
                  "sources, and a spreadsheet column is the first and not "
                  "the second.")
    return tuple(rows), none_said, note


def _traits(entity) -> tuple:
    """The identifying details on record, in reading order, translated."""
    if entity is None:
        return ()
    attributes = dict(entity.attributes or {})
    rows = []
    for key, label in TRAIT_LABELS.items():
        if key not in attributes:
            continue
        raw = attributes[key]
        value, tone = str(raw), ""
        if key in _FLAG_WORDS:
            yes, no, flagged = _FLAG_WORDS[key]
            on = str(raw) in ("1", "True", "true", "yes")
            value, tone = (yes, flagged) if on else (no, "")
        elif key in _COUNTRY_TRAITS:
            value = country_name(str(raw))
        elif key in _DATE_TRAITS:
            value = _date(str(raw))
        elif key == "id_document_type":
            value = _ID_DOCUMENTS.get(str(raw), str(raw).replace("_", " ").capitalize())
        rows.append(Trait(label=label, value=value, tone=tone))
    return tuple(rows)


def _ties(graph, entity_id: str) -> tuple:
    """Who holds this party, and what this party holds."""
    ties = []
    for edge in graph.owners_of(entity_id):
        verb = _HELD_BY.get(str(edge.relation), "is connected to")
        ties.append(Tie(
            direction="Held by",
            who=graph.name_of(edge.owner),
            share=(_pct(edge.percentage) if str(edge.relation) == "OWNS" else ""),
            basis=f"{graph.name_of(edge.owner)} {verb} this party.",
            ref=edge.owner,
        ))
    for edge in graph.holdings_of(entity_id):
        verb = _HELD_BY.get(str(edge.relation), "is connected to")
        ties.append(Tie(
            direction="Holds",
            who=graph.name_of(edge.owned),
            share=(_pct(edge.percentage) if str(edge.relation) == "OWNS" else ""),
            basis=f"This party {verb} {graph.name_of(edge.owned)}.",
            ref=edge.owned,
        ))
    return tuple(ties)


def _movements(events) -> tuple:
    """Commitments promised and payments arrived, newest first."""
    rows = []
    for event in events:
        kind = str(event.event_type)
        if kind not in ("COMMITMENT_MADE", "PAYMENT_RECEIVED"):
            continue
        payload = event.payload or {}
        amount = _money(payload.get("amount"), payload.get("currency"))
        if kind == "COMMITMENT_MADE":
            rows.append(Movement(when=_date(event.occurred_at), what="Committed",
                                 amount=amount, note="", tone=""))
            continue
        note, tone = "Matched what was called", "settled"
        if payload.get("anomaly"):
            note, tone = "Raised a query", "today"
        rows.append(Movement(when=_date(event.occurred_at), what="Received",
                             amount=amount, note=note, tone=tone))
    rows.reverse()
    return tuple(rows)


def _money_summary(events) -> str:
    """Totals, per currency, never added across currencies.

    Converting to a single figure would need a rate this system does not hold
    and cannot source. A total that quietly assumes one is a number an officer
    might repeat to a regulator.
    """
    committed: dict = {}
    received: dict = {}
    queried = 0
    payments = 0
    for event in events:
        kind = str(event.event_type)
        payload = event.payload or {}
        amount, currency = payload.get("amount"), payload.get("currency")
        if not isinstance(amount, (int, float)):
            continue
        if kind == "COMMITMENT_MADE":
            committed[currency] = committed.get(currency, 0.0) + amount
        elif kind == "PAYMENT_RECEIVED":
            received[currency] = received.get(currency, 0.0) + amount
            payments += 1
            if payload.get("anomaly"):
                queried += 1

    parts = []
    if committed:
        totals = _join([_money(v, k) for k, v in sorted(committed.items(),
                                                        key=lambda p: str(p[0]))])
        parts.append(f"Committed {totals}.")
    if received:
        totals = _join([_money(v, k) for k, v in sorted(received.items(),
                                                        key=lambda p: str(p[0]))])
        tail = "."
        if queried:
            tail = (f", and {queried} of them "
                    f"{_plural(queried, 'raised a query', 'raised queries')}.")
        parts.append(f"Received {totals} across "
                     f"{payments} {_plural(payments, 'payment')}{tail}")
    return " ".join(parts)


#: What each risk category means for how often the customer is seen again.
#: The words a reader needs, not the enum.
RISK_WORDS = {"HIGH": "High risk", "MEDIUM": "Medium risk",
              "LOW": "Low risk"}

RISK_CAVEAT = (
    "This categorisation and the reasons for it are confidential. Clause "
    "4.1(d) requires that they are not revealed to the customer, so that a "
    "customer under scrutiny is not tipped off."
)


#: Said above a proposed band. The distinction it draws is the one clause
#: 4.2 draws in its closing sentence, and the reason this product may show a
#: band at all: an arithmetic starting point is not a categorisation, and the
#: officer who sets the category is the one whose name goes on it.
PROPOSAL_LEAD = (
    "A starting point, not a decision. This is what the scorecard makes of "
    "the factors answered so far; the category is yours to set, and yours "
    "to disagree with."
)

#: Said where most of clause 4.2's list is still unanswered. A band computed
#: from four of nineteen factors is a band about four factors, and showing it
#: with the same confidence as a fully worked one would be the arithmetic
#: overstating what it knows.
PROPOSAL_IS_THIN = (
    "Too few of the factors this scorecard can weigh have been answered for "
    "the arithmetic to mean much yet. Answering more of them below is what "
    "makes it worth anything."
)

#: What the band is a band *of*. The scorecard weighs eight of clause 4.2's
#: nineteen factors -- the ones this firm's own records can answer -- and the
#: other eleven need a person. Naming that on every proposal is the whole
#: reason a band may be shown under a clause that forbids deciding: an
#: officer reading "low" is entitled to know it is low on the scorable
#: factors, not low as a customer.
PROPOSAL_SCOPE = (
    "{weighed} of the {weighable} factors this scorecard can weigh are "
    "answered, and they come to {points}. The other {by_hand} in clause 4.2 "
    "can only be answered by a person, which is why this is a band and not "
    "a category."
)

#: Bands, said as bands. Deliberately not RISK_WORDS: those say "Low risk",
#: which is the name of a *category* somebody puts their name to under clause
#: 4.1(a). A scorecard proposes a position on its own scale and nothing more,
#: and giving the two the same words is how the first quietly becomes the
#: second on a screen somebody reads in a hurry.
BAND_WORDS = {
    "LOW": "the low band",
    "MEDIUM": "the medium band",
    "HIGH": "the high band",
}


def _risk_panel(engine, entity_id: str, today) -> dict:
    """The customer's risk assessment, as an officer reads it."""
    from .risk import (BY_REF, FACTORS, next_review, observe, unanswered,
                       what_screening_found)

    assessment = engine.state.risk.get(entity_id)

    # What the records can see is shown whether or not anyone has settled a
    # category, because the point of the panel is to put the evidence in
    # front of the person who has to weigh it.
    try:
        seen = dict(observe(engine, entity_id))
    except KeyError:
        seen = {}
    if assessment is not None:
        seen.update(assessment.observations)

    rows = []
    for factor in FACTORS:
        found = seen.get(factor.ref)
        if found is None or found.present is None:
            continue
        rows.append(RiskFactor(
            ref=factor.ref,
            group=factor.group,
            wording=factor.wording,
            present=bool(found.present),
            because=found.because,
            answered_by=found.answered_by,
        ))

    found = what_screening_found(engine, entity_id)

    # A starting point, computed from exactly what is on screen above. It is
    # shown whether or not a category has been settled: before, so somebody
    # has something to react to instead of a blank; after, so an officer
    # revisiting the file can see whether the evidence has moved away from
    # the category somebody set.
    from .scorecard import propose

    suggested = propose(seen)
    points_said = ("no points" if not suggested.points
                   else f"{suggested.points} point"
                        f"{'' if suggested.points == 1 else 's'}")
    proposal = {
        "band": BAND_WORDS.get(suggested.band, suggested.band),
        "points": suggested.points,
        "lead": PROPOSAL_LEAD,
        "scope": PROPOSAL_SCOPE.format(
            weighed=suggested.weighed,
            weighable=suggested.weighable,
            points=points_said,
            by_hand=len(FACTORS) - suggested.weighable,
        ),
        "thin": PROPOSAL_IS_THIN if suggested.thin else "",
        "counted": tuple(
            ProposedFactor(
                ref=part.ref,
                wording=BY_REF[part.ref].wording if part.ref in BY_REF else part.ref,
                weight=part.weight,
                because=part.because,
            )
            for part in suggested.counted
        ),
        "scorecard": suggested.scorecard,
    }

    still_open = tuple(
        OpenFactor(ref=f.ref, group=f.group, wording=f.wording)
        for f in unanswered(assessment)
    )
    open_count = len(still_open)
    still = ""
    if open_count:
        still = (f"{open_count} of the {len(FACTORS)} factors clause 4.2 "
                 f"lists have not been answered by anyone. They cannot be "
                 f"read off the records — only a person can settle "
                 f"them.")

    if assessment is None or not assessment.settled:
        return {
            "heading": "How risky this customer is",
            "summary": ("Nobody has categorised this customer yet. Until "
                        "somebody does, there is no date by which they must "
                        "be looked at again."),
            "category": "",
            "factors": tuple(rows),
            "unanswered": still,
            "due": "",
            "caveat": RISK_CAVEAT,
            "open": still_open,
            "screening": found.summary,
            "guidance": found.guidance,
            "proposal": proposal,
        }

    word = RISK_WORDS.get(assessment.category, assessment.category)
    summary = (f"{word}, set by {assessment.by} on "
               f"{_date(assessment.on)}. Their reason: "
               f"{_sentence(assessment.reason)}")

    due = next_review(assessment.category, assessment.on)
    when = ""
    if due:
        overdue = today is not None and due.on <= str(today)[:10]
        when = (f"Due to be looked at again on {_date(due.on)} — "
                f"{due.because}.")
        if overdue:
            when = (f"Was due to be looked at again on {_date(due.on)} "
                    f"— {due.because}.")

    return {
        "heading": "How risky this customer is",
        "summary": summary,
        "category": assessment.category,
        "factors": tuple(rows),
        "unanswered": still,
        "due": when,
        "caveat": RISK_CAVEAT,
        "open": still_open,
        "screening": found.summary,
        "guidance": found.guidance,
        "proposal": proposal,
    }


def party(engine, entity_id: str, today=None) -> "Party":
    """One party, and everything recorded about them.

    The queue answers "what needs me" and a file answers "why does this need
    me". Neither answers the question an officer is asked on the telephone --
    "what do we know about this investor" -- which until now could only be
    answered by opening every file that happened to mention them. Nothing here
    is new information. It is the log, filtered to one subject.
    """
    graph = engine.state.graph
    describe = describer(graph)
    entity = graph.entities.get(entity_id)
    events = sorted(
        (event for event in engine.log if event.subject == entity_id),
        key=lambda event: (event.occurred_at, event.seq),
    )

    cases = [case for case in engine.state.casebook.cases.values()
             if case.subject == entity_id]
    cases.sort(key=lambda case: case.queue_key)
    open_cases = [case for case in cases if case.is_open]
    settled_cases = [case for case in cases if not case.is_open]

    counts: dict = {}

    def row(case) -> "FileRow":
        label = KIND.get(case.case_type, "Review")
        counts[label] = counts.get(label, 0) + 1
        item = item_for(case, describe, f"{label} {counts[label]}")
        return FileRow(reference=item.reference, headline=item.headline,
                       urgency=item.urgency, tone=TONE[case.severity],
                       case_id=case.case_id)

    # describe() rather than name_of(): the latter falls back to the id, and
    # an id printed where a name belongs looks like a name.
    name = describe(entity_id, cases[0].case_type if cases else "")
    kind = PARTY_KINDS.get(str(graph.kind_of(entity_id) or ""), "")

    standing = ""
    if open_cases and settled_cases:
        standing = (f"{len(open_cases)} {_plural(len(open_cases), 'file')} open, "
                    f"{len(settled_cases)} settled.")
    elif open_cases:
        standing = (f"{len(open_cases)} {_plural(len(open_cases), 'file')} "
                    f"{_plural(len(open_cases), 'needs', 'need')} a decision.")
    elif settled_cases:
        standing = (f"Nothing open. {len(settled_cases)} "
                    f"{_plural(len(settled_cases), 'file')} already settled.")
    elif events:
        standing = "Nothing has ever been opened on this party."

    moments = []
    for event in events:
        what, tone = _party_what(event, describe)
        moments.append(Moment(
            when=_date(event.occurred_at),
            kind=MOMENT_KIND.get("FACT", "Something was observed"),
            what=what, who=_moment_who(event.actor), tone=tone,
        ))
    moments = tuple(moments)

    traits = _traits(entity)
    papers, papers_none, papers_note = _papers_panel(engine, entity_id, today)
    ties = _ties(graph, entity_id)
    panel = _risk_panel(engine, entity_id, today)

    return Party(
        risk_heading=panel["heading"],
        risk_summary=panel["summary"],
        risk_category=panel["category"],
        risk_factors=panel["factors"],
        risk_unanswered=panel["unanswered"],
        risk_proposed=panel["proposal"]["band"],
        risk_proposed_lead=panel["proposal"]["lead"],
        risk_proposed_thin=panel["proposal"]["thin"],
        risk_proposed_scope=panel["proposal"]["scope"],
        risk_proposed_points=panel["proposal"]["points"],
        risk_proposed_from=panel["proposal"]["counted"],
        risk_scorecard=panel["proposal"]["scorecard"],
        risk_due=panel["due"],
        risk_caveat=panel["caveat"],
        risk_open=panel["open"],
        risk_screening=panel["screening"],
        risk_guidance=panel["guidance"],
        name=name,
        kind=kind,
        heading=name,
        standing=standing,
        unknown=("" if entity is not None else
                 UNREGISTERED_SUBJECT if events else NOTHING_RECORDED),
        traits_heading="What we hold on this party",
        traits=traits,
        papers_heading="The papers behind these facts",
        papers=papers,
        papers_none=papers_none,
        papers_note=papers_note,
        traits_caveat=TRAITS_CAVEAT if traits else "",
        ties_heading="How this party connects to others",
        ties=ties,
        ties_none=("No ownership has been declared either way."
                   if not ties else ""),
        money_heading="Money promised and money received",
        money_summary=_money_summary(events),
        movements=_movements(events),
        money_none=("No commitment or payment has been recorded."
                    if not _movements(events) else ""),
        open_heading="What needs a decision",
        open_files=tuple(row(case) for case in open_cases),
        settled_heading="What has been settled",
        settled_files=tuple(row(case) for case in settled_cases),
        timeline_heading="Everything recorded about this party, oldest first",
        timeline=moments,
        back=UI["back_to_queue"],
        entity_id=entity_id,
    )


# ---------------------------------------------------------------------------
# Who has been checked against the watchlists, and who has not
# ---------------------------------------------------------------------------

#: Clause 5.9 requires screening to be *ongoing*. It does not say how often,
#: and neither does anything else this system holds. Reporting a party as
#: "overdue for re-screening" would therefore be inventing an obligation the
#: regulator has not imposed -- so the page reports dates and declines to
#: judge them. The interval is the firm's policy, and the firm has to set it.
#: Said against a party checked before the newest list this workspace has
#: been screened against. Deliberately not a judgement about *time* -- that
#: is what SCREENING_INTERVAL_CAVEAT below declines to make, and it still
#: declines to. This is a different and harder fact: the list itself has
#: been replaced since, so somebody added to it in the meantime is somebody
#: this party has never been checked against. A record saying "checked" is
#: not wrong about the past and is no longer an answer about the present.
OUT_OF_DATE_CHECK = (
    "Checked against an older version of the watchlist. Anyone added since "
    "has not been checked against this party."
)

#: The summary line, where any are behind. Says what it can speak for: the
#: newest list this workspace has seen, which is not necessarily the newest
#: the service holds -- nothing here can know that until a sweep runs.
OUT_OF_DATE_SUMMARY = (
    "{n} of these {were} checked against an older version of the watchlist "
    "than the newest this workspace has screened against. Running the sweep "
    "again checks them against the current list."
)

SCREENING_INTERVAL_CAVEAT = (
    "Clause 5.9 requires screening to be ongoing, but it does not say how "
    "often. This page reports when each party was last checked and does not "
    "judge whether that is recent enough. The interval is your firm\u2019s "
    "policy to set, and this system does not hold it."
)

#: Why the count is of investors rather than of everyone on file. Clause 5.9
#: names customers, and inflating the denominator with intermediate holding
#: companies would overstate the gap in one direction while understating how
#: much of it is a customer.
SCREENING_SCOPE_NOTE = (
    "Counted here are the parties who have committed money to a fund. Others "
    "appear on the register only as links in an ownership chain."
)

NO_CHECK = "No record of a check"
NOTHING_FOUND = "Nothing found"


@dataclass(frozen=True)
class Check:
    """One party\u2019s screening standing."""

    who: str
    kind: str
    when: str
    result: str
    tone: str
    #: A machine address: which party page this row leads to.
    ref: str
    #: Said only where this party was checked against a list this workspace
    #: has since moved past. Empty is the ordinary case and shows nothing --
    #: a row that had to explain itself every time would train an officer to
    #: stop reading the column.
    currency: str = ""


@dataclass(frozen=True)
class Screening:
    """Who has been checked, who has not, and what the rule requires.

    A match already reaches the officer as a Case. A *clean* check reaches
    nothing at all -- it opens no Case by design, so before this page there
    was no screen anywhere in the product that could show it. That is the
    wrong way round: the clean result is the one an inspector asks to see,
    because it is the only evidence the check was ever performed.
    """

    heading: str
    coverage_summary: str
    coverage_tone: str
    scope_note: str
    rule_heading: str
    rule_says: str
    rule_clause: str
    rule_caveat: str
    #: A machine address, like ``ClauseRow.link``. Never read aloud.
    link: str
    unchecked_heading: str
    unchecked: tuple
    unchecked_more: str
    checked_heading: str
    checked: tuple
    checked_none: str
    #: Empty when every check on record was made against the newest list this
    #: workspace has screened against. A firm that has just run the sweep
    #: should see nothing here, and seeing nothing should mean something.
    out_of_date: str = ""
    back: str = ""


def _latest_screenings(engine) -> dict:
    """The last check on each party, and whether anything was found.

    Keyed on the subject, so a party checked five times reports its most
    recent standing rather than five rows. Every check is still on the log;
    this is a summary, not a replacement for it.
    """
    latest: dict = {}
    for event in engine.log:
        if str(event.event_type) != "SCREENING_COMPLETED":
            continue
        payload = event.payload or {}
        record = latest.setdefault(
            event.subject,
            {"when": "", "matches": 0, "checks": 0, "version": ""},
        )
        record["checks"] += 1
        if payload.get("matched"):
            record["matches"] += 1
        if event.occurred_at > record["when"]:
            record["when"] = event.occurred_at
        # Taken from the last screening in log order rather than the latest
        # by date: two screens on one day are ordered by the log and by
        # nothing else, and the version that matters is whichever was
        # written most recently.
        record["version"] = str(
            (payload.get("basis") or {}).get("list_version") or "")
    return latest



def shared_names(graph) -> frozenset:
    """Names held by more than one party on the register.

    Two different people really are called Priya Hussain, and five distinct
    trusts really are called Sovereign Succession Trust. Listing them as
    identical rows is truthful and unusable: an officer cannot tell which is
    which, and the failure mode is acting on the wrong party.
    """
    seen: dict = {}
    for entity in graph.entities.values():
        seen[entity.name] = seen.get(entity.name, 0) + 1
    return frozenset(name for name, count in seen.items() if count > 1)


def qualified_name(graph, entity_id: str, shared: frozenset) -> str:
    """A name, with just enough already-recorded detail to tell it apart.

    Only ever detail the register already holds -- where a party is from, or
    when a person was born. Nothing is invented to break a tie, so a party
    with nothing distinguishing on file stays ambiguous on screen, which is
    itself the true answer.
    """
    entity = graph.entities.get(entity_id)
    if entity is None or entity.name not in shared:
        return graph.name_of(entity_id)

    attributes = entity.attributes or {}
    born = attributes.get("dob")
    if born:
        return f"{entity.name} (born {_date(str(born))})"
    where = (attributes.get("jurisdiction")
             or attributes.get("country_of_incorporation")
             or attributes.get("nationality")
             or attributes.get("country_of_residence"))
    if where:
        return f"{entity.name} ({country_name(str(where))})"
    return entity.name

def screening(engine, today=None, per_list: int = 12) -> "Screening":
    """Watchlist coverage across the customers of this firm."""
    from .citations import DOCUMENTS

    graph = engine.state.graph
    known = graph.entities

    customers = sorted({
        event.payload.get("investor")
        for event in engine.log
        if str(event.event_type) == "COMMITMENT_MADE"
        and event.payload.get("investor") in known
    })
    latest = _latest_screenings(engine)
    shared = shared_names(graph)
    from .rescreening import newest_version

    newest = newest_version(engine)

    def check_for(entity_id: str):
        """(sort key, Check). The key is the ISO date, never the shown one:
        "10 June 2026" sorts before "13 August 2026" as text, which would
        order the list convincingly and wrongly."""
        record = latest.get(entity_id)
        kind = PARTY_KINDS.get(str(graph.kind_of(entity_id) or ""), "")
        if record is None:
            return "", Check(who=qualified_name(graph, entity_id, shared),
                             kind=kind, when="", result=NO_CHECK,
                             tone="stop", ref=entity_id)
        if record["matches"]:
            found = (f"{record['matches']} "
                     f"{_plural(record['matches'], 'match', 'matches')} to review")
            tone = "today"
        else:
            found, tone = NOTHING_FOUND, "settled"
        behind = bool(newest) and record.get("version", "") != newest
        return record["when"], Check(
            who=qualified_name(graph, entity_id, shared), kind=kind,
            when=_date(record["when"]), result=found, tone=tone, ref=entity_id,
            currency=OUT_OF_DATE_CHECK if behind else "")

    checks = [check_for(entity_id) for entity_id in customers]
    unchecked = [check for _, check in checks if check.result == NO_CHECK]
    checked = [check for _, check in
               sorted((pair for pair in checks if pair[1].result != NO_CHECK),
                      key=lambda pair: pair[0])]

    total = len(customers)
    done = len(checked)
    missing = len(unchecked)
    if not total:
        summary, tone = "No party has committed to a fund yet.", "settled"
    elif missing:
        summary = (
            f"{total} {_plural(total, 'party', 'parties')} "
            f"{_plural(total, 'has', 'have')} committed money to a fund. "
            f"{done} {_plural(done, 'has', 'have')} been checked against the "
            f"watchlists. {missing} {_plural(missing, 'has', 'have')} no "
            f"record of a check."
        )
        tone = "stop"
    else:
        summary = (
            f"All {total} {_plural(total, 'party', 'parties')} who have "
            f"committed money to a fund have been checked against the "
            f"watchlists."
        )
        tone = "settled"

    behind = sum(1 for check in checked if check.currency)
    out_of_date = (
        OUT_OF_DATE_SUMMARY.format(n=behind,
                                   were=_plural(behind, "was", "were"))
        if behind else ""
    )

    clause = CLAUSES.get("5.9")
    hidden = max(0, len(unchecked) - per_list)
    return Screening(
        heading="Watchlist screening",
        coverage_summary=summary,
        coverage_tone=tone,
        scope_note=SCREENING_SCOPE_NOTE if total else "",
        rule_heading="The rule behind this",
        rule_says=(PLAIN_RULES.get("5.9", clause.heading) if clause else ""),
        rule_clause=(f"Clause {clause.clause_id}" if clause else ""),
        rule_caveat=SCREENING_INTERVAL_CAVEAT,
        out_of_date=out_of_date,
        link=(DOCUMENTS[clause.doc_id].url if clause else ""),
        unchecked_heading="Nobody has checked these",
        unchecked=tuple(unchecked[:per_list]),
        unchecked_more=(
            f"Showing {per_list} of {len(unchecked)}." if hidden else ""
        ),
        checked_heading="Checks on record, oldest first",
        checked=tuple(checked),
        checked_none=("No check has been recorded against any customer."
                      if not checked else ""),
        back=UI["back_to_queue"],
    )
