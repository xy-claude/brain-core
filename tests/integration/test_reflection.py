"""Reflection capability tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from central_brain.decisions import complete, decide, reverse
from central_brain.memory import log_event
from central_brain.reflection import (
    SessionContext,
    SessionReflection,
    gather_session_context,
    list_reflections,
    save_reflection,
    template_summary,
)
from central_brain.storage import Database

# ── gather_session_context ───────────────────────────────────────────────────


def test_gather_with_no_activity(db: Database) -> None:
    ctx = gather_session_context(db, session_id="empty-session")
    assert ctx.session_id == "empty-session"
    assert ctx.events == []
    assert ctx.event_counts_by_type == {}
    assert ctx.recent_decisions == []
    assert ctx.decision_status_counts == {}
    assert ctx.prior_reflections == []
    assert ctx.started_at is None
    assert ctx.ended_at is None


def test_gather_counts_events_by_type(db: Database) -> None:
    log_event(db, event_type="user_message", session_id="s1")
    log_event(db, event_type="user_message", session_id="s1")
    log_event(db, event_type="tool_call", session_id="s1")
    log_event(db, event_type="user_message", session_id="other")  # noise

    ctx = gather_session_context(db, session_id="s1")
    assert len(ctx.events) == 3
    assert ctx.event_counts_by_type == {"user_message": 2, "tool_call": 1}


def test_gather_includes_recent_decisions(db: Database) -> None:
    decide(db, action="plan A", reversible=True)
    d2 = decide(db, action="plan B", reversible=True)
    complete(db, d2.id)

    ctx = gather_session_context(db, session_id="any")
    assert len(ctx.recent_decisions) == 2
    assert ctx.decision_status_counts == {"active": 1, "completed": 1}


def test_gather_reflects_reversed_count(db: Database) -> None:
    a = decide(db, action="a", reversible=True)
    b = decide(db, action="b", reversible=True)
    reverse(db, a.id)
    complete(db, b.id)

    ctx = gather_session_context(db, session_id="any")
    assert ctx.decision_status_counts == {"reversed": 1, "completed": 1}


def test_gather_includes_prior_reflections(db: Database) -> None:
    save_reflection(db, session_id="sX", what_went_well="first pass")
    save_reflection(db, session_id="sX", what_to_improve="try again")
    save_reflection(db, session_id="other")  # noise

    ctx = gather_session_context(db, session_id="sX")
    assert len(ctx.prior_reflections) == 2
    assert all(r.session_id == "sX" for r in ctx.prior_reflections)


def test_gather_window_times_derived_from_events(db: Database) -> None:
    log_event(db, event_type="e", session_id="s1")
    log_event(db, event_type="e", session_id="s1")
    ctx = gather_session_context(db, session_id="s1")
    assert ctx.started_at is not None
    assert ctx.ended_at is not None
    assert ctx.started_at <= ctx.ended_at


def test_gather_respects_event_limit(db: Database) -> None:
    for _ in range(5):
        log_event(db, event_type="e", session_id="s1")
    ctx = gather_session_context(db, session_id="s1", event_limit=3)
    assert len(ctx.events) == 3


def test_gather_rejects_empty_session_id(db: Database) -> None:
    with pytest.raises(ValueError, match="session_id must not be empty"):
        gather_session_context(db, session_id="  ")


def test_gather_rejects_bad_limits(db: Database) -> None:
    with pytest.raises(ValueError, match="must be >= 1"):
        gather_session_context(db, session_id="s1", event_limit=0)
    with pytest.raises(ValueError, match="must be >= 1"):
        gather_session_context(db, session_id="s1", decision_limit=0)


# ── save_reflection ──────────────────────────────────────────────────────────


def test_save_reflection_round_trip(db: Database) -> None:
    r = save_reflection(
        db,
        session_id="s1",
        what_went_well="shipped milestone",
        what_to_improve="fewer audit rounds",
        apply_next_session="review first, edit second",
    )
    assert r.id > 0
    assert r.session_id == "s1"
    assert r.what_went_well == "shipped milestone"
    assert r.what_to_improve == "fewer audit rounds"
    assert r.apply_next_session == "review first, edit second"
    assert r.auto_generated is False


def test_save_reflection_sparse_is_valid(db: Database) -> None:
    """Reflections can have any subset of prose fields — all-None is legal."""
    r = save_reflection(db, session_id="s1")
    assert r.what_went_well is None
    assert r.what_to_improve is None
    assert r.apply_next_session is None


def test_save_reflection_auto_flag_round_trips(db: Database) -> None:
    r = save_reflection(db, session_id="s1", auto_generated=True)
    assert r.auto_generated is True
    assert isinstance(r.auto_generated, bool)


def test_save_reflection_rejects_empty_session_id(db: Database) -> None:
    with pytest.raises(ValueError, match="session_id must not be empty"):
        save_reflection(db, session_id=" ")


def test_multiple_reflections_per_session(db: Database) -> None:
    save_reflection(db, session_id="s1", what_went_well="a")
    save_reflection(db, session_id="s1", what_went_well="b")
    save_reflection(db, session_id="s1", what_went_well="c")

    all_for_session = list_reflections(db, session_id="s1")
    assert len(all_for_session) == 3
    # newest first
    assert [r.what_went_well for r in all_for_session] == ["c", "b", "a"]


def test_list_reflections_limit(db: Database) -> None:
    for i in range(5):
        save_reflection(db, session_id="s1", what_went_well=str(i))
    assert len(list_reflections(db, limit=2)) == 2


def test_list_reflections_bad_limit(db: Database) -> None:
    with pytest.raises(ValueError, match="limit must be"):
        list_reflections(db, limit=0)


# ── template_summary ─────────────────────────────────────────────────────────


def test_template_summary_empty_session(db: Database) -> None:
    ctx = gather_session_context(db, session_id="empty")
    out = template_summary(ctx)
    assert "empty" in out
    assert "No events" in out
    assert "No recent decisions" in out


def test_template_summary_includes_event_breakdown(db: Database) -> None:
    log_event(db, event_type="user_message", session_id="s1")
    log_event(db, event_type="tool_call", session_id="s1")
    log_event(db, event_type="tool_call", session_id="s1")

    ctx = gather_session_context(db, session_id="s1")
    out = template_summary(ctx)
    assert "tool_call: 2" in out
    assert "user_message: 1" in out
    # Higher counts listed first
    assert out.index("tool_call: 2") < out.index("user_message: 1")


def test_template_summary_includes_decisions(db: Database) -> None:
    d = decide(db, action="plan", reversible=True)
    complete(db, d.id)

    ctx = gather_session_context(db, session_id="s1")
    out = template_summary(ctx)
    assert "completed: 1" in out


def test_template_summary_is_deterministic(db: Database) -> None:
    log_event(db, event_type="e", session_id="s1")
    ctx = gather_session_context(db, session_id="s1")
    first = template_summary(ctx)
    second = template_summary(ctx)
    assert first == second


def test_template_summary_includes_prior_reflections(db: Database) -> None:
    save_reflection(db, session_id="s1", what_went_well="previously")
    ctx = gather_session_context(db, session_id="s1")
    out = template_summary(ctx)
    assert "Prior reflections" in out


# ── dataclass contracts ──────────────────────────────────────────────────────


def test_session_reflection_is_frozen() -> None:
    r = SessionReflection(
        id=1,
        session_id="s1",
        what_went_well=None,
        what_to_improve=None,
        apply_next_session=None,
        auto_generated=False,
        created_at=datetime(2024, 1, 1),
    )
    with pytest.raises(AttributeError):
        r.session_id = "x"  # type: ignore[misc]


def test_session_context_is_frozen() -> None:
    ctx = SessionContext(
        session_id="s1",
        events=[],
        event_counts_by_type={},
        recent_decisions=[],
        decision_status_counts={},
        prior_reflections=[],
    )
    with pytest.raises(AttributeError):
        ctx.session_id = "x"  # type: ignore[misc]
