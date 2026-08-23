"""A starting point for the risk category, and never the answer.

``risk.py`` gathers what this firm's own records can say about the nineteen
factors clause 4.2 names, and stops there on purpose: the clause closes by
saying that the presence of one or more factors "may not always indicate a
high risk", and a system that added them up and announced a category would
be contradicting the rule it claims to implement. ``engine.assess_risk``
takes the category from a named person, gated exactly as a decision is.

What sat between those two was nothing at all. An officer opened a customer,
read a list of observations, and set a category with no starting point --
which is not neutrality, it is work handed back. Every party page in this
product says "nobody has categorised this customer yet", and on a book of
several hundred that sentence is the whole problem: not that the officer
disagrees with the machine, but that there is nothing to agree or disagree
with, so nobody starts.

So this proposes a band and shows its arithmetic. Six commitments make that
safe to do under a rule that forbids deciding.

**It is data, not code.** The weights below are a table with a version
stamped on it, the same way ``policies.RULEPACK`` versions the rules. A
proposal records which version produced it, so a firm asked in two years why
this customer was rated medium can answer with the scorecard as it stood, not
as it stands.

**Nothing here writes anything.** There is no engine parameter in this
module and no event. The proposal is handed to a screen; the officer's
category still travels through ``assess_risk`` and is still the only thing
recorded. A test holds that structurally.

**An unassessed factor is never a zero.** It is carried as unassessed and
counted separately, and the proposal says how many of the nineteen nobody
has answered. Scoring silence as absence is how a customer nobody examined
reads as a customer with nothing wrong -- which is this codebase's oldest
mistake wearing its most respectable clothes.

**No single factor decides.** No weight is large enough on its own to reach
the high band, because clause 4.2 says one factor may not always indicate
high risk and a scorecard that let one do so would be that sentence with
extra steps. A test proves it for every factor, so the property survives
somebody retuning the numbers.

**The high band stays reachable.** The EBA guidelines warn about scorecards
tuned so that nothing ever scores high. A test proves the band is reachable
from real combinations rather than only in principle.

**The proposal is confidential like the category it suggests.** Clause
4.1(d), inserted 2 January 2026, keeps the category and its reasons from the
customer. A proposal is the reasons, so it belongs on the same side of that
line and never on a customer-facing surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from .risk import FACTORS, Assessment, Observation

#: Stamped into every proposal. Bump on any change to a weight, a band edge
#: or the cap below: a proposal is shown beside a category somebody then puts
#: their name to, and "which scorecard said that" must have an answer.
SCORECARD = "2026-08-23.1"

LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"

#: Points at or above which a proposal lands in each band. Two numbers, so
#: the whole shape of the thing is legible: below the first is low, at or
#: above the second is high.
MEDIUM_AT = 3
HIGH_AT = 7

#: The most any one factor may contribute. Clause 4.2's closing sentence in
#: arithmetic: no single observation reaches HIGH_AT, so no single factor can
#: propose a high category by itself. Enforced by a test over every weight,
#: not merely by the weights happening to be small today.
MOST_ONE_FACTOR_MAY_WEIGH = HIGH_AT - 1

#: What each factor contributes when present. Absent from this table means a
#: factor this firm's records cannot speak to -- it can still be answered by
#: a person, and then it weighs what the table says or nothing if it is not
#: here. Weights are deliberately coarse: three tiers, because a scorecard
#: with eleven distinct weights implies a precision nobody can defend to an
#: examiner who asks why this factor is a 4 and that one a 5.
#:
#: The reasoning per weight, since an examiner will ask:
#:   3 -- the regulator or an international body has named this jurisdiction
#:        or party. Somebody outside this firm has already made a finding.
#:   2 -- a structural feature that hides who benefits: layered ownership,
#:        an asset-holding vehicle, a third-party payer.
#:   1 -- a signal worth weighing that is common in legitimate business.
WEIGHTS: Mapping[str, int] = {
    # -- the customer --------------------------------------------------
    "4.2(a)(ii)": 2,            # ownership structure unusual or opaque
    "4.2(a)(iv, second)": 2,    # personal asset-holding vehicle
    # -- the country ----------------------------------------------------
    "4.2(b)(i)": 1,             # exposure to the jurisdiction at all
    "4.2(b)(iii)": 3,           # named by credible sources
    "4.2(b)(iv)": 3,            # no effective AML/CFT systems
    "4.2(b)(v)": 3,             # subject to sanctions or embargoes
    # -- the product or channel -----------------------------------------
    "4.2(c)(iv)": 2,            # payments from unknown or third parties
    "4.2(c)(vi)": 2,            # anonymous transactions
}


@dataclass(frozen=True)
class Contribution:
    """One factor's part in a proposal, and why it counted."""

    ref: str
    weight: int
    because: str
    #: Set where a person answered this rather than the records.
    answered_by: str = ""


@dataclass(frozen=True)
class Proposal:
    """A band this scorecard would suggest, with everything behind it."""

    band: str
    points: int
    scorecard: str
    counted: tuple[Contribution, ...] = ()
    #: Refs nobody has answered either way, across the whole of clause 4.2.
    #: Never counted as absent.
    unassessed: tuple[str, ...] = ()
    #: Factors present but carrying no weight in this scorecard -- shown so
    #: an officer can see the scorecard noticed them and chose not to score
    #: them, which is different from not having looked.
    present_but_unweighted: tuple[str, ...] = ()
    #: How many of the factors this scorecard can weigh have been answered,
    #: and how many there are.
    weighed: int = 0
    weighable: int = 0

    @property
    def thin(self) -> bool:
        """Whether too little is answered for the arithmetic to mean much.

        Measured over the factors this scorecard *weighs*, not over all
        nineteen. The first version of this compared against the whole list
        and was wrong in a way worth recording: eleven of clause 4.2's
        factors can only be answered by a person, so a party whose records
        had answered seven of the eight scorable ones -- nearly everything
        this arithmetic can know -- was still reported as resting on very
        little. That understates a real signal, and a caveat that fires on
        every customer is a caveat nobody reads by the second week.

        The eleven a person must answer are not forgotten; they are the
        panel's own "still unanswered" line, and they are why this proposes
        a band and never a category.
        """
        if not self.weighable:
            return True
        return self.weighed * 2 < self.weighable


def band_for(points: int) -> str:
    if points >= HIGH_AT:
        return HIGH
    if points >= MEDIUM_AT:
        return MEDIUM
    return LOW


def propose(observations: Mapping[str, Observation]) -> Proposal:
    """What band this scorecard suggests, given what has been observed.

    Takes observations rather than an engine or an entity id: this module
    reads no records and writes none, and a function that cannot reach the
    log is a function that cannot record a category by accident.
    """
    counted: list[Contribution] = []
    unweighted: list[str] = []
    points = 0

    for factor in FACTORS:
        seen = observations.get(factor.ref)
        if seen is None or seen.present is None:
            continue
        if not seen.present:
            continue
        weight = WEIGHTS.get(factor.ref, 0)
        if not weight:
            unweighted.append(factor.ref)
            continue
        points += weight
        counted.append(Contribution(ref=factor.ref, weight=weight,
                                    because=seen.because,
                                    answered_by=seen.answered_by))

    def answered(ref: str) -> bool:
        found = observations.get(ref)
        return found is not None and found.present is not None

    unassessed = tuple(factor.ref for factor in FACTORS
                       if not answered(factor.ref))
    return Proposal(
        band=band_for(points),
        points=points,
        scorecard=SCORECARD,
        counted=tuple(counted),
        unassessed=unassessed,
        present_but_unweighted=tuple(unweighted),
        weighed=sum(1 for ref in WEIGHTS if answered(ref)),
        weighable=len(WEIGHTS),
    )


def propose_for(assessment: Optional[Assessment]) -> Proposal:
    """The proposal for an assessment as it currently stands.

    An entity nobody has looked at yet gets a proposal built from nothing:
    zero points, every factor unassessed, and ``thin`` true. That is
    deliberately not an error -- zero points is what the arithmetic says of
    no evidence -- but a screen that rendered it as "low" would be reporting
    an unexamined customer as a clean one, so ``thin`` is what the wording
    keys off and the band is not shown alone.
    """
    return propose(assessment.observations if assessment else {})
