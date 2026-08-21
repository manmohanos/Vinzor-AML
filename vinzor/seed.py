"""Load the synthetic FME dataset into an event log.

This is an *adapter*, and it is the only place that knows anything about CSV
files or about how the generator chose to name its columns. Two translations
happen here so that the core never has to:

1. **Edge direction is normalised.** The dataset stores ``TRUST
   -BENEFICIARY_OF-> PERSON``, where the target is the beneficiary of the
   source, and ``PERSON -OWNS-> COMPANY``, where the source owns the target.
   Those point opposite ways. Here they both become an explicit
   ``owner``/``owned`` pair.

2. **Derived conclusions are not ingested.** ``data/generated/ubochains.json``
   holds pre-computed UBO answers, and its ``UBO`` and ``TRANSACTION`` alerts
   in ``alerts.csv`` are likewise conclusions rather than observations. They
   are skipped: this system derives those itself, from the edges, and a
   conclusion imported as a fact can never be checked.

   That is not a theoretical concern here. The chains in ``ubochains.json``
   cite edges that do not exist in ``edges.csv`` -- the ``single_ubo`` chain is
   written back to front, and the ``no_single_ubo_over_25pct`` chain names a
   ``BENEFICIARY_OF`` edge the graph does not contain. The final answer for the
   first one (56%) happens to be right; the provenance is not. Recomputing
   from the edge table gives an answer that can be shown to a regulator.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterator, Optional

from .engine import Vinzor
from .eventlog import EventLog
from .licence import Category
from .model import EntityKind, EventType, Relation

DEFAULT_DATASET = (
    Path(__file__).resolve().parents[1] / "data" / "generated"
)

#: Watchlist alerts are observations about an entity. UBO and TRANSACTION
#: alerts are the generator's own conclusions and are re-derived instead.
INGESTED_ALERT_TYPES = {"SANCTIONS", "PEP", "ADVERSE_MEDIA"}

#: The dataset is a static snapshot; reference rows carry no date of their own.
DATASET_EPOCH = "2026-08-07"

#: The fund manager whose workspace this is, and its registration.
#:
#: The dataset describes investors, not the firm looking at them, so a seeded
#: workspace held no licence at all -- and without one ``observe_deadlines``
#: returns immediately. Every quarterly return and recurring fee the calendar
#: models was therefore unreachable from the served screen: the feature ran
#: correctly in tests and in ``python -m vinzor``, and a compliance officer
#: could never see a single overdue filing. The demo already invents these
#: exact values; they belong here, where both paths read them.
FME_SELF = "fme_self"
FME_NAME = "Acme GIFT Fund Managers Ltd"
FME_LICENCE_NUMBER = "IFSCA/FME/II/2024-25/084"
FME_GRANTED_ON = "2025-01-10"
FME_CATEGORY = Category.REGISTERED_NON_RETAIL.value

_ENTITY_FILES = (
    # dob and the identity document are here because screening compares them.
    # A "possible match" that cannot be compared is not reviewable.
    ("persons.csv", EntityKind.PERSON, "full_name",
     ("nationality", "country_of_residence", "dob", "id_document_type",
      "id_document_number", "pep_flag", "high_risk_jurisdiction")),
    ("companies.csv", EntityKind.COMPANY, "legal_name",
     ("jurisdiction", "country_of_incorporation", "is_shell", "is_listed")),
    ("trusts.csv", EntityKind.TRUST, "trust_name",
     ("jurisdiction", "trust_type", "is_discretionary", "has_protector")),
    ("funds.csv", EntityKind.FUND, "fund_name",
     ("fund_type", "vehicle_jurisdiction", "strategy")),
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _normalise_edge(row: dict[str, str]) -> Optional[dict[str, Any]]:
    """Map a dataset edge onto an explicit (owner, owned) pair.

    Returns ``None`` for relations that carry no ownership or control meaning,
    such as ``COMMITS_CAPITAL_TO`` (modelled as its own event) and
    ``SATISFIES`` (payment-to-call linkage, carried on the payment).
    """
    relation = row["relation"]
    if relation == "OWNS":
        owner, owned = row["source_id"], row["target_id"]
    elif relation == "BENEFICIARY_OF":
        # trust -> person: the *target* benefits from the *source*
        owner, owned = row["target_id"], row["source_id"]
    elif relation == "TRUSTEE_OF":
        # company -> trust: the source controls the target, holds no interest
        owner, owned = row["source_id"], row["target_id"]
    else:
        return None
    return {
        "owner": owner,
        "owned": owned,
        "relation": Relation(relation).value,
        "percentage": float(row["percentage"]) if row["percentage"] else 0.0,
        "edge_id": row["id"],
    }


def seed(
    engine: Optional[Vinzor] = None, dataset: Path = DEFAULT_DATASET
) -> Vinzor:
    """Replay the dataset into ``engine`` (a fresh in-memory one by default).

    Events are emitted in a fixed order -- entities, then ownership, then dated
    activity -- so the resulting log, and therefore every Case id derived from
    it, is byte-identical on every run. Backfilling reference data ahead of
    activity is a property of this loader, not a claim about real time.
    """
    engine = engine if engine is not None else Vinzor(EventLog())
    dataset = Path(dataset)

    # 0. The firm itself, and its registration. Everything else in the dataset
    #    is somebody the firm looks at; this is the firm being looked at.
    #    Without it the obligation calendar has no start date and stays silent.
    engine.ingest(
        event_type=EventType.ENTITY_REGISTERED,
        subject=FME_SELF,
        occurred_at=FME_GRANTED_ON,
        payload={"kind": EntityKind.COMPANY.value, "name": FME_NAME},
    )
    engine.ingest(
        event_type=EventType.LICENCE_GRANTED,
        subject=FME_SELF,
        occurred_at=FME_GRANTED_ON,
        payload={"category": FME_CATEGORY, "number": FME_LICENCE_NUMBER},
    )

    # 1. Entities.
    for filename, kind, name_field, attr_fields in _ENTITY_FILES:
        for row in sorted(_rows(dataset / filename), key=lambda r: r["id"]):
            engine.ingest(
                event_type=EventType.ENTITY_REGISTERED,
                subject=row["id"],
                occurred_at=DATASET_EPOCH,
                payload={
                    "kind": kind.value,
                    "name": row[name_field],
                    "attributes": {f: row[f] for f in attr_fields if f in row},
                },
            )

    # 2. Ownership and control.
    for row in sorted(_rows(dataset / "edges.csv"), key=lambda r: r["id"]):
        payload = _normalise_edge(row)
        if payload is None:
            continue
        engine.ingest(
            event_type=EventType.OWNERSHIP_DECLARED,
            subject=payload["owned"],
            occurred_at=row["start_date"] or DATASET_EPOCH,
            payload=payload,
        )

    # 3. Dated activity, in date order.
    for _, emit in sorted(_activity(dataset), key=lambda item: item[0]):
        emit(engine)

    return engine


def _activity(dataset: Path) -> Iterator[tuple[tuple[str, str], Any]]:
    """Yield ``((date, id), emitter)`` for everything that happens on a date."""

    for row in _rows(dataset / "capital_commitments.csv"):
        def emit(engine: Vinzor, row: dict[str, str] = row) -> None:
            engine.ingest(
                event_type=EventType.COMMITMENT_MADE,
                subject=row["investor_id"],
                occurred_at=row["commitment_date"],
                payload={
                    "investor": row["investor_id"],
                    "fund": row["fund_id"],
                    "amount": float(row["commitment_amount"]),
                    "currency": row["commitment_currency"],
                    "commitment_id": row["id"],
                },
            )

        yield (row["commitment_date"], row["id"]), emit

    for row in _rows(dataset / "alerts.csv"):
        if row["alert_type"] not in INGESTED_ALERT_TYPES:
            continue

        def emit(engine: Vinzor, row: dict[str, str] = row) -> None:
            engine.ingest(
                event_type=EventType.SCREENING_COMPLETED,
                subject=row["entity_id"],
                occurred_at=row["created_date"],
                payload={
                    "list_type": row["alert_type"],
                    "matched": True,
                    "rule": row["source_rule"],
                    "alert_id": row["id"],
                },
            )

        yield (row["created_date"], row["id"]), emit

    for row in _rows(dataset / "payments.csv"):
        anomaly = json.loads(row["anomaly_metadata"]) if row["anomaly_metadata"] else {}
        payer = row["from_counterparty_id"]
        # When the payer is unknown the payment itself is what is under
        # review, so it becomes the subject of any Case.
        subject = payer if payer and payer != "UNKNOWN" else row["id"]

        def emit(engine: Vinzor, row: dict[str, str] = row,
                 anomaly: dict[str, Any] = anomaly, subject: str = subject) -> None:
            engine.ingest(
                event_type=EventType.PAYMENT_RECEIVED,
                subject=subject,
                occurred_at=row["payment_date"],
                payload={
                    "payment_id": row["id"],
                    "payment_ref": row["payment_ref"],
                    "amount": float(row["amount"]),
                    "currency": row["currency"],
                    "expected_currency": row["expected_currency"],
                    "payer": row["from_counterparty_id"],
                    "fund": row["to_fund_id"],
                    "called_amount": float(row["matching_allocated_amount"])
                    if row["matching_allocated_amount"]
                    else None,
                    "anomaly": anomaly.get("class"),
                    "anomaly_detail": anomaly.get("detail"),
                },
            )

        yield (row["payment_date"], row["id"]), emit
