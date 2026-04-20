"""CLI tests via typer's CliRunner."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from central_brain import __version__
from central_brain.cli.main import app

runner = CliRunner()


# ── version ──────────────────────────────────────────────────────────────────


def test_version_prints_semver() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


# ── init ─────────────────────────────────────────────────────────────────────


def test_init_scaffolds_agent(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "test-bot", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.stdout

    assert (tmp_path / "brain.yaml").exists()
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / ".mcp.json").exists()
    assert (tmp_path / ".gitignore").exists()
    assert (tmp_path / "data").is_dir()

    yaml_body = (tmp_path / "brain.yaml").read_text()
    assert "name: test-bot" in yaml_body

    md_body = (tmp_path / "CLAUDE.md").read_text()
    assert md_body.startswith("# test-bot")


def test_init_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    # First pass succeeds
    first = runner.invoke(app, ["init", "one", "--path", str(tmp_path)])
    assert first.exit_code == 0

    # Second without --force fails
    second = runner.invoke(app, ["init", "two", "--path", str(tmp_path)])
    assert second.exit_code == 1
    assert "already exist" in second.stdout or "already exist" in (second.stderr or "")


def test_init_force_overwrites(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "one", "--path", str(tmp_path)])
    result = runner.invoke(app, ["init", "two", "--path", str(tmp_path), "--force"])
    assert result.exit_code == 0
    assert "name: two" in (tmp_path / "brain.yaml").read_text()


def test_init_rejects_empty_name(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "   ", "--path", str(tmp_path)])
    assert result.exit_code == 1


# ── doctor ───────────────────────────────────────────────────────────────────


def test_doctor_on_fresh_agent(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "my-bot", "--path", str(tmp_path)])
    result = runner.invoke(app, ["doctor", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "my-bot" in result.stdout
    assert "facts" in result.stdout
    assert "decisions" in result.stdout
    assert "Health check: OK" in result.stdout


def test_doctor_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", str(tmp_path)])
    assert result.exit_code == 1


def test_doctor_invalid_config(tmp_path: Path) -> None:
    (tmp_path / "brain.yaml").write_text("garbage: ~\n", encoding="utf-8")
    result = runner.invoke(app, ["doctor", str(tmp_path)])
    assert result.exit_code == 1


def test_doctor_reports_hsam_when_enabled(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "my-bot", "--path", str(tmp_path)])
    result = runner.invoke(app, ["doctor", str(tmp_path)])
    assert "HSAM" in result.stdout


# ── export ───────────────────────────────────────────────────────────────────


def test_export_empty_agent(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "my-bot", "--path", str(tmp_path)])
    result = runner.invoke(app, ["export", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "# my-bot" in result.stdout
    assert "No facts" in result.stdout
    assert "No decisions" in result.stdout
    assert "No events" in result.stdout


def test_export_with_data(tmp_path: Path) -> None:
    # Scaffold
    runner.invoke(app, ["init", "my-bot", "--path", str(tmp_path)])

    # Write some state directly via Agent API (faster than running a full flow)
    from central_brain import Agent

    with Agent.from_config(tmp_path / "brain.yaml") as agent:
        agent.remember("Sir prefers dark mode", kind="preference", tags=["ui"])
        agent.remember("deploys on Tuesday", kind="constraint")
        d = agent.decide(action="ship it", reversible=True, reasoning="tests green")
        agent.complete(d.id)
        agent.start_session("s-1")
        agent.log_event(event_type="user_message", payload={"text": "hi"})

    result = runner.invoke(app, ["export", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "Sir prefers dark mode" in out
    assert "ship it" in out
    assert "user_message" in out
    assert "[completed]" in out
    assert "preference" in out  # section header for fact kind


def test_export_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["export", str(tmp_path)])
    assert result.exit_code == 1
