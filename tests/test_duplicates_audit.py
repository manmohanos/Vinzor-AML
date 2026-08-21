"""What entity resolution claims, tested by attacking it.

This block stated a speed and no accuracy. Every other block in the product
states how well it works -- screening scores 90.7% F1 against 455,219
analyst judgements, the payment rules were measured and found worthless
before better ones were written -- and this one said "61x faster" and "flat
at 7ms a party". Fast at what was never asked, and flat was not true either.

``tools/duplicate_shapes.py`` asks. Sixteen ways a real book ends up holding
one party twice, seven pairs who genuinely are different people, each
planted alone and put to the product.

**It found four of sixteen duplicates invisible**, and all four for one
reason. Blocking brings two records together only if two parts of their
names agree, so a name with two usable parts and one part changed shares
nothing and is never compared at all. That is a marriage where the surname
was replaced, a name recorded with an initial, a name transliterated
another way, and a short name that gained a part -- including the marriage
the module's own opening paragraph is about. Single parts are now indexed
too, but only while a part is rare enough to mean something.

**It found the flat cost was not flat.** The index was rebuilt on every
registration to keep it safe for readers, which copies the whole of it, so
per-party cost grew with the book. On a book of distinct names -- what a
real client book is -- it doubled every time the book doubled: 0.28ms a
party over a thousand, 1.09ms over eight thousand. The original measurement
had used a small pool of repeated names, where the index stops growing and
the cost genuinely does flatten. Nothing iterates these dictionaries, so
they are now updated in place, and the same measurement is flat: 0.39ms and
0.27ms.

**Widening the blocking then exposed a wrong sentence.** A brother and
sister -- same surname, same family email, same landline -- came together
for the first time, counted three agreeing facts, and were raised as
possibly one person under the words "one name contained in the other",
which was not true of either name. Counting had treated a shared telephone
and a birthday as interchangeable. They are not: a household shares an
address, a person has a birthday.

Sixteen of sixteen are found now, and none of the seven namesake pairs is
raised.
"""

from __future__ import annotations

import pytest

from vinzor.duplicates import (COMMON_PART, MOST_TO_COMPARE, PERSONAL, look,
                               parts_of, sounds_of)
from vinzor.model import EntityKind, EventType

WHEN = "2026-08-20"


def register(engine, entity_id, name, kind=EntityKind.PERSON, **attributes):
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=entity_id,
                  occurred_at=WHEN, actor="test",
                  payload={"kind": kind.value, "name": name,
                           "attributes": {k: v for k, v in attributes.items()
                                          if v}})


def pair(engine, left, right):
    """What the product says about two planted records."""
    register(engine, "a", left[0], left[1], **left[2])
    register(engine, "b", right[0], right[1], **right[2])
    return look(engine.state.graph, engine.state.resemblances, "b")


# -- the four that were invisible --------------------------------------------


def test_a_married_name_with_the_surname_replaced_is_found(engine):
    """The case this module's own first paragraph names -- "somebody
    marries and the surname changes" -- and the one its blocking rule could
    not bring together. "Priya Raghavan" and "Priya Menon" share one part
    of a two-part name, so they produced no key in common."""
    found = pair(engine,
                 ("Priya Raghavan", EntityKind.PERSON,
                  {"dob": "1988-02-03", "email": "priya@example.com"}),
                 ("Priya Menon", EntityKind.PERSON,
                  {"dob": "1988-02-03", "email": "priya@example.com"}))
    assert found
    assert "date of birth" in found[0].because


def test_a_name_recorded_with_an_initial_is_found(engine):
    """A book holds "R. Kumar" where the register holds "Rajesh Kumar".
    The initial is too short to be a name part, so one record had a single
    usable part and the other had two, and they never met."""
    found = pair(engine,
                 ("Rajesh Kumar", EntityKind.PERSON,
                  {"dob": "1979-04-11", "phone": "+919812345678"}),
                 ("R. Kumar", EntityKind.PERSON,
                  {"dob": "1979-04-11", "phone": "+919812345678"}))
    assert found


def test_a_name_transliterated_another_way_is_found(engine):
    """"Mohammed" and "Muhammad" do not sound alike to the blocking rule,
    and "Al" is too short to count, so a three-part name came down to one
    part in common."""
    found = pair(engine,
                 ("Mohammed Al Farsi", EntityKind.PERSON,
                  {"dob": "1975-11-20", "phone": "+971501234567"}),
                 ("Muhammad Al Farsi", EntityKind.PERSON,
                  {"dob": "1975-11-20", "phone": "+971501234567"}))
    assert found


def test_a_short_name_that_gained_a_part_is_found(engine):
    """"Kim Ho" keeps one usable part once the two-letter one is dropped;
    "Kim Ho Jun" keeps two. Nothing brought them together."""
    found = pair(engine,
                 ("Kim Ho", EntityKind.PERSON,
                  {"dob": "1990-05-05", "email": "kimho@example.com"}),
                 ("Kim Ho Jun", EntityKind.PERSON,
                  {"dob": "1990-05-05", "email": "kimho@example.com"}))
    assert found


def test_the_shapes_that_already_worked_still_do(engine):
    """A fix to recall that costs a case elsewhere is not a fix."""
    found = pair(engine,
                 ("Zenith Capital", EntityKind.COMPANY,
                  {"date_of_incorporation": "2014-06-01",
                   "email": "ops@zenith.example"}),
                 ("Zenith Capital Private Limited", EntityKind.COMPANY,
                  {"date_of_incorporation": "2014-06-01",
                   "email": "ops@zenith.example"}))
    assert found


# -- and the namesakes it must leave alone -----------------------------------


def test_a_brother_and_sister_sharing_a_household_are_not_one_person(engine):
    """What widening the blocking exposed. Same surname, same family email,
    same landline: three agreeing facts by the old count, and the pair was
    raised under words that were not true of either name."""
    found = pair(engine,
                 ("Priya Raghavan", EntityKind.PERSON,
                  {"email": "family@example.com", "phone": "+919812345678"}),
                 ("Arjun Raghavan", EntityKind.PERSON,
                  {"email": "family@example.com", "phone": "+919812345678"}))
    assert not found


def test_a_shared_surname_and_a_shared_birthday_are_not_enough(engine):
    """Two agreeing facts, one of them personal, and still only half a name
    in common. On a book of any size this pair happens by chance."""
    found = pair(engine,
                 ("Rajesh Kumar", EntityKind.PERSON, {"dob": "1979-04-11"}),
                 ("Amit Kumar", EntityKind.PERSON, {"dob": "1979-04-11"}))
    assert not found


def test_a_household_is_one_fact_about_a_place_not_two_about_a_person():
    """The distinction the count could not make. An email address and a
    telephone number are where somebody is; a date of birth is who they
    are, and families share the first two by living together."""
    assert "dob" in PERSONAL and "date_of_incorporation" in PERSONAL
    assert "email" not in PERSONAL and "phone" not in PERSONAL


def test_two_funds_from_one_house_are_not_one_fund(engine):
    found = pair(engine,
                 ("Meridian Growth Fund I", EntityKind.FUND,
                  {"date_of_incorporation": "2019-04-01"}),
                 ("Meridian Growth Fund II", EntityKind.FUND,
                  {"date_of_incorporation": "2021-04-01"}))
    assert not found


# -- what the index costs ----------------------------------------------------


def test_the_index_is_not_copied_on_every_registration(engine):
    """The whole of the quadratic term. Rebuilding the index kept it safe
    for a reader mid-iteration, which is why ``state.actors`` is rebuilt --
    but nothing iterates these, and copying them cost the whole index on
    every party registered."""
    register(engine, "p0", "Anjali Deshpande")
    resemblances = engine.state.resemblances
    sound, part, identifier = (resemblances.by_sound, resemblances.by_part,
                               resemblances.by_identifier)

    register(engine, "p1", "Vikram Chandrasekhar", pan="ABCDE1234F")

    assert resemblances.by_sound is sound
    assert resemblances.by_part is part
    assert resemblances.by_identifier is identifier
    assert len(sound) > 1


def test_a_part_everybody_shares_stops_being_indexed(engine):
    """Blocking on single parts is what makes the four shapes above
    findable, and it is also what made loading five thousand investors take
    six minutes before pairs were introduced. The cap is the whole reason
    it is affordable: past it a part says only that the name is common."""
    for index in range(COMMON_PART + 5):
        register(engine, f"p{index}", f"Given{index} Kumar")

    held = engine.state.resemblances.by_part.get("kumar")
    assert held is None, "a part everybody shares is still being indexed"

    register(engine, "rare", "Anjali Vishwanathan")
    kept = [group for part, group in engine.state.resemblances.by_part.items()
            if part.startswith("vis") and group]
    assert kept and all(len(group) <= COMMON_PART for group in kept), (
        "a part almost nobody shares should still be indexed")


def test_a_common_part_brings_nobody_together(engine):
    """The cap has to be honest about what it costs: once a surname is
    everywhere, two records sharing only that surname are no longer
    compared, and no amount of agreeing on other fields will raise them."""
    for index in range(COMMON_PART + 5):
        register(engine, f"p{index}", f"Given{index} Kumar")
    register(engine, "x", "Rajesh Kumar", dob="1979-04-11",
             phone="+919812345678")
    register(engine, "y", "R. Kumar", dob="1979-04-11",
             phone="+919812345678")

    assert not look(engine.state.graph, engine.state.resemblances, "y")


def test_an_identifier_still_finds_them_when_the_name_cannot(engine):
    """Which is why the cap is survivable. The pair above is not findable
    from a name shared by hundreds, by this product or any other; a
    permanent account number is matched exactly and before any of it."""
    for index in range(COMMON_PART + 5):
        register(engine, f"p{index}", f"Given{index} Kumar")
    register(engine, "x", "Rajesh Kumar", pan="ABCDE1234F")
    register(engine, "y", "R. Kumar", pan="ABCDE1234F")

    found = look(engine.state.graph, engine.state.resemblances, "y")
    assert found and found[0].identified


def test_two_shared_parts_are_compared_before_one(engine):
    """A record sharing a whole name is better evidence than one sharing a
    common part of it, whatever the counts say. Letting the two compete on
    a single tally would have let a handful of weak agreements outrank a
    name that matched outright, once the comparison budget filled."""
    register(engine, "twin", "Priya Raghavan", dob="1988-02-03")
    for index in range(MOST_TO_COMPARE + 10):
        register(engine, f"n{index}", f"Priya Surname{index}")
    register(engine, "b", "Priya Raghavan", dob="1988-02-03")

    found = look(engine.state.graph, engine.state.resemblances, "b")
    assert any(f.left == "twin" or f.right == "twin" for f in found)


# -- the blocking keys themselves --------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("Priya Raghavan", ["pria", "raghavan"]),
    ("R. Kumar", ["kumar"]),
    ("Kim Ho", ["kim"]),
    ("ACME   HOLDINGS", ["acme", "holdings"]),
])
def test_the_parts_of_a_name_drop_what_is_too_short_to_mean_anything(
        name, expected):
    """Initials and particles -- "R.", "al", "de", "van" -- are dropped,
    which is a real cost and the reason "Kim Ho" comes down to one part.
    Keeping them would put every party with an initial in one group."""
    assert parts_of(name) == sorted(expected)


def test_a_single_part_name_still_produces_a_key():
    """A one-part name has no pair to make a key from, and dropping it
    would leave those parties unfindable by name at all."""
    assert sounds_of("Madonna")
    assert sounds_of("Kim Ho") == frozenset({"kim"})
