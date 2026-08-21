"""Shared fixtures and tiny builders.

The builders exist so a test reads as the scenario it is describing rather than
as a pile of ``ingest`` calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vinzor.engine import Vinzor  # noqa: E402
from vinzor.eventlog import EventLog  # noqa: E402
from vinzor.model import EntityKind, EventType, Relation, Role  # noqa: E402

#: Fixed date used wherever a test does not care about time. The core never
#: reads a clock, so tests never need to freeze one.
WHEN = "2026-08-07"


@pytest.fixture
def engine() -> Vinzor:
    return Vinzor(EventLog())


def register(
    engine: Vinzor, entity_id: str, kind: EntityKind, name: str | None = None, **attrs
) -> None:
    engine.ingest(
        event_type=EventType.ENTITY_REGISTERED,
        subject=entity_id,
        occurred_at=WHEN,
        payload={"kind": kind.value, "name": name or entity_id, "attributes": attrs},
    )


def person(engine: Vinzor, entity_id: str, name: str | None = None) -> None:
    register(engine, entity_id, EntityKind.PERSON, name)


def company(engine: Vinzor, entity_id: str, name: str | None = None) -> None:
    register(engine, entity_id, EntityKind.COMPANY, name)


def owns(
    engine: Vinzor,
    owner: str,
    owned: str,
    percentage: float,
    relation: Relation = Relation.OWNS,
):
    return engine.ingest(
        event_type=EventType.OWNERSHIP_DECLARED,
        subject=owned,
        occurred_at=WHEN,
        payload={
            "owner": owner,
            "owned": owned,
            "percentage": percentage,
            "relation": relation.value,
        },
    )


def commits(engine: Vinzor, investor: str, fund: str = "fnd_1", amount: float = 1e6):
    return engine.ingest(
        event_type=EventType.COMMITMENT_MADE,
        subject=investor,
        occurred_at=WHEN,
        payload={"investor": investor, "fund": fund, "amount": amount},
    )


def screened(engine: Vinzor, subject: str, list_type: str, matched: bool = True,
             alert_id: str = "alt_1", when: str = WHEN):
    return engine.ingest(
        event_type=EventType.SCREENING_COMPLETED,
        subject=subject,
        occurred_at=when,
        payload={"list_type": list_type, "matched": matched, "alert_id": alert_id},
    )


def paid(engine: Vinzor, subject: str, anomaly: str | None = None,
         payment_id: str = "pay_1", when: str = WHEN, **extra):
    # An ordinary payment: the investor pays what was called, in the currency
    # expected, from their own account. Only the payer is read by a rule now:
    # since 21 August 2026 the amount, the called amount and the two
    # currencies are recorded and nothing looks at them. They stay because
    # the log, the briefing and every figure a reader sees are built from
    # them, and a test payment with no money in it is not a payment.
    payload = {"payment_id": payment_id, "payment_ref": "TX-1", "amount": 1000.0,
               "called_amount": 1000.0, "currency": "USD",
               "expected_currency": "USD", "payer": subject,
               "anomaly": anomaly}
    payload.update(extra)
    return engine.ingest(
        event_type=EventType.PAYMENT_RECEIVED,
        subject=subject,
        occurred_at=when,
        payload=payload,
    )


def trust_of(engine: Vinzor, entity_id: str, name: str | None = None) -> None:
    register(engine, entity_id, EntityKind.TRUST, name)


def officer(engine: Vinzor, name: str = "Meera Nair",
            role: Role = Role.AML_OFFICER) -> None:
    """Enrol a person so they may decide. Who may decide is workspace data."""
    engine.enroll(name=name, role=role, enrolled_at=WHEN)
