"""Decision logging + status transitions.

Semantics:
  * A new decision starts in status ``active``.
  * ``reverse()`` transitions active → reversed. Optionally links to a
    replacement decision via ``reversed_by`` (caller must create the
    replacement via :func:`decide` first, then pass its id).
  * ``complete()`` transitions active → completed.
  * Re-applying the same transition is a no-op (idempotent). Cross-state
    transitions (reversed → completed, completed → reversed) raise
    ValueError to prevent silent state corruption.
  * Completed decisions are immutable; reversed decisions are immutable
    except for the optional ``reversed_by`` link, which is set at reversal
    time and never changed.

Validation:
  * ``risk``, ``confidence`` validated at Python boundary against Literal
    type aliases, in addition to the SQL CHECK constraints.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from brain_core.storage.db import Database

Risk = Literal["low", "medium", "high"]
Confidence = Literal["low", "medium", "high"]
Status = Literal["active", "reversed", "completed"]

_VALID_RISK: Final[frozenset[str]] = frozenset({"low", "medium", "high"})
_VALID_CONFIDENCE: Final[frozenset[str]] = frozenset({"low", "medium", "high"})
_VALID_STATUS: Final[frozenset[str]] = frozenset({"active", "reversed", "completed"})


@dataclass(frozen=True, slots=True)
class Decision:
    """A single logged decision."""

    id: int
    action: str
    reversible: bool
    risk: Risk
    confidence: Confidence
    reasoning: str | None
    alternatives: list[str]
    status: Status
    reversed_by: int | None
    created_at: datetime


def decide(
    db: Database,
    action: str,
    reversible: bool,
    risk: Risk = "medium",
    confidence: Confidence = "medium",
    reasoning: str | None = None,
    alternatives: list[str] | None = None,
) -> Decision:
    """Log a new decision in status ``active``. Returns the Decision.

    Raises:
        ValueError: if ``action`` is empty, or ``risk``/``confidence`` are
            not one of the allowed values.
    """
    if not action.strip():
        raise ValueError("action must not be empty")
    if risk not in _VALID_RISK:
        raise ValueError(f"risk must be one of {sorted(_VALID_RISK)}, got {risk!r}")
    if confidence not in _VALID_CONFIDENCE:
        raise ValueError(
            f"confidence must be one of {sorted(_VALID_CONFIDENCE)}, got {confidence!r}"
        )

    alternatives_json = json.dumps(alternatives) if alternatives else None

    cursor = db.execute(
        "INSERT INTO decisions "
        "(action, reversible, risk, confidence, reasoning, alternatives) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (action, int(reversible), risk, confidence, reasoning, alternatives_json),
    )
    new_id = cursor.lastrowid
    if new_id is None:  # pragma: no cover — defensive
        raise RuntimeError("INSERT did not return a rowid for decision")

    fetched = get_decision(db, new_id)
    if fetched is None:  # pragma: no cover — defensive
        raise RuntimeError(f"decision vanished after INSERT: id={new_id}")
    return fetched


def reverse(
    db: Database,
    decision_id: int,
    replaced_by: int | None = None,
) -> Decision:
    """Mark a decision as reversed. Returns the updated Decision.

    Args:
        decision_id: the decision to reverse.
        replaced_by: optional id of the replacement decision. The
            replacement must already exist (create it first via
            :func:`decide`).

    Raises:
        ValueError: if the decision does not exist, if ``replaced_by``
            refers to a non-existent decision, if ``replaced_by`` equals
            ``decision_id`` (self-reference), or if the decision is already
            ``completed``.
    """
    current = get_decision(db, decision_id)
    if current is None:
        raise ValueError(f"no decision with id={decision_id}")

    if replaced_by is not None:
        if replaced_by == decision_id:
            raise ValueError("replaced_by cannot be the same as decision_id")
        replacement = get_decision(db, replaced_by)
        if replacement is None:
            raise ValueError(f"no replacement decision with id={replaced_by}")

    if current.status == "reversed":
        return current  # idempotent
    if current.status == "completed":
        raise ValueError(f"cannot reverse a completed decision (id={decision_id})")

    db.execute(
        "UPDATE decisions SET status = 'reversed', reversed_by = ? WHERE id = ?",
        (replaced_by, decision_id),
    )
    updated = get_decision(db, decision_id)
    if updated is None:  # pragma: no cover — defensive
        raise RuntimeError(f"decision vanished after UPDATE: id={decision_id}")
    return updated


def complete(db: Database, decision_id: int) -> Decision:
    """Mark a decision as completed. Returns the updated Decision.

    Raises:
        ValueError: if the decision does not exist or is ``reversed``.
    """
    current = get_decision(db, decision_id)
    if current is None:
        raise ValueError(f"no decision with id={decision_id}")

    if current.status == "completed":
        return current  # idempotent
    if current.status == "reversed":
        raise ValueError(f"cannot complete a reversed decision (id={decision_id})")

    db.execute(
        "UPDATE decisions SET status = 'completed' WHERE id = ?",
        (decision_id,),
    )
    updated = get_decision(db, decision_id)
    if updated is None:  # pragma: no cover — defensive
        raise RuntimeError(f"decision vanished after UPDATE: id={decision_id}")
    return updated


def get_decision(db: Database, decision_id: int) -> Decision | None:
    """Fetch a decision by id, or None if not found."""
    row = db.fetchone("SELECT * FROM decisions WHERE id = ?", (decision_id,))
    return _row_to_decision(row) if row is not None else None


def list_decisions(
    db: Database,
    status: Status | None = None,
    limit: int = 50,
) -> list[Decision]:
    """List decisions, newest first.

    Args:
        status: if given, filters to that status only.
        limit: max rows returned.

    Raises:
        ValueError: if ``status`` is not one of the allowed values, or
            ``limit`` < 1.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if status is not None and status not in _VALID_STATUS:
        raise ValueError(f"status must be one of {sorted(_VALID_STATUS)}, got {status!r}")

    if status is None:
        rows = db.fetchall("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,))
    else:
        rows = db.fetchall(
            "SELECT * FROM decisions WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status, limit),
        )
    return [_row_to_decision(r) for r in rows]


# ── internal helpers ─────────────────────────────────────────────────────────


def _row_to_decision(row: sqlite3.Row) -> Decision:
    return Decision(
        id=int(row["id"]),
        action=str(row["action"]),
        reversible=bool(row["reversible"]),
        risk=_cast_risk(str(row["risk"])),
        confidence=_cast_confidence(str(row["confidence"])),
        reasoning=(str(row["reasoning"]) if row["reasoning"] is not None else None),
        alternatives=(json.loads(row["alternatives"]) if row["alternatives"] else []),
        status=_cast_status(str(row["status"])),
        reversed_by=(int(row["reversed_by"]) if row["reversed_by"] is not None else None),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _cast_risk(value: str) -> Risk:
    # Schema CHECK constraint guarantees validity; cast at the type boundary.
    assert value in _VALID_RISK, f"invalid risk from DB: {value!r}"
    return value  # type: ignore[return-value]


def _cast_confidence(value: str) -> Confidence:
    assert value in _VALID_CONFIDENCE, f"invalid confidence from DB: {value!r}"
    return value  # type: ignore[return-value]


def _cast_status(value: str) -> Status:
    assert value in _VALID_STATUS, f"invalid status from DB: {value!r}"
    return value  # type: ignore[return-value]
