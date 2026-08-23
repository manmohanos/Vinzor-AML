"""What makes a customer high risk, in the regulator's own list.

Clause 4.2 of the IFSCA guidelines names nineteen things a Regulated Entity
"shall take into account" when judging whether a customer is high risk, in
three groups: the customer, the country, and the product or channel. This
module holds that list, looks for the ones we can see in our own records,
and leaves the rest to a person.

Three decisions run through all of it, and each comes from the clause
itself rather than from taste:

* **No score, and no automatic category.** Clause 4.2 closes with the
  sentence "the presence of one or more risk factors alone may not always
  indicate a high risk of ML/TF in a particular situation". A system that
  added the factors up and announced an answer would be contradicting the
  rule it claims to implement. So this module presents evidence; a named
  person sets the category and writes why.
* **A factor nobody has looked at says so.** Every factor is present,
  absent, or *not yet assessed* -- three states, not two. Recording silence
  as "absent" would let an unexamined customer read as a clean one.
* **The categorisation is confidential.** Clause 4.1(d), inserted by the
  circular of 2 January 2026, requires that the risk category and the
  reasons for it are kept from the customer, to avoid tipping off. Nothing
  here may be rendered on a customer-facing surface.

The wording of each factor is quoted from the document, including where the
document is itself irregular: group (a) numbers two different items "(iv)".
That is the regulator's numbering, not a transcription error, and it is
reproduced rather than tidied -- an officer looking for "4.2(a)(iv)" in the
PDF must find what we showed them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .graph import Conclusion
from .model import EntityKind, EventType

# ---------------------------------------------------------------------------
# the list itself
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Factor:
    """One thing clause 4.2 says to take into account."""

    ref: str
    group: str
    #: Quoted from the guidelines. Shortened only by dropping the leading
    #: "Whether", which every item shares and no reader needs repeated.
    wording: str
    #: Whether our own records can speak to this at all. Where False, the
    #: answer can only come from a person -- and saying so is more useful
    #: than leaving a reader to wonder why we never filled it in.
    we_can_look: bool = False


CUSTOMER = "The customer"
COUNTRY = "The country"
CHANNEL = "The product or channel"

FACTORS: tuple[Factor, ...] = (
    # -- (a) Customer risk ------------------------------------------------
    Factor("4.2(a)(i)", CUSTOMER,
           "the customers are from high risk businesses, activities or "
           "sectors, as well as from other sectors as may be identified by "
           "the Regulated Entity"),
    Factor("4.2(a)(ii)", CUSTOMER,
           "the ownership structure of the legal person or arrangement "
           "appears unusual or excessively complex",
           we_can_look=True),
    Factor("4.2(a)(iii)", CUSTOMER,
           "the business relations are conducted under unusual "
           "circumstances, such as significant unexplained geographic "
           "distance between the Regulated Entity and the customer"),
    # The guidelines number the next two items (iv) and (iv). Reproduced as
    # published; see the module docstring.
    Factor("4.2(a)(iv)", CUSTOMER,
           "the companies have nominee shareholders or shares in bearer "
           "form"),
    Factor("4.2(a)(iv, second)", CUSTOMER,
           "the legal persons or legal arrangements are personal asset "
           "holding vehicles",
           we_can_look=True),
    Factor("4.2(a)(v)", CUSTOMER,
           "the corporate structure of the customer is unusual or "
           "excessively complex given the nature of the business"),

    # -- (b) Country or Geographic risk -----------------------------------
    Factor("4.2(b)(i)", COUNTRY,
           "the countries or jurisdictions the Regulated Entity is exposed "
           "to have relatively high levels of corruption, organized crime "
           "or inadequate AML/CFT measures, as identified by the FATF",
           we_can_look=True),
    Factor("4.2(b)(ii)", COUNTRY,
           "the countries or jurisdictions are identified by any credible "
           "body as having significant levels of corruption, terrorism "
           "financing or other criminal activities"),
    Factor("4.2(b)(iii)", COUNTRY,
           "the countries or jurisdictions are identified by credible "
           "sources, such as mutual evaluation or detailed assessment "
           "reports, as not having adequate AML/CFT systems",
           we_can_look=True),
    Factor("4.2(b)(iv)", COUNTRY,
           "the countries or jurisdictions do not have effective systems to "
           "counter ML/TF, or are not implementing AML/CFT measures "
           "consistent with FATF recommendations",
           we_can_look=True),
    Factor("4.2(b)(v)", COUNTRY,
           "the countries or jurisdictions are subject to sanctions, "
           "embargos or similar measures issued by International "
           "Organisations or India",
           we_can_look=True),
    Factor("4.2(b)(vi)", COUNTRY,
           "the countries or jurisdictions are funding or supporting "
           "terrorism"),
    Factor("4.2(b)(vii)", COUNTRY,
           "the countries or jurisdictions have organizations operating "
           "within their territory that have been designated as terrorist "
           "organizations"),

    # -- (c) Product, service, transaction or delivery channel ------------
    Factor("4.2(c)(i)", CHANNEL,
           "the service involves private banking"),
    Factor("4.2(c)(ii)", CHANNEL,
           "the product, service or transaction is one that might favour "
           "anonymity"),
    Factor("4.2(c)(iii)", CHANNEL,
           "the situation involves non-face-to-face business relationships "
           "or transactions, without adequate safeguards"),
    Factor("4.2(c)(iv)", CHANNEL,
           "the payments received are from unknown or unassociated third "
           "parties",
           we_can_look=True),
    Factor("4.2(c)(v)", CHANNEL,
           "the services offered are in relation to nominee directors, "
           "nominee shareholders or the formation of companies in another "
           "country"),
    Factor("4.2(c)(vi)", CHANNEL,
           "there are anonymous transactions, or any transaction which "
           "involves frequent payments received from unknown or "
           "unassociated third parties",
           we_can_look=True),
)

BY_REF: Mapping[str, Factor] = {f.ref: f for f in FACTORS}


# ---------------------------------------------------------------------------
# the country lists clause 4.2(b) points at
# ---------------------------------------------------------------------------

#: The FATF plenary these lists were taken from. Carried with the data
#: because a country list without its date is a claim about today that will
#: quietly become false: the FATF revises these three times a year.
FATF_AS_AT = "2026-06-19"

#: "High-Risk Jurisdictions subject to a Call for Action" -- the black list.
CALL_FOR_ACTION = frozenset({"IR", "KP", "MM"})

#: "Jurisdictions under Increased Monitoring" -- the grey list.
INCREASED_MONITORING = frozenset({
    "AO", "BO", "BA", "BG", "CM", "CI", "CD", "HT", "IQ", "KE", "KW", "LA",
    "LB", "MC", "NP", "PG", "SS", "SY", "VE", "VN", "VG", "YE",
})

#: Where a party's country can be recorded. All of them are looked at: a
#: customer incorporated in one place and resident in another is exposed
#: through both, which is what "exposed to" in 4.2(b)(i) means.
COUNTRY_FIELDS = ("nationality", "country_of_residence",
                  "country_of_incorporation", "jurisdiction")

#: An ownership chain longer than this is the "excessively complex" the
#: clause describes. Four layers is where the expert reading of these
#: structures says people stop being able to follow them by hand.
DEEP_CHAIN = 4


# ---------------------------------------------------------------------------
# what our own records can say
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """What we found about one factor, and what we looked at to find it."""

    ref: str
    #: True, False, or None for "nobody has established this either way".
    present: Optional[bool]
    because: str = ""
    #: Set where a person answered rather than the records.
    answered_by: str = ""


@dataclass
class Assessment:
    """A customer's risk assessment as it currently stands."""

    entity_id: str
    observations: dict = field(default_factory=dict)
    category: str = ""
    reason: str = ""
    by: str = ""
    on: str = ""
    seq: int = 0

    @property
    def settled(self) -> bool:
        return bool(self.category)

    def answered(self) -> int:
        return sum(1 for o in self.observations.values()
                   if o.present is not None)

    def present(self) -> list:
        return [o for o in self.observations.values() if o.present]


def _countries_of(entity) -> list[tuple[str, str]]:
    out = []
    for field_name in COUNTRY_FIELDS:
        code = str((entity.attributes or {}).get(field_name) or "").upper()
        if len(code) == 2:
            out.append((field_name.replace("_", " "), code))
    return out


#: Months as a reader writes them. A date on a screen is written the way a
#: person writes one; the ISO form is for storing, not for reading.
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _written(iso: str) -> str:
    try:
        year, month, day = (int(part) for part in str(iso)[:10].split("-"))
        return f"{day} {_MONTHS[month - 1]} {year}"
    except (ValueError, IndexError):
        return str(iso)


def _named(codes) -> str:
    from .countries import COUNTRIES

    return ", ".join(sorted(COUNTRIES.get(c, c) for c in codes))


def observe(engine, entity_id: str) -> dict:
    """Look for every factor our own records can speak to.

    Returns one Observation per factor we can look at. Factors we cannot
    see are left out entirely rather than recorded as absent -- the caller
    renders them as unanswered, which is what they are.
    """
    graph = engine.state.graph
    entity = graph.entities.get(entity_id)
    if entity is None:
        raise KeyError(entity_id)

    found: dict = {}

    def note(ref: str, present: bool, because: str) -> None:
        found[ref] = Observation(ref=ref, present=present, because=because)

    # -- 4.2(a)(ii) and the second (iv): what the structure looks like ----
    result = graph.resolve_ubo(entity_id)
    # An owner can be reached by more than one route through the structure;
    # the longest is what makes it hard to follow, so that is the depth.
    depth = max((len(route) for owner in result.owners
                 for route in owner.paths), default=0)
    if result.cycles:
        note("4.2(a)(ii)", True,
             "the ownership declared for this party runs in a circle, so no "
             "natural person can be reached through it")
    elif result.conclusion is Conclusion.INCOMPLETE:
        note("4.2(a)(ii)", True,
             "the ownership chain cannot be completed from what has been "
             "declared")
    elif depth >= DEEP_CHAIN:
        note("4.2(a)(ii)", True,
             f"ownership runs through {depth} layers before reaching a "
             f"natural person")
    elif result.conclusion is Conclusion.IDENTIFIED:
        note("4.2(a)(ii)", False,
             f"ownership resolves to a named person through {depth} "
             f"layer(s)")

    if entity.kind is EntityKind.TRUST:
        note("4.2(a)(iv, second)", True,
             "this party is a trust, which is a legal arrangement of the "
             "kind the clause describes")
    elif entity.kind in (EntityKind.COMPANY, EntityKind.PARTNERSHIP,
                         EntityKind.FUND):
        note("4.2(a)(iv, second)", False,
             "this party is an operating form rather than a holding "
             "arrangement, on what has been recorded")

    # -- 4.2(b): the countries this party is exposed through --------------
    countries = _countries_of(entity)
    black = {c for _, c in countries if c in CALL_FOR_ACTION}
    grey = {c for _, c in countries if c in INCREASED_MONITORING}

    if black:
        for ref in ("4.2(b)(i)", "4.2(b)(iii)", "4.2(b)(iv)", "4.2(b)(v)"):
            note(ref, True,
                 f"{_named(black)} is on the FATF list of jurisdictions "
                 f"subject to a call for action, as at "
                 f"{_written(FATF_AS_AT)}")
    elif grey:
        for ref in ("4.2(b)(i)", "4.2(b)(iii)", "4.2(b)(iv)"):
            note(ref, True,
                 f"{_named(grey)} is on the FATF list of jurisdictions "
                 f"under increased monitoring, as at "
                 f"{_written(FATF_AS_AT)}")
        note("4.2(b)(v)", False,
             f"{_named(grey)} is not subject to a call for action")
    elif countries:
        where = ", ".join(f"{what} {_named([code])}"
                          for what, code in countries)
        for ref in ("4.2(b)(i)", "4.2(b)(iii)", "4.2(b)(iv)", "4.2(b)(v)"):
            note(ref, False,
                 f"neither FATF list names {where}, as at "
                 f"{_written(FATF_AS_AT)}")

    # -- 4.2(c)(iv) and (vi): where the money came from -------------------
    #
    # This used to collect two rules: a payment from another party, and a
    # payment that arrived with no sender on it at all. The second was
    # removed on 21 August 2026, and the wording below had to move with it.
    # It is the reason this block is worth reading twice: an absence is only
    # reportable if something looked, and nothing looks for a payment with no
    # sender any more. A regulatory risk factor that says "nothing found"
    # when nothing was examined is the exact failure this product exists to
    # prevent, so what is printed now says only what is still checked.
    from_others = []
    for case in engine.state.casebook.cases.values():
        if case.subject != entity_id or case.case_type != "PAYMENT_MISMATCH":
            continue
        for evidence in case.evidence:
            if "THIRD_PARTY" in str(evidence.policy_id or ""):
                from_others.append(case)
                break

    if from_others:
        note("4.2(c)(iv)", True,
             f"{len(from_others)} payment(s) to this party came from "
             f"someone other than the party itself")
        note("4.2(c)(vi)", len(from_others) > 1,
             f"{len(from_others)} such payment(s) have been recorded")
    else:
        paid = any(case.subject == entity_id
                   and case.case_type == "PAYMENT_MISMATCH"
                   for case in engine.state.casebook.cases.values())
        if paid:
            note("4.2(c)(iv)", False,
                 "no payment to this party has come from a sender other "
                 "than the party itself; payments arriving with no sender "
                 "recorded are not examined")

    return found


def unanswered(assessment: Optional[Assessment]) -> list[Factor]:
    """The factors still waiting on a person."""
    seen = assessment.observations if assessment else {}
    return [f for f in FACTORS
            if seen.get(f.ref) is None or seen[f.ref].present is None]


# ---------------------------------------------------------------------------
# when the customer has to be looked at again -- clause 5.11
# ---------------------------------------------------------------------------

#: How long may pass before a customer's due diligence is refreshed, by
#: category. Clause 5.11 sets these; they are not ours to choose, which is
#: why they are written here as the clause writes them rather than as
#: configuration.
EVERY_YEARS: Mapping[str, int] = {"HIGH": 1, "MEDIUM": 3, "LOW": 5}

#: The proviso inserted by the circular of 2 January 2026: a resident
#: Indian customer who already has a relationship with the Financial Group
#: in India may be refreshed less often, because the group already holds
#: the diligence.
EVERY_YEARS_IN_GROUP: Mapping[str, int] = {"HIGH": 2, "MEDIUM": 8, "LOW": 10}


@dataclass(frozen=True)
class Due:
    """When a customer must next be looked at, and on what authority."""

    on: str
    years: int
    category: str
    clause: str = "5.11"
    #: Why this interval and not another -- the sentence an officer reads.
    because: str = ""


def _add_years(iso: str, years: int) -> str:
    """The same day, some years later. 29 February becomes 28 February in a
    year that has no 29th, which is the only ambiguity the calendar offers
    and the conservative reading of it."""
    year, month, day = (int(part) for part in str(iso)[:10].split("-"))
    year += years
    if month == 2 and day == 29:
        leap = year % 4 == 0 and (year % 100 or year % 400 == 0)
        if not leap:
            day = 28
    return f"{year:04d}-{month:02d}-{day:02d}"


def days_late(due_on: str, today: str) -> int:
    """How long a review has been owed. Never negative -- a date that has not
    arrived is not lateness of zero days, it is not lateness at all, and the
    callers of this only ask about instances already past."""
    from datetime import date

    def _d(iso: str) -> date:
        return date(*(int(part) for part in str(iso)[:10].split("-")))

    return max(0, (_d(today) - _d(due_on)).days)


def next_review(category: str, since: str, *, in_financial_group: bool = False,
                group_category: str = "") -> Optional[Due]:
    """When this customer's diligence must next be refreshed.

    ``since`` is the date the account was opened or the diligence last
    updated, which is what clause 5.11 measures from.

    Where the customer is inside an Indian Financial Group and that group
    has categorised them differently, the clause says the stricter of the
    two periodicities applies -- so both are worked out and the shorter
    interval wins. Stated in the reason, because an officer asked to
    justify a date should not have to reconstruct which of two rules
    produced it.
    """
    category = str(category or "").upper()
    if category not in EVERY_YEARS:
        return None

    schedule = EVERY_YEARS_IN_GROUP if in_financial_group else EVERY_YEARS
    years = schedule[category]
    because = (f"{category.lower()} risk, refreshed every "
               f"{years} year{'s' if years != 1 else ''} under clause 5.11")

    other = str(group_category or "").upper()
    if in_financial_group and other in schedule and other != category:
        theirs = schedule[other]
        if theirs < years:
            because = (
                f"the group holding this customer rates them "
                f"{other.lower()} risk where we rate them "
                f"{category.lower()}; clause 5.11 applies the stricter of "
                f"the two, so every {theirs} "
                f"year{'s' if theirs != 1 else ''} rather than {years}"
            )
            years = theirs
        else:
            because += (f"; the group rates them {other.lower()}, which "
                        f"would be less often, so ours applies")

    return Due(on=_add_years(since, years), years=years, category=category,
               because=because)


def due_for_review(engine, today: str) -> list:
    """Every customer whose refresh date has arrived, soonest first.

    A customer nobody has categorised is not listed here. That is not an
    oversight to be papered over with a default: clause 5.11 keys the
    interval to a category, so without one there is no date to be past, and
    the thing that needs doing is the assessment rather than the refresh.
    ``never_assessed`` is what surfaces those.
    """
    out = []
    for entity_id, assessment in engine.state.risk.items():
        if not assessment.settled:
            continue
        due = next_review(assessment.category, assessment.on)
        if due and due.on <= str(today)[:10]:
            out.append((entity_id, assessment, due))
    out.sort(key=lambda row: row[2].on)
    return out


def never_assessed(engine) -> list:
    """Parties carrying no risk category at all.

    Every customer needs one -- it is what clause 5.11 keys the refresh
    interval to -- so a party without one is not merely unrated, it is
    outside the periodic-review regime entirely.
    """
    return [entity_id for entity_id in engine.state.graph.entities
            if entity_id not in engine.state.risk
            or not engine.state.risk[entity_id].settled]


# ---------------------------------------------------------------------------
# what the watchlists found, put in front of the person categorising
# ---------------------------------------------------------------------------

#: What each kind of watchlist match is called on a screen. Never the code.
MATCH_WORDS = {
    "SANCTIONS": "may be on a sanctions list",
    "PEP": "may hold or be close to public office",
    "ADVERSE_MEDIA": "has been written about in the press",
    "WATCHLIST": "matched a watchlist this register does not yet classify",
}


@dataclass(frozen=True)
class WhatScreeningFound:
    """Watchlist matches on one party, and what the clauses ask of them.

    Deliberately not a clause 4.2 factor. None of the nineteen covers a
    watchlist match: 4.2(a) is about the customer's structure and sector,
    4.2(b) about countries, 4.2(c) about products and channels. Screening
    is governed by clause 5.9, and a match on somebody in public office by
    clause 5.5. Filing it under a 4.2 bullet that does not say it would be
    the invented citation this register refuses everywhere else -- so it
    sits beside the factors instead, cited to the clauses that do say it.
    """

    matched: bool
    kinds: tuple[str, ...] = ()
    summary: str = ""
    guidance: tuple[str, ...] = ()
    open_files: int = 0
    #: Whether anybody has ever run a watchlist check on this party.
    #: Separate from ``matched`` because the two used to share a sentence:
    #: a party nobody had screened read exactly like a party screened and
    #: found clean, on the screen where somebody decides how risky they
    #: are. Not knowing and knowing nothing is there are different answers,
    #: and only one of them is reassuring.
    ever_checked: bool = False
    #: The day of the most recent check, and whether that check found the
    #: match. A party delisted in April still matched in March, and an
    #: officer needs both halves of that.
    last_checked: str = ""
    still_listed: bool = False


#: Guidance Note (4) under clause 5.5. Quoted because it is the sentence
#: that decides how this screen behaves, and because a reader who is about
#: to categorise somebody in public office should see the regulator saying
#: it rather than us paraphrasing it.
PEP_IS_NOT_AUTOMATICALLY_HIGH = (
    "The guidelines say a Regulated Entity should not automatically treat "
    "everyone who holds public office as high risk. Each is to be assessed "
    "on a risk-sensitive basis, and the firm determines what category is "
    "appropriate \u2014 Guidance Note (4) under clause 5.5."
)

PEP_MEASURES_APPLY_ANYWAY = (
    "Whatever category is set, the additional measures under clause 5.5(b) "
    "still apply \u2014 source of wealth, identity verified before "
    "acceptance, senior management approval, and closer ongoing "
    "monitoring. If the category is high, clause 5.6 enhanced due "
    "diligence applies on top."
)


def what_screening_found(engine, entity_id: str) -> WhatScreeningFound:
    """Every watchlist match recorded against this party.

    Read from the screening records themselves rather than from the files
    they opened, so a match still shows here after its file has been
    settled -- an officer categorising somebody needs to know they matched,
    not only that somebody once had a file about it.
    """
    kinds: list[str] = []
    last_checked = ""
    latest_matched = False
    for event in engine.log:
        if event.event_type is not EventType.SCREENING_COMPLETED:
            continue
        if event.subject != entity_id:
            continue
        payload = event.payload or {}
        when = str(event.occurred_at)[:10]
        if when > last_checked:
            last_checked, latest_matched = when, bool(payload.get("matched"))
        elif when == last_checked and payload.get("matched"):
            # Several records can share a day -- one per watchlist entity
            # matched. A day on which anything matched is a day that
            # matched.
            latest_matched = True
        if not payload.get("matched"):
            continue
        # Every kind, not only the one the match is filed under. A
        # sanctioned head of state is filed under sanctions and is also
        # politically exposed; reading one value meant the officer
        # categorising them was shown "may be on a sanctions list" and
        # never the guidance about public office that clause 5.5 turns on.
        for kind in (payload.get("list_types")
                     or [payload.get("list_type") or "WATCHLIST"]):
            kind = str(kind)
            if kind not in kinds:
                kinds.append(kind)

    if not last_checked:
        return WhatScreeningFound(
            matched=False, ever_checked=False,
            summary=("Nobody has run a watchlist check on this party. That "
                     "is not the same as a check that found nothing — "
                     "this party has not been looked for."))

    if not kinds:
        return WhatScreeningFound(
            matched=False, ever_checked=True, last_checked=last_checked,
            summary=(f"A watchlist check on {_written(last_checked)} found "
                     f"nothing against this party."))

    open_files = sum(
        1 for case in engine.state.casebook.cases.values()
        if case.subject == entity_id
        and case.case_type == "SCREENING_HIT" and case.is_open)

    said = _join([MATCH_WORDS.get(kind, MATCH_WORDS["WATCHLIST"])
                  for kind in kinds])
    summary = f"A watchlist check found that this party {said}."
    if open_files:
        summary += (f" {_counted(open_files, 'file is', 'files are')} still "
                    f"open about it.")

    guidance = []
    if not latest_matched:
        # The lists change. A party removed from one still matched when
        # they were on it, and both halves belong on the screen: hiding
        # the match would lose why the file exists, and hiding the later
        # clean check leaves somebody categorised against a listing that
        # no longer exists.
        summary += (f" The most recent check, on {_written(last_checked)}, "
                    f"found nothing.")
    if "PEP" in kinds:
        guidance = [PEP_IS_NOT_AUTOMATICALLY_HIGH, PEP_MEASURES_APPLY_ANYWAY]
    return WhatScreeningFound(matched=True, kinds=tuple(kinds),
                              summary=summary, guidance=tuple(guidance),
                              open_files=open_files, ever_checked=True,
                              last_checked=last_checked,
                              still_listed=latest_matched)


def _join(parts) -> str:
    parts = list(parts)
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _counted(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"
