"""Pure tool implementations — no MCP machinery.

Each ``tool_*`` function takes an :class:`~brain_core.Agent` plus its
typed arguments and returns JSON-serializable output (dict or list of
dicts). The MCP server in :mod:`brain_core.mcp.server` wraps these as
stdio tools; tests call them directly.

All datetimes are serialized as ISO-8601 strings at the boundary.
"""

from __future__ import annotations

from typing import Any, cast

from brain_core.agent import Agent
from brain_core.decisions.classifier import (
    Confidence,
    Decision,
    Risk,
    Status,
)
from brain_core.memory.episodic import Event
from brain_core.memory.structured import Fact, FactKind
from brain_core.reflection.session import SessionContext, SessionReflection

# ── memory ───────────────────────────────────────────────────────────────────


def tool_remember(
    agent: Agent,
    content: str,
    kind: FactKind = "fact",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a fact. Idempotent on normalized content."""
    return _fact_to_dict(agent.remember(content, kind=kind, tags=tags, metadata=metadata))


def tool_recall(
    agent: Agent,
    query: str | None = None,
    kind: FactKind | None = None,
    limit: int = 10,
    include_superseded: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve facts. FTS5-ranked if ``query`` is given, else newest-first."""
    return [
        _fact_to_dict(f)
        for f in agent.recall(
            query=query,
            kind=kind,
            limit=limit,
            include_superseded=include_superseded,
        )
    ]


def tool_brain_recall(
    agent: Agent,
    query: str,
    scope: str = "all",
    format: str = "concise",
    limit: int = 10,
) -> dict[str, Any]:
    """v0.2: one query across SQLite, vault, Hindsight and graph. Capped, deduplicated."""
    return agent.brain_recall(query, scope=scope, fmt=format, limit=limit)


def tool_brain_remember(
    agent: Agent,
    text: str,
    kind: str,
    domain: str = "",
    source: str = "",
    mission: str | None = None,
    force: bool = False,
    extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    """v0.2: write-through vault → sqlite → Hindsight → graph with per-layer status."""
    return agent.brain_remember(
        text,
        kind,
        domain=domain,
        source=source,
        mission=mission,
        force=force,
        **cast(dict[str, Any], extra or {}),
    )


def tool_brain_session(
    agent: Agent,
    phase: str,
    session_id: str | None = None,
    executive_state: str | None = None,
    critique: str | None = None,
    sync: str | None = None,
) -> dict[str, Any]:
    """v0.2: START block / END writes in one call."""
    return agent.brain_session(
        phase, session_id, executive_state=executive_state, critique=critique, sync=sync
    )


def tool_brain_distill(
    agent: Agent,
    source: str,
    text: str | None = None,
    title: str | None = None,
    author: str | None = None,
    published: str | None = None,
) -> dict[str, Any]:
    """v0.2: capture a URL / file / text into raw/."""
    return agent.brain_distill(source, text=text, title=title, author=author, published=published)


def tool_brain_status(agent: Agent) -> dict[str, Any]:
    """v0.2: health in one call."""
    return agent.brain_status()


def tool_supersede(
    agent: Agent,
    old_fact_id: int,
    new_content: str,
    kind: FactKind = "fact",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replace an old fact with a new one; old fact keeps a pointer to new."""
    return _fact_to_dict(
        agent.supersede(old_fact_id, new_content, kind=kind, tags=tags, metadata=metadata)
    )


def tool_log_event(
    agent: Agent,
    event_type: str,
    payload: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Append an event to the episodic log. Uses the active session by default."""
    return _event_to_dict(agent.log_event(event_type, payload=payload, session_id=session_id))


def tool_recent_events(
    agent: Agent,
    session_id: str | None = None,
    event_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch recent events, newest first. Optional session + type filter."""
    return [
        _event_to_dict(e)
        for e in agent.recent_events(session_id=session_id, event_type=event_type, limit=limit)
    ]


def tool_append_today(agent: Agent, text: str) -> dict[str, Any]:
    """Append text to today's HSAM markdown archive."""
    day = agent.append_today(text)
    return {
        "date": day.date.isoformat(),
        "archive_path": day.archive_path,
        "word_count": day.word_count,
        "last_written": day.last_written.isoformat(),
    }


# ── decisions ────────────────────────────────────────────────────────────────


def tool_decide(
    agent: Agent,
    action: str,
    reversible: bool,
    risk: Risk = "medium",
    confidence: Confidence = "medium",
    reasoning: str | None = None,
    alternatives: list[str] | None = None,
) -> dict[str, Any]:
    """Log a new decision in status 'active'."""
    return _decision_to_dict(
        agent.decide(
            action=action,
            reversible=reversible,
            risk=risk,
            confidence=confidence,
            reasoning=reasoning,
            alternatives=alternatives,
        )
    )


def tool_reverse(
    agent: Agent,
    decision_id: int,
    replaced_by: int | None = None,
) -> dict[str, Any]:
    """Mark a decision reversed. Optionally link to a replacement decision."""
    return _decision_to_dict(agent.reverse(decision_id, replaced_by=replaced_by))


def tool_complete(agent: Agent, decision_id: int) -> dict[str, Any]:
    """Mark a decision completed."""
    return _decision_to_dict(agent.complete(decision_id))


def tool_list_decisions(
    agent: Agent,
    status: Status | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List decisions, newest first. Optional status filter."""
    return [_decision_to_dict(d) for d in agent.list_decisions(status=status, limit=limit)]


# ── reflection ───────────────────────────────────────────────────────────────


def tool_gather_context(
    agent: Agent,
    session_id: str | None = None,
    event_limit: int = 20,
    decision_limit: int = 20,
) -> dict[str, Any]:
    """Assemble structured reflection context for the active (or named) session.

    The returned dict is what a runtime LLM reads before synthesizing the
    reflection. Tools should call :func:`tool_save_reflection` with the
    synthesis result.
    """
    ctx = agent.gather_context(
        session_id=session_id,
        event_limit=event_limit,
        decision_limit=decision_limit,
    )
    return _context_to_dict(ctx)


def tool_save_reflection(
    agent: Agent,
    session_id: str | None = None,
    what_went_well: str | None = None,
    what_to_improve: str | None = None,
    apply_next_session: str | None = None,
    auto_generated: bool = False,
) -> dict[str, Any]:
    """Persist a reflection. Any subset of prose fields is valid."""
    return _reflection_to_dict(
        agent.save_reflection(
            session_id=session_id,
            what_went_well=what_went_well,
            what_to_improve=what_to_improve,
            apply_next_session=apply_next_session,
            auto_generated=auto_generated,
        )
    )


def tool_template_summary(agent: Agent, session_id: str | None = None) -> dict[str, str]:
    """Deterministic template-only summary (zero LLM). Returns ``{"summary": "..."}``."""
    return {"summary": agent.template_summary(session_id=session_id)}


# ── session ──────────────────────────────────────────────────────────────────


def tool_current_session(agent: Agent) -> dict[str, Any]:
    """Report the active session id and agent name."""
    return {
        "agent": agent.name,
        "session_id": agent.current_session,
        "capabilities": list(agent.config.capabilities),
    }


# ── serialization helpers ────────────────────────────────────────────────────


def _fact_to_dict(f: Fact) -> dict[str, Any]:
    return {
        "id": f.id,
        "content": f.content,
        "kind": f.kind,
        "tags": f.tags,
        "metadata": f.metadata,
        "content_hash": f.content_hash,
        "created_at": f.created_at.isoformat(),
        "updated_at": f.updated_at.isoformat(),
        "superseded_by": f.superseded_by,
    }


def _event_to_dict(e: Event) -> dict[str, Any]:
    return {
        "id": e.id,
        "event_type": e.event_type,
        "payload": e.payload,
        "session_id": e.session_id,
        "occurred_at": e.occurred_at.isoformat(),
    }


def _decision_to_dict(d: Decision) -> dict[str, Any]:
    return {
        "id": d.id,
        "action": d.action,
        "reversible": d.reversible,
        "risk": d.risk,
        "confidence": d.confidence,
        "reasoning": d.reasoning,
        "alternatives": d.alternatives,
        "status": d.status,
        "reversed_by": d.reversed_by,
        "created_at": d.created_at.isoformat(),
    }


def _reflection_to_dict(r: SessionReflection) -> dict[str, Any]:
    return {
        "id": r.id,
        "session_id": r.session_id,
        "what_went_well": r.what_went_well,
        "what_to_improve": r.what_to_improve,
        "apply_next_session": r.apply_next_session,
        "auto_generated": r.auto_generated,
        "created_at": r.created_at.isoformat(),
    }


def _context_to_dict(ctx: SessionContext) -> dict[str, Any]:
    return {
        "session_id": ctx.session_id,
        "events": [_event_to_dict(e) for e in ctx.events],
        "event_counts_by_type": ctx.event_counts_by_type,
        "recent_decisions": [_decision_to_dict(d) for d in ctx.recent_decisions],
        "decision_status_counts": ctx.decision_status_counts,
        "prior_reflections": [_reflection_to_dict(r) for r in ctx.prior_reflections],
        "started_at": ctx.started_at.isoformat() if ctx.started_at else None,
        "ended_at": ctx.ended_at.isoformat() if ctx.ended_at else None,
    }
