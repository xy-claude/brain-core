"""brain adopt: an existing agent folder gets brain.yaml, MCP entry, hooks, rule and index."""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from brain_core.agent import Agent
from brain_core.cli.main import app

runner = CliRunner()


def test_adopt_is_additive_and_idempotent(tmp_path: Path) -> None:
    agent_dir = tmp_path / "Atlas"
    (agent_dir / ".claude").mkdir(parents=True)
    (agent_dir / "CLAUDE.md").write_text("# Atlas\n")
    (agent_dir / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"url": "x"}}}))
    (agent_dir / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo bye"}]}]}})
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "facts.md").write_text(
        "# Facts\n\n## Sys\n- one fact (2026-10-01)\n- two fact (2026-10-02)\n"
    )

    args = [
        "adopt",
        str(agent_dir),
        "--vault",
        str(vault),
        "--user",
        "Alex",
        "--peers",
        "../*/sync.md",
    ]
    r = runner.invoke(app, args)
    assert r.exit_code == 0, r.stdout
    assert re.search(r"brain\.yaml\s+written", r.stdout) and re.search(
        r"index\s+2 new rows", r.stdout
    )
    servers = json.loads((agent_dir / ".mcp.json").read_text())["mcpServers"]
    assert set(servers) == {"other", "brain"} and servers["brain"]["args"][0] == "serve"
    hooks = json.loads((agent_dir / ".claude" / "settings.json").read_text())["hooks"]
    assert hooks["Stop"][0]["hooks"][0]["command"] == "echo bye"  # existing hook untouched
    assert set(hooks) == {"Stop", "SessionStart", "PreCompact", "PostToolUseFailure"}
    assert "capture --path" in hooks["Stop"][1]["hooks"][0]["command"]
    rule = (agent_dir / ".claude" / "rules" / "04-memory.md").read_text()
    assert rule.startswith("# Atlas — Memory") and "Alex, N items staged" in rule
    assert not (agent_dir / "CLAUDE.md").read_text().startswith("# brain")  # never touched
    with Agent.from_config(agent_dir / "brain.yaml") as agent:
        assert "hindsight" not in {s.name for s in agent.stores}  # no --bank → lite
        assert agent.config.session.peers == ["../*/sync.md"]
        assert agent.brain_recall("two fact")["results"][0]["source"].startswith("facts.md:")

    again = runner.invoke(app, args)
    assert again.exit_code == 0 and "kept" in again.stdout and "0 new rows" in again.stdout
    hooks = json.loads((agent_dir / ".claude" / "settings.json").read_text())["hooks"]
    assert len(hooks["Stop"]) == 2  # no duplicate hook on the second run
