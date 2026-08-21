"""Which duplicates this book can see, and which it cannot.

    python tools/duplicate_shapes.py

Every other block in this product states an accuracy. Screening scores 90.7%
F1 against 455,219 analyst judgements; the payment rules were measured against
a Danish bank's alerts and found worthless before two better ones were
written. Entity resolution stated only a *speed*: 61x faster, flat at 7ms a
party. Fast at what was never asked.

So this asks. Each shape below is a way a real book ends up holding one party
twice -- a registrar exporting two folios, a marriage, a company gaining
"Private Limited", a name typed with an initial. They are planted one pair at
a time in a clean workspace and the product is asked what it sees.

**Namesakes are planted too, and they are the point.** A detector that
raises every pair scores perfect recall and is useless, because an officer
who is shown four hundred pairs a week stops reading them. So the control
set holds people who genuinely are different -- two men called Rajesh Kumar
with different birthdays, a father and son sharing a name -- and anything
raised there is counted against the score.

**This flatters the product.** Each pair is planted alone, with no book
around it, so nothing competes for the comparison budget. A duplicate missed
here is missed anywhere; one found here may still be lost on a real book of
fifty thousand where four hundred people share a surname.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vinzor.duplicates import look, sounds_of              # noqa: E402
from vinzor.engine import Vinzor                           # noqa: E402
from vinzor.eventlog import EventLog                       # noqa: E402
from vinzor.model import EntityKind, EventType             # noqa: E402

WHEN = "2026-08-20"


def workspace() -> Vinzor:
    return Vinzor(EventLog())


def register(engine, entity_id, name, kind=EntityKind.PERSON, **attributes):
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=entity_id,
                  occurred_at=WHEN, actor="test",
                  payload={"kind": kind.value, "name": name,
                           "attributes": {k: v for k, v in attributes.items()
                                          if v}})


#: (label, left, right) where left and right are (name, kind, attributes).
#: Every pair here is one party twice.
SAME = [
    ("two folios, same number",
     ("Rajesh Kumar", EntityKind.PERSON, {"pan": "ABCDE1234F",
                                          "customer_reference": "F-001"}),
     ("Rajesh Kumar", EntityKind.PERSON, {"pan": "ABCDE1234F",
                                          "customer_reference": "F-902"})),
    ("two folios, no number, same birthday",
     ("Rajesh Kumar", EntityKind.PERSON, {"dob": "1979-04-11",
                                          "customer_reference": "F-001"}),
     ("Rajesh Kumar", EntityKind.PERSON, {"dob": "1979-04-11",
                                          "customer_reference": "F-902"})),
    ("a letter mistyped",
     ("Rajesh Kumar", EntityKind.PERSON, {"dob": "1979-04-11"}),
     ("Rajesh Kumaar", EntityKind.PERSON, {"dob": "1979-04-11"})),
    ("married, surname added",
     ("Priya Raghavan", EntityKind.PERSON, {"dob": "1988-02-03",
                                            "email": "priya@example.com"}),
     ("Priya Raghavan Menon", EntityKind.PERSON, {"dob": "1988-02-03",
                                                  "email": "priya@example.com"})),
    ("married, surname replaced",
     ("Priya Raghavan", EntityKind.PERSON, {"dob": "1988-02-03",
                                            "email": "priya@example.com"}),
     ("Priya Menon", EntityKind.PERSON, {"dob": "1988-02-03",
                                         "email": "priya@example.com"})),
    ("married, surname replaced, number carried",
     ("Priya Raghavan", EntityKind.PERSON, {"pan": "PQRST5678K"}),
     ("Priya Menon", EntityKind.PERSON, {"pan": "PQRST5678K"})),
    ("recorded with an initial",
     ("Rajesh Kumar", EntityKind.PERSON, {"dob": "1979-04-11",
                                          "phone": "+919812345678"}),
     ("R. Kumar", EntityKind.PERSON, {"dob": "1979-04-11",
                                      "phone": "+919812345678"})),
    ("company gains Private Limited",
     ("Zenith Capital", EntityKind.COMPANY, {"date_of_incorporation": "2014-06-01",
                                             "email": "ops@zenith.example"}),
     ("Zenith Capital Private Limited", EntityKind.COMPANY,
      {"date_of_incorporation": "2014-06-01", "email": "ops@zenith.example"})),
    ("company written Ltd not Limited",
     ("Meridian Holdings Limited", EntityKind.COMPANY,
      {"date_of_incorporation": "2011-03-09", "email": "ir@meridian.example"}),
     ("Meridian Holdings Ltd", EntityKind.COMPANY,
      {"date_of_incorporation": "2011-03-09", "email": "ir@meridian.example"})),
    ("company written Pvt Ltd",
     ("Orion Advisors Private Limited", EntityKind.COMPANY, {"cin": "U67190MH2011"}),
     ("Orion Advisors Pvt Ltd", EntityKind.COMPANY, {"cin": "U67190MH2011"})),
    ("spacing and case",
     ("Acme Holdings", EntityKind.COMPANY, {"date_of_incorporation": "2009-01-05",
                                            "email": "a@acme.example"}),
     ("ACME   HOLDINGS", EntityKind.COMPANY, {"date_of_incorporation": "2009-01-05",
                                              "email": "a@acme.example"})),
    ("transliterated differently",
     ("Mohammed Al Farsi", EntityKind.PERSON, {"dob": "1975-11-20",
                                               "phone": "+971501234567"}),
     ("Muhammad Al Farsi", EntityKind.PERSON, {"dob": "1975-11-20",
                                               "phone": "+971501234567"})),
    ("two-character name parts",
     ("Li Wei", EntityKind.PERSON, {"dob": "1982-07-14",
                                    "email": "liwei@example.com"}),
     ("Li Wei", EntityKind.PERSON, {"dob": "1982-07-14",
                                    "email": "liwei@example.com"})),
    ("Korean name, part added",
     ("Kim Ho", EntityKind.PERSON, {"dob": "1990-05-05",
                                    "email": "kimho@example.com"}),
     ("Kim Ho Jun", EntityKind.PERSON, {"dob": "1990-05-05",
                                        "email": "kimho@example.com"})),
    ("name order reversed",
     ("Kumar Rajesh", EntityKind.PERSON, {"dob": "1979-04-11",
                                          "email": "rk@example.com"}),
     ("Rajesh Kumar", EntityKind.PERSON, {"dob": "1979-04-11",
                                          "email": "rk@example.com"})),
    ("a feeder vehicle, same identity document",
     ("Sunrise Feeder I", EntityKind.FUND, {"id_document_number": "IDX-99812"}),
     ("Sunrise Feeder One", EntityKind.FUND, {"id_document_number": "IDX-99812"})),
]

#: Pairs that are genuinely two parties. Anything raised here is a false
#: alarm, and false alarms are what teach an officer to stop reading.
DIFFERENT = [
    ("two men called Rajesh Kumar",
     ("Rajesh Kumar", EntityKind.PERSON, {"dob": "1979-04-11",
                                          "pan": "ABCDE1234F"}),
     ("Rajesh Kumar", EntityKind.PERSON, {"dob": "1991-09-02",
                                          "pan": "ZYXWV9876B"})),
    ("father and son",
     ("Anil Sharma", EntityKind.PERSON, {"dob": "1955-01-30"}),
     ("Anil Sharma", EntityKind.PERSON, {"dob": "1984-06-17"})),
    ("two funds from one house",
     ("Meridian Growth Fund I", EntityKind.FUND,
      {"date_of_incorporation": "2019-04-01"}),
     ("Meridian Growth Fund II", EntityKind.FUND,
      {"date_of_incorporation": "2021-04-01"})),
    ("siblings sharing a household",
     ("Priya Raghavan", EntityKind.PERSON, {"email": "family@example.com",
                                            "phone": "+919812345678"}),
     ("Arjun Raghavan", EntityKind.PERSON, {"email": "family@example.com",
                                            "phone": "+919812345678"})),
    ("same surname, same birthday",
     ("Rajesh Kumar", EntityKind.PERSON, {"dob": "1979-04-11"}),
     ("Amit Kumar", EntityKind.PERSON, {"dob": "1979-04-11"})),
    ("cousins, one household",
     ("Deepak Iyer", EntityKind.PERSON, {"email": "iyers@example.com",
                                         "phone": "+919820011223"}),
     ("Kavya Iyer", EntityKind.PERSON, {"email": "iyers@example.com",
                                        "phone": "+919820011223"})),
    ("a namesake at the same firm",
     ("Zenith Capital Partners", EntityKind.COMPANY,
      {"cin": "U11111MH2011", "email": "one@zenith.example"}),
     ("Zenith Capital Advisors", EntityKind.COMPANY,
      {"cin": "U22222MH2015", "email": "two@zenith.example"})),
]


def raised(left, right) -> tuple:
    """What the product says about one planted pair, alone in a workspace."""
    engine = workspace()
    register(engine, "a", left[0], left[1], **left[2])
    register(engine, "b", right[0], right[1], **right[2])
    found = look(engine.state.graph, engine.state.resemblances, "b")
    return found


def why_not(left, right) -> str:
    """Where a missed pair was lost: before comparison, or during it."""
    if not (sounds_of(left[0]) & sounds_of(right[0])):
        engine = workspace()
        register(engine, "a", left[0], left[1], **left[2])
        register(engine, "b", right[0], right[1], **right[2])
        if not engine.state.resemblances.candidates(
                right[0], right[2], excluding="b"):
            return ("never compared: the two names share no blocking key, "
                    "and no identifier brought them together")
    return "compared, and not judged worth raising"


#: Measured 20 August 2026 and written down, so a regression is a failed
#: build. Both directions matter and they pull against each other: finding
#: fewer duplicates hides real ones, raising more namesakes costs an officer
#: an hour each.
FOUND_WHEN_SET = 16
ALARMS_WHEN_SET = 0


def main() -> int:
    print()
    print("  THE SAME PARTY, TWICE")
    print()
    seen = 0
    for label, left, right in SAME:
        found = raised(left, right)
        if found:
            seen += 1
            print(f"  sees it   {label:<38} {left[0]!r} / {right[0]!r}")
        else:
            print(f"  BLIND     {label:<38} {left[0]!r} / {right[0]!r}")
            print(f"                -> {why_not(left, right)}")
    print()
    print(f"  {seen} of {len(SAME)} duplicate shapes are found.")
    print()

    print("  GENUINELY DIFFERENT PARTIES")
    print()
    alarms = 0
    for label, left, right in DIFFERENT:
        found = raised(left, right)
        if found:
            alarms += 1
            print(f"  RAISES    {label:<38} {found[0].because[:78]}")
        else:
            print(f"  quiet     {label:<38}")
    print()
    print(f"  {alarms} of {len(DIFFERENT)} namesake pairs are raised as "
          f"possible duplicates.")
    print()
    total = len(SAME) + len(DIFFERENT)
    right_answers = seen + (len(DIFFERENT) - alarms)
    print(f"  {right_answers} of {total} pairs answered correctly.")
    print()
    if seen < FOUND_WHEN_SET or alarms > ALARMS_WHEN_SET:
        print(f"  FAILING: {FOUND_WHEN_SET} duplicate shapes were found and "
              f"{ALARMS_WHEN_SET} namesakes raised when this floor was set; "
              f"now {seen} and {alarms}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
