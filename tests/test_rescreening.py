"""Screening the book again, without handing back every answered question.

The property this file exists for is the last one: a false positive an
officer dismissed must not return tomorrow night, and the night after, for
as long as the party is on the book. Everything else here is in service of
being able to state that one honestly.
"""

from __future__ import annotations

import json

import pytest

from vinzor.model import EventType, Outcome, Role
from vinzor.rescreening import (
    UNKNOWN_VERSION,
    Currency,
    currency,
    overdue,
    rescreen,
    settled_alerts,
)
from vinzor.screening import ScreeningUnavailable, WatchlistClient, screen

from conftest import WHEN, officer, person

LATER = "2026-08-20"
VERSION_ONE = "20260807-aaa"
VERSION_TWO = "20260820-bbb"

A_HIT = {"id": "ofac-1", "caption": "Rohan Desai", "score": 0.95,
         "match": True, "properties": {"topics": ["sanction"]},
         "datasets": ["us_ofac_sdn"]}


def service(*results, version=VERSION_ONE):
    """A fake yente that publishes a version and answers every query."""
    calls = []

    def transport(url, body, headers):
        if body is None:
            return json.dumps({"datasets": [
                {"name": "default", "index_current": True,
                 "version": transport.version},
            ]}).encode()
        sent = json.loads(body)
        calls.append(sent)
        answers = {key: {"results": list(transport.results)}
                   for key in (sent.get("queries") or {"q": None})}
        return json.dumps({"responses": answers}).encode()

    transport.version = version
    transport.results = list(results)
    transport.calls = calls
    return transport


# -- the property this module exists for -------------------------------------


def test_a_dismissed_match_does_not_come_back_the_next_night(engine):
    """The whole reason ``settled`` exists.

    A closed Case that meets the same finding again does not reopen as more
    evidence -- ``cases._reopened_case_id`` deliberately opens a *new* Case,
    which is right for a breach that genuinely recurs. A watchlist match is
    not a recurrence; it is one standing fact observed again. Left alone, a
    nightly re-screen would hand an officer back every false positive they
    have ever dismissed, every single night.
    """
    officer(engine)
    person(engine, "p1", "Rohan Desai")
    transport = service(A_HIT)
    client = WatchlistClient(transport=transport)

    screen(engine, "p1", screened_at=WHEN, client=client)
    opened = [c for c in engine.state.casebook.cases.values()
              if c.subject == "p1"]
    assert len(opened) == 1, "the first screen should raise the match once"

    engine.decide(case_id=opened[0].case_id, outcome=Outcome.APPROVE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  rationale="Different date of birth; not our investor.",
                  decided_at=WHEN)
    assert not engine.state.casebook.cases[opened[0].case_id].is_open

    # The list moves on, so the party is due again.
    transport.version = VERSION_TWO
    swept = rescreen(engine, today=LATER, client=client)

    assert swept.screened == 1, "the party was due and should have been looked at"
    cases = [c for c in engine.state.casebook.cases.values()
             if c.subject == "p1"]
    assert len(cases) == 1, (
        "a dismissed match was raised again as a new Case -- an officer would "
        "meet this same false positive every night forever")


def test_holding_a_match_back_is_said_out_loud(engine):
    """Declining to re-raise is not the same as not having seen it. A screen
    that quietly dropped what it found would be the defect this codebase
    keeps finding, wearing better clothes."""
    officer(engine)
    person(engine, "p1", "Rohan Desai")
    transport = service(A_HIT)
    client = WatchlistClient(transport=transport)

    screen(engine, "p1", screened_at=WHEN, client=client)
    case = [c for c in engine.state.casebook.cases.values()
            if c.subject == "p1"][0]
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  rationale="Different date of birth; not our investor.",
                  decided_at=WHEN)

    transport.version = VERSION_TWO
    rescreen(engine, today=LATER, client=client)

    last = [e for e in engine.log
            if e.event_type is EventType.SCREENING_COMPLETED][-1]
    assert last.payload["matched"] is False
    assert last.payload["basis"]["settled_already"] == ["os:ofac-1"], (
        "the record does not say what it saw and chose not to re-raise")


def test_an_open_match_is_still_recorded_against_its_own_case(engine):
    """Only *closed* matches are held back. A match nobody has answered yet
    belongs on that open file as more evidence that it is still true."""
    officer(engine)
    person(engine, "p1", "Rohan Desai")
    transport = service(A_HIT)
    client = WatchlistClient(transport=transport)

    screen(engine, "p1", screened_at=WHEN, client=client)
    transport.version = VERSION_TWO
    rescreen(engine, today=LATER, client=client)

    cases = [c for c in engine.state.casebook.cases.values()
             if c.subject == "p1"]
    assert len(cases) == 1, "an open match should not have opened a second Case"
    assert len(cases[0].evidence) > 1, (
        "the re-screen should have added evidence to the open file")


def test_settled_alerts_reads_only_closed_cases(engine):
    officer(engine)
    person(engine, "p1", "Rohan Desai")
    client = WatchlistClient(transport=service(A_HIT))
    screen(engine, "p1", screened_at=WHEN, client=client)

    assert settled_alerts(engine, "p1") == frozenset(), "nothing is settled yet"

    case = [c for c in engine.state.casebook.cases.values()
            if c.subject == "p1"][0]
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  rationale="Different date of birth; not our investor.",
                  decided_at=WHEN)
    assert settled_alerts(engine, "p1") == frozenset({"os:ofac-1"})


# -- who is overdue ----------------------------------------------------------


def test_a_party_never_screened_is_overdue(engine):
    person(engine, "p1", "Rohan Desai")
    due = overdue(engine, VERSION_ONE)
    assert [row.party for row in due] == ["p1"]
    assert due[0].never


def test_a_party_screened_against_an_older_list_is_overdue(engine):
    person(engine, "p1", "Rohan Desai")
    screen(engine, "p1", screened_at=WHEN,
           client=WatchlistClient(transport=service()))

    assert overdue(engine, VERSION_ONE) == (), "screened against this very list"
    assert [row.party for row in overdue(engine, VERSION_TWO)] == ["p1"]


def test_a_screening_that_cannot_say_which_list_it_saw_is_overdue(engine):
    """Every screening written before versions were recorded carries no
    version. "We cannot say what this was checked against" is not a claim of
    currency, and the first run after this ships re-screens the book once
    for exactly that reason."""
    row = Currency(party="p1", name="Rohan Desai",
                   last_screened=WHEN, version=UNKNOWN_VERSION)
    assert row.stale_against(VERSION_ONE)


def test_nothing_is_overdue_merely_because_the_catalogue_was_quiet(engine):
    """A screen is not stale because the service declined to say what it
    holds this evening. Treating it so would re-screen the whole book every
    run for as long as the catalogue stayed reticent."""
    person(engine, "p1", "Rohan Desai")
    screen(engine, "p1", screened_at=WHEN,
           client=WatchlistClient(transport=service()))

    assert overdue(engine, UNKNOWN_VERSION) == ()


def test_currency_reports_every_party_not_only_the_screened_ones(engine):
    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Anita Rao")
    screen(engine, "p1", screened_at=WHEN,
           client=WatchlistClient(transport=service()))

    rows = {row.party: row for row in currency(engine)}
    assert set(rows) == {"p1", "p2"}
    assert rows["p1"].version == VERSION_ONE
    assert rows["p2"].never


# -- a run that cannot reach the service -------------------------------------


def test_a_party_the_service_refused_is_named_never_counted_as_screened(engine):
    """``screening.py`` writes no fact at all when it cannot be sure. A run
    over the book keeps that discipline: the party is carried out in the
    result rather than silently passed over, and nothing is recorded for it
    that could later read as a clean screen."""
    person(engine, "p1", "Rohan Desai")

    def refusing(url, body, headers):
        if body is None:
            return json.dumps({"datasets": [
                {"name": "default", "index_current": False,
                 "version": VERSION_ONE},
            ]}).encode()
        return json.dumps({"responses": {"q": {"results": []}}}).encode()

    before = len(engine.log)
    swept = rescreen(engine, today=LATER,
                     client=WatchlistClient(transport=refusing))

    assert swept.screened == 0
    assert [party for party, _why in swept.unreachable] == ["p1"]
    assert len(engine.log) == before, "a refused screen wrote a fact anyway"


def test_one_unreachable_party_does_not_end_the_run(engine):
    """A sweep that stops at the first bad name never finishes a real book."""
    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Anita Rao")

    def sometimes(url, body, headers):
        if body is None:
            return json.dumps({"datasets": [
                {"name": "default", "index_current": True,
                 "version": VERSION_ONE},
            ]}).encode()
        if "Rohan" in body.decode("utf-8"):
            raise OSError("the network went away")
        return json.dumps({"responses": {"q": {"results": []}}}).encode()

    swept = rescreen(engine, today=LATER,
                     client=WatchlistClient(transport=sometimes))

    assert swept.looked_at == ("p2",)
    assert [party for party, _why in swept.unreachable] == ["p1"]


def test_the_version_is_asked_for_once_not_once_per_party(engine):
    """A book of four hundred should not fetch the *version* four hundred
    times for one fact that cannot change during the run.

    The catalogue is still read once per clean screen, by the older guard
    that refuses to call an empty answer clean unless the scope is loaded --
    a different question, asked for a different reason, and one this does not
    change. So the count here is one version read plus one guard read per
    party, not two per party. Narrowing the guard's own reads is a real
    optimisation and deliberately not made here: the service runs on the same
    machine as this code, nobody has measured it hurting, and the first
    version of that optimisation was what defeated the guard entirely once
    already (see ``screening._refuse_unless_indexed``).
    """
    for n in range(3):
        person(engine, f"p{n}", f"Person {n}")

    reads = []
    inner = service()

    def counting(url, body, headers):
        if body is None:
            reads.append(url)
        return inner(url, body, headers)

    swept = rescreen(engine, today=LATER,
                     client=WatchlistClient(transport=counting))

    assert swept.screened == 3
    assert len(reads) == 1 + 3, (
        f"expected one version read plus one guard read per party, "
        f"got {len(reads)}")


def test_rescreening_writes_the_version_it_screened_against(engine):
    person(engine, "p1", "Rohan Desai")
    rescreen(engine, today=LATER,
             client=WatchlistClient(transport=service(version=VERSION_TWO)))

    last = [e for e in engine.log
            if e.event_type is EventType.SCREENING_COMPLETED][-1]
    assert last.payload["basis"]["list_version"] == VERSION_TWO
    assert overdue(engine, VERSION_TWO) == (), "still overdue after a screen"
