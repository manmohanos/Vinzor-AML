"""Passwords and sessions, kept deliberately out of the event log.

Until now the four names on the opening screen were a menu, not a sign-in.
That is honest for a demonstration on one laptop and disqualifying the
moment real customer data arrives -- but the hole was not the missing
password screen. It was that every write took the actor's name *from the
request body*: post ``{"person": "Rohan Kapoor"}`` and you were Senior
Management, and could clear the politically-exposed files only Senior
Management may clear. A login page in front of that would have been
theatre. What had to change was that the server works out who you are and
stops believing what you tell it.

**Why credentials are not events.** Everything else this product knows
lives in the append-only log, and a password hash must not. A log with no
delete is a log you can never rotate away from: the day a hashing choice is
broken, every hash ever set is still in the record, and that record is the
one handed to a regulator. So the secret lives in its own table in the same
file, where it can be replaced and forgotten.

What *is* an event is the authorisation: that somebody was given a way in,
by whom, and when. That is a compliance fact and it belongs in the record.
The secret itself is an operational one and does not.

Sessions are not events either, for a different reason: they are as
frequent as usage, and a log that grows with page views rather than with
facts stops being a record of anything. Who could have decided something on
a given day is answered by the enrolments and the grants, which are both in
the log.

**Three things this does that are easy to leave out.**

* The session token is stored **hashed**. A leaked database of live tokens
  is a leaked database of live sessions, and the point of hashing the
  password is lost if the thing it issues is kept in the clear beside it.
* A wrong password and an unknown name take the **same path and the same
  work**, so neither the answer nor the time it took says whether somebody
  is enrolled here.
* Wrong attempts are counted and eventually refuse for a while. Without it
  a hundred-millisecond hash is merely a slow oracle, not a closed door.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union

#: Work factor for scrypt. Measured on this machine: about 93 ms and 16 MB
#: per attempt at 2^14, which is slow enough to make guessing expensive and
#: fast enough that nobody notices signing in. Stored per record rather than
#: assumed, so it can be raised later without invalidating what is already
#: set -- an old hash keeps the numbers it was made with.
COST = 2 ** 14
BLOCK = 8
PARALLEL = 1
KEY_BYTES = 64

#: How long a session lasts without being used. A compliance officer's
#: screen sits open all day, so this is long enough not to interrupt work
#: and short enough that an unlocked laptop in an office is not a standing
#: invitation.
HOURS_IDLE = 8

#: How many wrong attempts before a name stops answering, and for how long.
#: Not a lockout anybody can trigger against somebody else permanently: it
#: expires, because a competitor who can lock out your compliance officer
#: for a day has done real damage with no password at all.
WRONG_TRIES = 5
LOCKED_MINUTES = 15

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sign_in (
    name         TEXT PRIMARY KEY,
    salt         BLOB    NOT NULL,
    secret       BLOB    NOT NULL,
    cost         INTEGER NOT NULL,
    block        INTEGER NOT NULL,
    parallel     INTEGER NOT NULL,
    set_on       TEXT    NOT NULL,
    wrong_tries  INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessions (
    token    TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    started  TEXT NOT NULL,
    expires  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS sessions_by_name ON sessions(name);
"""

#: Used when no record exists, so that an unknown name costs the same as a
#: known one. Fixed rather than random: the work is what matters, and a
#: random salt per attempt would be one more thing to get wrong.
_NOBODY_SALT = b"vinzor-no-such-person-constant-salt"


@dataclass(frozen=True)
class Refused:
    """Why a sign-in did not work, in words meant for the person trying."""

    said: str
    #: Minutes until it is worth trying again, where that is the reason.
    wait_minutes: int = 0


def _moment(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _stretch(password: str, salt: bytes, cost: int, block: int,
             parallel: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=cost, r=block, p=parallel,
        dklen=KEY_BYTES, maxmem=cost * block * 256)


class Credentials:
    """Ways in to one workspace. Its own tables, in the workspace's file."""

    def __init__(self, path: Union[str, Path] = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- setting a way in --------------------------------------------------

    def set_password(self, name: str, password: str, when: str) -> None:
        """Give somebody a way in, or replace the one they had."""
        problem = weak(password)
        if problem:
            raise ValueError(problem)
        salt = os.urandom(16)
        secret = _stretch(password, salt, COST, BLOCK, PARALLEL)
        self._conn.execute(
            "INSERT INTO sign_in (name, salt, secret, cost, block, parallel, "
            "set_on, wrong_tries, locked_until) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, '') "
            "ON CONFLICT(name) DO UPDATE SET salt=excluded.salt, "
            "secret=excluded.secret, cost=excluded.cost, "
            "block=excluded.block, parallel=excluded.parallel, "
            "set_on=excluded.set_on, wrong_tries=0, locked_until=''",
            (name, salt, secret, COST, BLOCK, PARALLEL, str(when)))
        self._conn.commit()
        # Changing a password ends every session it opened. Otherwise the
        # thing you do *because* somebody else may have your password
        # leaves theirs untouched.
        self.end_all_for(name)

    def has_password(self, name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sign_in WHERE name = ?", (name,)).fetchone()
        return row is not None

    def anybody_can_sign_in(self) -> bool:
        row = self._conn.execute("SELECT 1 FROM sign_in LIMIT 1").fetchone()
        return row is not None

    def forget(self, name: str) -> None:
        self._conn.execute("DELETE FROM sign_in WHERE name = ?", (name,))
        self._conn.commit()
        self.end_all_for(name)

    # -- signing in --------------------------------------------------------

    def sign_in(self, name: str, password: str, now: str):
        """A session token, or why not.

        An unknown name and a wrong password take the same path, cost the
        same work and give the same answer. Telling somebody which of the
        two they got wrong tells them who works here.

        **Two ways that was measured to be not quite true, and what each of
        them costs.**

        *Timing, on the locked path.* A name already locked out returned
        before any hashing ran -- median 0.03 ms against 60.75 ms for an
        unknown name, roughly two thousand times faster and an unmistakable
        tell. The stretch now runs first, whatever the answer is going to be,
        so the locked path costs what every other path costs.

        *The lockout itself, across attempts.* Lockout is per record, so an
        enrolled name with a password stops answering after five wrong tries
        while an unknown name never does. Over HTTP that classified the whole
        roster in **24 requests and 2.3 seconds**: two names "has a password",
        two "no way in". This is inherent to a per-account lockout -- the
        alternative is either locking names nobody has enrolled, which lets a
        stranger lock the roster out by guessing at it, or an unbounded table
        of every string anybody has ever submitted.

        So it is a **stated limit rather than a fixed one**: this sign-in
        does not hide *who is enrolled* from somebody willing to spend
        attempts. It hides their passwords, and one attempt tells nothing.
        Anyone deploying this on a public address should put a rate limit in
        front of it. ``tests/test_signin.py`` holds both halves in place --
        the timing, and this docstring's honesty about the rest.
        """
        row = self._conn.execute(
            "SELECT * FROM sign_in WHERE name = ?", (str(name),)).fetchone()

        # Before any branch. The work is what makes the paths cost the same,
        # and a branch that skips it is a branch a stopwatch can see.
        offered = _stretch(
            password,
            row["salt"] if row is not None else _NOBODY_SALT,
            row["cost"] if row is not None else COST,
            row["block"] if row is not None else BLOCK,
            row["parallel"] if row is not None else PARALLEL,
        )

        if row is not None:
            locked = _moment(row["locked_until"])
            asking = _moment(now)
            if locked and asking and asking < locked:
                minutes = max(1, int((locked - asking).total_seconds() // 60))
                # The same write and commit every other path makes, so that
                # the cost matches. Without it the locked path came back
                # about six milliseconds early -- small, and still a signal.
                self._conn.execute(
                    "UPDATE sign_in SET wrong_tries = wrong_tries "
                    "WHERE name = ?", (row["name"],))
                self._conn.commit()
                return None, Refused(
                    said="Too many wrong attempts. This name is not "
                         "answering for a few minutes.",
                    wait_minutes=minutes)

        if row is None:
            # The same work as a real attempt, so that the time taken says
            # nothing about whether this name is enrolled. Both halves
            # matter and this was measured: with only the hashing matched,
            # an enrolled name still answered a consistent 8 ms slower than
            # an unknown one, because the real path also writes down the
            # failed attempt and commits. Eight milliseconds is a list of
            # who works here, and unknown names never lock out, so there is
            # no limit on how often somebody may ask.
            self._conn.execute(
                "UPDATE sign_in SET wrong_tries = wrong_tries WHERE name = ?",
                (str(name),))
            self._conn.commit()
            return None, Refused(said=WRONG)

        if not hmac.compare_digest(offered, row["secret"]):
            self._note_wrong(row, now)
            return None, Refused(said=WRONG)

        self._conn.execute(
            "UPDATE sign_in SET wrong_tries = 0, locked_until = '' "
            "WHERE name = ?", (row["name"],))
        self._conn.commit()
        return self.start_session(row["name"], now), None

    def _note_wrong(self, row, now: str) -> None:
        tries = int(row["wrong_tries"]) + 1
        locked = ""
        if tries >= WRONG_TRIES:
            asking = _moment(now)
            if asking:
                locked = (asking
                          + timedelta(minutes=LOCKED_MINUTES)).isoformat()
            tries = 0
        self._conn.execute(
            "UPDATE sign_in SET wrong_tries = ?, locked_until = ? "
            "WHERE name = ?", (tries, locked, row["name"]))
        self._conn.commit()

    # -- sessions ----------------------------------------------------------

    def start_session(self, name: str, now: str) -> str:
        """A fresh token. What is returned is the only copy in the clear."""
        token = secrets.token_urlsafe(32)
        started = _moment(now) or datetime.fromisoformat("2000-01-01T00:00:00")
        self._conn.execute(
            "INSERT INTO sessions (token, name, started, expires) "
            "VALUES (?, ?, ?, ?)",
            (_fingerprint(token), name, started.isoformat(),
             (started + timedelta(hours=HOURS_IDLE)).isoformat()))
        self._conn.commit()
        return token

    def who(self, token: str, now: str) -> Optional[str]:
        """Whose session this is, if it is still one.

        Every use pushes the expiry out, which is what makes it an idle
        timeout rather than a session that dies mid-sentence after eight
        hours of work.
        """
        if not token:
            return None
        row = self._conn.execute(
            "SELECT name, expires FROM sessions WHERE token = ?",
            (_fingerprint(token),)).fetchone()
        if row is None:
            return None
        asking, expires = _moment(now), _moment(row["expires"])
        if asking is None or expires is None or asking >= expires:
            self.end_session(token)
            return None
        self._conn.execute(
            "UPDATE sessions SET expires = ? WHERE token = ?",
            ((asking + timedelta(hours=HOURS_IDLE)).isoformat(),
             _fingerprint(token)))
        self._conn.commit()
        return str(row["name"])

    def end_session(self, token: str) -> None:
        if not token:
            return
        self._conn.execute("DELETE FROM sessions WHERE token = ?",
                           (_fingerprint(token),))
        self._conn.commit()

    def end_all_for(self, name: str) -> None:
        self._conn.execute("DELETE FROM sessions WHERE name = ?", (name,))
        self._conn.commit()

    def forget_expired(self, now: str) -> int:
        asking = _moment(now)
        if asking is None:
            return 0
        cursor = self._conn.execute("DELETE FROM sessions WHERE expires < ?",
                                    (asking.isoformat(),))
        self._conn.commit()
        return cursor.rowcount or 0


def _fingerprint(token: str) -> str:
    """What is kept instead of the token itself."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


#: Said for every failed sign-in, whoever they claim to be.
WRONG = "That name and password do not go together."

#: The shortest password accepted. Length is what defeats guessing, so it
#: is the only rule here: a demand for a capital letter and a symbol buys
#: almost nothing and reliably produces the same password everywhere with a
#: 1 and a ! on the end.
SHORTEST = 12


def weak(password: str) -> str:
    """Why this password will not do, or nothing."""
    text = str(password or "")
    if len(text) < SHORTEST:
        return (f"A password needs at least {SHORTEST} characters. Length is "
                f"what makes guessing expensive; a short one with a symbol in "
                f"it is still short.")
    if text.strip() != text:
        return ("A password that begins or ends with a space is one nobody "
                "can type reliably twice.")
    if len(set(text)) < 5:
        return "That is too few different characters to be worth much."
    return ""
