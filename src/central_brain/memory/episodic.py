"""Episodic memory: append-only event log.

Every observable occurrence (user message, tool call, decision made,
correction received) can be logged as an Event with a structured payload.
Consumers query by ``session_id`` or ``event_type``, ordered by time.

No dedup here — episodic memory is meant to be complete. If a duplicate
appears, that fact is itself information.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from central_brain.storage.db import Database


@dataclass(frozen=True, slots=True)
class Event:
    """A single logged event."""

    id: int
    event_type: str
    payload: dict[str, Any]
    session_id: str | None
    occurred_at: datetime


def log_event(
    db: Database,
    event_type: str,
    payload: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> Event:
    """Append an event to the log. Returns the stored Event.

    Raises:
        ValueError: if ``event_type`` is empty.
    """
    if not event_type.strip():
        raise ValueError("event_type must not be empty")

    payload_json = json.dumps(payload) if payload else None
    cursor = db.execute(
        "INSERT INTO events (event_type, payload, session_id) VALUES (?, ?, ?)",
        (event_type, payload_json, session_id),
    )
    event_id = cursor.lastrowid
    if event_id is None:  # pragma: no cover — defensive
        raise RuntimeError("INSERT did not return a rowid for event")

    row = db.fetchone("SELECT * FROM events WHERE id = ?", (event_id,))
    if row is None:  # pragma: no cover — defensive
        raise RuntimeError(f"event vanished after INSERT: id={event_id}")
    return _row_to_event(row)


def recent_events(
    db: Database,
    session_id: str | None = None,
    event_type: str | None = None,
    limit: int = 50,
) -> list[Event]:
    """Return the most recent events, newest first.

    Optional filters:
        session_id: only events in a specific session
        event_type: only events of a specific type

    Ordering: ``id DESC`` (strict tie-break beyond ``occurred_at``).
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")

    where: list[str] = []
    params: list[Any] = []
    if session_id is not None:
        where.append("session_id = ?")
        params.append(session_id)
    if event_type is not None:
        where.append("event_type = ?")
        params.append(event_type)

    sql = "SELECT * FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = db.fetchall(sql, tuple(params))
    return [_row_to_event(r) for r in rows]


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=int(row["id"]),
        event_type=str(row["event_type"]),
        payload=json.loads(row["payload"]) if row["payload"] else {},
        session_id=(str(row["session_id"]) if row["session_id"] is not None else None),
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
    )
