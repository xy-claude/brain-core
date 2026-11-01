"""MCP server wiring tests.

Verifies the FastMCP server registers every expected tool with the
correct name and that call_tool works end-to-end for a representative
sample. We don't spin up the stdio transport — that's for manual /
Claude Code integration testing.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from brain_core import Agent
from brain_core.mcp.server import build_server

_EXPECTED_TOOLS = {
    "brain_recall",
    "remember",
    "recall",
    "supersede",
    "log_event",
    "recent_events",
    "append_today",
    "decide",
    "reverse",
    "complete",
    "list_decisions",
    "gather_context",
    "save_reflection",
    "template_summary",
    "current_session",
}


@pytest.fixture
def agent(tmp_path: Path) -> Agent:
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(textwrap.dedent("name: mcp-test\n"), encoding="utf-8")
    return Agent.from_config(cfg)


@pytest.mark.asyncio
async def test_server_registers_all_expected_tools(agent: Agent) -> None:
    try:
        server = build_server(agent)
        registered = await server.list_tools()
        names = {t.name for t in registered}
        assert names == _EXPECTED_TOOLS, (
            f"missing: {_EXPECTED_TOOLS - names}, unexpected: {names - _EXPECTED_TOOLS}"
        )
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_server_tool_remember_round_trip(agent: Agent) -> None:
    try:
        server = build_server(agent)
        result = await server.call_tool(
            "remember",
            {"content": "tested via MCP", "kind": "fact"},
        )
        # FastMCP returns a tuple: (content_parts, structured_output) on newer versions,
        # or just content_parts on older. Unpack defensively.
        structured = result[1] if isinstance(result, tuple) else result
        assert isinstance(structured, dict)
        assert structured["content"] == "tested via MCP"
        assert structured["kind"] == "fact"
        assert isinstance(structured["id"], int)
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_server_name_includes_agent_name(agent: Agent) -> None:
    try:
        server = build_server(agent)
        assert "mcp-test" in server.name
    finally:
        agent.close()
