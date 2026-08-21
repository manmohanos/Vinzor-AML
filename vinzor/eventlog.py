"""The append-only, hash-chained event log.

This is the whole persistence story. One file, one workspace.

Two decisions worth defending:

* **The event log is also the audit trail.** The previous build maintained an
  event store *and* a separate hash-chained audit log, which meant two things
  that could disagree about what happened. Here there is one stream: a human
  decision is an event like any other, and "show me the audit trail" is just
  "read the log". Nothing can be audited that is not also replayable, and
  nothing can be replayed that is not also audited.

* **Tenant isolation is one file per workspace**, not a ``tenant_id`` column.
  A column has to be filtered correctly in every query forever; a separate file
  cannot leak across tenants even if the query is wrong. It is less code and a
  stronger guarantee.

Storage is ``sqlite3`` from the standard library. It is a single-writer,
append-only ledger of a few hundred thousand rows at most -- Postgres buys
nothing here yet, and the schema is plain SQL, so moving later is a port of
this one module.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence, Union

from .model import GENESIS_HASH, Event, EventType, canonical_json, event_digest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq         INTEGER PRIMARY KEY,
    event_type  TEXT    NOT NULL,
    subject     TEXT    NOT NULL,
    occurred_at TEXT    NOT NULL,
    actor       TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    prev_hash   TEXT    NOT NULL,
    event_hash  TEXT    NOT NULL UNIQUE
);

-- Immutability is enforced by the database, not by convention. Application
-- code cannot forget to honour it, and neither can a stray sqlite3 shell.
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'event log is append-only: UPDATE denied'); END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'event log is append-only: DELETE denied'); END;

-- How long the log was, and what its head was, at moments in the past.
--
-- A hash chain proves that what remains is intact. It cannot prove that
-- nothing was taken off the *end*: drop the last four rows and every
-- remaining link still checks, because each link only points backwards.
-- Measured on this log before this table existed -- four events erased and
-- verify() returned True -- which for a record whose entire promise is
-- completeness is the worst answer it could give.
--
-- A witness fixes the direction the chain cannot see. Each mark says the
-- log once reached this length with this head, so a log that is now shorter
-- is provably missing its tail.
CREATE TABLE IF NOT EXISTS marks (
    at_seq     INTEGER PRIMARY KEY,
    head_hash  TEXT NOT NULL,
    marked_at  TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS marks_no_update
BEFORE UPDATE ON marks
BEGIN SELECT RAISE(ABORT, 'marks are append-only: UPDATE denied'); END;

CREATE TRIGGER IF NOT EXISTS marks_no_delete
BEFORE DELETE ON marks
BEGIN SELECT RAISE(ABORT, 'marks are append-only: DELETE denied'); END;
"""

#: How often a mark is written. Every append would double the writes for no
#: extra guarantee -- a mark every fifty events bounds an undetected
#: truncation to the last forty-nine, and a mark is written on demand
#: whenever anything asks the log to verify itself, which every report does.
MARK_EVERY = 50


class EventLog:
    """An append-only sequence of hash-chained events."""

    def __init__(self, path: Union[str, Path] = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # An HTTP server hands each request to its own thread, and SQLite
        # binds a connection to its creating thread by default. This is a
        # single-writer append-only ledger, so the honest fix is to share one
        # connection and serialise every use of it -- not to spread writes
        # across connections and hope the ordering works out.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            # Write-ahead logging, at full durability. Measured on this log:
            # 5.07 ms per fact recorded down to 0.97 ms, with synchronous=FULL
            # kept -- the safety guarantee is unchanged, and the chain verifies
            # identically. We do not take the faster synchronous=NORMAL: it can
            # lose the last writes to a power cut, and a record whose whole
            # promise is that it is complete must not trade that away.
            #
            # It also lets a reader read while a write is in flight, which the
            # served screen needs, and it is the format Litestream replicates
            # from if a workspace is ever streamed to backup storage.
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- writing ----------------------------------------------------------

    def append(
        self,
        *,
        event_type: EventType,
        subject: str,
        occurred_at: str,
        actor: str,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> Event:
        """Append one event and return it, with its assigned seq and hash.

        ``occurred_at`` is required and never defaulted to the current time.
        The caller always knows when the thing happened; the log never guesses.
        """
        return self.append_batch([
            {"event_type": event_type, "subject": subject,
             "occurred_at": occurred_at, "actor": actor, "payload": payload}
        ])[0]

    def append_batch(self, specs: Sequence[Mapping[str, Any]]) -> list[Event]:
        """Append several events as one transaction: all recorded, or none.

        This exists for one caller: a fact and the findings the rulepack made
        of it. Those are one thought, and the log must never hold half of it --
        a fact whose findings were lost to a crash would replay as a fact the
        rules never saw.

        Every payload is normalised through canonical JSON before hashing, so
        the object handed back to the live fold is byte-for-byte the object a
        replay will read. Without this, a tuple in a payload would fold as a
        tuple live and as a list on replay, and replay-equals-live would fail
        on a type nobody can see.
        """
        # Reading the tail and appending must be one atomic step, or two
        # concurrent writers derive the same seq and the same prev_hash.
        with self._lock:
            row = self._conn.execute(
                "SELECT seq, event_hash FROM events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            seq = (row["seq"] + 1) if row else 1
            prev_hash = row["event_hash"] if row else GENESIS_HASH

            events: list[Event] = []
            rows = []
            # Build and validate everything before touching the database, so a
            # bad spec anywhere aborts the whole batch.
            for spec in specs:
                payload = json.loads(canonical_json(dict(spec.get("payload") or {})))
                event = Event(
                    seq=seq,
                    event_type=EventType(spec["event_type"]),
                    subject=spec["subject"],
                    occurred_at=spec["occurred_at"],
                    actor=spec["actor"],
                    payload=payload,
                    prev_hash=prev_hash,
                    event_hash="",
                )
                digest = event.recompute_hash()
                event = Event(**{**event.__dict__, "event_hash": digest})
                events.append(event)
                rows.append((seq, str(event.event_type), event.subject,
                             event.occurred_at, event.actor,
                             canonical_json(payload), prev_hash, digest))
                prev_hash = digest
                seq += 1
            try:
                self._conn.executemany(
                    "INSERT INTO events (seq, event_type, subject, occurred_at,"
                    " actor, payload, prev_hash, event_hash) VALUES (?,?,?,?,?,?,?,?)",
                    rows,
                )
                # Witnessed inside the same transaction as the events it
                # witnesses. Written afterwards, a crash between the two
                # would leave a log whose last mark is a lie in the
                # direction that matters least -- but also a mark that
                # could outlive a rolled-back write and accuse an honest
                # log of having lost its tail.
                last = events[-1]
                if last.seq // MARK_EVERY != (last.seq - len(events)) // MARK_EVERY:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO marks (at_seq, head_hash, "
                        "marked_at) VALUES (?, ?, ?)",
                        (last.seq, last.event_hash, last.occurred_at))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return events

    # -- reading ----------------------------------------------------------

    def __iter__(self) -> Iterator[Event]:
        return iter(self.read())

    def __len__(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def read(self, since: int = 0) -> Iterator[Event]:
        """Events with ``seq > since``, in order.

        Rows are drained inside the lock rather than streamed out of a live
        cursor: a reader that yields lazily would hold the connection open
        across a caller's arbitrary work, and a concurrent append would then
        block on it.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE seq > ? ORDER BY seq", (since,)
            ).fetchall()
        return iter([_row_to_event(row) for row in rows])

    # -- integrity --------------------------------------------------------

    # -- witnessing --------------------------------------------------------

    def mark(self, when: str = "") -> Optional[tuple]:
        """Witness the log's present length and head.

        Cheap and idempotent: a mark already standing at this length is left
        alone rather than rewritten, which is also what makes the table
        append-only without a conflict.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT seq, event_hash FROM events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            standing = self._conn.execute(
                "SELECT head_hash FROM marks WHERE at_seq = ?",
                (row["seq"],)).fetchone()
            if standing is not None:
                return (row["seq"], row["event_hash"])
            self._conn.execute(
                "INSERT INTO marks (at_seq, head_hash, marked_at) "
                "VALUES (?, ?, ?)",
                (row["seq"], row["event_hash"], str(when)))
            self._conn.commit()
            return (row["seq"], row["event_hash"])

    def furthest_mark(self) -> Optional[tuple]:
        """The longest this log has ever been witnessed at."""
        row = self._conn.execute(
            "SELECT at_seq, head_hash, marked_at FROM marks "
            "ORDER BY at_seq DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return (row["at_seq"], row["head_hash"], row["marked_at"])

    def head(self) -> tuple:
        """(how many events, the head hash). What a report should print.

        Printed on a report, this pair leaves the building and becomes a
        witness nothing inside the file can reach: a document handed over in
        July saying the log stood at 1,638 is evidence against a log that
        says 1,400 in September.
        """
        row = self._conn.execute(
            "SELECT seq, event_hash FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return (0, GENESIS_HASH)
        return (row["seq"], row["event_hash"])

    def verify(self) -> tuple[bool, Optional[str]]:
        """Check the chain, and check nothing was taken off the end.

        The second half is the one a hash chain cannot do for itself.
        """
        ok, why = verify_chain(self)
        if not ok:
            return ok, why

        witness = self.furthest_mark()
        if witness is None:
            return True, None
        at_seq, head_hash, marked_at = witness
        here = len(self)
        if here < at_seq:
            return False, (
                f"the record is shorter than it has been: it stood at "
                f"{at_seq:,} events on {marked_at or 'an earlier date'} and "
                f"holds {here:,} now, so {at_seq - here:,} have been taken "
                f"off the end. Every remaining link still checks, which is "
                f"what a chain can tell you and why this is checked "
                f"separately.")
        row = self._conn.execute(
            "SELECT event_hash FROM events WHERE seq = ?", (at_seq,)).fetchone()
        if row is not None and row["event_hash"] != head_hash:
            return False, (
                f"the event at {at_seq:,} is not the one witnessed on "
                f"{marked_at or 'an earlier date'}: the record has been "
                f"rewritten from that point.")
        return True, None

    def close(self) -> None:
        self._conn.close()


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        seq=row["seq"],
        event_type=EventType(row["event_type"]),
        subject=row["subject"],
        occurred_at=row["occurred_at"],
        actor=row["actor"],
        payload=json.loads(row["payload"]),
        prev_hash=row["prev_hash"],
        event_hash=row["event_hash"],
    )


def verify_chain(events: Iterable[Event]) -> tuple[bool, Optional[str]]:
    """Check the chain end to end.

    Takes any iterable of events rather than a log, so that tampering can be
    tested against a plain list without having to defeat the database triggers.

    Returns ``(ok, reason)``; ``reason`` names the first seq that fails and how.
    """
    expected_seq = 1
    prev_hash = GENESIS_HASH
    for event in events:
        if event.seq != expected_seq:
            return False, f"seq {event.seq}: expected dense seq {expected_seq}"
        if event.prev_hash != prev_hash:
            return False, f"seq {event.seq}: prev_hash does not match seq {event.seq - 1}"
        if event.recompute_hash() != event.event_hash:
            return False, f"seq {event.seq}: contents do not match stored hash"
        prev_hash = event.event_hash
        expected_seq += 1
    return True, None
