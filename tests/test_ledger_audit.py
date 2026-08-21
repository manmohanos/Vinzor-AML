"""What the ledger claims, tested by attacking it.

This block was written down as "finished in a way the others are not", and
the useful work on a claim like that is trying to break it rather than
restating it. Two attacks succeeded.

**A hash chain cannot see its own tail.** Erase the last four events and
every remaining link still checks, because each one points backwards. For a
record whose entire promise is completeness, "verifies" was the worst
possible answer. Witness marks fix the direction the chain cannot look.

**Python writes NaN and Infinity into JSON by default**, and they are not
JSON. A single division that went wrong upstream would have put a payload on
the permanent record that no strict parser -- including a regulator's --
could read, under a hash covering bytes no other implementation would agree
with.

The rest held under attack and is kept here so it goes on holding.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from vinzor.eventlog import MARK_EVERY, EventLog
from vinzor.model import EventType, NotRecordable, canonical_json


def a_book(path, how_many=12) -> EventLog:
    log = EventLog(path)
    for index in range(how_many):
        log.append(event_type=EventType.ENTITY_REGISTERED, subject=f"p{index}",
                   occurred_at="2026-08-20", actor="test",
                   payload={"kind": "PERSON", "name": f"Party {index}",
                            "attributes": {}})
    return log


def unguard(path, *tables) -> sqlite3.Connection:
    """File-level access, which no database can defend against.

    The point of the tests below is not that this is impossible -- anybody
    holding the file can do it -- but that the log can still tell you
    afterwards.
    """
    conn = sqlite3.connect(path)
    for table in tables or ("events",):
        conn.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
        conn.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
    return conn


# -- append-only, through the ordinary door ----------------------------------


def test_an_event_cannot_be_changed(tmp_path):
    log = a_book(tmp_path / "a.db")
    with sqlite3.connect(tmp_path / "a.db") as conn:
        with pytest.raises(sqlite3.DatabaseError, match="UPDATE denied"):
            conn.execute("UPDATE events SET actor='forged' WHERE seq=5")


def test_an_event_cannot_be_removed(tmp_path):
    log = a_book(tmp_path / "a.db")
    with sqlite3.connect(tmp_path / "a.db") as conn:
        with pytest.raises(sqlite3.DatabaseError, match="DELETE denied"):
            conn.execute("DELETE FROM events WHERE seq=5")


def test_a_witness_mark_cannot_be_changed_or_removed(tmp_path):
    """The witness is only worth having if it is as hard to edit as what it
    witnesses."""
    log = a_book(tmp_path / "a.db")
    log.mark("2026-08-20")
    with sqlite3.connect(tmp_path / "a.db") as conn:
        with pytest.raises(sqlite3.DatabaseError, match="DELETE denied"):
            conn.execute("DELETE FROM marks")
        with pytest.raises(sqlite3.DatabaseError, match="UPDATE denied"):
            conn.execute("UPDATE marks SET at_seq=1")


# -- tampering, with the guards removed --------------------------------------


def test_a_changed_event_is_caught(tmp_path):
    a_book(tmp_path / "a.db")
    conn = unguard(tmp_path / "a.db")
    conn.execute("UPDATE events SET actor='forged' WHERE seq=5")
    conn.commit()
    conn.close()
    ok, why = EventLog(tmp_path / "a.db").verify()
    assert not ok
    assert "seq 5" in why


def test_an_event_cut_from_the_middle_is_caught(tmp_path):
    a_book(tmp_path / "a.db")
    conn = unguard(tmp_path / "a.db")
    conn.execute("DELETE FROM events WHERE seq IN (5,6)")
    conn.commit()
    conn.close()
    ok, why = EventLog(tmp_path / "a.db").verify()
    assert not ok


def test_the_tail_cannot_be_erased_unnoticed(tmp_path):
    """The attack that succeeded. Four events erased, every remaining link
    still checking, and verify() said True -- because a chain proves what
    remains is intact and cannot speak about what is gone from the end."""
    log = a_book(tmp_path / "a.db", how_many=20)
    log.mark("2026-08-20")
    conn = unguard(tmp_path / "a.db")
    conn.execute("DELETE FROM events WHERE seq > 16")
    conn.commit()
    conn.close()

    ok, why = EventLog(tmp_path / "a.db").verify()
    assert not ok
    assert "shorter than it has been" in why
    assert "20" in why and "16" in why


def test_a_rewritten_tail_is_caught_as_well_as_a_shorter_one(tmp_path):
    """Truncate *and* rewrite, so the log is the length it was witnessed at
    but is no longer the same log."""
    log = a_book(tmp_path / "a.db", how_many=20)
    log.mark("2026-08-20")
    conn = unguard(tmp_path / "a.db")
    conn.execute("DELETE FROM events WHERE seq > 20")
    conn.execute("UPDATE events SET actor='forged' WHERE seq=20")
    conn.commit()
    conn.close()
    ok, _why = EventLog(tmp_path / "a.db").verify()
    assert not ok


def test_an_honest_log_that_grows_still_verifies(tmp_path):
    """The whole risk of a witness is that it accuses an honest record.
    A log longer than its last mark is the ordinary case."""
    log = a_book(tmp_path / "a.db", how_many=20)
    log.mark("2026-08-20")
    for index in range(9):
        log.append(event_type=EventType.ENTITY_REGISTERED, subject=f"more{index}",
                   occurred_at="2026-08-21", actor="test",
                   payload={"kind": "PERSON", "name": "More", "attributes": {}})
    assert log.verify() == (True, None)
    assert EventLog(tmp_path / "a.db").verify() == (True, None)


def test_a_log_nobody_witnessed_still_verifies(tmp_path):
    """Marks arrived after workspaces existed. An older log with none must
    not read as broken."""
    a_book(tmp_path / "a.db", how_many=3)
    assert EventLog(tmp_path / "a.db").verify() == (True, None)


def test_marks_are_written_as_the_log_grows(tmp_path):
    """Without this the guarantee depends on somebody remembering to ask."""
    log = a_book(tmp_path / "a.db", how_many=MARK_EVERY + 5)
    assert log.furthest_mark() is not None


def test_the_head_is_what_a_report_prints(tmp_path):
    log = a_book(tmp_path / "a.db", how_many=7)
    count, head = log.head()
    assert count == 7
    assert head == list(log.read())[-1].event_hash


def test_an_empty_log_has_a_head_and_no_mark(tmp_path):
    log = EventLog(tmp_path / "empty.db")
    assert log.head()[0] == 0
    assert log.mark("2026-08-20") is None
    assert log.verify() == (True, None)


# -- what cannot go on the record --------------------------------------------


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_number_json_cannot_write_is_refused(tmp_path, value):
    """Python writes NaN and Infinity happily and they are not JSON. The
    file stops being readable by a strict parser, and the hash covers bytes
    no other implementation would agree with."""
    log = EventLog(tmp_path / "a.db")
    with pytest.raises(NotRecordable):
        log.append(event_type=EventType.ENTITY_REGISTERED, subject="p",
                   occurred_at="2026-08-20", actor="test",
                   payload={"kind": "PERSON", "name": "x", "attributes": {},
                            "amount": value})
    assert len(log) == 0


def test_the_refusal_says_the_defect_is_upstream(tmp_path):
    with pytest.raises(NotRecordable, match="computed it went wrong"):
        canonical_json({"amount": float("nan")})


def test_ordinary_numbers_are_untouched(tmp_path):
    log = EventLog(tmp_path / "a.db")
    log.append(event_type=EventType.ENTITY_REGISTERED, subject="p",
               occurred_at="2026-08-20", actor="test",
               payload={"kind": "PERSON", "name": "x", "attributes": {},
                        "amount": 0.1 + 0.2, "big": 10 ** 18, "neg": -0.0})
    back = list(log.read())[0].payload
    assert back["amount"] == 0.1 + 0.2
    assert back["big"] == 10 ** 18


# -- the claims that held --------------------------------------------------


def test_many_writers_never_share_a_sequence_number(tmp_path):
    log = EventLog(tmp_path / "a.db")
    trouble = []

    def hammer(who):
        for index in range(25):
            try:
                log.append(event_type=EventType.ENTITY_REGISTERED,
                           subject=f"t{who}-{index}", occurred_at="2026-08-20",
                           actor=f"thread{who}",
                           payload={"kind": "PERSON", "name": "x",
                                    "attributes": {}})
            except Exception as broke:      # pragma: no cover
                trouble.append(repr(broke))

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    seqs = [event.seq for event in log.read()]
    assert not trouble
    assert len(seqs) == len(set(seqs)) == 150
    assert log.verify() == (True, None)


def test_a_replayed_payload_is_the_one_the_rules_saw(tmp_path):
    """A tuple folds as a tuple live and as a list on replay unless it is
    normalised on the way in. Replay-equals-live would fail on a type
    nobody can see."""
    log = EventLog(tmp_path / "a.db")
    written = log.append(
        event_type=EventType.ENTITY_REGISTERED, subject="p",
        occurred_at="2026-08-20", actor="test",
        payload={"kind": "PERSON", "name": "Ravi रवि",
                 "attributes": {}, "list": (1, 2, {"deep": (3,)})})
    read_back = list(EventLog(tmp_path / "a.db").read())[0]
    assert written.payload == read_back.payload
    assert written.event_hash == read_back.event_hash
    assert isinstance(read_back.payload["list"], list)


def test_a_batch_that_fails_leaves_nothing_behind(tmp_path):
    """A fact and the findings made of it are one thought, and the log must
    never hold half of it."""
    log = a_book(tmp_path / "a.db", how_many=3)
    before = len(log)
    with pytest.raises(Exception):
        log.append_batch([
            {"event_type": EventType.ENTITY_REGISTERED, "subject": "good",
             "occurred_at": "2026-08-20", "actor": "t", "payload": {}},
            {"event_type": "NOT_A_REAL_EVENT", "subject": "bad",
             "occurred_at": "2026-08-20", "actor": "t", "payload": {}},
        ])
    assert len(log) == before
    assert log.verify() == (True, None)
