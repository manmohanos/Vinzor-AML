"""The thread, assembled from the record rather than kept beside it.

A chat interface usually needs a store of its own: messages, threads, who
said what when. This one does not, and the reason is worth stating because
it decided the design.

Every turn that matters is already an event. A question asked of the
assistant is ``ASSISTANT_ASKED`` and carries the question, the answer, and
which tools were read. Work delegated is ``TASK_GIVEN`` and carries what
was asked, what the assistant said back, and the plan. So a conversation is
not a thing to be stored; it is a *reading* of two event kinds in the order
they happened.

Three things follow, and each would have had to be built otherwise.

* It survives everything the log survives. A thread cannot drift from the
  work it commissioned, because they are the same records.
* An inspector asking what the officer asked the machine, and what the
  machine did about it, gets one answer rather than two systems to
  reconcile.
* Nothing has to be deleted when a workspace is exported, replayed or
  handed over, because there is no second store to forget about.

**Turns belong to a person, not to a session.** Somebody who signs in on
another machine sees their own thread, because the record is keyed on who
asked rather than on a browser. The obvious alternative -- a session id --
would have made the same officer two people.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from .model import EventType


@dataclass(frozen=True)
class Turn:
    """One exchange: what somebody asked, and what came of it."""

    #: "answer" where the record was read and replied to, "work" where
    #: agents were set going.
    kind: str
    asked: str
    asked_by: str
    when: str
    #: Ordering within a day, so two turns on one date keep their sequence.
    at: int
    #: What the assistant said back. For work this is what it was about to
    #: do; for an answer it is the answer.
    said: str = ""
    #: Empty unless the answer was withheld, with the reason.
    withheld: str = ""
    #: What the reader looked at, so an answer can be checked.
    looked_at: tuple = ()
    #: Set on a work turn, so the thread can show its live progress.
    task_id: str = ""


@dataclass
class Talk:
    """Every exchange on this workspace, in order."""

    turns: tuple = ()

    def apply(self, event) -> None:
        payload = event.payload or {}
        if event.event_type is EventType.ASSISTANT_ASKED:
            self.turns = self.turns + (Turn(
                kind="answer",
                asked=str(payload.get("question") or ""),
                # The actor on this event is the assistant, because the
                # assistant wrote it. Who *asked* is the subject.
                asked_by=str(event.subject or ""),
                when=str(event.occurred_at)[:10],
                at=int(getattr(event, "seq", 0) or 0),
                said=str(payload.get("answer") or ""),
                withheld=str(payload.get("withheld") or ""),
                # What a person calls it, falling back to the internal name
                # for a record written before tools had a human name.
                looked_at=tuple(
                    str(one.get("shown") or one.get("tool") or "")
                    for one in (payload.get("looked_at") or ())
                    if isinstance(one, dict)),
            ),)
        elif event.event_type is EventType.TASK_GIVEN:
            self.turns = self.turns + (Turn(
                kind="work",
                asked=str(payload.get("asked") or ""),
                asked_by=str(event.actor or ""),
                when=str(event.occurred_at)[:10],
                at=int(getattr(event, "seq", 0) or 0),
                said=str(payload.get("about") or ""),
                task_id=str(event.subject or ""),
            ),)

    def thread(self, person: str = "", most: int = 40) -> tuple:
        """One person's thread, oldest first, most recent `most` turns.

        Oldest first because a conversation reads downward, and the reader
        arriving at the bottom is where the newest turn should be.
        """
        mine = [turn for turn in self.turns
                if not person or turn.asked_by == person]
        mine.sort(key=lambda turn: turn.at)
        return tuple(mine[-most:])

    def recent_asks(self, person: str = "", most: int = 8) -> tuple:
        """What this person asked lately, newest first and each once.

        For the panel that offers them back. Repeats are dropped: a list
        that shows the same question four times is a list nobody scans.
        """
        seen: set = set()
        out = []
        for turn in reversed(self.thread(person, most=200)):
            text = turn.asked.strip()
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            out.append(turn)
            if len(out) >= most:
                break
        return tuple(out)


#: Offered on an empty thread. Written as an officer would type them, not
#: as commands, because the whole point is that it takes a sentence.
#: Deliberately split across the two things it can do, so the first thing
#: somebody learns is that the difference exists.
OPENERS = (
    ("Ask about what is already known", (
        "What am I late on?",
        "Who on the book is on a watchlist?",
        "Why is the Crest Settlor Trust file still open?",
        "What does clause 5.5 say about politically exposed persons?",
    )),
    ("Set the agents working", (
        "Run the morning check across the whole book.",
        "Check whether the book is fit to hand over.",
        "Prepare the quarterly picture.",
    )),
)
