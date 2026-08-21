"""What an agent writes on the permanent record, tested for whether it is true.

The block's structural claims all held: nine tools, five recipes, none of the
nine writes or mutates anything, progress really is a reading of the log, and
the fold really does refuse a decision authored under an agent's own name.

**What did not hold was the arithmetic.** Three steps put counts on the log
that did not mean what their words said, and each one failed in the safe-
sounding direction.

* The ownership walk took the first sixty entities of *any* kind, in
  registration order, and called them structures. On the shipped book that
  is one structure and fifty-nine natural people -- who have no ownership
  chain, so nothing about them can be incomplete. It recorded **"60
  structures followed, none could not be completed"** while eighty-three
  structures it never looked at held eighteen broken chains.
* The screening step counted an attempt as a check and swallowed every
  failure. One character wrong in an environment variable, and a run in
  which the watchlist refused all forty requests recorded **"40 of 218
  checked, 0 worth a look"** -- the words a clean pass uses.
* And it cut its list of matched parties at eight without saying so. A
  morning check that found twelve named eight and dropped four, two of them
  debarments.

All three are the same defect wearing different clothes: not knowing,
written down as knowing, on a record nobody can rewrite.
"""

from __future__ import annotations

import pytest

from vinzor.agents import (MOST_NAMES, MOST_STRUCTURES, _screen_everyone,
                           _walk_ownership)
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType

WHEN = "2026-08-20"


def a_book(people=59, structures=6):
    """People first, so registration order puts the structures last -- which
    is exactly how the walk came to miss them."""
    engine = Vinzor(EventLog())
    for index in range(people):
        engine.ingest(event_type=EventType.ENTITY_REGISTERED,
                      subject=f"per{index}", occurred_at=WHEN, actor="t",
                      payload={"kind": EntityKind.PERSON.value,
                               "name": f"A Person {index}", "attributes": {}})
    for index in range(structures):
        engine.ingest(event_type=EventType.ENTITY_REGISTERED,
                      subject=f"co{index}", occurred_at=WHEN, actor="t",
                      payload={"kind": EntityKind.COMPANY.value,
                               "name": f"A Company {index}", "attributes": {}})
    return engine


# -- the ownership walk ------------------------------------------------------


def test_the_ownership_walk_follows_structures_not_whoever_registered_first():
    """A natural person is their own beneficial owner. Walking one, finding
    nothing incomplete and counting it as a structure followed is how "none
    could not be completed" came to mean nothing at all."""
    engine = a_book()
    found = _walk_ownership(engine)

    assert "of 6 structures followed" in found.headline
    assert found.carried["structures"] == 6
    assert found.carried["looked"] == 6


def test_a_book_of_only_people_has_no_structures_to_follow():
    engine = a_book(people=20, structures=0)
    found = _walk_ownership(engine)
    assert "0 of 0 structures" in found.headline


def test_a_walk_that_stopped_short_says_where_it_stopped():
    engine = a_book(people=1, structures=4)
    found = _walk_ownership(engine, cap=2)
    assert found.carried["looked"] == 2
    assert any("stopped at 2" in line and "4 structures" in line
               for line in found.details)


def test_how_many_structures_are_followed_is_a_stated_limit():
    import inspect

    import vinzor.agents as agents

    assert isinstance(MOST_STRUCTURES, int)
    stated = inspect.getsource(agents)
    stated = stated[:stated.index("MOST_STRUCTURES = ")]
    assert "any* kind" in stated or "any kind" in stated


# -- the screening step ------------------------------------------------------


class _Refuses:
    """A watchlist that answers nothing, the way a mistyped scope does."""

    def match(self, **_rest):
        from vinzor.screening import ScreeningUnavailable

        raise ScreeningUnavailable(
            "The screening service answered 404 and the check was not "
            "performed. Nothing was recorded.")


class _Finds:
    def __init__(self, how_many):
        self.how_many = how_many
        self.asked = 0

    def match(self, **_rest):
        from vinzor.screening import Hit

        self.asked += 1
        if self.asked > self.how_many:
            return [], {}
        return [Hit(entity_id=f"os:{self.asked}", caption="x", score=1.0,
                    topics=("sanction",), datasets=())], {}


def test_a_run_where_every_check_was_refused_does_not_read_as_a_clean_pass():
    """The words a clean pass uses, for a run that reached nothing. One
    character wrong in an environment variable produced exactly this."""
    engine = a_book(people=5, structures=0)
    found = _screen_everyone(engine, client=_Refuses(), cap=5)

    assert "checked, 0 worth a look" not in found.headline
    assert "could be checked" in found.headline
    assert found.how == "failed"
    assert found.carried["checked"] == 0
    assert found.carried["refused"] == 5


def test_the_reason_the_checks_failed_is_on_the_record():
    """Otherwise the next reader has a failed step and no way to know it was
    a mistyped setting rather than a watchlist that is down."""
    engine = a_book(people=3, structures=0)
    found = _screen_everyone(engine, client=_Refuses(), cap=3)
    assert any("404" in line for line in found.details)


def test_a_run_where_some_checks_failed_says_how_many():
    engine = a_book(people=4, structures=0)

    class _Sometimes:
        def __init__(self):
            self.asked = 0

        def match(self, **_rest):
            from vinzor.screening import ScreeningUnavailable

            self.asked += 1
            if self.asked % 2:
                raise ScreeningUnavailable("could not be reached")
            return [], {}

    found = _screen_everyone(engine, client=_Sometimes(), cap=4)
    assert found.carried["checked"] == 2
    assert found.carried["refused"] == 2
    assert "could not be checked" in found.headline


def test_a_clean_run_still_reads_as_a_clean_run():
    """The fix must not make an ordinary morning look like a failure."""
    engine = a_book(people=4, structures=0)
    found = _screen_everyone(engine, client=_Finds(0), cap=4)
    assert found.headline.startswith("4 of 4 checked, 0 worth a look")
    assert "could not be checked" not in found.headline
    assert found.how == "done"


def test_matched_parties_beyond_the_list_are_counted_out_loud():
    """Twelve matched, eight named, four dropped -- two of them debarments,
    and nothing on the page or the record said anything was left out."""
    engine = a_book(people=MOST_NAMES + 4, structures=0)
    found = _screen_everyone(engine, client=_Finds(MOST_NAMES + 4),
                             cap=MOST_NAMES + 4)

    assert found.carried["matched"] == MOST_NAMES + 4
    assert any("4 more that matched, not named here" in line
               for line in found.details)


def test_a_list_that_fits_says_nothing_extra():
    engine = a_book(people=3, structures=0)
    found = _screen_everyone(engine, client=_Finds(3), cap=3)
    assert not any("not named here" in line for line in found.details)
