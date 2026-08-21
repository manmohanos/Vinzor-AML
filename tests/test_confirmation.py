"""A qualified person putting their name to a clause.

Two properties carry the whole feature. A sign-off must be impossible for
anything that is not an enrolled human, and it must not outlive the wording it
was given. Everything else here is furniture.
"""

from __future__ import annotations

import dataclasses

import pytest

from vinzor.cases import DecisionDenied
from vinzor.citations import CLAUSES, verified_now, wording_digest
from vinzor.model import Role

from conftest import officer


def sign(engine, clause_id="5.9", who="Meera Nair", role=Role.AML_OFFICER,
         qualification="Company Secretary, ICSI membership 12345",
         note="Read against page 34 of the master; wording and page match.",
         on="2026-08-14"):
    return engine.confirm_clause(clause_id=clause_id, reviewer=who, role=role,
                                 qualification=qualification, note=note,
                                 confirmed_at=on)


def test_a_signed_clause_names_who_stands_behind_it(engine):
    officer(engine)
    sign(engine)

    record = verified_now("5.9", engine.state.verifications)
    assert record["reviewer"] == "Meera Nair"
    assert "ICSI" in record["qualification"]
    assert record["verified_at"] == "2026-08-14"


def test_nothing_ships_pre_signed(engine):
    """A clause a customer never looked at must not arrive claiming someone
    did. The register is software; the sign-off is theirs."""
    assert not any(c.verified for c in CLAUSES.values())
    assert engine.state.verifications == {}


def test_a_sign_off_does_not_survive_the_wording_changing(engine, monkeypatch):
    """The reason the wording digest is stored at all. If the extract is later
    corrected, the signature must not carry forward onto words nobody read.
    """
    officer(engine)
    sign(engine)
    assert verified_now("5.9", engine.state.verifications)

    corrected = dataclasses.replace(CLAUSES["5.9"], extract="Something else.")
    monkeypatch.setitem(CLAUSES, "5.9", corrected)

    assert verified_now("5.9", engine.state.verifications) is None, \
        "a signature carried over onto wording nobody signed"


def test_a_sign_off_does_not_survive_the_page_moving(engine, monkeypatch):
    """"I checked this sentence" means nothing without which document and
    where. IFSCA repaginates its master with every circular."""
    officer(engine)
    sign(engine)

    moved = dataclasses.replace(CLAUSES["5.9"], page=999)
    monkeypatch.setitem(CLAUSES, "5.9", moved)
    assert verified_now("5.9", engine.state.verifications) is None


def test_only_an_enrolled_person_may_sign(engine):
    with pytest.raises(DecisionDenied, match="not enrolled"):
        sign(engine, who="Someone Unknown")
    assert engine.state.verifications == {}


def test_a_read_only_role_may_read_the_register_but_not_confirm_it(engine):
    engine.enroll(name="Priya Rao", role=Role.VIEWER, enrolled_at="2026-08-01")
    with pytest.raises(DecisionDenied, match="not confirm"):
        sign(engine, who="Priya Rao", role=Role.VIEWER)
    assert engine.state.verifications == {}


def test_a_machine_can_never_sign_a_clause(engine):
    """The assistant is never enrolled, so the fold refuses it -- the same
    gate that stops it settling a Case, for the same reason."""
    with pytest.raises(DecisionDenied):
        sign(engine, who="assistant", role=Role.AI)
    with pytest.raises(DecisionDenied):
        sign(engine, who="system", role=Role.SYSTEM)
    assert engine.state.verifications == {}


def test_a_forged_sign_off_fails_on_replay(engine):
    """The fold enforces the gate too, so a row written straight into the
    database has to be accompanied by a forged enrolment -- which is itself in
    the audit trail under a hash.
    """
    from vinzor.engine import project
    from vinzor.model import EventType

    officer(engine)
    sign(engine)
    assert verified_now("5.9", project(engine.log).verifications)

    # Same event, but from someone never enrolled.
    engine.log.append(
        event_type=EventType.CLAUSE_VERIFIED, subject="5.6",
        occurred_at="2026-08-14", actor="A Stranger",
        payload={"role": "COMPLIANCE", "qualification": "x", "note": "y",
                 "wording": wording_digest(CLAUSES["5.6"])},
    )
    with pytest.raises(DecisionDenied, match="not enrolled"):
        project(engine.log)


def test_a_sign_off_must_say_what_qualifies_it_and_what_was_checked(engine):
    officer(engine)
    for missing in ("qualification", "note"):
        with pytest.raises(ValueError):
            sign(engine, **{missing: "   "})
    assert engine.state.verifications == {}


def test_signing_an_unknown_clause_fails_loudly(engine):
    officer(engine)
    with pytest.raises(KeyError, match="no registered clause"):
        sign(engine, clause_id="99.9")


def test_the_register_counts_confirmations_from_the_workspace(engine):
    """Who signed what is a fact about this firm, not a property of the
    software, so the count comes off the log."""
    from vinzor.briefing import regulatory
    from vinzor.model import EventType

    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="fme",
                  occurred_at="2025-01-10",
                  payload={"kind": "COMPANY", "name": "Acme"})
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="fme",
                  occurred_at="2025-01-10",
                  payload={"category": "REGISTERED_NON_RETAIL", "number": "X"})
    officer(engine)

    assert "0 confirmed by a person" in regulatory(engine, "2026-08-14").register_summary
    sign(engine)
    sign(engine, clause_id="5.6")

    page = regulatory(engine, "2026-08-14")
    assert (f"2 confirmed by a person, {len(CLAUSES) - 2} not yet"
            in page.register_summary)
    row = next(c for c in page.clauses if c.clause == "5.9")
    assert row.checked == "Checked by a person"
    assert row.tone == "settled"
    assert "Meera Nair" in row.confirmed_by and "ICSI" in row.confirmed_by
    # The caveat stays while any clause is unsigned.
    assert page.register_caveat


def test_the_caveat_only_goes_when_every_clause_is_signed(engine):
    from vinzor.briefing import regulatory
    from vinzor.model import EventType

    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="fme",
                  occurred_at="2025-01-10",
                  payload={"kind": "COMPANY", "name": "Acme"})
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="fme",
                  occurred_at="2025-01-10",
                  payload={"category": "REGISTERED_NON_RETAIL", "number": "X"})
    officer(engine)
    for clause_id in list(CLAUSES):
        sign(engine, clause_id=clause_id)

    page = regulatory(engine, "2026-08-14")
    assert page.register_caveat == ""
    # Counted from the register rather than typed, so registering a clause
    # is not a test edit.
    assert (f"{len(CLAUSES)} confirmed by a person, 0 not yet"
            in page.register_summary)


def test_the_sign_off_page_says_nothing_technical(engine):
    """A new user-facing field. The sweep walks it like everything else."""
    import re

    from test_briefing import JARGON, _strings
    from vinzor.briefing import regulatory
    from vinzor.model import EventType

    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="fme",
                  occurred_at="2025-01-10",
                  payload={"kind": "COMPANY", "name": "Acme"})
    engine.ingest(event_type=EventType.LICENCE_GRANTED, subject="fme",
                  occurred_at="2025-01-10",
                  payload={"category": "REGISTERED_NON_RETAIL", "number": "X"})
    officer(engine)
    sign(engine)

    offences = []
    for path, text in _strings(regulatory(engine, "2026-08-14"), "regulatory"):
        for pattern, what in JARGON:
            match = re.search(pattern, text)
            if match:
                offences.append(f"{path}: {what} ({match.group(0)!r})")
    assert not offences, "jargon reached the reader:\n  " + "\n  ".join(offences)
