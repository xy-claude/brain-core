"""Session reflection: gather context + persist synthesis.

Contract:
  * The library never calls an LLM. It assembles data (:func:`gather_session_context`)
    and either hands it to a runtime for LLM synthesis, or produces a
    deterministic template summary (:func:`template_summary`) for headless
    / cron / offline contexts.
  * ``save_reflection`` persists whatever synthesis is produced. The
    ``auto_generated`` flag distinguishes template-produced reflections from
    LLM-produced ones (so dashboards can surface which is which).

Decision→session linking note:
  In v0 the schema does not carry ``session_id`` on the ``decisions`` table.
  :func:`gather_session_context` therefore returns *recent* decisions
  globally, not decisions scoped to a session. When the Agent class
  (Milestone 5) starts emitting ``decision.made`` events for every
  :func:`~central_brain.decisions.decide` call, callers can correlate
  decisions to sessions through the event log.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from central_brain.decisions.classifier import Decision, list_decisions
from central_brain.memory.episodic import Event, recent_events
from central_brain.storage.db import Database


@dataclass(frozen=True, slots=True)
class SessionReflection:
    """A persisted reflection row."""

    id: int
    session_id: str
    what_went_well: str | None
    what_to_improve: str | None
    apply_next_session: str | None
    auto_generated: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Structured input for session reflection synthesis.

    Handed to a runtime (Claude Code / LLM) or to :func:`template_summary`.
    """

    session_id: str
    events: list[Event]
    event_counts_by_type: dict[str, int]
    recent_decisions: list[Decision]
    decision_status_counts: dict[str, int]
    prior_reflections: list[SessionReflection]
    started_at: datetime | None = None
    ended_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def gather_session_context(
    db: Database,
    session_id: str,
    event_limit: int = 20,
    decision_limit: int = 20,
) -> SessionContext:
    """Assemble the structured context a runtime needs to reflect on a session.

    Args:
        db: open database.
        session_id: the session to gather context for.
        event_limit: max recent events to include.
        decision_limit: max recent decisions to include (global, not scoped).

    Raises:
        ValueError: if ``session_id`` is empty, or limits are < 1.
    """
    if not session_id.strip():
        raise ValueError("session_id must not be empty")
    if event_limit < 1 or decision_limit < 1:
        raise ValueError("event_limit and decision_limit must be >= 1")

    events = recent_events(db, session_id=session_id, limit=event_limit)
    event_counts = dict(Counter(e.event_type for e in events))

    decisions = list_decisions(db, limit=decision_limit)
    decision_status: dict[str, int] = dict(Counter(str(d.status) for d in decisions))

    prior = list_reflections(db, session_id=session_id, limit=event_limit)

    started_at = min((e.occurred_at for e in events), default=None)
    ended_at = max((e.occurred_at for e in events), default=None)

    return SessionContext(
        session_id=session_id,
        events=events,
        event_counts_by_type=event_counts,
        recent_decisions=decisions,
        decision_status_counts=decision_status,
        prior_reflections=prior,
        started_at=started_at,
        ended_at=ended_at,
    )


def save_reflection(
    db: Database,
    session_id: str,
    what_went_well: str | None = None,
    what_to_improve: str | None = None,
    apply_next_session: str | None = None,
    auto_generated: bool = False,
) -> SessionReflection:
    """Persist a reflection. Returns the stored SessionReflection.

    All three prose fields are nullable — a sparse reflection (e.g., only
    ``what_to_improve``) is valid.

    Raises:
        ValueError: if ``session_id`` is empty.
    """
    if not session_id.strip():
        raise ValueError("session_id must not be empty")

    cursor = db.execute(
        "INSERT INTO reflections "
        "(session_id, what_went_well, what_to_improve, apply_next_session, auto_generated) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            session_id,
            what_went_well,
            what_to_improve,
            apply_next_session,
            int(auto_generated),
        ),
    )
    new_id = cursor.lastrowid
    if new_id is None:  # pragma: no cover — defensive
        raise RuntimeError("INSERT did not return a rowid for reflection")

    row = db.fetchone("SELECT * FROM reflections WHERE id = ?", (new_id,))
    if row is None:  # pragma: no cover — defensive
        raise RuntimeError(f"reflection vanished after INSERT: id={new_id}")
    return _row_to_reflection(row)


def list_reflections(
    db: Database,
    session_id: str | None = None,
    limit: int = 20,
) -> list[SessionReflection]:
    """List reflections, newest first. Optional ``session_id`` filter."""
    if limit < 1:
        raise ValueError("limit must be >= 1")

    if session_id is None:
        rows = db.fetchall("SELECT * FROM reflections ORDER BY id DESC LIMIT ?", (limit,))
    else:
        rows = db.fetchall(
            "SELECT * FROM reflections WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
    return [_row_to_reflection(r) for r in rows]


def template_summary(context: SessionContext) -> str:
    """Deterministic template-based summary. No LLM calls.

    Used as the fallback synthesis path for headless / cron contexts, or as
    a baseline the runtime LLM can refine further.
    """
    lines: list[str] = [f"# Session reflection: {context.session_id}"]

    if context.started_at and context.ended_at:
        duration = context.ended_at - context.started_at
        lines.append(
            f"_Window: {context.started_at.isoformat()} → "
            f"{context.ended_at.isoformat()} "
            f"({duration.total_seconds():.0f}s)_"
        )

    lines.append("")
    lines.append(f"## Events ({len(context.events)})")
    if context.event_counts_by_type:
        for event_type, count in sorted(
            context.event_counts_by_type.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            lines.append(f"- {event_type}: {count}")
    else:
        lines.append("_No events logged in this session._")

    lines.append("")
    lines.append(f"## Decisions ({len(context.recent_decisions)} recent)")
    if context.decision_status_counts:
        for status, count in sorted(
            context.decision_status_counts.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            lines.append(f"- {status}: {count}")
    else:
        lines.append("_No recent decisions._")

    if context.prior_reflections:
        lines.append("")
        lines.append(f"## Prior reflections ({len(context.prior_reflections)})")
        for r in context.prior_reflections:
            lines.append(
                f"- {r.created_at.isoformat()} ({'auto' if r.auto_generated else 'manual'})"
            )

    return "\n".join(lines)


# ── internal helpers ─────────────────────────────────────────────────────────


def _row_to_reflection(row: sqlite3.Row) -> SessionReflection:
    return SessionReflection(
        id=int(row["id"]),
        session_id=str(row["session_id"]),
        what_went_well=(str(row["what_went_well"]) if row["what_went_well"] is not None else None),
        what_to_improve=(
            str(row["what_to_improve"]) if row["what_to_improve"] is not None else None
        ),
        apply_next_session=(
            str(row["apply_next_session"]) if row["apply_next_session"] is not None else None
        ),
        auto_generated=bool(row["auto_generated"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )
