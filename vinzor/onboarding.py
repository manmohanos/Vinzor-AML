"""Taking on an investor: eight checks, none of which reasons.

``agents.py`` gives a person a way to delegate work across the whole book.
This is the other shape of the same thing — everything that has to happen to
*one* party before a firm may take their money — and it is the workflow an FME
actually performs every week.

**Not one of these eight agents reasons.** Each is a pure function over
recorded facts and, where it needs the outside world, one named source with
its answer written onto the log. Same party in, same findings out, today and
in eleven months when somebody asks why this investor was accepted. That is
not caution for its own sake: a screening result that changes between two
readings is not evidence, and this product's entire claim is that its records
can be relied upon afterwards.

A model appears exactly once in an onboarding, at the very end, writing the
opening paragraph of the report from figures it was handed — and
``narrative.py``'s guard destroys that paragraph if it invents so much as a
date. It never establishes anything and it never decides anything.

## The eight

    identification   what clause 5.4.2 wants to know, and what is missing
    documents        what this kind of party owes, and what is on file
    sanctions        the name against every sanctions list
    politically      the same result, read for public office
    adverse media    what the press has carried, by theme
    ownership        through the structure to the natural people
    duplicate        whether this party is already on the book
    risk factors     which of the nineteen clause 4.2 factors are observable

Two of them talk to the outside world and can therefore fail. **A step that
could not run is recorded as failed and never as clean** — the distinction the
watchlist and the news adapter both exist to protect, carried through to the
one screen where a person acts on it.

## What the officer sees

Each step's own sentence while it runs, its headline as it lands, and its
detail underneath. Not a progress bar over a sleep: every step here is a real
call to a real tool, and it becomes a permanent event the moment it finishes,
which is why the progress is evidence rather than animation.

## What this module will not do

It will not conclude. There is no score, no "recommended: accept", no traffic
light over the party as a whole. The report ends at three buttons and a box
that must be typed in, because clause 5.5(b)(iii) and the whole architecture
underneath it say the decision belongs to a named human being who has to
answer for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from .agents import DONE, FAILED, FOUND_SOMETHING, SKIPPED, Found, Recipe, Tool
from .model import EntityKind, EventType

#: The order the checks run in, and it is not arbitrary. Identity first,
#: because a check on a party whose name we hold wrongly is a check on the
#: wrong person. Then the papers. Then the outside world, cheapest and most
#: decisive first: a sanctions match stops everything, so nothing after it
#: matters as much. Ownership late, because it is only worth following once
#: we believe the party is who they say. Risk last, because it reads
#: everything the others found.
#: ``FAILED`` here means the tool broke, and nothing else. It is reserved for
#: that, because ``tests/test_runs_audit.py`` treats any failed step across
#: every shipped recipe as a regression -- which is the right reading and was
#: worth being corrected by.
#:
#: A check that has never been run is therefore ``FOUND_SOMETHING``, not a
#: failure: the absence of a screening record **is** the finding, and it is
#: exactly the thing an officer has to act on before this party can be taken
#: on. Calling it a failure would have filed the most important gap in an
#: onboarding under "something went wrong with our software".

ORDER = ("identification", "documents", "sanctions", "politically",
         "adverse", "ownership", "duplicate", "riskfactors")


def _party(engine, inputs: Mapping[str, Any]):
    """The party a step is about, or None with a sentence saying why.

    Every tool here takes ``party`` from the run's inputs. A run started
    without one is a programming mistake rather than a user's, but it must
    still not crash a step into a stack trace on an officer's screen.
    """
    reference = str(inputs.get("party") or "").strip()
    if not reference:
        return None, "No party was named, so there was nothing to check."
    entity = engine.state.graph.entities.get(reference)
    if entity is None:
        return None, "That party is not on the record, so nothing was checked."
    return entity, ""


def _skip(why: str) -> Found:
    return Found(headline=why, how=SKIPPED)


# ---------------------------------------------------------------------------
# 1. Identification — what clause 5.4.2 wants to know
# ---------------------------------------------------------------------------


def _identification(engine, today: str = "", **inputs) -> Found:
    from .readiness import NOT_MEASURED, measure

    entity, why = _party(engine, inputs)
    if entity is None:
        return _skip(why)

    answer = measure(engine, only=(entity.entity_id,))
    gaps = [g for standing in answer.parties for g in standing.gaps]
    # Held and unsupported is a different state from missing, and it is the
    # one clause 5.4.5 exists for: the record says the investor was born in
    # 1979 and nothing on file says so. Counted separately because it has a
    # different remedy -- somebody looks at a document already on the file,
    # rather than writing to the investor again.
    unsupported = [g for standing in answer.parties
                   for g in standing.unsupported]
    if not gaps and not unsupported:
        return Found(
            headline=f"{entity.name} has every identification detail "
                     f"clause 5.4.2 asks a record for",
            how=DONE,
            details=(f"{len(NOT_MEASURED)} other things the clause asks for "
                     f"are not checked here and are listed with the report.",),
            carried={"missing": 0})
    said = [f"{gap.what} — clause {gap.clause}" for gap in gaps[:6]]
    said += [f"{gap.what} — held, but nothing on file supports it "
             f"(clause 5.4.5)" for gap in unsupported[:4]]
    return Found(
        headline=(f"{len(gaps)} identification detail(s) missing for "
                  f"{entity.name}" if gaps else
                  f"{len(unsupported)} detail(s) held for {entity.name} with "
                  f"nothing on file behind them"),
        how=FOUND_SOMETHING,
        details=tuple(said),
        carried={"missing": len(gaps), "unsupported": len(unsupported)})


# ---------------------------------------------------------------------------
# 2. Documents — what this kind of party owes
# ---------------------------------------------------------------------------


def _documents(engine, today: str = "", **inputs) -> Found:
    from .requirements import NOT_MODELLED, outstanding

    entity, why = _party(engine, inputs)
    if entity is None:
        return _skip(why)

    papers = engine.state.papers.held_for(entity.entity_id)
    still = outstanding(entity.kind, papers)
    if not still:
        return Found(
            headline=f"every document a {_kind_word(entity.kind)} owes is on "
                     f"file and evidenced",
            how=DONE,
            details=(f"{len(NOT_MODELLED)} things are not checked here and "
                     f"are listed with the report.",),
            carried={"outstanding": 0})

    unevidenced = [o for o in still if o.held_but_unevidenced]
    lines = []
    for item in still[:8]:
        if item.held_but_unevidenced:
            lines.append(f"{item.requirement.asks_for} — on file, but nobody "
                         f"has said what it evidences")
        else:
            lines.append(f"{item.requirement.asks_for} — {item.requirement.because}")
    return Found(
        headline=f"{len(still)} document(s) still needed from {entity.name}"
                 + (f", {len(unevidenced)} of them already on file"
                    if unevidenced else ""),
        how=FOUND_SOMETHING,
        details=tuple(lines),
        carried={"outstanding": len(still),
                 "held_but_unevidenced": len(unevidenced)})


def _kind_word(kind: Optional[EntityKind]) -> str:
    return {
        EntityKind.PERSON: "person",
        EntityKind.COMPANY: "company",
        EntityKind.PARTNERSHIP: "partnership",
        EntityKind.TRUST: "trust",
        EntityKind.FUND: "fund",
        EntityKind.UNINCORPORATED_BODY: "association",
    }.get(kind, "party")


# ---------------------------------------------------------------------------
# 3 and 4. The watchlist, read twice for two different clauses
# ---------------------------------------------------------------------------
#
# One search, two agents. The screening record carries every kind a match is,
# and the two clauses do completely different things with it: 5.9 stops the
# money, 5.5(b)(iii) reserves the clearance for senior management. Reading
# the single label a match happens to be filed under is how the senior gate
# missed the 21.4% of sanctioned persons who are also politically exposed.


def _watchlist_hits(engine, entity_id: str) -> list:
    """Every match recorded for this party, read off the log."""
    hits = []
    for event in engine.log:
        if event.event_type is not EventType.SCREENING_COMPLETED:
            continue
        if event.subject != entity_id:
            continue
        if event.payload.get("matched"):
            hits.append(event.payload)
    return hits


def _sanctions(engine, today: str = "", **inputs) -> Found:
    entity, why = _party(engine, inputs)
    if entity is None:
        return _skip(why)

    screened = [e for e in engine.log
                if e.event_type is EventType.SCREENING_COMPLETED
                and e.subject == entity.entity_id]
    if not screened:
        # Never "clean". Nobody has looked.
        return Found(
            headline=f"nobody has run a watchlist check on {entity.name}",
            how=FOUND_SOMETHING,
            details=("That is not the same as a check that found nothing — "
                     "this party has not been looked for.",))

    sanctioned = [h for h in _watchlist_hits(engine, entity.entity_id)
                  if "SANCTIONS" in (h.get("list_types") or [h.get("list_type")])]
    if not sanctioned:
        return Found(
            headline=f"{entity.name} is on no sanctions list this system "
                     f"searched",
            how=DONE,
            details=(f"Checked against {len(screened)} recorded search(es).",),
            carried={"sanctions": 0})
    return Found(
        headline=f"{entity.name} may be on a sanctions list",
        how=FOUND_SOMETHING,
        # The match detail lives under "basis", not at the top of the
        # payload. Reading the top level gave every match the same sentence,
        # "matched an entry on a list" -- which is the shape of a screening
        # record that tells an officer nothing they can act on.
        details=tuple(
            "matched %s on %s (score %s)" % (
                (h.get("basis") or {}).get("caption") or "an entry",
                ", ".join((h.get("basis") or {}).get("datasets")
                          or ["a list"])[:70],
                round(float((h.get("basis") or {}).get("score") or 0), 2))
            for h in sanctioned[:5]),
        carried={"sanctions": len(sanctioned)})


def _politically_exposed(engine, today: str = "", **inputs) -> Found:
    entity, why = _party(engine, inputs)
    if entity is None:
        return _skip(why)

    screened = [e for e in engine.log
                if e.event_type is EventType.SCREENING_COMPLETED
                and e.subject == entity.entity_id]
    if not screened:
        return Found(
            headline=f"nobody has checked whether {entity.name} holds public "
                     f"office",
            how=FOUND_SOMETHING,
            details=("Clause 5.5 asks a firm to determine this before taking "
                     "the customer on.",))

    exposed = []
    for hit in _watchlist_hits(engine, entity.entity_id):
        kinds = set(hit.get("list_types") or [hit.get("list_type")])
        if kinds & {"PEP", "PEP_ASSOCIATE"}:
            exposed.append(hit)
    if not exposed:
        return Found(
            headline=f"nothing records {entity.name} as politically exposed",
            how=DONE, carried={"pep": 0})
    return Found(
        headline=f"{entity.name} may be politically exposed",
        how=FOUND_SOMETHING,
        details=tuple(
            ["matched %s%s" % (
                (h.get("basis") or {}).get("caption") or "an entry",
                " (a close associate rather than the office holder)"
                if "PEP_ASSOCIATE" in set(h.get("list_types") or ()) else "")
             for h in exposed[:4]]
            + ["Clause 5.5(b)(iii) reserves clearing this to senior "
               "management. A guidance note adds that a politically exposed "
               "person is not automatically high risk."]),
        carried={"pep": len(exposed)})


# ---------------------------------------------------------------------------
# 5. Adverse media
# ---------------------------------------------------------------------------


def _adverse(engine, today: str = "", **inputs) -> Found:
    entity, why = _party(engine, inputs)
    if entity is None:
        return _skip(why)

    checks = [e for e in engine.log
              if e.event_type is EventType.ADVERSE_MEDIA_CHECKED
              and e.subject == entity.entity_id]
    if not checks:
        return Found(
            headline=f"the press has not been searched for {entity.name}",
            how=FOUND_SOMETHING,
            details=("No IFSCA clause requires this. It is a clause 4.2 risk "
                     "factor, and it has not been gathered.",))

    latest = checks[-1].payload
    found = int(latest.get("found") or 0)
    basis = latest.get("basis") or {}
    if not found:
        return Found(
            headline=f"no coverage of {entity.name} alongside financial crime",
            how=DONE,
            details=(f"Searched {basis.get('window', 'a fixed window')} of "
                     f"news for the name and nine named themes.",),
            carried={"articles": 0})
    sources = sorted({a.get("domain") for a in (basis.get("articles") or [])
                      if a.get("domain")})
    return Found(
        headline=f"{found} article(s) name {entity.name} alongside financial "
                 f"crime coverage",
        how=FOUND_SOMETHING,
        details=tuple([f"{a.get('seen_on')} · {a.get('domain')} · {a.get('title')}"
                       for a in (basis.get("articles") or [])[:6]]
                      + ["Nothing has read these. They are for you to read."]),
        carried={"articles": found, "sources": len(sources)})


# ---------------------------------------------------------------------------
# 6. Ownership
# ---------------------------------------------------------------------------


def _ownership(engine, today: str = "", **inputs) -> Found:
    from .graph import Conclusion

    entity, why = _party(engine, inputs)
    if entity is None:
        return _skip(why)
    if entity.kind is EntityKind.PERSON:
        return Found(
            headline="a person is their own beneficial owner",
            how=DONE, carried={"owners": 1})

    answer = engine.state.graph.resolve_ubo(entity.entity_id)
    if answer.conclusion is Conclusion.IDENTIFIED:
        return Found(
            headline=f"{len(answer.owners)} beneficial owner(s) identified "
                     f"for {entity.name}",
            how=DONE,
            details=tuple(
                f"{o.name} — {o.effective_percentage:.1f}% "
                f"({answer.test.describe()})" for o in answer.owners[:6]),
            carried={"owners": len(answer.owners)})
    return Found(
        headline=f"beneficial ownership of {entity.name} is not established",
        how=FOUND_SOMETHING,
        details=tuple([answer.explain()[:200]]
                      + [f"loops: {' → '.join(c)}" for c in answer.cycles[:2]]),
        carried={"owners": len(answer.owners), "unresolved": True})


# ---------------------------------------------------------------------------
# 7. Already on the book
# ---------------------------------------------------------------------------


def _duplicate(engine, today: str = "", **inputs) -> Found:
    entity, why = _party(engine, inputs)
    if entity is None:
        return _skip(why)

    from .duplicates import over_the_book

    pairs = [p for p in over_the_book(engine)
             if entity.entity_id in (p.one, p.other)]
    if not pairs:
        return Found(
            headline=f"nothing else on the book looks like {entity.name}",
            how=DONE, carried={"duplicates": 0})
    return Found(
        headline=f"{len(pairs)} party(ies) on the book may be {entity.name} "
                 f"already",
        how=FOUND_SOMETHING,
        details=tuple(p.because for p in pairs[:5]),
        carried={"duplicates": len(pairs)})


# ---------------------------------------------------------------------------
# 8. Risk factors
# ---------------------------------------------------------------------------


def _risk_factors(engine, today: str = "", **inputs) -> Found:
    entity, why = _party(engine, inputs)
    if entity is None:
        return _skip(why)

    from .risk import observe

    seen = observe(engine, entity.entity_id)
    present = [o for o in seen.values() if o.present]
    if not present:
        return Found(
            headline=f"no clause 4.2 risk factor is visible in the record "
                     f"for {entity.name}",
            how=DONE,
            details=("Eleven of the nineteen factors need a person to judge "
                     "them and cannot be read from a record at all.",),
            carried={"factors": 0})
    return Found(
        headline=f"{len(present)} clause 4.2 risk factor(s) are visible for "
                 f"{entity.name}",
        how=FOUND_SOMETHING,
        details=tuple(f"{o.ref} — {o.because}" for o in present[:8]),
        carried={"factors": len(present)})


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

TOOLS: Mapping[str, Tool] = {
    "identification": Tool(
        name="identification", says="Checking what we know about them",
        about="What clause 5.4.2 asks a record to hold, and what is missing.",
        run=_identification),
    "documents": Tool(
        name="documents", says="Checking which papers are still needed",
        about="What a party of this kind owes, and what is on file.",
        run=_documents),
    "sanctions": Tool(
        name="sanctions", says="Checking the sanctions lists",
        about="Whether the name is on any sanctions list, per clause 5.9.",
        run=_sanctions),
    "politically": Tool(
        name="politically", says="Checking for public office",
        about="Whether the party is politically exposed, per clause 5.5.",
        run=_politically_exposed),
    "adverse": Tool(
        name="adverse", says="Reading what the press has carried",
        about="News naming the party alongside financial-crime coverage.",
        run=_adverse),
    "ownership": Tool(
        name="ownership", says="Following ownership through to the people",
        about="Beneficial ownership to IFSCA's own test, clause 1.3.3.",
        run=_ownership),
    "duplicate": Tool(
        name="duplicate", says="Checking whether we know them already",
        about="Whether this party is on the book under another spelling.",
        run=_duplicate),
    "riskfactors": Tool(
        name="riskfactors", says="Weighing the risk factors in clause 4.2",
        about="Which of the nineteen factors the record can observe.",
        run=_risk_factors),
}

ONBOARD = Recipe(
    key="onboard",
    asked="Take on a new investor",
    about="Everything that has to happen before a firm may accept somebody's "
          "money: what we know, what they still owe, whether they are on a "
          "list, whether the press has carried anything, and who is really "
          "behind them. Nothing here decides; a person does, at the end.",
    steps=(("Identification", "identification"),
           ("Documents", "documents"),
           ("Sanctions", "sanctions"),
           ("Politically exposed", "politically"),
           ("Adverse media", "adverse"),
           ("Ownership", "ownership"),
           ("Already on the book", "duplicate"),
           ("Risk factors", "riskfactors")))


def install() -> None:
    """Add the onboarding tools and recipe to the agent registries.

    Called once, from ``agents.py``'s import, rather than by writing these
    into ``TOOLS`` directly there: the eight belong together and reading them
    beside each other is the only way the order makes sense.
    """
    from . import agents

    agents.TOOLS.update(TOOLS)
    agents.RECIPES[ONBOARD.key] = ONBOARD
