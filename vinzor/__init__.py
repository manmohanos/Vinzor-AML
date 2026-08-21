"""Vinzor core: operational trust infrastructure for private capital.

The whole system in one paragraph. Facts arrive as **events** and are appended
to a hash-chained log, which is both the source of truth and the audit trail.
Everything else -- the ownership **graph**, the open **Cases** -- is a
projection folded out of that log and can be rebuilt at any time. **Policies**
read each event and decide whether it opens a Case. A Case carries the
**Evidence** for its own existence, and only a **human** in a deciding role can
close one.

Read the modules in this order: ``model`` (the vocabulary), ``eventlog`` (the
one thing that is persisted), ``graph`` and ``cases`` (the projections),
``policies`` (the rules), ``engine`` (the wiring).
"""

from .cases import CaseBook, DecisionDenied, UnknownCase
from .engine import State, Vinzor, apply_event, project
from .eventlog import EventLog, verify_chain
from .graph import Conclusion, OwnershipGraph, UboResult
from .model import (
    DECIDING_ROLES,
    Case,
    CaseStatus,
    Decision,
    Event,
    EventType,
    Evidence,
    EvidenceKind,
    Finding,
    Outcome,
    Relation,
    Role,
    Severity,
)

__version__ = "0.1.0"

__all__ = [
    "CaseBook",
    "Case",
    "CaseStatus",
    "Conclusion",
    "DECIDING_ROLES",
    "Decision",
    "DecisionDenied",
    "Event",
    "EventLog",
    "EventType",
    "Evidence",
    "EvidenceKind",
    "Finding",
    "Outcome",
    "OwnershipGraph",
    "Relation",
    "Role",
    "Severity",
    "State",
    "UboResult",
    "UnknownCase",
    "Vinzor",
    "apply_event",
    "project",
    "verify_chain",
]
