"""Agent integration tests — end-to-end via the high-level API."""

from __future__ import annotations

import textwrap
from datetime import date as Date
from pathlib import Path

import pytest

from central_brain import Agent, BrainConfig
from central_brain.storage import Database, migrate


def write_config(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return cfg


# ── construction ─────────────────────────────────────────────────────────────


def test_from_config_creates_data_dir_and_db(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: test-agent\n")
    with Agent.from_config(cfg) as agent:
        assert agent.name == "test-agent"
        assert agent.data_dir == tmp_path / "data"
        assert (tmp_path / "data" / "brain.db").exists()


def test_from_config_resolves_relative_paths(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path,
        """
        name: x
        workspace:
          data_dir: ./alt
        """,
    )
    with Agent.from_config(cfg) as agent:
        assert agent.data_dir == tmp_path / "alt"
        assert (tmp_path / "alt" / "brain.db").exists()


# ── memory delegation ────────────────────────────────────────────────────────


def test_agent_memory_round_trip(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with Agent.from_config(cfg) as agent:
        fact = agent.remember("Sir prefers dark mode", kind="preference")
        assert fact.id > 0
        [hit] = agent.recall(query="dark mode")
        assert hit.id == fact.id


def test_agent_log_event_uses_current_session(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with Agent.from_config(cfg) as agent:
        agent.start_session("s1")
        ev = agent.log_event(event_type="user_message", payload={"text": "hi"})
        assert ev.session_id == "s1"


def test_agent_log_event_explicit_session_overrides(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with Agent.from_config(cfg) as agent:
        agent.start_session("default")
        ev = agent.log_event(event_type="e", session_id="override")
        assert ev.session_id == "override"


def test_agent_append_today_writes_hsam(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with Agent.from_config(cfg) as agent:
        day = agent.append_today("hello world", today=Date(2026, 4, 20))
        assert day.archive_path == "hsam/2026-04-20.md"
        assert (tmp_path / "data" / "hsam" / "2026-04-20.md").exists()


def test_agent_append_today_respects_hsam_disabled(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path,
        """
        name: x
        memory:
          hsam:
            enabled: false
        """,
    )
    with Agent.from_config(cfg) as agent, pytest.raises(RuntimeError, match="HSAM is disabled"):
        agent.append_today("anything")


def test_agent_append_today_custom_subdir(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path,
        """
        name: x
        memory:
          hsam:
            subdir: journal
        """,
    )
    with Agent.from_config(cfg) as agent:
        agent.append_today("entry", today=Date(2026, 4, 20))
        assert (tmp_path / "data" / "journal" / "2026-04-20.md").exists()


# ── decisions delegation ─────────────────────────────────────────────────────


def test_agent_decide_and_complete(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with Agent.from_config(cfg) as agent:
        d = agent.decide(action="deploy", reversible=True, risk="medium")
        done = agent.complete(d.id)
        assert done.status == "completed"


def test_agent_reverse_with_replacement(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with Agent.from_config(cfg) as agent:
        old = agent.decide(action="old", reversible=True)
        new = agent.decide(action="new", reversible=True)
        reversed_old = agent.reverse(old.id, replaced_by=new.id)
        assert reversed_old.status == "reversed"
        assert reversed_old.reversed_by == new.id


def test_agent_list_decisions_filter(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with Agent.from_config(cfg) as agent:
        a = agent.decide(action="a", reversible=True)
        agent.decide(action="b", reversible=True)
        agent.reverse(a.id)
        assert len(agent.list_decisions(status="reversed")) == 1
        assert len(agent.list_decisions(status="active")) == 1


# ── reflection delegation ────────────────────────────────────────────────────


def test_agent_gather_context_uses_current_session(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with Agent.from_config(cfg) as agent:
        agent.start_session("s1")
        agent.log_event(event_type="user_message")
        agent.log_event(event_type="tool_call")
        ctx = agent.gather_context()
        assert ctx.session_id == "s1"
        assert len(ctx.events) == 2


def test_agent_gather_context_requires_session(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with (
        Agent.from_config(cfg) as agent,
        pytest.raises(RuntimeError, match="no active session"),
    ):
        agent.gather_context()


def test_agent_save_reflection_round_trip(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with Agent.from_config(cfg) as agent:
        agent.start_session("s1")
        r = agent.save_reflection(
            what_went_well="clean milestone",
            apply_next_session="keep the scope tight",
        )
        assert r.session_id == "s1"
        assert r.what_went_well == "clean milestone"


def test_agent_template_summary_contains_session_id(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with Agent.from_config(cfg) as agent:
        agent.start_session("alpha")
        summary = agent.template_summary()
        assert "alpha" in summary


# ── capability gating ────────────────────────────────────────────────────────


def test_disabled_memory_blocks_remember(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path,
        """
        name: x
        capabilities:
          - decisions
        """,
    )
    with (
        Agent.from_config(cfg) as agent,
        pytest.raises(RuntimeError, match="'memory' is not enabled"),
    ):
        agent.remember("x")


def test_disabled_decisions_blocks_decide(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path,
        """
        name: x
        capabilities:
          - memory
        """,
    )
    with (
        Agent.from_config(cfg) as agent,
        pytest.raises(RuntimeError, match="'decisions' is not enabled"),
    ):
        agent.decide(action="x", reversible=True)


def test_disabled_reflection_blocks_gather(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path,
        """
        name: x
        capabilities:
          - memory
        """,
    )
    with Agent.from_config(cfg) as agent:
        agent.start_session("s1")
        with pytest.raises(RuntimeError, match="'reflection' is not enabled"):
            agent.gather_context()


# ── lifecycle + session ──────────────────────────────────────────────────────


def test_session_state_transitions(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with Agent.from_config(cfg) as agent:
        assert agent.current_session is None
        agent.start_session("s1")
        assert agent.current_session == "s1"
        agent.end_session()
        assert agent.current_session is None


def test_start_session_rejects_empty(tmp_path: Path) -> None:
    cfg = write_config(tmp_path, "name: x\n")
    with (
        Agent.from_config(cfg) as agent,
        pytest.raises(ValueError, match="session_id must not be empty"),
    ):
        agent.start_session("  ")


def test_agent_direct_construction(tmp_path: Path) -> None:
    """__init__ can be called directly for tests — no yaml required."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = Database.connect(data_dir / "brain.db")
    migrate(db)
    config = BrainConfig(name="direct")
    agent = Agent(config=config, db=db, data_dir=data_dir)
    try:
        assert agent.name == "direct"
    finally:
        agent.close()
