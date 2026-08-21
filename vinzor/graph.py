"""The ownership graph, and beneficial ownership as IFSCA actually defines it.

The graph holds no truth of its own. It is rebuilt from ``ENTITY_REGISTERED``
and ``OWNERSHIP_DECLARED`` events and can be thrown away at any time.

On edge direction: an ``OWNERSHIP_DECLARED`` event names ``owner`` and ``owned``
explicitly. Adapters work out which way their source data points; by the time a
fact reaches the core it is unambiguous.

Beneficial ownership is *computed here, on demand*, never read from storage. A
derived conclusion that is persisted is one that can drift from the facts.

**The test is not 25%.** FATF guidance says 25%, and the earlier build, its
dataset and its research notes all assumed it. IFSCA does not. Clause 1.3.3 of
the AML/CFT/KYC Guidelines sets a different test for each customer type, and
the company threshold was cut from twenty-five per cent to **ten** by circular
in May 2023. Anything built to 25% under-reports beneficial owners against the
regulator this product is for. The thresholds below are transcribed from the
clause, and each one cites it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from .model import EntityKind, Event, EventType, Relation, StrEnum

#: How far to walk an ownership chain before giving up.
MAX_DEPTH = 12

#: How many ownership edges one walk may follow before it stops and says so.
#:
#: A stated limit rather than a hidden one, and the reason it exists is that
#: following every route through an ownership graph is exponential in the
#: worst case -- not as a theoretical worry but as a shape a spreadsheet
#: produces. Eight companies each declared as owned by the other seven, which
#: is what a group structure looks like when somebody enters every company
#: against every other, has 13,701 edges to walk and finds 27,391 distinct
#: cycles; ten such companies has 986,411 edges and takes five seconds; each
#: further company multiplies it again. Beneficial ownership is resolved when
#: money is promised (``policies.py``), so an import carrying that mistake
#: would not have produced a slow screen -- it would have stopped the write.
#:
#: What it can cost: a genuinely enormous structure is reported as
#: unfinished rather than resolved. That is the safe direction. The
#: percentages already found are kept and shown as "at least", the
#: conclusion is INCOMPLETE, and nothing is presented as a clean answer --
#: a truncated walk that reported "no beneficial owner" would be the worst
#: outcome available here.
#:
#: The margin is not fine. Across the 94 non-person parties in a real
#: workspace the worst walk visited *four* edges.
MOST_EDGES = 100_000

#: Relations carrying an economic interest, and therefore the percentage
#: arithmetic. Trustee and settlor confer no interest but are still mandatory
#: parties for a trust -- see ``TRUST_MANDATORY_ROLES``.
OWNERSHIP_RELATIONS = frozenset({Relation.OWNS, Relation.BENEFICIARY_OF})


@dataclass(frozen=True)
class OwnershipTest:
    """The beneficial-ownership test for one customer type, per IFSCA 1.3.3."""

    threshold: float
    #: 1.3.3(a) says "more than ten per cent"; 1.3.3(d) says "ten per cent or
    #: more". The difference is in the text, so it is in the code.
    inclusive: bool
    clause: str

    def meets(self, percentage: float) -> bool:
        return percentage >= self.threshold if self.inclusive else percentage > self.threshold

    def describe(self) -> str:
        return f"{'at or above' if self.inclusive else 'above'} {self.threshold:g}%"


#: IFSCA 1.3.3. A FUND vehicle is tested as a company; it is a body corporate
#: and the clause offers no separate limb for it.
IFSCA_TESTS: Mapping[EntityKind, OwnershipTest] = {
    EntityKind.COMPANY: OwnershipTest(10.0, False, "1.3.3(a)"),
    EntityKind.FUND: OwnershipTest(10.0, False, "1.3.3(a)"),
    EntityKind.PARTNERSHIP: OwnershipTest(10.0, False, "1.3.3(b)"),
    EntityKind.UNINCORPORATED_BODY: OwnershipTest(15.0, False, "1.3.3(c)"),
    EntityKind.TRUST: OwnershipTest(10.0, True, "1.3.3(d)"),
}

DEFAULT_TEST = IFSCA_TESTS[EntityKind.COMPANY]

#: 1.3.3(d): for a trust these parties are identified whatever their percentage.
TRUST_MANDATORY_ROLES: Mapping[Relation, str] = {
    Relation.SETTLOR_OF: "author of the trust",
    Relation.TRUSTEE_OF: "trustee",
}

#: 1.3.3(a)(ii) also makes a person a beneficial owner where they can appoint a
#: majority of directors or otherwise control management or policy decisions.
#: No directorship or control-agreement data reaches this system today, so that
#: limb is not evaluated -- and every result says so rather than implying the
#: ownership limb is the whole test.
CONTROL_LIMB = (
    "control through other means (1.3.3(a)(ii)): not evaluated — no "
    "directorship, voting-agreement or management-control data available"
)


class Conclusion(StrEnum):
    """What the resolver established, in the regulator's own terms."""

    IDENTIFIED = "IDENTIFIED"
    #: 1.3.3(c) explanation: where no natural person is identified, the
    #: beneficial owner is the senior managing official. Not a dead end --
    #: a different obligation.
    SENIOR_MANAGING_OFFICIAL_REQUIRED = "SENIOR_MANAGING_OFFICIAL_REQUIRED"
    #: The chain cannot be completed: a loop, an undeclared intermediate, or a
    #: mandatory trust party that was never named.
    INCOMPLETE = "INCOMPLETE"
    NOT_DECLARED = "NOT_DECLARED"


@dataclass(frozen=True)
class Entity:
    entity_id: str
    kind: EntityKind
    name: str
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OwnershipEdge:
    owner: str
    owned: str
    percentage: float
    relation: Relation
    source_seq: int


@dataclass(frozen=True)
class BeneficialOwner:
    person_id: str
    name: str
    effective_percentage: float
    paths: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class MandatoryParty:
    """A party a trust must name regardless of any percentage (1.3.3(d))."""

    party_id: str
    name: str
    role: str
    relation: Relation


@dataclass(frozen=True)
class UboResult:
    subject: str
    subject_kind: Optional[EntityKind]
    test: OwnershipTest
    owners: tuple[BeneficialOwner, ...]
    below_threshold: tuple[BeneficialOwner, ...]
    mandatory_parties: tuple[MandatoryParty, ...]
    #: Mandatory roles the data never declared.
    missing_roles: tuple[str, ...]
    cycles: tuple[tuple[str, ...], ...]
    dead_ends: tuple[str, ...]
    limbs_not_evaluated: tuple[str, ...] = (CONTROL_LIMB,)
    #: True where the walk ran out of budget (:data:`MOST_EDGES`) before it
    #: had followed every route. Everything reported is still true; what is
    #: not true is that it is all of it.
    stopped_early: bool = False

    @property
    def conclusion(self) -> Conclusion:
        if (self.missing_roles or self.cycles or self.dead_ends
                or self.stopped_early):
            return Conclusion.INCOMPLETE
        if self.owners:
            return Conclusion.IDENTIFIED
        if self.below_threshold or self.mandatory_parties:
            return Conclusion.SENIOR_MANAGING_OFFICIAL_REQUIRED
        return Conclusion.NOT_DECLARED

    @property
    def clause(self) -> str:
        return self.test.clause

    def explain(self) -> str:
        conclusion = self.conclusion
        if conclusion is Conclusion.IDENTIFIED:
            top = self.owners[0]
            extra = f" and {len(self.owners) - 1} other(s)" if len(self.owners) > 1 else ""
            return (
                f"{top.name} holds {top.effective_percentage:.1f}% of {self.subject}"
                f"{extra}; test is {self.test.describe()} per {self.test.clause}"
            )
        if conclusion is Conclusion.SENIOR_MANAGING_OFFICIAL_REQUIRED:
            best = (
                f"largest holding is {self.below_threshold[0].name} at "
                f"{self.below_threshold[0].effective_percentage:.1f}%"
                if self.below_threshold
                else "no natural person holds an economic interest"
            )
            return (
                f"no beneficial owner of {self.subject} meets the "
                f"{self.test.describe()} test ({self.test.clause}); {best}. "
                f"The senior managing official must be recorded instead "
                f"(1.3.3(c) explanation)"
            )
        if conclusion is Conclusion.INCOMPLETE:
            why = []
            if self.missing_roles:
                why.append(f"undeclared mandatory part{'ies' if len(self.missing_roles) > 1 else 'y'}: "
                           f"{', '.join(self.missing_roles)}")
            if self.cycles:
                why.append(f"{len(self.cycles)} ownership cycle(s)")
            if self.dead_ends:
                why.append(f"undeclared ownership for {', '.join(sorted(self.dead_ends))}")
            if self.stopped_early:
                why.append(f"the structure has more routes through it than "
                           f"this system follows ({MOST_EDGES:,}), so the "
                           f"holdings below are at least what is shown and "
                           f"may be more")
            found = (
                f" ({len(self.owners)} owner(s) found so far)" if self.owners else ""
            )
            return (
                f"beneficial ownership of {self.subject} is not established"
                f"{found}: {'; '.join(why)}"
            )
        return f"no ownership or control declared for {self.subject}"


class OwnershipGraph:
    """Entities and who owns them. Mutated only by ``apply``."""

    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self._owners_of: dict[str, list[OwnershipEdge]] = {}
        #: Relations conferring control but no economic interest.
        self._controllers_of: dict[str, list[OwnershipEdge]] = {}

    # -- projection -------------------------------------------------------

    def apply(self, event: Event) -> None:
        if event.event_type is EventType.ENTITY_REGISTERED:
            payload = event.payload
            self.entities[event.subject] = Entity(
                entity_id=event.subject,
                kind=EntityKind(payload["kind"]),
                name=payload.get("name", event.subject),
                attributes=payload.get("attributes", {}),
            )
        elif event.event_type is EventType.OWNERSHIP_DECLARED:
            payload = event.payload
            edge = OwnershipEdge(
                owner=payload["owner"],
                owned=payload["owned"],
                percentage=float(payload.get("percentage") or 0.0),
                relation=Relation(payload["relation"]),
                source_seq=event.seq,
            )
            bucket = (
                self._owners_of
                if edge.relation in OWNERSHIP_RELATIONS
                else self._controllers_of
            )
            # A holding declared twice is one holding, restated -- not two
            # holdings that add up. Appending meant re-importing an ownership
            # file doubled every percentage in it, and six per cent declared
            # twice became a twelve per cent beneficial owner who does not
            # exist. The log keeps both declarations; the projection keeps the
            # latest, which is what a projection is for.
            existing = bucket.setdefault(edge.owned, [])
            for position, older in enumerate(existing):
                if (older.owner == edge.owner
                        and older.relation == edge.relation):
                    if older.source_seq <= edge.source_seq:
                        existing[position] = edge
                    break
            else:
                existing.append(edge)

    # -- queries ----------------------------------------------------------

    def owners_of(self, entity_id: str) -> list[OwnershipEdge]:
        return list(self._owners_of.get(entity_id, []))

    def controllers_of(self, entity_id: str) -> list[OwnershipEdge]:
        return list(self._controllers_of.get(entity_id, []))

    def holdings_of(self, entity_id: str) -> list[OwnershipEdge]:
        """What this entity holds -- the other direction from ``owners_of``.

        The resolver only ever walks upward, from a customer towards the people
        behind it, so nothing needed this until a reader wanted one party's
        whole position on a single page. Scanning is honest at this size: the
        index that would make it cheap has to be kept correct on every edge,
        and an index that can disagree with the edges is a second truth.
        """
        return [edge for edges in self._owners_of.values() for edge in edges
                if edge.owner == entity_id]

    def kind_of(self, entity_id: str) -> Optional[EntityKind]:
        entity = self.entities.get(entity_id)
        return entity.kind if entity else None

    def name_of(self, entity_id: str) -> str:
        entity = self.entities.get(entity_id)
        return entity.name if entity else entity_id

    def test_for(self, entity_id: str) -> OwnershipTest:
        return IFSCA_TESTS.get(self.kind_of(entity_id), DEFAULT_TEST)

    def resolve_ubo(self, subject: str, test: Optional[OwnershipTest] = None) -> UboResult:
        """Identify beneficial owners of ``subject`` under IFSCA 1.3.3.

        Walks up the ownership chain multiplying percentages; a natural person
        terminates a branch and multiple routes to the same person are summed.
        For a trust, additionally collects the parties 1.3.3(d) requires to be
        named whatever their interest, and reports any that were never
        declared.
        """
        kind = self.kind_of(subject)
        test = test or IFSCA_TESTS.get(kind, DEFAULT_TEST)

        holdings: dict[str, float] = {}
        routes: dict[str, list[tuple[str, ...]]] = {}
        cycles: list[tuple[str, ...]] = []
        #: The same cycles, for asking whether one has been seen already.
        #: The list is kept for its order, which is what a reader is shown;
        #: this is what stops the asking being a scan of it. Eight companies
        #: each declared as owning the other seven -- an ordinary way for a
        #: group structure to arrive from a spreadsheet -- find 27,391
        #: cycles, and checking each against a list that long as it grew
        #: took twenty-nine seconds. The same walk visits only 13,701
        #: edges: almost none of that time was spent walking.
        seen_cycles: set = set()
        dead_ends: set[str] = set()

        budget = MOST_EDGES
        stopped_early = False

        def walk(node: str, factor: float, path: tuple[str, ...]) -> None:
            nonlocal budget, stopped_early
            if len(path) > MAX_DEPTH:
                dead_ends.add(node)
                return
            edges = self._owners_of.get(node)
            if not edges:
                # The subject having no owners is "not declared"; an
                # intermediate having none is a genuine gap in the chain.
                if node != subject:
                    dead_ends.add(node)
                return
            for edge in edges:
                # Counted here, one per edge examined, so a walk that stays
                # inside the budget does exactly what it always did -- the
                # counter is never consulted for anything but stopping, and
                # every percentage below it is arrived at by the same
                # additions in the same order as before.
                #
                # The subject's own owners are exempt. Edges are followed in
                # the order they were declared, so a budget spent on a
                # tangle further up can run out before reaching a person
                # holding forty per cent of the subject directly -- which is
                # both the most important line on the page and the one
                # nobody needed a computer to find. Exempting them cannot
                # reintroduce the blowup: they are the edges of one node,
                # not a multiplying set of routes.
                if len(path) > 1:
                    if budget <= 0:
                        stopped_early = True
                        return
                    budget -= 1
                if edge.owner in path:
                    cycle = path[path.index(edge.owner):] + (edge.owner,)
                    if cycle not in seen_cycles:
                        seen_cycles.add(cycle)
                        cycles.append(cycle)
                    continue
                effective = factor * (edge.percentage / 100.0)
                if self.kind_of(edge.owner) is EntityKind.PERSON:
                    holdings[edge.owner] = holdings.get(edge.owner, 0.0) + effective
                    routes.setdefault(edge.owner, []).append(path + (edge.owner,))
                else:
                    walk(edge.owner, effective, path + (edge.owner,))

        walk(subject, 1.0, (subject,))

        found = sorted(
            (
                BeneficialOwner(
                    person_id=person,
                    name=self.name_of(person),
                    effective_percentage=round(share * 100.0, 4),
                    paths=tuple(routes[person]),
                )
                for person, share in holdings.items()
            ),
            key=lambda o: (-o.effective_percentage, o.person_id),
        )
        owners = tuple(o for o in found if test.meets(o.effective_percentage))
        below = tuple(o for o in found if not test.meets(o.effective_percentage))

        mandatory, missing = self._trust_parties(subject, kind)

        return UboResult(
            subject=subject,
            subject_kind=kind,
            test=test,
            owners=owners,
            below_threshold=below,
            mandatory_parties=mandatory,
            missing_roles=missing,
            cycles=tuple(cycles),
            dead_ends=tuple(sorted(dead_ends)),
            stopped_early=stopped_early,
        )

    def _trust_parties(
        self, subject: str, kind: Optional[EntityKind]
    ) -> tuple[tuple[MandatoryParty, ...], tuple[str, ...]]:
        """IFSCA 1.3.3(d): author, trustee and controllers, percentage or not."""
        if kind is not EntityKind.TRUST:
            return (), ()
        declared: list[MandatoryParty] = []
        missing: list[str] = []
        # A trust may have two settlors, three trustees and several
        # protectors, and 1.3.3(d) requires *every* one of them to be
        # identified. Keying a dict by relation kept only the last party
        # declared for each role and silently dropped the rest -- and the
        # result still read IDENTIFIED, so an officer was told the ownership
        # of a trust was fully established while co-trustees the log knew
        # about were missing from the file.
        by_relation: dict[Relation, list[OwnershipEdge]] = {}
        for edge in self._controllers_of.get(subject, []):
            by_relation.setdefault(edge.relation, []).append(edge)
        for relation, role in TRUST_MANDATORY_ROLES.items():
            edges = by_relation.get(relation) or []
            if not edges:
                missing.append(role)
            for edge in edges:
                declared.append(
                    MandatoryParty(
                        party_id=edge.owner,
                        name=self.name_of(edge.owner),
                        role=role,
                        relation=relation,
                    )
                )
        return tuple(declared), tuple(missing)

    def cycle_through(self, owner: str, owned: str) -> Optional[tuple[str, ...]]:
        """Does declaring ``owner`` as an owner of ``owned`` close a loop?"""
        stack: list[tuple[str, tuple[str, ...]]] = [(owner, (owner,))]
        seen: set[str] = set()
        while stack:
            node, path = stack.pop()
            if node == owned and len(path) > 1:
                return path
            if node in seen:
                continue
            seen.add(node)
            for edge in self._owners_of.get(node, []):
                stack.append((edge.owner, path + (edge.owner,)))
        return None
