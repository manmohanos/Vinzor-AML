"""The log is the only thing that is persisted, so it gets the hardest tests."""

from __future__ import annotations

import dataclasses
import sqlite3

import pytest

from vinzor.eventlog import EventLog, verify_chain
from vinzor.model import GENESIS_HASH, EventType

from conftest import WHEN


def _append(log: EventLog, n: int) -> None:
    for i in range(n):
        log.append(
            event_type=EventType.ENTITY_REGISTERED,
            subject=f"per_{i}",
            occurred_at=WHEN,
            actor="system",
            payload={"kind": "PERSON", "name": f"P{i}"},
        )


def test_seq_is_dense_and_starts_at_one():
    log = EventLog()
    _append(log, 3)
    assert [e.seq for e in log] == [1, 2, 3]


def test_first_event_links_to_genesis_and_the_rest_chain():
    log = EventLog()
    _append(log, 3)
    events = list(log)
    assert events[0].prev_hash == GENESIS_HASH
    assert events[1].prev_hash == events[0].event_hash
    assert events[2].prev_hash == events[1].event_hash


def test_healthy_chain_verifies():
    log = EventLog()
    _append(log, 5)
    assert log.verify() == (True, None)


def test_editing_a_payload_breaks_the_chain():
    log = EventLog()
    _append(log, 5)
    events = list(log)
    events[2] = dataclasses.replace(events[2], payload={"kind": "PERSON", "name": "forged"})

    ok, reason = verify_chain(events)
    assert not ok
    assert "seq 3" in reason


def test_removing_an_event_breaks_the_chain():
    log = EventLog()
    _append(log, 5)
    events = list(log)
    del events[2]

    ok, reason = verify_chain(events)
    assert not ok


def test_reordering_events_breaks_the_chain():
    log = EventLog()
    _append(log, 5)
    events = list(log)
    events[1], events[2] = events[2], events[1]

    ok, _ = verify_chain(events)
    assert not ok


def test_database_refuses_update():
    log = EventLog()
    _append(log, 1)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        log._conn.execute("UPDATE events SET subject = 'x' WHERE seq = 1")


def test_database_refuses_delete():
    log = EventLog()
    _append(log, 1)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        log._conn.execute("DELETE FROM events WHERE seq = 1")


def test_identical_inputs_produce_identical_hashes():
    """No hidden clock, no randomness: the same facts hash the same way.

    If anything in the write path ever reads ``datetime.now()``, this fails.
    """
    a, b = EventLog(), EventLog()
    _append(a, 4)
    _append(b, 4)
    assert [e.event_hash for e in a] == [e.event_hash for e in b]


def test_payload_key_order_does_not_change_the_hash():
    a, b = EventLog(), EventLog()
    a.append(event_type=EventType.ENTITY_REGISTERED, subject="s", occurred_at=WHEN,
             actor="system", payload={"x": 1, "y": 2})
    b.append(event_type=EventType.ENTITY_REGISTERED, subject="s", occurred_at=WHEN,
             actor="system", payload={"y": 2, "x": 1})
    assert list(a)[0].event_hash == list(b)[0].event_hash


def test_survives_a_round_trip_to_disk(tmp_path):
    path = tmp_path / "ws" / "log.db"
    log = EventLog(path)
    _append(log, 3)
    hashes = [e.event_hash for e in log]
    log.close()

    reopened = EventLog(path)
    assert [e.event_hash for e in reopened] == hashes
    assert reopened.verify() == (True, None)


def test_read_since_returns_only_newer_events():
    log = EventLog()
    _append(log, 5)
    assert [e.seq for e in log.read(since=3)] == [4, 5]


# -- tamper detection, fuzzed rather than only tried at one hand-picked spot -
#
# ``test_editing_a_payload_breaks_the_chain`` and its neighbours above each
# try exactly one kind of tamper at exactly one position (seq 3 of 5). That
# proves the chain catches *that* forgery; it does not prove every field, at
# every position in a log of any length, is covered. Mutation-testing
# literature calls the untried combinations "surviving mutants" -- changes a
# real attacker could make that the existing tests never exercised. This
# sweeps every mutable field of ``Event`` against every position of logs of
# several lengths, seeded so it is exactly as reproducible as a hand-picked
# example.


def test_tampering_any_single_field_at_any_position_always_breaks_the_chain():
    """No field, at no position, can be forged without ``verify_chain`` catching it.

    Each trial takes a fresh untampered log, edits exactly one field of one
    event to a different value, and asserts the chain no longer verifies.
    Covers every field ``Event.recompute_hash`` folds in (``event_type``,
    ``subject``, ``occurred_at``, ``actor``, ``payload``) plus the two chain
    links themselves (``prev_hash``, ``event_hash``), across logs of five
    different lengths and every position in each.
    """
    import random

    from vinzor.model import EventType as ET

    rng = random.Random(20260814)
    fields = ("event_type", "subject", "occurred_at", "actor", "payload",
              "prev_hash", "event_hash")
    trials = 0

    for length in (1, 2, 5, 9, 16):
        for position in range(length):
            for field_name in fields:
                log = EventLog()
                _append(log, length)
                events = list(log)
                assert verify_chain(events) == (True, None)

                target = events[position]
                if field_name == "event_type":
                    other = ET.OWNERSHIP_DECLARED if target.event_type is not ET.OWNERSHIP_DECLARED else ET.SCREENING_COMPLETED
                    tampered = dataclasses.replace(target, event_type=other)
                elif field_name == "subject":
                    tampered = dataclasses.replace(target, subject=target.subject + "_forged")
                elif field_name == "occurred_at":
                    tampered = dataclasses.replace(target, occurred_at="1999-01-01")
                elif field_name == "actor":
                    tampered = dataclasses.replace(target, actor="forger")
                elif field_name == "payload":
                    tampered = dataclasses.replace(
                        target, payload={**target.payload, "name": "forged"}
                    )
                elif field_name == "prev_hash":
                    tampered = dataclasses.replace(
                        target, prev_hash="f" * 64 if target.prev_hash != "f" * 64 else "e" * 64
                    )
                else:  # event_hash
                    tampered = dataclasses.replace(
                        target, event_hash="f" * 64 if target.event_hash != "f" * 64 else "e" * 64
                    )

                events[position] = tampered
                ok, reason = verify_chain(events)
                assert not ok, (
                    f"length={length} position={position} field={field_name} "
                    f"was tampered and still verified"
                )
                assert reason
                trials += 1
                log.close()

    assert trials == sum(length for length in (1, 2, 5, 9, 16)) * len(fields)


# -- a date that is not a date -----------------------------------------------


def test_a_date_that_does_not_exist_never_reaches_the_log(engine):
    """A payment dated 2026-13-45 used to fail as "tuple index out of range"
    from inside the payment window -- which tells an operator loading a client
    file precisely nothing -- and event types that happen to do no date
    arithmetic accepted the same value quietly, leaving a workspace carrying a
    date that would only fail years later when something tried to read it.
    """
    from vinzor.model import EntityKind, EventType

    before = len(engine.log)
    for wrong in ("2026-13-45", "2026-02-30", "15/08/2026", "yesterday", ""):
        with pytest.raises(ValueError, match="date"):
            engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="p1",
                          occurred_at=wrong,
                          payload={"kind": EntityKind.PERSON.value,
                                   "name": "A Person", "attributes": {}})
    assert len(engine.log) == before, "a refused date still wrote a record"


def test_the_refusal_says_which_date_and_why(engine):
    from vinzor.model import check_date

    with pytest.raises(ValueError, match="month must be in 1..12"):
        check_date("2026-13-01")
    with pytest.raises(ValueError, match="day is out of range"):
        check_date("2026-02-30")
    # A leap day is a real date and must survive.
    assert check_date("2024-02-29") == "2024-02-29"


def test_a_real_date_is_untouched(engine):
    from vinzor.model import EntityKind, EventType

    result = engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="p1",
                           occurred_at=" 2026-08-15 ",
                           payload={"kind": EntityKind.PERSON.value,
                                    "name": "A Person", "attributes": {}})
    assert result.event.occurred_at == "2026-08-15"
