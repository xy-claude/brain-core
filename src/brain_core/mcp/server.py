"""FastMCP server wiring.

The server is one process per agent, spawned by Claude Code via .mcp.json::

    {
      "mcpServers": {
        "brain-core": {
          "command": "brain",
          "args": ["serve", "."]
        }
      }
    }

On startup the server opens the agent, generates a session id, registers
every tool from :mod:`brain_core.mcp.tools`, and runs on stdio.
Shutdown closes the agent cleanly.

This module imports the ``mcp`` package at module load; if the mcp extra
is not installed the import fails with a useful message. Callers invoking
the server from the CLI should handle ImportError upstream (see
``brain serve`` in :mod:`brain_core.cli.main`).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from brain_core.agent import Agent
from brain_core.decisions.classifier import Confidence, Risk, Status
from brain_core.mcp import tools
from brain_core.memory.structured import FactKind

_SESSION_PREFIX = "mcp-"


def build_server(agent: Agent) -> FastMCP:
    """Register all brain-core tools on a FastMCP instance.

    The returned server is ready to ``.run()``. Exposed for testing.
    """
    server = FastMCP(name=f"brain-core:{agent.name}")

    @server.tool()
    def remember(
        content: str,
        kind: FactKind = "fact",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store a fact. Idempotent on normalized content."""
        return tools.tool_remember(agent, content, kind, tags, metadata)

    @server.tool()
    def recall(
        query: str | None = None,
        kind: FactKind | None = None,
        limit: int = 10,
        include_superseded: bool = False,
    ) -> list[dict[str, Any]]:
        """Retrieve facts. FTS5-ranked if query given, else newest-first."""
        return tools.tool_recall(agent, query, kind, limit, include_superseded)

    @server.tool()
    def supersede(
        old_fact_id: int,
        new_content: str,
        kind: FactKind = "fact",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Replace an old fact; old keeps a pointer to the new one."""
        return tools.tool_supersede(agent, old_fact_id, new_content, kind, tags, metadata)

    @server.tool()
    def log_event(
        event_type: str,
        payload: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Append an event to the episodic log."""
        return tools.tool_log_event(agent, event_type, payload, session_id)

    @server.tool()
    def recent_events(
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch recent events, newest first."""
        return tools.tool_recent_events(agent, session_id, event_type, limit)

    @server.tool()
    def append_today(text: str) -> dict[str, Any]:
        """Append text to today's HSAM markdown archive."""
        return tools.tool_append_today(agent, text)

    @server.tool()
    def decide(
        action: str,
        reversible: bool,
        risk: Risk = "medium",
        confidence: Confidence = "medium",
        reasoning: str | None = None,
        alternatives: list[str] | None = None,
    ) -> dict[str, Any]:
        """Log a new decision in status 'active'."""
        return tools.tool_decide(
            agent, action, reversible, risk, confidence, reasoning, alternatives
        )

    @server.tool()
    def reverse(
        decision_id: int,
        replaced_by: int | None = None,
    ) -> dict[str, Any]:
        """Mark a decision reversed."""
        return tools.tool_reverse(agent, decision_id, replaced_by)

    @server.tool()
    def complete(decision_id: int) -> dict[str, Any]:
        """Mark a decision completed."""
        return tools.tool_complete(agent, decision_id)

    @server.tool()
    def list_decisions(
        status: Status | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List decisions, newest first."""
        return tools.tool_list_decisions(agent, status, limit)

    @server.tool()
    def gather_context(
        session_id: str | None = None,
        event_limit: int = 20,
        decision_limit: int = 20,
    ) -> dict[str, Any]:
        """Assemble structured reflection context for a session."""
        return tools.tool_gather_context(agent, session_id, event_limit, decision_limit)

    @server.tool()
    def save_reflection(
        session_id: str | None = None,
        what_went_well: str | None = None,
        what_to_improve: str | None = None,
        apply_next_session: str | None = None,
        auto_generated: bool = False,
    ) -> dict[str, Any]:
        """Persist a reflection."""
        return tools.tool_save_reflection(
            agent,
            session_id,
            what_went_well,
            what_to_improve,
            apply_next_session,
            auto_generated,
        )

    @server.tool()
    def template_summary(session_id: str | None = None) -> dict[str, str]:
        """Deterministic template-only summary (zero LLM)."""
        return tools.tool_template_summary(agent, session_id)

    @server.tool()
    def current_session() -> dict[str, Any]:
        """Report the active session id, agent name, enabled capabilities."""
        return tools.tool_current_session(agent)

    return server


def run_server(config_path: Path) -> None:
    """Entry point for ``brain serve``.

    Loads the agent, assigns a session id for the server's lifetime,
    builds + runs the FastMCP server on stdio. Closes the agent on exit.
    """
    agent = Agent.from_config(config_path)
    session_id = f"{_SESSION_PREFIX}{uuid.uuid4().hex[:12]}"
    agent.start_session(session_id)
    try:
        server = build_server(agent)
        server.run()  # stdio by default
    finally:
        agent.close()
