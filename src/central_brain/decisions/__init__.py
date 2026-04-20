"""Decisions capability: classified decision log with reversal tracking.

Public types:
    Decision — frozen dataclass returned at the API boundary.
    Risk, Confidence, Status — Literal type aliases for enum-like fields.

Public functions:
    decide(db, action, reversible, risk, confidence, reasoning, alternatives)
    reverse(db, decision_id, replaced_by=None)
    complete(db, decision_id)
    get_decision(db, decision_id)
    list_decisions(db, status=None, limit=50)
"""

from central_brain.decisions.classifier import (
    Confidence,
    Decision,
    Risk,
    Status,
    complete,
    decide,
    get_decision,
    list_decisions,
    reverse,
)

__all__ = [
    "Confidence",
    "Decision",
    "Risk",
    "Status",
    "complete",
    "decide",
    "get_decision",
    "list_decisions",
    "reverse",
]
