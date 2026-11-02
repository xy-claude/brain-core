"""MCP server wiring: exactly the five brain_* tools, and one round trip through FastMCP."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, cast

import pytest

from brain_core import Agent
from brain_core.mcp.server import build_server

_EXPECTED_TOOLS = {
    "brain_recall",
    "brain_remember",
    "brain_session",
    "brain_distill",
    "brain_status",
}


@pytest.fixture
def agent(tmp_path: Path) -> Agent:
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(textwrap.dedent("name: mcp-test\n"), encoding="utf-8")
    return Agent.from_config(cfg)


@pytest.mark.asyncio
async def test_server_registers_only_the_five_brain_tools(agent: Agent) -> None:
    try:
        names = {t.name for t in await build_server(agent).list_tools()}
        assert names == _EXPECTED_TOOLS, (
            f"missing: {_EXPECTED_TOOLS - names}, extra: {names - _EXPECTED_TOOLS}"
        )
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_server_remember_then_recall_round_trip(agent: Agent) -> None:
    try:
        server = build_server(agent)
        w = await server.call_tool(
            "brain_remember", {"text": "tested via MCP on port 8888", "kind": "fact"}
        )
        structured = cast(dict[str, Any], w[1] if isinstance(w, tuple) else w)
        assert (
            structured["status"] == "written"
            and structured["layers"]["sqlite"]["status"] == "written"
        )
        r = await server.call_tool("brain_recall", {"query": "tested MCP 8888"})
        structured = cast(dict[str, Any], r[1] if isinstance(r, tuple) else r)
        assert structured["results"][0]["text"] == "tested via MCP on port 8888"
        s = await server.call_tool("brain_status", {})
        structured = cast(dict[str, Any], s[1] if isinstance(s, tuple) else s)
        assert structured["stores"]["sqlite"]["ok"] is True
        assert "mcp-test" in server.name
        # every call left one metrics row: runtime, response tokens, error flag
        per = structured["tools"]["per_tool"]
        assert per["brain_remember"]["calls"] == 1 and per["brain_recall"]["errors"] == 0
        assert per["brain_recall"]["avg_tokens"] > 0
        with pytest.raises(Exception, match="scope must be"):  # the transport turns it into text
            await server.call_tool("brain_recall", {"query": "x", "scope": "nope"})
        rows = agent.db.fetchall("SELECT tags FROM metrics WHERE metric_name = 'tool.brain_recall'")
        assert [json.loads(r["tags"])["error"] for r in rows] == [0, 1]
    finally:
        agent.close()
