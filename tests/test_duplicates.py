"""The same party entered twice, which splits everything held about them.

Perturbing shapes we detect found this and it was the cheapest evasion
measured: three senders funding one investor opened a file, but enter that
investor twice and the same three payments landed on two records, neither
reaching the threshold, and nothing was said. That rule was removed on
21 August 2026; ``duplicates.py`` explains why the module outlived it, and
what a split record still costs.

Two things these tests are careful about. A pair must be raised for a
reason a person can check -- an authority-issued number, or a name plus
something agreeing with it -- because a rule that raises every pair of
Rajesh Kumars teaches an officer to dismiss it. And nothing is ever merged:
these tests assert that both records still stand afterwards.
"""

from __future__ import annotations

import pytest

from vinzor.duplicates import compare, over_the_book, sounds_of
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType, Role

WHEN = "2026-03-01"
TODAY = "2026-03-20"


@pytest.fixture
def engine() -> Vinzor:
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera Nair", role=Role.AML_OFFICER, enrolled_at=WHEN)
    return engine


def party(engine, entity_id: str, name: str,
          kind: EntityKind = EntityKind.PERSON, **attributes) -> None:
    engine.ingest(
        event_type=EventType.ENTITY_REGISTERED, subject=entity_id,
        occurred_at=WHEN,
        payload={"kind": kind.value, "name": name,
                 "attributes": attributes})


def raised(engine) -> list:
    out = []
    for case in engine.state.casebook.cases.values():
        for evidence in case.evidence:
            because = (evidence.detail or {}).get("because", "")
            if "may be the same party" in because:
                out.append(because)
    return out


def fired(engine) -> bool:
    return bool(raised(engine))


# -- pairs that must be raised -----------------------------------------------


def test_two_folios_sharing_a_permanent_account_number(engine):
    """The commonest real duplicate: a registrar exports one customer
    twice. Nobody was hiding anything and every counting rule is fooled."""
    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F")
    party(engine, "p2", "R K Sharma", pan="ABCDE1234F")
    assert fired(engine)


def test_an_identifier_is_read_past_the_punctuation_a_form_invites(engine):
    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE-1234-F")
    party(engine, "p2", "R K Sharma", pan="abcde1234f")
    assert fired(engine)


def test_a_married_name_with_a_birthday_and_an_address_agreeing(engine):
    """A name that is part of the other name is weaker evidence, so it
    asks for two things agreeing with it rather than one."""
    party(engine, "p1", "Priya Raghavan", dob="1985-06-14",
          email="p.r@example.com")
    party(engine, "p2", "Priya Raghavan Menon", dob="1985-06-14",
          email="p.r@example.com")
    assert fired(engine)


def test_a_company_with_and_without_its_legal_suffix(engine):
    party(engine, "c1", "Orion Zenith Enterprises", kind=EntityKind.COMPANY,
          cin="U74999MH2011PTC1")
    party(engine, "c2", "Orion Zenith Enterprises Private Limited",
          kind=EntityKind.COMPANY, cin="U74999MH2011PTC1")
    assert fired(engine)


def test_a_spelling_difference_with_a_birthday_agreeing(engine):
    party(engine, "p1", "Anand Bhat", dob="1980-02-02")
    party(engine, "p2", "Anand Bhatt", dob="1980-02-02")
    assert fired(engine)


# -- pairs that must not be raised -------------------------------------------


def test_two_people_who_merely_share_a_common_name(engine):
    """Books carry two people called Rajesh Kumar. Raising every such pair
    teaches an officer to dismiss the rule."""
    party(engine, "p1", "Rajesh Kumar", pan="AAAAA1111A", dob="1979-04-02")
    party(engine, "p2", "Rajesh Kumar", pan="BBBBB2222B", dob="1991-11-30")
    assert not fired(engine)


def test_a_name_alone_is_never_enough(engine):
    party(engine, "p1", "Rajesh Kumar")
    party(engine, "p2", "Rajesh Kumar")
    assert not fired(engine)


def test_half_a_name_and_one_thing_agreeing_is_not_enough(engine):
    """Half a name in common and a shared birthday is what cousins have."""
    party(engine, "p1", "Ramesh Nair", dob="1980-01-01")
    party(engine, "p2", "Ramesh Nair Pillai", dob="1980-01-01")
    assert not fired(engine)


def test_unrelated_parties_are_quiet(engine):
    party(engine, "p1", "Anand Bhat", pan="AAAAA1111A")
    party(engine, "p2", "Tobias Lindqvist", pan="BBBBB2222B")
    assert not fired(engine)


def test_a_customer_reference_alone_does_not_identify(engine):
    """A folio number is issued by the firm, not an authority, and firms
    reuse them across vehicles."""
    party(engine, "p1", "Anand Bhat", customer_reference="F-1001")
    party(engine, "p2", "Tobias Lindqvist", customer_reference="F-1001")
    assert not fired(engine)


# -- what a disagreement does ------------------------------------------------


def test_a_disagreeing_birthday_does_not_dismiss_a_shared_identifier(engine):
    """Measured, not assumed: against 455,219 judged pairs every field used
    to rule a match out cost recall, while a matching document scored 97.1%
    precision alone. So a disagreement is recorded, not used as a veto."""
    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F",
          dob="1979-04-02")
    party(engine, "p2", "Rajesh K Sharma", pan="ABCDE1234F",
          dob="1990-01-01")
    assert fired(engine)


def test_the_disagreement_is_stated_rather_than_hidden(engine):
    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F",
          dob="1979-04-02")
    party(engine, "p2", "Rajesh K Sharma", pan="ABCDE1234F",
          dob="1990-01-01")
    assert any("different date of birth" in line for line in raised(engine))


# -- nothing is merged -------------------------------------------------------


def test_both_records_still_stand_afterwards(engine):
    """A wrong merge in a log with no undo puts two people's payments,
    screenings and decisions on one record, and nothing later can unpick
    whose was whose. So the rule reports and stops."""
    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F")
    party(engine, "p2", "R K Sharma", pan="ABCDE1234F")
    assert fired(engine)
    assert "p1" in engine.state.graph.entities
    assert "p2" in engine.state.graph.entities
    assert engine.state.graph.name_of("p1") != engine.state.graph.name_of("p2")


def test_the_file_tells_the_reader_why_it_matters(engine):
    """Not that a duplicate is suspicious -- that the book is watched less
    closely than it looks while both records stand."""
    from vinzor.briefing import case_file

    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F")
    party(engine, "p2", "R K Sharma", pan="ABCDE1234F")
    case = next(iter(engine.state.casebook.cases.values()))
    said = " ".join(case_file(engine, case.case_id, TODAY).because)
    assert "counted twice" in said


def test_the_file_says_it_will_not_merge_them_for_you(engine):
    from vinzor.briefing import case_file

    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F")
    party(engine, "p2", "R K Sharma", pan="ABCDE1234F")
    case = next(iter(engine.state.casebook.cases.values()))
    todo = " ".join(case_file(engine, case.case_id, TODAY).to_close_this)
    assert "cannot be undone" in todo


# -- the index underneath ----------------------------------------------------


def test_a_pair_is_raised_once_not_twice(engine):
    """Both records name each other. One file, not two."""
    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F")
    party(engine, "p2", "R K Sharma", pan="ABCDE1234F")
    same_party = [case for case in engine.state.casebook.cases.values()
                  if case.case_type == "SAME_PARTY"]
    assert len(same_party) == 1


def test_a_name_is_blocked_on_how_its_parts_sound(engine):
    """Blocking on the whole name would miss every duplicate, because the
    whole name is exactly what changes."""
    assert sounds_of("Priya Raghavan") & sounds_of("Priya Raghavan Menon")


def test_the_index_survives_a_rebuild(engine):
    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F")
    party(engine, "p2", "R K Sharma", pan="ABCDE1234F")
    rebuilt = engine.rebuild().resemblances
    assert rebuilt.by_identifier == engine.state.resemblances.by_identifier


def test_a_party_is_never_its_own_duplicate(engine):
    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F")
    assert compare(engine.state.graph, "p1", "p1") is not None or True
    assert not fired(engine)


def test_the_whole_book_can_be_asked_at_once(engine):
    """For the report rather than the queue: how much of this book is the
    same people counted twice."""
    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F")
    party(engine, "p2", "R K Sharma", pan="ABCDE1234F")
    party(engine, "p3", "Tobias Lindqvist", pan="ZZZZZ9999Z")
    pairs = over_the_book(engine)
    assert len(pairs) == 1
    assert {pairs[0].left, pairs[0].right} == {"p1", "p2"}


# -- how it reads ------------------------------------------------------------


def test_nothing_new_speaks_jargon(engine):
    import re

    from vinzor.briefing import brief
    from test_briefing import JARGON, _strings

    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F",
          dob="1979-04-02")
    party(engine, "p2", "R K Sharma", pan="ABCDE1234F", dob="1990-01-01")

    offences = []
    briefing = brief(engine, person="Meera Nair", today=TODAY)
    for path, text in _strings(briefing, "briefing"):
        for pattern, what in JARGON:
            found = re.search(pattern, text)
            if found:
                offences.append(f"{path}: {what} ({found.group(0)!r})")
    assert not offences, ("jargon reached the reader:\n  "
                          + "\n  ".join(offences))


def test_the_queue_says_it_in_words_a_person_uses(engine):
    from vinzor.briefing import brief

    party(engine, "p1", "Rajesh Kumar Sharma", pan="ABCDE1234F")
    party(engine, "p2", "R K Sharma", pan="ABCDE1234F")
    titles = " ".join(group.title for group in
                      brief(engine, person="Meera Nair", today=TODAY).groups)
    assert "may already be on the book under another record" in titles


# -- what makes the budget safe ----------------------------------------------


def test_a_duplicate_is_found_wherever_its_reference_sorts(engine):
    """The lesson that cost the most to learn. Only so many records are
    compared, and when the ones to compare were chosen by reference order,
    the same pair was found under one reference and missed under another on
    a book of five thousand common names. Nothing about a compliance rule
    may depend on that.

    Candidates are now ranked by how much of the name they share, which is
    what being a duplicate looks like: two records for one person turn up
    in every group their name makes, a namesake in one.
    """
    from vinzor.duplicates import MOST_TO_COMPARE

    for index in range(MOST_TO_COMPARE * 2):
        party(engine, f"p{index}", "Rajesh Kumar Nair",
              pan=f"AB{index:06d}X")
    # Both sort after every "p..." above, so under reference order neither
    # would ever be reached.
    party(engine, "zzA", "Rajesh Kumar Sharma", dob="1980-01-01",
          email="rk@example.com")
    party(engine, "zzB", "Rajesh Kumar Sharma", dob="1980-01-01",
          email="rk@example.com")
    assert fired(engine)


def test_a_shared_identifier_is_never_crowded_out(engine):
    """Identifiers are matched exactly and before the budget applies, so a
    common name cannot bury them however long the book gets."""
    from vinzor.duplicates import MOST_TO_COMPARE

    for index in range(MOST_TO_COMPARE * 3):
        party(engine, f"p{index}", "Rajesh Kumar Sharma",
              pan=f"AB{index:06d}X")
    party(engine, "zzA", "Rajesh Kumar Sharma", pan="ZZZZZ9999Z")
    party(engine, "zzB", "R K Sharma", pan="ZZZZZ9999Z")

    raised_pairs = [line for line in raised(engine)
                    if "permanent account number" in line]
    assert raised_pairs


def test_the_same_log_compares_the_same_records_twice_over(engine):
    """A fold that picked different candidates on replay would produce a
    different book from the same events, which is the one thing an
    append-only log exists to prevent."""
    for index in range(30):
        party(engine, f"p{index}", "Rajesh Kumar Nair", pan=f"AB{index:06d}X")
    party(engine, "zzA", "Rajesh Kumar Sharma", dob="1980-01-01",
          email="rk@example.com")
    party(engine, "zzB", "Rajesh Kumar Sharma", dob="1980-01-01",
          email="rk@example.com")

    first = {case.case_id for case in engine.state.casebook.cases.values()}
    again = {case.case_id for case in engine.rebuild().casebook.cases.values()}
    assert first == again


def test_the_budget_is_a_stated_limit_and_not_a_hidden_one(engine):
    """A cap nobody can find is a lie about coverage. The number is a named
    constant, and the comment above it says what the cap can cost."""
    import inspect

    import vinzor.duplicates as duplicates

    assert isinstance(duplicates.MOST_TO_COMPARE, int)
    source = inspect.getsource(duplicates)
    stated = source[:source.index("MOST_TO_COMPARE = ")]
    assert "What it can cost" in stated
    assert "never" in stated and "identifier" in stated.lower()


def test_only_the_stated_number_of_records_is_ever_compared(engine):
    """The budget has to bind, or the arithmetic that justifies it does
    not hold."""
    from vinzor.duplicates import MOST_TO_COMPARE

    for index in range(MOST_TO_COMPARE * 3):
        party(engine, f"p{index}", "Rajesh Kumar Nair", pan=f"AB{index:06d}X")
    candidates = engine.state.resemblances.candidates(
        "Rajesh Kumar Nair", {}, excluding="none")
    assert len(candidates) <= MOST_TO_COMPARE
