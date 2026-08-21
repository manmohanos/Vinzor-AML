"""What the screening block claims, tested by attacking it.

The block makes three claims worth attacking: that no name typed here leaves
the machine, that a failed check is never mistaken for a clean one, and that
an officer categorising a party can see what the watchlists said about them.

**The residency guard held.** It was attacked with the URLs that fool a
naive parser -- ``http://127.0.0.1@evil.example/``, where the local address
is userinfo and the real host is somebody else's; lookalike hostnames like
``127.0.0.1.evil.example``; the integer and hex spellings of 127.0.0.1 that
a substring check would miss. Every one is reported as leaving the machine.
Those cases are kept here so it goes on holding.

**Two attacks succeeded.**

*A setting that was not an address escaped the contract.* This module
promises a caller either results or ``ScreeningUnavailable``. An empty
service address broke that promise with a raw ``ValueError`` from inside
urllib -- and the place it surfaced was a background screening run after an
import, where it left a progress bar counting toward a total it would never
reach, with no message saying why. Addresses are now checked before
anything is sent, and the message names the right remedy: an address typed
without ``http://`` is a setting to correct, not a service to restart.

*A party nobody had screened read exactly like a party screened and found
clean.* Both produced "No watchlist check on this party has found
anything", on the screen where somebody decides how risky a party is. It is
true of a party nobody looked for, in the way that says nothing, and it
reads as reassurance. The same function also had no way to say that a party
who matched in March was not on any list in August, so a delisting could
never appear.
"""

from __future__ import annotations

import pytest

from vinzor.model import EntityKind, EventType
from vinzor.risk import what_screening_found
from vinzor.screening import (ScreeningUnavailable, WatchlistClient,
                              leaves_this_machine, unusable)


def known(engine, entity_id: str, name: str) -> None:
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=entity_id,
                  occurred_at="2026-03-01", actor="system",
                  payload={"kind": EntityKind.PERSON.value, "name": name,
                           "attributes": {}})


def checked(engine, entity_id: str, when: str, matched: bool) -> None:
    payload = {"matched": matched, "basis": {"service": "http://127.0.0.1:8090"}}
    if matched:
        payload.update({"list_type": "SANCTIONS", "rule": "match",
                        "alert_id": f"os:{entity_id}"})
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject=entity_id,
                  occurred_at=when, actor="system", payload=payload)


# -- no name leaves the machine ----------------------------------------------


@pytest.mark.parametrize("url", [
    # The local address is userinfo; the host is somebody else entirely.
    "http://127.0.0.1@evil.example/",
    "http://localhost@evil.example/",
    "http://localhost:8090@evil.example/",
    "http://localhost%40evil.example/",
    # The local address is in the fragment or the query, not the host.
    "http://evil.example#@127.0.0.1/",
    "http://evil.example?@localhost/",
    # Hostnames that merely contain a local one.
    "http://LOCALHOST.evil.example/",
    "http://127.0.0.1.evil.example/",
    "http://mylocalhost.example/",
    # Spellings of 127.0.0.1 that are not the string "127.0.0.1". These do
    # resolve to this machine, so reporting them as leaving is the cautious
    # answer rather than the exact one -- the warning is about disclosure,
    # and over-warning costs a sentence while under-warning costs a client
    # book.
    "http://0x7f000001/",
    "http://2130706433/",
    "http://127.1/",
])
def test_an_address_that_is_not_plainly_this_machine_is_reported_as_leaving(url):
    """A substring check would pass several of these. The guard parses."""
    assert leaves_this_machine(url) is True


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8090", "http://localhost:8090", "http://[::1]:8090",
    "http://LocalHost:8090", "http://127.0.0.1", "https://localhost/match",
])
def test_the_self_hosted_index_is_still_recognised_as_this_machine(url):
    """Without this the block above would pass just as well if the guard
    said "leaves" to everything, which would warn a firm off the one
    deployment that keeps its client book at home."""
    assert leaves_this_machine(url) is False


def test_the_default_is_the_case_that_leaves():
    """The safe-looking case is the one that goes to a third party."""
    from vinzor.screening import DEFAULT_URL

    assert leaves_this_machine(DEFAULT_URL) is True
    assert leaves_this_machine("") is True


# -- a setting that is not an address ----------------------------------------


@pytest.mark.parametrize("url", [
    "", "   ", "localhost:8090", "127.0.0.1:8090", "api.opensanctions.org",
    "ftp://elsewhere/x", "http://", "not an address at all",
])
def test_an_unusable_address_is_refused_and_never_escapes_as_something_else(url):
    """The promise is results or ``ScreeningUnavailable``. An empty setting
    used to break it with a ValueError out of urllib, which surfaced as a
    background screening run that stopped counting and never said why."""
    with pytest.raises(ScreeningUnavailable):
        WatchlistClient(url=url, scope="default").match(
            name="Ravi Kumar", kind=EntityKind.PERSON)


def test_an_address_typed_without_a_scheme_says_so_rather_than_blaming_the_service():
    """"The service could not be reached" sends somebody to restart a
    service that was never the problem. This is a setting to correct."""
    said = unusable("localhost:8090")
    assert "http://" in said
    assert "could not be reached" not in said
    assert "nothing was recorded" in said


def test_no_address_at_all_says_to_set_one():
    said = unusable("")
    assert "No screening service address is set" in said
    assert "nothing was recorded" in said


def test_a_usable_address_is_not_refused():
    """Otherwise the tests above would pass with a function that refused
    everything, and no party could ever be screened."""
    assert unusable("http://127.0.0.1:8090") == ""
    assert unusable("https://api.opensanctions.org") == ""


def test_a_screening_run_that_cannot_reach_a_service_stops_and_says_why(
        engine, monkeypatch):
    """Where the escaped ValueError actually showed. The run is on a
    background thread, so an exception it does not catch is not reported
    anywhere -- the progress bar simply stops, short of its total, with an
    empty problem."""
    from vinzor.server import SCREENING_RUNS, _screen_fresh

    known(engine, "p1", "Ravi Kumar")
    monkeypatch.setenv("VINZOR_SCREENING_URL", "")
    SCREENING_RUNS["d"] = {"done": 0, "total": 1, "matches": 0,
                           "state": "running", "kind": "parties", "problem": ""}
    _screen_fresh(engine, ["p1"], "d")

    assert SCREENING_RUNS["d"]["state"] == "stopped"
    assert "address is set" in SCREENING_RUNS["d"]["problem"]
    assert not [e for e in engine.log
                if e.event_type is EventType.SCREENING_COMPLETED]


# -- not knowing is not the same as knowing nothing is there ------------------


def test_a_party_nobody_screened_does_not_read_like_a_party_screened_clean(engine):
    """The attack that succeeded. Both used to say "No watchlist check on
    this party has found anything" -- true of a party nobody looked for, in
    the way that says nothing, on the screen where somebody decides how
    risky they are."""
    known(engine, "p1", "Never Screened")
    known(engine, "p2", "Screened Clean")
    checked(engine, "p2", "2026-08-20", matched=False)

    never = what_screening_found(engine, "p1")
    clean = what_screening_found(engine, "p2")

    assert never.summary != clean.summary
    assert never.ever_checked is False
    assert clean.ever_checked is True
    assert "not been looked for" in never.summary
    assert "20 August 2026" in clean.summary


def test_the_absence_of_a_check_is_not_dressed_up_as_a_result(engine):
    """The sentence has to open on the absence, not on a check. It may go
    on to name the thing it is not -- saying "this is not a check that
    found nothing" is the whole point -- but it may not begin as though a
    check happened, because that is the half a reader skimming takes."""
    known(engine, "p1", "Never Screened")
    said = what_screening_found(engine, "p1").summary
    assert said.startswith("Nobody has run a watchlist check")
    assert "not the same as" in said


def test_a_party_since_removed_from_a_list_shows_both_halves(engine):
    """Lists change. Hiding the match would lose why the file exists;
    hiding the later clean check leaves somebody categorised against a
    listing that no longer exists."""
    known(engine, "p1", "Delisted")
    checked(engine, "p1", "2026-03-01", matched=True)
    checked(engine, "p1", "2026-08-20", matched=False)

    found = what_screening_found(engine, "p1")
    assert found.matched is True            # they did match, in March
    assert found.still_listed is False
    assert "sanctions list" in found.summary
    assert "most recent check, on 20 August 2026, found nothing" in found.summary


def test_a_party_still_on_a_list_is_not_told_the_check_found_nothing(engine):
    known(engine, "p1", "Still Listed")
    checked(engine, "p1", "2026-03-01", matched=True)
    checked(engine, "p1", "2026-08-20", matched=True)

    found = what_screening_found(engine, "p1")
    assert found.still_listed is True
    assert "found nothing" not in found.summary


def test_two_records_on_one_day_count_as_a_day_that_matched(engine):
    """A single check writes one record per watchlist entity matched, all
    on the same day. Reading only the last of them would call a day that
    matched a day that did not."""
    known(engine, "p1", "Two Matches One Day")
    checked(engine, "p1", "2026-08-20", matched=False)
    checked(engine, "p1", "2026-08-20", matched=True)

    found = what_screening_found(engine, "p1")
    assert found.still_listed is True
    assert "found nothing" not in found.summary


def test_the_date_of_the_last_check_is_carried_even_when_nothing_matched(engine):
    """Clause 5.9 requires screening to be ongoing. Nothing here judges
    whether a given interval is recent enough -- the guidelines do not say,
    and the firm's policy is not held in this system -- but a screen that
    cannot say *when* cannot be judged by anybody either."""
    known(engine, "p1", "Screened Clean")
    checked(engine, "p1", "2026-08-20", matched=False)
    assert what_screening_found(engine, "p1").last_checked == "2026-08-20"
