"""Pure MCP tool function tests — no server machinery.

These run without the mcp extra needing to be invoked — we call the
implementation functions directly to verify serialization + behavior.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from brain_core import Agent
from brain_core.mcp import tools


def make_agent(tmp_path: Path) -> Agent:
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(textwrap.dedent("name: t\n"), encoding="utf-8")
    return Agent.from_config(cfg)


# ── serialization round-trips ────────────────────────────────────────────────


def test_tool_remember_returns_serializable_dict(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        out = tools.tool_remember(agent, "hello", kind="fact", tags=["t1"])
    assert out["content"] == "hello"
    assert out["kind"] == "fact"
    assert out["tags"] == ["t1"]
    assert isinstance(out["created_at"], str)  # ISO string, not datetime
    assert isinstance(out["id"], int)


def test_tool_recall_returns_list_of_dicts(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        tools.tool_remember(agent, "alpha")
        tools.tool_remember(agent, "beta")
        results = tools.tool_recall(agent)
    assert isinstance(results, list)
    assert len(results) == 2
    assert all(isinstance(r, dict) for r in results)


def test_tool_recall_with_query(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        tools.tool_remember(agent, "deployment failed because env var missing")
        tools.tool_remember(agent, "user loves dark mode")
        hits = tools.tool_recall(agent, query="deployment")
    assert len(hits) == 1
    assert "deployment" in hits[0]["content"]


def test_tool_supersede(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        old = tools.tool_remember(agent, "old fact")
        new = tools.tool_supersede(agent, old["id"], "new fact")
    assert new["id"] != old["id"]
    assert new["content"] == "new fact"


# ── events ───────────────────────────────────────────────────────────────────


def test_tool_log_event_and_recent_events(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        agent.start_session("s1")
        tools.tool_log_event(agent, "user_message", payload={"text": "hi"})
        tools.tool_log_event(agent, "tool_call")
        events = tools.tool_recent_events(agent, session_id="s1")
    assert len(events) == 2
    assert events[0]["event_type"] == "tool_call"  # newest first


def test_tool_append_today(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        out = tools.tool_append_today(agent, "first line of the day.")
    assert "archive_path" in out
    assert out["word_count"] > 0
    assert isinstance(out["date"], str)


# ── decisions ────────────────────────────────────────────────────────────────


def test_tool_decide_complete_round_trip(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        d = tools.tool_decide(agent, action="ship it", reversible=True, risk="low")
        done = tools.tool_complete(agent, d["id"])
    assert d["status"] == "active"
    assert done["status"] == "completed"


def test_tool_reverse_with_replacement(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        old = tools.tool_decide(agent, action="old", reversible=True)
        new = tools.tool_decide(agent, action="new", reversible=True)
        reversed_old = tools.tool_reverse(agent, old["id"], replaced_by=new["id"])
    assert reversed_old["status"] == "reversed"
    assert reversed_old["reversed_by"] == new["id"]


def test_tool_list_decisions_filter(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        a = tools.tool_decide(agent, action="a", reversible=True)
        tools.tool_decide(agent, action="b", reversible=True)
        tools.tool_reverse(agent, a["id"])
        reversed_list = tools.tool_list_decisions(agent, status="reversed")
    assert len(reversed_list) == 1
    assert reversed_list[0]["status"] == "reversed"


# ── reflection ───────────────────────────────────────────────────────────────


def test_tool_gather_and_save_reflection(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        agent.start_session("s1")
        tools.tool_log_event(agent, "user_message")
        tools.tool_decide(agent, action="ship", reversible=True)

        ctx = tools.tool_gather_context(agent)
        assert ctx["session_id"] == "s1"
        assert len(ctx["events"]) == 1
        assert len(ctx["recent_decisions"]) == 1
        assert "active" in ctx["decision_status_counts"]

        r = tools.tool_save_reflection(
            agent,
            what_went_well="milestone shipped",
            auto_generated=False,
        )
    assert r["session_id"] == "s1"
    assert r["what_went_well"] == "milestone shipped"
    assert r["auto_generated"] is False


def test_tool_template_summary(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        agent.start_session("alpha")
        out = tools.tool_template_summary(agent)
    assert "summary" in out
    assert "alpha" in out["summary"]


# ── session introspection ────────────────────────────────────────────────────


def test_tool_current_session(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        agent.start_session("mcp-abc")
        out = tools.tool_current_session(agent)
    assert out["agent"] == "t"
    assert out["session_id"] == "mcp-abc"
    assert "memory" in out["capabilities"]


def test_tool_current_session_no_active(tmp_path: Path) -> None:
    with make_agent(tmp_path) as agent:
        out = tools.tool_current_session(agent)
    assert out["session_id"] is None


# ── capability gating flows through ──────────────────────────────────────────


def test_tool_remember_raises_when_memory_disabled(tmp_path: Path) -> None:
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            name: t
            capabilities:
              - decisions
            """
        ).lstrip(),
        encoding="utf-8",
    )
    with (
        Agent.from_config(cfg) as agent,
        pytest.raises(RuntimeError, match="'memory' is not enabled"),
    ):
        tools.tool_remember(agent, "x")
