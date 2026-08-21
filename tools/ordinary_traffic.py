"""How often the payment rules fire on a book with nothing wrong in it.

    python tools/ordinary_traffic.py

Two tools already ask what these rules catch. ``typologies.py`` plants the
seven named laundering shapes and asks whether we see them; ``adversarial.py``
perturbs a shape we do see and asks what the evasion cost. Both plant their
shape **alone, in an empty workspace**, and both say so.

Neither asks the question a compliance officer actually lives with: how much
does this thing fire when nothing is wrong. That number decides whether a
product is used or ignored, and it had never been measured. A rule that
finds every typology and also opens a file on one payment in five has not
been calibrated, it has been switched on.

**Everything below is innocent, and each one is innocent for a stated
reason.** They are the ordinary furniture of a fund administrator's book:

* capital calls met from the investor's own account, in the fund's currency
* a nominee or feeder paying on behalf of several investors, which is what
  a feeder vehicle *is*
* an investor paying from a foreign account, which is most of GIFT City
* two entities with a running account, settling both ways
* a drawdown met in instalments because the investor's bank caps transfers
* a payment that arrives a little over the call and is held on account

None of it is laundering. Every file opened here is a false positive, and
the count is the cost of the rule in an officer's week.

**Three of these eight now control nothing, and they are kept anyway.**
After the payment rules were cut to one on 21 August 2026, the only rule left
that can fire here is "the money came from someone other than the investor".
The foreign-currency subscriptions, the drawdown in instalments and the
payment held on account were each innocent against a rule that no longer
exists, and there is nothing left for them to be innocent against. They stay
because they are 17 of the 78 payments the rate is measured over, and a rate
over a hand-picked numerator is not a rate.

**Where the 9 files now come from, measured 21 August 2026.** Eight of them
are the running account, and one is the ordinary chain of service payments.
Two firms that settle both ways are third parties to each other on every
payment, and the book declares no ownership between them, so the surviving
rule opens a file on each leg. That is the whole false-positive rate of this
product on this book, and it is one shape.

**What this is not.** It is not a base rate for a real firm -- the mix here
is chosen, not observed, and a firm whose investors all pay in dollars from
their own accounts will see far less. It is a floor: these shapes exist in
every fund book, so a rule that fires on them fires on every fund book.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vinzor.engine import Vinzor                          # noqa: E402
from vinzor.eventlog import EventLog                      # noqa: E402
from vinzor.model import EntityKind, EventType            # noqa: E402

FUND = "fnd_main"
CURRENCY = "USD"


def workspace() -> Vinzor:
    engine = Vinzor(EventLog())
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=FUND,
                  occurred_at="2026-01-01", actor="t",
                  payload={"kind": EntityKind.FUND.value,
                           "name": "The Fund", "attributes": {}})
    return engine


def party(engine, eid, name, kind=EntityKind.PERSON):
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=eid,
                  occurred_at="2026-01-01", actor="t",
                  payload={"kind": kind.value, "name": name, "attributes": {}})


def holds(engine, vehicle, holder, pct):
    """The holder owns part of the vehicle -- units in a feeder, an interest
    held through a nominee. A real book carries these because they are how
    beneficial ownership is worked out; they are declared here for the same
    reason and not to make a rule quieter."""
    engine.ingest(event_type=EventType.OWNERSHIP_DECLARED, subject=vehicle,
                  occurred_at="2026-01-03", actor="t",
                  payload={"owner": holder, "owned": vehicle,
                           "percentage": pct, "relation": "OWNS"})


def commit(engine, investor, amount=1_000_000.0):
    engine.ingest(event_type=EventType.COMMITMENT_MADE, subject=investor,
                  occurred_at="2026-01-05", actor="t",
                  payload={"investor": investor, "fund": FUND,
                           "amount": amount})


def pay(engine, investor, payer, ref, day, amount, called=None,
        currency=CURRENCY):
    engine.ingest(
        event_type=EventType.PAYMENT_RECEIVED, subject=investor,
        occurred_at=f"2026-03-{day:02d}", actor="t",
        payload={"payer": payer, "payment_id": ref, "amount": amount,
                 "called_amount": called if called is not None else amount,
                 "currency": currency, "expected_currency": CURRENCY,
                 "fund": FUND})


# -- the ordinary furniture of a fund book -----------------------------------


def own_account_calls(engine, how_many=40):
    """The base case: an investor meets a call from their own account, in
    the fund's currency, for the amount called."""
    for index in range(how_many):
        eid = f"inv{index}"
        party(engine, eid, f"Investor {index}")
        commit(engine, eid)
        pay(engine, eid, eid, f"own{index}", 2 + index % 20, 250_000.0)


def a_feeder_paying_for_its_investors(engine, how_many=8):
    """A feeder vehicle subscribes on behalf of the investors in it. One
    account pays for many people, which is the definition of a feeder and
    not a shared-payer ring."""
    party(engine, "feeder", "Cayman Feeder I", EntityKind.FUND)
    for index in range(how_many):
        eid = f"fed{index}"
        party(engine, eid, f"Feeder Investor {index}")
        holds(engine, "feeder", eid, 100.0 / how_many)
        commit(engine, eid)
        pay(engine, eid, "feeder", f"fed{index}", 4, 120_000.0)


def a_nominee_holding_for_clients(engine, how_many=6):
    """A private bank pays for its clients out of one omnibus account. Same
    shape, different institution."""
    party(engine, "nominee", "Zurich Private Bank Nominees", EntityKind.COMPANY)
    for index in range(how_many):
        eid = f"nom{index}"
        party(engine, eid, f"Nominee Client {index}")
        holds(engine, "nominee", eid, 100.0 / how_many)
        commit(engine, eid)
        pay(engine, eid, "nominee", f"nom{index}", 6, 90_000.0)


def foreign_currency_subscriptions(engine):
    """Investors pay from where they bank. In an international financial
    centre this is most of the book, and the bank converts on receipt.

    These eight were the loudest thing on a real book while the unexpected
    currency rule existed. It was removed on 21 August 2026 and no currency
    is compared with any other now, so these control nothing. Kept for the
    denominator."""
    for index, currency in enumerate(
            ("AED", "EUR", "GBP", "SGD", "JPY", "INR", "CHF", "AUD")):
        eid = f"fx{index}"
        party(engine, eid, f"Overseas Investor {index}")
        commit(engine, eid)
        pay(engine, eid, eid, f"fx{index}", 8, 200_000.0, currency=currency)


def a_running_account(engine):
    """Two entities that settle both ways all year. The money goes back to
    where it started every month, and nothing is being laundered.

    This held the round-trip rule quiet, and that took two attempts to get
    right. The round-trip rule was removed on 21 August 2026, and these
    eight payments did not go quiet with it -- they are now 8 of the 9
    files this whole book opens, because two firms settling both ways are
    third parties to each other and the book declares no ownership between
    them. The loudest false positive the product has left is here."""
    party(engine, "ops_a", "Fund Services India", EntityKind.COMPANY)
    party(engine, "ops_b", "Fund Services Mauritius", EntityKind.COMPANY)
    commit(engine, "ops_a")
    commit(engine, "ops_b")
    for month, day in enumerate((3, 9, 15, 21)):
        pay(engine, "ops_a", "ops_b", f"ra_out{month}", day, 40_000.0)
        pay(engine, "ops_b", "ops_a", f"ra_in{month}", day + 2, 38_000.0)


def a_drawdown_in_instalments(engine, how_many=4):
    """An investor whose bank caps a single transfer, so a call is met in
    several smaller ones over a few days.

    This was the shape the structuring rule looked for, arrived at
    innocently, and holding that rule quiet on it was the point. The rule
    was removed on 21 August 2026, so these four control nothing. Kept for
    the denominator."""
    party(engine, "capped", "An Investor Whose Bank Caps Transfers")
    commit(engine, "capped")
    for index in range(how_many):
        pay(engine, "capped", "capped", f"cap{index}", 10 + index, 8_000.0,
            called=32_000.0)


def a_payment_held_on_account(engine):
    """A little more than the call arrives and the surplus is held against
    the next one.

    Ordinary, and the overpayment tolerance was measured for it. That rule
    was removed on 21 August 2026 and nothing compares an amount with a
    call now, so this controls nothing. Kept for the denominator."""
    party(engine, "over", "A Slightly Generous Investor")
    commit(engine, "over")
    pay(engine, "over", "over", "over1", 12, 262_000.0, called=250_000.0)


def a_chain_of_ordinary_service_payments(engine):
    """Money that legitimately passes along: an investor pays a feeder, the
    feeder pays the master, the master pays its administrator.

    This held the passed-along-a-chain rule quiet, and that rule was removed
    on 21 August 2026. Two of the three legs are still held quiet by the
    ownership the book declares; the third, the administrator paying the
    master, opens a file, because an administrator is nobody's declared
    owner. It is the ninth of the nine files this book opens."""
    for eid, name in (("chain_inv", "An Investor"), ("chain_feed", "A Feeder"),
                      ("chain_master", "The Master Fund"),
                      ("chain_admin", "The Administrator")):
        party(engine, eid, name, EntityKind.COMPANY)
        commit(engine, eid)
    holds(engine, "chain_feed", "chain_inv", 100.0)
    holds(engine, "chain_master", "chain_feed", 60.0)
    pay(engine, "chain_feed", "chain_inv", "ch1", 2, 500_000.0)
    pay(engine, "chain_master", "chain_feed", "ch2", 4, 500_000.0)
    pay(engine, "chain_admin", "chain_master", "ch3", 6, 20_000.0)


ORDINARY = (
    ("calls met from the investor's own account", own_account_calls),
    ("a feeder paying for its investors", a_feeder_paying_for_its_investors),
    ("a nominee holding for clients", a_nominee_holding_for_clients),
    ("subscriptions in foreign currency", foreign_currency_subscriptions),
    ("a running account settling both ways", a_running_account),
    ("a drawdown met in instalments", a_drawdown_in_instalments),
    ("a payment held on account", a_payment_held_on_account),
    ("an ordinary chain of service payments",
     a_chain_of_ordinary_service_payments),
)


def a_book() -> Vinzor:
    engine = workspace()
    for _label, build in ORDINARY:
        build(engine)
    return engine


def files_by_policy(engine) -> Counter:
    out: Counter = Counter()
    for event in engine.log:
        if event.event_type is not EventType.CASE_OPENED:
            continue
        if not str(event.payload.get("policy_id", "")).startswith("POL_PAY"):
            continue
        out[str(event.payload["policy_id"])] += 1
    return out


#: The most false positives per hundred ordinary payments this product will
#: ship with. Stated rather than hidden, which is the rule everywhere else in
#: this codebase and was missing here: the tool measured the number and then
#: exited 0 whatever it was, so a change that doubled it read as a report.
#:
#: 11.5 measured on 21 August 2026, against 24.4 on 20 August and 57.7 before
#: the payments calibration.
#:
#: **The fall from 24.4 to 11.5 is not a calibration win and must never be
#: reported as one.** Nothing about the surviving rule changed: "the money
#: came from someone other than the investor" opened 9 files on this book
#: before the cut and opens the same 9 now. The other 10 files went away
#: because the eight rules that opened them were deleted. Same denominator,
#: fewer rules, smaller numerator. The 57.7 to 24.4 fall was earned -- that
#: one came from teaching a rule about declared ownership so it stopped
#: reporting feeders as findings. This one was bought by looking at less.
LOUDEST_ACCEPTABLE = 30.0


def main() -> int:
    engine = a_book()
    payments = sum(1 for e in engine.log
                   if e.event_type is EventType.PAYMENT_RECEIVED)
    opened = files_by_policy(engine)

    print()
    print("  A BOOK WITH NOTHING WRONG IN IT")
    print()
    for label, _ in ORDINARY:
        print(f"    {label}")
    print()
    print(f"  {payments} payments. Every file below is a false positive.")
    print()
    print(f"  {'rule':<34}{'files':>7}{'per 100 payments':>19}")
    print("  " + "-" * 60)
    for name, count in opened.most_common():
        print(f"  {name:<34}{count:>7}{count / payments * 100:>18.1f}")
    total = sum(opened.values())
    print("  " + "-" * 60)
    print(f"  {'every payment rule':<34}{total:>7}"
          f"{total / payments * 100:>18.1f}")
    print()
    if not total:
        print("  Nothing fired. Either the rules are well judged or this")
        print("  book is too tidy to be a test -- check the shapes above.")
    print()
    loud = total / payments * 100
    if loud > LOUDEST_ACCEPTABLE:
        print(f"  FAILING: {loud:.1f} files per 100 payments on a book with "
              f"nothing wrong in it, against a stated ceiling of "
              f"{LOUDEST_ACCEPTABLE:.1f}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
