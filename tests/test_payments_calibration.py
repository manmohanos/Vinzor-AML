"""How loud the payment rule is on a book with nothing wrong in it.

Two tools already asked what the payment rules catch. ``typologies.py``
plants the seven named laundering shapes; ``adversarial.py`` perturbs a shape
we see and asks what the evasion cost. Both plant their shape **alone, in an
empty workspace**, and both say so.

Neither asked the question a compliance officer lives with: how much does
this fire when nothing is wrong. That number had never been measured, and
measuring it (``tools/ordinary_traffic.py``) put the rules at **57.7 files
per hundred payments on a book containing no wrongdoing at all**.

Two rules produced most of it, and for the same reason. "The money came
from someone other than the investor" and "the same sender has paid several
investors" both compared identifiers and asked nothing else -- so a feeder
vehicle paying the investors who hold units in it opened a file every time,
and so did a private bank paying for its clients out of an omnibus account.
That is not a laundering ring. That is what a feeder *is*.

Both were taught to ask the ownership graph whether the book already says
the two parties belong together, and **the rate fell to 24.4 per hundred**.
That fall was earned: the same rules, looking at more before they spoke.

**The rate is 11.5 now, and that second fall was not earned.** On 21 August
2026 nine of the ten payment rules were removed, including the shared-payer
rule this file was half about. The surviving rule's own contribution has not
moved -- 9 files on the same 78 payments, before and after. The other 10
files stopped appearing because the rules that opened them stopped existing.
Fewer rules over the same book is a smaller number, not a better product,
and nothing in this file or in ``ordinary_traffic.py`` may present it as a
calibration win.

What else moved with it, since both were quoted here as evidence the fix cost
nothing: ``typologies`` recognised 7 of 7 and now recognises 0 of 7, and the
adversarial lab held ten trials against four rules and now holds one against
one, which reads EVADED.

**The door is still open and is still worth measuring.** Somebody can declare
an ownership link to quiet the rule, and that is the whole of what the trial
in ``adversarial.py`` now shows: three third-party files become none, for the
price of three declarations. It used to buy them a worse question -- naming
the natural people behind the sender under 1.3.3, with three further payment
rules underneath that a declaration did not reach. Those three are gone, so
the ownership question is all that is left behind the door.
"""

from __future__ import annotations

import pytest

from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType
from vinzor.payments import related

FUND = "fnd"


@pytest.fixture
def book() -> Vinzor:
    engine = Vinzor(EventLog())
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=FUND,
                  occurred_at="2026-01-01", actor="t",
                  payload={"kind": EntityKind.FUND.value, "name": "The Fund",
                           "attributes": {}})
    return engine


def party(engine, eid, name, kind=EntityKind.COMPANY):
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=eid,
                  occurred_at="2026-01-01", actor="t",
                  payload={"kind": kind.value, "name": name, "attributes": {}})


def holds(engine, vehicle, holder, pct=100.0):
    engine.ingest(event_type=EventType.OWNERSHIP_DECLARED, subject=vehicle,
                  occurred_at="2026-01-02", actor="t",
                  payload={"owner": holder, "owned": vehicle,
                           "percentage": pct, "relation": "OWNS"})


def commit(engine, investor):
    engine.ingest(event_type=EventType.COMMITMENT_MADE, subject=investor,
                  occurred_at="2026-01-05", actor="t",
                  payload={"investor": investor, "fund": FUND,
                           "amount": 1_000_000.0})


def pay(engine, investor, payer, ref, day):
    engine.ingest(
        event_type=EventType.PAYMENT_RECEIVED, subject=investor,
        occurred_at=f"2026-03-{day:02d}", actor="t",
        payload={"payer": payer, "payment_id": ref, "amount": 250_000.0,
                 "called_amount": 250_000.0, "currency": "USD",
                 "expected_currency": "USD", "fund": FUND})


def policies_that_fired(engine) -> set:
    return {str(e.payload.get("policy_id")) for e in engine.log
            if e.event_type is EventType.CASE_OPENED}


# -- what the ordinary furniture of a fund book does now ---------------------


def test_a_feeder_paying_its_own_investors_opens_no_payment_file(book):
    """The single loudest false positive. A feeder vehicle subscribing for
    the people who hold units in it is one account paying many investors,
    and it is also just a feeder."""
    party(book, "feeder", "Cayman Feeder I", EntityKind.FUND)
    for index in range(4):
        eid = f"fed{index}"
        party(book, eid, f"Feeder Investor {index}")
        holds(book, "feeder", eid, 25.0)
        commit(book, eid)
        pay(book, eid, "feeder", f"f{index}", 4 + index)

    assert "POL_PAY_THIRD_PARTY" not in policies_that_fired(book)


def test_a_nominee_paying_for_its_clients_opens_no_payment_file(book):
    """Same shape, different institution: a private bank paying out of an
    omnibus account for the clients whose interests it holds."""
    party(book, "nominee", "Zurich Private Bank Nominees")
    for index in range(4):
        eid = f"nom{index}"
        party(book, eid, f"Nominee Client {index}")
        holds(book, "nominee", eid, 25.0)
        commit(book, eid)
        pay(book, eid, "nominee", f"n{index}", 4 + index)

    assert "POL_PAY_THIRD_PARTY" not in policies_that_fired(book)


def test_a_master_paying_through_a_feeder_is_still_related(book):
    """Two steps apart rather than one. A master, its feeder and the
    feeder's investors are one structure, and the book says so."""
    party(book, "master", "The Master Fund", EntityKind.FUND)
    party(book, "feeder", "The Feeder", EntityKind.FUND)
    party(book, "inv", "An Investor")
    holds(book, "feeder", "inv")
    holds(book, "master", "feeder")

    assert related(book.state.graph, "master", "inv")


# -- and what it must still catch --------------------------------------------


def test_an_unrelated_account_paying_investors_still_fires(book):
    """The shape the rule exists for, and the reason the fix has to read
    the graph rather than switch the rule off. A mule is not declared as
    anybody's owner.

    This used to assert the shared-payer rule as well -- the point of the
    shape was one account funding three unrelated investors. That rule was
    removed on 21 August 2026, so what is left to assert is that each of the
    three payments is a third party paying, one file at a time, with nothing
    counting how many of them there are.
    """
    party(book, "mule", "An Unrelated Account")
    for index in range(3):
        eid = f"inv{index}"
        party(book, eid, f"Investor {index}")
        commit(book, eid)
        pay(book, eid, "mule", f"m{index}", 4 + index)

    assert "POL_PAY_THIRD_PARTY" in policies_that_fired(book)


def test_a_stranger_paying_one_investor_is_still_a_third_party(book):
    party(book, "stranger", "Somebody Else Entirely")
    party(book, "inv", "An Investor")
    commit(book, "inv")
    pay(book, "inv", "stranger", "s1", 4)

    assert "POL_PAY_THIRD_PARTY" in policies_that_fired(book)


# -- what "related" means, exactly -------------------------------------------


def test_a_party_is_not_related_to_itself(book):
    """The rule already handles the investor paying their own call before
    this is reached; saying a party is related to itself would make the
    helper mean something different from what it is called."""
    party(book, "one", "One Party")
    assert not related(book.state.graph, "one", "one")


def test_two_parties_with_nothing_declared_are_not_related(book):
    party(book, "a", "A")
    party(book, "b", "B")
    assert not related(book.state.graph, "a", "b")


def test_two_investors_in_one_feeder_are_related_to_each_other(book):
    """Both are held by the same vehicle, so somebody holds both."""
    party(book, "feeder", "A Feeder", EntityKind.FUND)
    party(book, "one", "First Investor")
    party(book, "two", "Second Investor")
    holds(book, "one", "feeder", 100.0)
    holds(book, "two", "feeder", 100.0)

    assert related(book.state.graph, "one", "two")


def test_relatedness_does_not_reach_across_the_whole_book(book):
    """A chain long enough and everything is related to everything, which
    would switch the rules off by degrees rather than by decision."""
    party(book, "c0", "Company 0")
    for index in range(1, 8):
        party(book, f"c{index}", f"Company {index}")
        holds(book, f"c{index - 1}", f"c{index}", 100.0)

    assert related(book.state.graph, "c0", "c1")
    assert not related(book.state.graph, "c0", "c7")


def test_relatedness_is_never_asked_without_a_graph(book):
    """``anomalies`` is called with no graph in a few places, and a helper
    that raised there would take the payment rules down with it."""
    assert not related(None, "a", "b")


# -- the rate itself, as a guard ---------------------------------------------


def test_the_ordinary_book_stays_quiet_enough_to_use():
    """The measurement that started this, pinned so it cannot drift back.
    57.7 files per hundred payments was the position before; anything near
    that again means a rule has stopped asking who the parties are.

    The ceiling is deliberately left at 30 rather than tightened onto the
    11.5 this book now produces. Tightening it would turn a deletion into a
    standard, and the next person to restore a payment rule would meet a red
    build telling them the product used to be quieter -- which it was, by
    doing less.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import ordinary_traffic

    engine = ordinary_traffic.a_book()
    payments = sum(1 for e in engine.log
                   if e.event_type is EventType.PAYMENT_RECEIVED)
    opened = sum(ordinary_traffic.files_by_policy(engine).values())
    rate = opened / payments * 100

    assert rate < 30, (
        f"{rate:.1f} files per hundred payments on a book with nothing "
        f"wrong in it. It was 57.7 before the rules read the ownership "
        f"graph, 24.4 after, and 11.5 once eight of the nine other rules "
        f"were deleted.")
    # The surviving rule's own contribution, which did not change when the
    # others were removed. Pinned separately from the rate so that nobody can
    # read a fall in the total as this rule having improved.
    assert ordinary_traffic.files_by_policy(engine)["POL_PAY_THIRD_PARTY"] == 9
