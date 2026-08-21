"""Work that has been waiting is work the queue has to put in front of you.

A file opened in 2018 sat fiftieth in a list that claimed to show the
oldest first, inside a group of 158 that displayed six, under a heading
about payments rather than about the two years it had been waiting. Every
part of that was working as written, and the file was still invisible.

These tests hold the queue to the opposite: age escapes the rule group, the
oldest work outranks everything, and the waiting is said out loud on the
row. None of it touches what the rules recorded -- severity, clause and
evidence are unchanged. Only where a person meets the file changes.
"""

from __future__ import annotations

import re

import pytest

from vinzor.briefing import AGED, SAY_THE_WAIT_AFTER, brief, waited_for
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import Outcome, Role, Severity

from conftest import officer, person, screened
from test_briefing import JARGON, _strings

TODAY = "2026-08-17"
LONG_AGO = "2018-11-06"          # comfortably past three months
LAST_WEEK = "2026-08-12"         # five days: still work in hand


@pytest.fixture
def engine() -> Vinzor:
    return Vinzor(EventLog())


def queue_of(engine, today=TODAY):
    return brief(engine, person="Meera Nair", today=today, hour=9)


def titles(briefing):
    return [group.title for group in briefing.groups]


# -- the group ---------------------------------------------------------------


def test_a_long_wait_takes_a_file_out_of_its_rule_group(engine):
    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Kavya Singh")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when=LONG_AGO)
    screened(engine, "p2", "SANCTIONS", alert_id="alt_2", when=TODAY)

    groups = {g.title: g for g in queue_of(engine).groups}
    aged = next(g for g in groups.values() if "waiting more than" in g.title)
    assert aged.total == 1
    assert aged.items[0].who == "Rohan Desai"

    # And the rule group keeps only the file that has not been waiting.
    by_rule = next(g for g in groups.values()
                   if "sanctions list" in g.title)
    assert by_rule.total == 1
    assert by_rule.items[0].who == "Kavya Singh"


def test_a_file_appears_once_not_in_both_places(engine):
    person(engine, "p1", "Rohan Desai")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when=LONG_AGO)

    briefing = queue_of(engine)
    seen = [item.case_id for group in briefing.groups
            for item in group.items]
    assert len(seen) == len(set(seen)), "a file was listed twice"


def test_waiting_outranks_every_rule(engine):
    """A file that has waited months goes above a critical one opened today.
    Nothing in a compliance list outranks work nobody has answered."""
    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Kavya Singh")
    screened(engine, "p1", "PEP", alert_id="alt_1", when=LONG_AGO)
    screened(engine, "p2", "SANCTIONS", alert_id="alt_2", when=TODAY)

    briefing = queue_of(engine)
    assert "waiting more than three months" in titles(briefing)[0]
    # The fresh critical file is still critical, and still right behind it.
    assert briefing.groups[1].tone == "stop"


def test_the_oldest_is_first_inside_the_group(engine):
    for number, when in ((1, "2020-01-01"), (2, "2018-11-06"),
                         (3, "2019-06-30")):
        person(engine, f"p{number}", f"Party {number}")
        screened(engine, f"p{number}", "SANCTIONS",
                 alert_id=f"alt_{number}", when=when)

    aged = queue_of(engine).groups[0]
    assert [item.who for item in aged.items] == ["Party 2", "Party 3",
                                                 "Party 1"]


def test_the_group_claims_no_clause_because_none_is_true_of_all(engine):
    """Files here were opened by different rules. Printing one file's clause
    over the group would be a shared statement that is not shared."""
    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Kavya Singh")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when=LONG_AGO)
    screened(engine, "p2", "PEP", alert_id="alt_2", when=LONG_AGO)

    aged = queue_of(engine).groups[0]
    assert aged.total == 2
    assert aged.rules == ()
    # Each file still carries its own, where it belongs.
    assert all(item.rules for item in aged.items)


def test_the_group_explains_itself_without_naming_any_rule(engine):
    person(engine, "p1", "Rohan Desai")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when=LONG_AGO)

    aged = queue_of(engine).groups[0]
    assert any("What they have in common is the waiting" in line
               for line in aged.because)
    assert any("oldest first" in line for line in aged.to_close_this)
    assert any("leaving it open is not a decision" in line
               for line in aged.to_close_this)


def test_a_settled_file_leaves_the_group_with_everything_else(engine):
    officer(engine, "Meera Nair", Role.AML_OFFICER)
    person(engine, "p1", "Rohan Desai")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when=LONG_AGO)
    assert "waiting more than three months" in titles(queue_of(engine))[0]

    case = engine.queue()[0]
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  rationale="Different date of birth; a false positive.",
                  decided_at=TODAY)
    assert not any("waiting more than" in title
                   for title in titles(queue_of(engine)))


# -- the wait, said out loud -------------------------------------------------


def test_the_row_says_how_long_it_has_waited(engine):
    person(engine, "p1", "Rohan Desai")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when=LONG_AGO)

    item = queue_of(engine).groups[0].items[0]
    assert item.waiting == "waiting 2,841 days"


def test_a_file_still_in_its_first_week_says_nothing_about_waiting(engine):
    person(engine, "p1", "Rohan Desai")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when=LAST_WEEK)

    item = queue_of(engine).groups[0].items[0]
    assert item.waiting == "", "a number on every row makes the number mean nothing"


def test_the_wait_starts_being_said_at_the_stated_threshold(engine):
    from datetime import date, timedelta

    class Fake:
        def __init__(self, when):
            self.opened_at = when
            self.is_open = True

    day = date.fromisoformat(TODAY)
    just_under = (day - timedelta(days=SAY_THE_WAIT_AFTER - 1)).isoformat()
    just_over = (day - timedelta(days=SAY_THE_WAIT_AFTER)).isoformat()
    assert waited_for(Fake(just_under), TODAY) == ""
    assert waited_for(Fake(just_over), TODAY) == f"waiting {SAY_THE_WAIT_AFTER} days"
    # And with no date to measure against, it says nothing rather than guessing.
    assert waited_for(Fake(LONG_AGO), "") == ""


# -- the ordering the list always claimed to have ----------------------------


def test_oldest_first_means_the_oldest_day_not_the_earliest_record(engine):
    """``queue_key`` sorted on the order rows were written down, so a
    workspace holding imported history put a 2018 file behind everything
    recorded before it. The list said "oldest first" the whole time."""
    person(engine, "p1", "Recent")
    person(engine, "p2", "Ancient")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when="2026-08-01")
    screened(engine, "p2", "SANCTIONS", alert_id="alt_2", when="2018-11-06")

    ordered = engine.queue()
    assert [c.opened_at for c in ordered] == ["2018-11-06", "2026-08-01"]
    assert all(c.severity is Severity.CRITICAL for c in ordered)


def test_two_files_opened_on_one_day_keep_a_settled_order(engine):
    """The record's sequence stays the tie-breaker, so the same log always
    produces the same list -- here and on a replay of it."""
    for number in (1, 2, 3):
        person(engine, f"p{number}", f"Party {number}")
        screened(engine, f"p{number}", "SANCTIONS",
                 alert_id=f"alt_{number}", when=LONG_AGO)

    once = [c.case_id for c in engine.queue()]
    assert once == [c.case_id for c in Vinzor(engine.log).queue()]


# -- the words ---------------------------------------------------------------


def test_the_new_group_says_nothing_technical(engine):
    person(engine, "p1", "Rohan Desai")
    person(engine, "p2", "Kavya Singh")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1", when=LONG_AGO)
    screened(engine, "p2", "PEP", alert_id="alt_2", when=LONG_AGO)

    offences = []
    for path, text in _strings(queue_of(engine).groups[0], "aged"):
        for pattern, what in JARGON:
            found = re.search(pattern, text)
            if found:
                offences.append(f"{path}: {what} ({found.group(0)!r})")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)
    assert AGED not in queue_of(engine).groups[0].title
