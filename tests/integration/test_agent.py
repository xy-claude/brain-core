"""Agent integration tests — end-to-end via the high-level API."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from brain_core import Agent, BrainConfig
from brain_core.storage import Database, migrate


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
