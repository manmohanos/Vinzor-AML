"""What IFSCA has actually enforced against — and how much of it we would catch.

This is a scorecard, not a feature. It exists because we have no design
partners yet and will not have one for some weeks, and guessing at what matters
is the most expensive mistake available to us. The regulator has already
published the answer: between July 2024 and June 2026 IFSCA took **25
enforcement actions** against entities in the IFSC, and the grounds are a
matter of public record.

**Reading them changed what I think this product is for.** The actions cluster
on operational and governance failure — an empty office during an inspection, a
quarterly return not filed, a principal officer who is not there, fees unpaid,
activity outside the authorised scope. AML and KYC breaches appear, but they
are not what most often costs an entity its registration. One of the actions is
against a Fund Management Entity for exactly the thing we do not model: its
principal officer and key managerial personnel were absent when IFSCA came to
look.

So this module scores us honestly against that record. Most of it we would miss
today. That is the intended result: a benchmark we fail is worth more than a
feature we invented, because it makes the roadmap argue for itself.

**Provenance.** Twenty-five actions are known to exist; eight are recorded here
in enough detail to score, taken from law-firm analyses and the regulator's
enforcement page rather than from the primary orders themselves. Each carries
its ``source``, and ``read_from_primary`` is False for all of them until someone
reads the orders. Treat the scorecard as indicative, and do not quote the counts
at anyone without checking them.

Two honest caveats about the benchmark itself, which the numbers cannot show:

* Enforcement counts measure what a regulator detects and publishes, not what
  is most harmful. Laundering is rarer, far harder to spot, and catastrophic
  when missed. A low AML count is not evidence that AML controls do not matter.
* Twenty-five actions from a young regulator ramping up its supervision is a
  small sample, and the mix will change.
* The score is currently **8 of 8, but 4 only through PARTIAL coverage** —
  half of what we would surface, we would only partly catch. Summaries of the
  full twenty-five do mention KYC/AML lapses, but none of the eight recorded
  here in detail was taken on that ground, so the one thing we cover most
  deeply never gets a chance to fire. The honest reading is not "our AML work
  is worthless" — it is "AML alone would have prevented none of the failures
  we can currently see."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .model import StrEnum
from typing import Mapping, Optional, Sequence


class Ground(StrEnum):
    """The kind of failure an action was taken for."""

    GOVERNANCE = "GOVERNANCE"        # people and premises: KMPs absent, office shut
    REPORTING = "REPORTING"          # periodic filings missed or late
    CAPITAL = "CAPITAL"              # minimum net worth / capital not maintained
    SCOPE = "SCOPE"                  # activity beyond what the licence permits
    COOPERATION = "COOPERATION"      # did not answer the regulator
    FEES = "FEES"                    # regulatory fees unpaid
    AML_KYC = "AML_KYC"              # customer due diligence, screening, monitoring
    DISCLOSURE = "DISCLOSURE"        # misstatement in filings or accounts


#: Counted from IFSCA's own enforcement page, July 2024 to July 2026. An
#: earlier version said 23, taken from a law-firm summary; the regulator's
#: own list has 25. Kept separate from the detailed list so the gap between
#: "known" and "scored" stays visible.
#: https://ifsca.gov.in/Pages/Contents/Enforcement-Actions
PUBLISHED_ACTIONS = 25


@dataclass(frozen=True)
class Action:
    entity: str
    entity_type: str
    date: str
    grounds: tuple[Ground, ...]
    conduct: str
    outcome: str
    source: str
    #: True only once someone has read IFSCA's own order rather than a summary.
    read_from_primary: bool = False


ACTIONS: Sequence[Action] = (
    Action(
        entity="Neo Asset Management Private Limited",
        entity_type="Fund Management Entity",
        date="2025-05",
        grounds=(Ground.GOVERNANCE,),
        conduct="On surprise Market Intelligence visits of 31 July, 21 August, "
                "17 October and 24 October 2024 the IFSC office was found closed "
                "and neither the Principal Officer nor other KMP were present. "
                "An advisory letter of 12 September 2024 was neither collected "
                "nor acknowledged. Held to breach Regulation 7(4) and Regulation "
                "10(1) of the Fund Management Regulations, 2022 — carried into "
                "the 2025 Regulations at Regulation 7(5).",
        outcome="Warning. Cancellation and monetary penalty were considered and "
                "not imposed, the entity having taken corrective measures "
                "including mandating full presence of the PO and KMP.",
        source="IFSCA Order F.No. IFSCA-RPRA0EFD/8/2024-RPRA, 2 May 2025, under "
               "Regulation 143 of the IFSCA (Fund Management) Regulations, 2022",
        read_from_primary=True,
    ),
    Action(
        entity="Karvy Broking (IFSC) Limited",
        entity_type="Broker",
        date="2026-05-21",
        grounds=(Ground.REPORTING, Ground.COOPERATION),
        conduct="Quarterly reports were still not submitted after a warning "
                "letter, breaching the Quarterly Report Circular read with "
                "Regulation 15(2) of the Capital Market Intermediaries "
                "Regulations, 2021 and Regulations 17(3) and 47(3) of the 2025 "
                "Regulations. A show cause notice of 16 January 2026 could not be "
                "delivered by post or e-mail and was served by affixture on 10 "
                "March 2026; the entity neither replied nor attended the hearing "
                "of 24 March 2026, and the matter proceeded ex parte.",
        outcome="Registration cancelled.",
        source="IFSCA Order F.No. IFSCA-RPRA0EFD/17/2025-RPRA, 21 May 2026",
        read_from_primary=True,
    ),
    Action(
        entity="Darwin Platform Aircraft Leasing",
        entity_type="Finance Company (aircraft lessor)",
        date="2024-07",
        grounds=(Ground.CAPITAL, Ground.REPORTING, Ground.GOVERNANCE,
                 Ground.COOPERATION),
        conduct="Minimum capital of USD 0.2M never infused; commencement of "
                "operations not communicated; mandatory filings missing; office "
                "closed during surprise visits; did not cooperate.",
        outcome="Registration cancelled.",
        source="Cyril Amarchand Mangaldas, India Corporate Law, June 2025",
    ),
    Action(
        entity="Prowess Insurance Brokers Private Limited",
        entity_type="Insurance Broker",
        date="2025-02",
        grounds=(Ground.SCOPE, Ground.DISCLOSURE),
        conduct="Continued writing new business despite a regulatory "
                "prohibition; carried on unauthorised reinsurance activity; "
                "recorded reinsurance income as risk management fees.",
        outcome="Authorisation cancelled.",
        source="Cyril Amarchand Mangaldas, India Corporate Law, June 2025",
    ),
    Action(
        entity="PBG Smart Accounts LLP",
        entity_type="Ancillary Service Provider",
        date="2024-10",
        grounds=(Ground.SCOPE,),
        conduct="Provided services to recipients not eligible under the "
                "Ancillary Services Framework.",
        outcome="Warning letter; ordered to cease and to repay tax benefits "
                "claimed.",
        source="Cyril Amarchand Mangaldas, India Corporate Law, June 2025",
    ),
    Action(
        entity="String AI IFSC Private Limited",
        entity_type="Regulated entity",
        date="2026-04-06",
        grounds=(Ground.GOVERNANCE, Ground.COOPERATION),
        conduct="Inadequate infrastructure and non-cooperation with the "
                "regulator.",
        outcome="Registration cancelled.",
        source="ADI International, IFSCA enforcement summary",
    ),
    Action(
        entity="Bonanza Portfolio IFSC Private Limited",
        entity_type="Broker",
        date="2026-05-27",
        grounds=(Ground.SCOPE,),
        conduct="Unauthorised global access trading.",
        outcome="Penalty and directions.",
        source="ADI International, IFSCA enforcement summary",
    ),
    Action(
        entity="Ashoka WhiteOak Capital Management LLP",
        entity_type="Fund Management Entity",
        date="2026-06-02",
        grounds=(Ground.SCOPE,),
        conduct="Distribution services provided without registration; personal "
                "investments made in its own funds.",
        outcome="Penalty.",
        source="ADI International, IFSCA enforcement summary",
    ),
)


# ---------------------------------------------------------------------------
# What we would and would not have caught
# ---------------------------------------------------------------------------


class Level(StrEnum):
    FULL = "FULL"
    #: The precondition is surfaced, but not the thing the regulator
    #: actually observes. Counted as coverage, reported separately.
    PARTIAL = "PARTIAL"
    NONE = "NONE"


@dataclass(frozen=True)
class Capability:
    """Whether the system can surface a ground, and what it would take."""

    level: Level
    position: str
    needs: str = ""
    caveat: str = ""

    @property
    def covered(self) -> bool:
        return self.level is not Level.NONE


#: Assessed against what the engine does today, not what it could do.
COVERAGE: Mapping[Ground, Capability] = {
    Ground.AML_KYC: Capability(
        level=Level.FULL,
        position="Sanctions and PEP matches, unresolved beneficial ownership, "
                 "a payer named on a sanctions list and a payment from a "
                 "party other than the investor open a Case with the clause "
                 "behind it.",
    ),
    Ground.GOVERNANCE: Capability(
        level=Level.PARTIAL,
        position="Regulation 7 is modelled: which posts the licence requires, "
                 "who holds each, whether the holder is recorded as based in "
                 "the IFSC, and the six-month clock once AUM passes USD 1bn. "
                 "A vacant or non-resident post opens a Case.",
        caveat="IFSCA established the Neo Asset failure by walking into the "
               "office on four separate days and finding it shut. No software "
               "sees an empty room. What is surfaced is the precondition, not "
               "the observation.",
    ),
    Ground.REPORTING: Capability(
        level=Level.PARTIAL,
        position="The quarterly report and the two recurring fees sit on a "
                 "calendar derived from the circulars, with deadlines, the USD "
                 "100-a-month late charge, and escalation once more than one "
                 "period is outstanding. Lateness is observed at a boundary and "
                 "recorded as an event.",
        caveat="Only three obligations are scheduled. AML/CFT returns, FATCA "
               "and CRS, scheme-level filings and KMP change intimations are "
               "all still absent, so a clean calendar does not mean everything "
               "owed has been filed.",
    ),
    Ground.CAPITAL: Capability(
        level=Level.PARTIAL,
        position="The minimum a licence category requires is held, the "
                 "firm's reported net worth is an event, and a figure "
                 "below the minimum opens a Case that stops everything. "
                 "Managing money that is not the firm's own adds to the "
                 "requirement.",
        caveat="The figures are not verified. They are what two law-firm "
               "readings of the Fund Management Regulations report, agreeing "
               "with each other and with nothing primary, and when the "
               "twenty-one clauses in citations.py were finally checked "
               "against IFSCA's own text twelve had a real problem. Every "
               "screen using an unconfirmed figure says so, and a person can "
               "confirm the minimum that actually applies. Separately, "
               "nothing here can verify the reported figure is true -- that "
               "is an auditor's work, and Darwin's capital was never infused "
               "at all rather than misstated.",
    ),
    Ground.COOPERATION: Capability(
        level=Level.PARTIAL,
        position="A letter from a regulator is recorded with the date it "
                 "arrived and the date it set, and stays on the morning "
                 "screen until answered. Once the date passes, lateness is "
                 "observed at a boundary and opens a Case that stops "
                 "everything, citing Regulation 120. The answer is recorded "
                 "with who sent it and what it said, because the question "
                 "an inspector asks is not whether you replied.",
        caveat="Nothing puts the letter in. Somebody has to type it, which "
               "is the same weakness that lost Karvy its registration: a "
               "show cause notice served by affixture, because post and "
               "e-mail both failed. A firm not opening its post is not a "
               "firm this will save. What it does cover is the ordinary "
               "case -- a letter that arrived, was read, and was then "
               "forgotten about for six weeks.",
    ),
    Ground.FEES: Capability(
        level=Level.PARTIAL,
        position="The flat and turnover-based recurring fees are on the same "
                 "calendar, due 30 April of each year after the year of grant.",
        caveat="Activity-based and scheme-level fees are not scheduled, and the "
               "amounts themselves are not held — only the deadline.",
    ),
    Ground.SCOPE: Capability(
        level=Level.FULL,
        position="Regulation 3(4) fixes what each category may undertake and "
                 "Regulation 137 forbids anything else without prior approval. "
                 "Both are modelled; an activity outside the category opens a "
                 "Case at once.",
        caveat="Depends on the activity reaching the log. The system cannot "
               "discover business the entity never recorded.",
    ),
    Ground.DISCLOSURE: Capability(
        level=Level.PARTIAL,
        position="A return can carry the figures it claimed, and they are "
                 "shown beside what the book holds -- what was committed, "
                 "what arrived, how many investors and schemes. A figure "
                 "the records hold nothing at all for opens a Case.",
        caveat="Only the extreme case is raised, deliberately. Assets under "
               "management are properly not the sum of commitments -- "
               "capital is called in tranches and values move -- so a rule "
               "on the difference would fire every quarter of every firm's "
               "life and be switched off by March. The ordinary gap is "
               "shown and left to a person. And Prowess was cancelled for "
               "recording reinsurance income as risk management fees, which "
               "is a misclassification inside the accounts: nothing here "
               "sees the accounts.",
    ),
}


@dataclass(frozen=True)
class Score:
    published: int
    scored: int
    would_surface: int
    would_miss: int
    by_ground: Mapping[Ground, int]
    partial_only: int
    uncovered_grounds: tuple[Ground, ...]
    read_from_primary: int

    @property
    def percent(self) -> float:
        return 100.0 * self.would_surface / self.scored if self.scored else 0.0


def would_surface(action: Action) -> bool:
    """Could the engine have raised this before the regulator did?

    Generous by design: one covered ground is enough. Even so, most fail --
    which is the finding, not a defect in the scoring.
    """
    return any(COVERAGE[g].covered for g in action.grounds)


def scorecard(actions: Sequence[Action] = ACTIONS) -> Score:
    counts: dict[Ground, int] = {}
    for action in actions:
        for ground in action.grounds:
            counts[ground] = counts.get(ground, 0) + 1
    caught = [a for a in actions if would_surface(a)]
    # Caught only because a PARTIAL capability matched: worth saying aloud.
    partial = [
        a for a in caught
        if all(COVERAGE[g].level is not Level.FULL
               for g in a.grounds if COVERAGE[g].covered)
    ]
    return Score(
        published=PUBLISHED_ACTIONS,
        scored=len(actions),
        would_surface=len(caught),
        would_miss=len(actions) - len(caught),
        by_ground=dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        partial_only=len(partial),
        uncovered_grounds=tuple(
            g for g, _ in sorted(counts.items(), key=lambda kv: -kv[1])
            if not COVERAGE[g].covered
        ),
        read_from_primary=sum(1 for a in actions if a.read_from_primary),
    )


def roadmap(actions: Sequence[Action] = ACTIONS) -> list[tuple[Ground, int, str]]:
    """What to build next, ordered by how often it has actually cost someone.

    The regulator's enforcement record sets the priority, so the roadmap does
    not depend on anyone's opinion — including mine.
    """
    counts = scorecard(actions).by_ground
    return [
        (ground, count, COVERAGE[ground].needs)
        for ground, count in counts.items()
        if not COVERAGE[ground].covered
    ]
