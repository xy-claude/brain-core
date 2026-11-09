"""brain desktop: one entry in the Claude desktop app's MCP config, nothing else touched."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brain_core import desktop
from brain_core.cli.main import app


def test_connect_adds_keeps_other_keys_backs_up_and_is_idempotent(tmp_path: Path) -> None:
    cfg = tmp_path / "Claude" / desktop.CONFIG_NAME
    cfg.parent.mkdir()
    cfg.write_text('{"preferences": {"theme": "dark"}, "mcpServers": {"other": {"command": "x"}}}')
    agent = tmp_path / "Atlas"
    assert desktop.connect(agent, cfg, "/b/brain").startswith("added")
    data = json.loads(cfg.read_text())
    assert data["preferences"] == {"theme": "dark"} and data["mcpServers"]["other"] == {
        "command": "x"
    }
    assert data["mcpServers"]["brain"] == {
        "command": "/b/brain",
        "args": ["serve", str(agent.resolve())],
    }
    assert "brain" not in json.loads(cfg.with_name(cfg.name + ".bak").read_text())["mcpServers"]
    assert desktop.connect(agent, cfg, "/b/brain").startswith("already connected")
    assert desktop.connect(tmp_path / "Other", cfg, "/b/brain").startswith("updated")
    assert "brain" not in json.loads(cfg.with_name(cfg.name + ".bak").read_text())["mcpServers"]


def test_connect_creates_a_missing_file_and_reads_one_with_a_bom(tmp_path: Path) -> None:
    cfg = tmp_path / "new" / desktop.CONFIG_NAME
    assert desktop.connect(tmp_path, cfg, "/b/brain").startswith("added")
    assert not cfg.with_name(cfg.name + ".bak").exists(), "nothing existed to back up"
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + b'{"a": 1}')  # PowerShell 5.1 writes UTF-8 with a BOM
    assert desktop.connect(tmp_path, bom, "/b/brain").startswith("added")
    assert json.loads(bom.read_text())["a"] == 1


@pytest.mark.parametrize("body", ["{not json", "[1, 2]", '{"mcpServers": []}'])
def test_connect_leaves_a_file_it_cannot_read_alone(tmp_path: Path, body: str) -> None:
    cfg = tmp_path / desktop.CONFIG_NAME
    cfg.write_text(body)
    assert desktop.connect(tmp_path, cfg, "/b/brain").startswith("left alone")
    assert cfg.read_text() == body


def test_config_paths_per_platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("brain_core.desktop.sys.platform", "darwin")
    mac = tmp_path / "Library" / "Application Support" / "Claude" / desktop.CONFIG_NAME
    assert desktop.config_paths(tmp_path) == [mac]
    monkeypatch.setattr("brain_core.desktop.sys.platform", "linux")
    assert desktop.config_paths(tmp_path) == []
    monkeypatch.setattr("brain_core.desktop.sys.platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    store = tmp_path / "Local" / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
    store.mkdir(parents=True)
    assert desktop.config_paths(tmp_path) == [
        tmp_path / "Roaming" / "Claude" / desktop.CONFIG_NAME,
        store / desktop.CONFIG_NAME,
    ]


def test_cli_connects_an_agent_and_refuses_a_folder_without_one(tmp_path: Path) -> None:
    runner = CliRunner()
    cfg = tmp_path / desktop.CONFIG_NAME
    r = runner.invoke(app, ["desktop", str(tmp_path), "--config", str(cfg)])
    assert r.exit_code == 1 and "no brain.yaml" in r.output
    agent = tmp_path / "agent"
    assert runner.invoke(app, ["init", "Atlas", "--path", str(agent), "--lite"]).exit_code == 0
    r = runner.invoke(app, ["desktop", str(agent), "--config", str(cfg)])
    assert r.exit_code == 0 and "added" in r.output and "reopen" in r.output
    assert json.loads(cfg.read_text())["mcpServers"]["brain"]["args"] == [
        "serve",
        str(agent.resolve()),
    ]
