"""CLI tests via typer's CliRunner."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from brain_core import __version__
from brain_core.cli.main import app

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


def test_init_force_overwrites_rules_but_keeps_the_vault(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "one", "--path", str(tmp_path)])
    facts = tmp_path / "vault" / "facts.md"
    facts.write_text(facts.read_text() + "\n- the one fact that must survive (2026-11-02)\n")
    result = runner.invoke(app, ["init", "two", "--path", str(tmp_path), "--force"])
    assert result.exit_code == 0
    assert "name: two" in (tmp_path / "brain.yaml").read_text()
    assert "the one fact that must survive" in facts.read_text()


def test_init_rejects_empty_name(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "   ", "--path", str(tmp_path)])
    assert result.exit_code == 1


# ── doctor ───────────────────────────────────────────────────────────────────


def test_doctor_on_fresh_agent(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "my-bot", "--path", str(tmp_path)])
    result = runner.invoke(app, ["doctor", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "my-bot" in result.stdout
    assert "store vault" in result.stdout and "Brain:" in result.stdout


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
    assert "Brain:" in result.stdout


def test_init_writes_the_whole_pack_with_user_and_profile(tmp_path: Path) -> None:
    prof = tmp_path / "profile" / ".claude" / "rules"
    prof.mkdir(parents=True)
    (prof / "06-mine.md").write_text("# my doctrine\n")
    out = tmp_path / "agent"
    result = runner.invoke(
        app,
        [
            "init",
            "Atlas",
            "--path",
            str(out),
            "--user",
            "Ada",
            "--profile",
            str(tmp_path / "profile"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    rules = sorted(p.name for p in (out / ".claude" / "rules").iterdir())
    assert rules == [
        "01-identity.md",
        "02-doctrine.md",
        "03-authority.md",
        "04-memory.md",
        "05-system.md",
        "06-mine.md",
    ]
    assert sorted(p.name for p in (out / ".claude" / "skills").iterdir()) == [
        "brain-check",
        "distill",
        "session-end",
    ]
    hook = out / ".claude" / "hooks" / "block-dangerous-bash.sh"
    assert hook.stat().st_mode & 0o111, "hook must be executable"
    assert "$CMD" in hook.read_text(), "shell variables untouched by substitution"
    assert "bank: atlas-brain" in (out / "brain.yaml").read_text()
    md = (out / "CLAUDE.md").read_text()
    assert md.startswith("# Atlas") and "Ada's operating intelligence" in md and "$" not in md
    assert "Address the user as **Ada**" in (out / "vault" / "user_profile.md").read_text()
    assert "atlas-brain" in (out / ".mcp.json").read_text()
    for f in (
        "executive_state.md",
        "facts.md",
        "patterns.md",
        "decisions_log.md",
        "knowledge/_index.md",
    ):
        assert (out / "vault" / f).exists(), f
    assert (out / "data" / ".gitkeep").exists()


# ── daily / weekly / cron / serve / hindsight wiring ─────────────────────────


def test_init_rejects_a_name_that_is_not_a_safe_identifier(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "a/b", "--path", str(tmp_path)])
    assert result.exit_code == 1 and not (tmp_path / "brain.yaml").exists()


def test_daily_and_weekly_print_the_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner.invoke(app, ["init", "bot", "--path", str(tmp_path)])
    monkeypatch.setattr(
        "brain_core.cron.daily",
        lambda agent: {"brief": "b.md", "brief_tokens": 12, "health": "h", "backup": "skipped"},
    )
    monkeypatch.setattr(
        "brain_core.cron.weekly", lambda agent: {"archived": {}, "mental_models": {"m": "ok"}}
    )
    out = runner.invoke(app, ["daily", str(tmp_path)])
    assert out.exit_code == 0 and "brief: b.md (~12 tokens)" in out.stdout
    out = runner.invoke(app, ["weekly", str(tmp_path)])
    assert out.exit_code == 0 and "archived: nothing" in out.stdout


def test_cron_install_status_uninstall_via_cli(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "bot", "--path", str(tmp_path)])
    la = str(tmp_path / "la")
    out = runner.invoke(app, ["cron", "install", str(tmp_path), "--launch-dir", la, "--no-load"])
    assert out.exit_code == 0 and out.stdout.count("wrote") == 2
    out = runner.invoke(app, ["cron", "status", str(tmp_path), "--launch-dir", la])
    assert "daily: installed" in out.stdout
    out = runner.invoke(app, ["cron", "bogus", str(tmp_path)])
    assert out.exit_code == 1


def test_serve_needs_a_config_then_runs_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runner.invoke(app, ["serve", str(tmp_path)]).exit_code == 1
    runner.invoke(app, ["init", "bot", "--path", str(tmp_path)])
    seen: list[Path] = []
    monkeypatch.setattr("brain_core.mcp.server.run_server", lambda p: seen.append(p))
    assert runner.invoke(app, ["serve", str(tmp_path)]).exit_code == 0
    assert seen == [tmp_path / "brain.yaml"]


def test_hindsight_command_reports_and_fails_on_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("brain_core.installer.health", lambda port: False)
    out = runner.invoke(app, ["hindsight", "status"])
    assert "DOWN" in out.stdout
    monkeypatch.setattr(
        "brain_core.installer.install_hindsight",
        lambda **kw: {"api_key": "ANTHROPIC_API_KEY written", "service": "not healthy after 1s"},
    )
    out = runner.invoke(app, ["hindsight", "install", "--dry-run"])
    assert out.exit_code == 1 and "api_key: ANTHROPIC_API_KEY written" in out.stdout


# ── recall / failure hook ────────────────────────────────────────────────────


def test_recall_prints_hits_and_the_failure_hook_adds_context(tmp_path: Path) -> None:
    import json

    from brain_core.stores.transcripts import project_dir

    out = tmp_path / "agent"
    assert runner.invoke(app, ["init", "Atlas", "--path", str(out)]).exit_code == 0
    yaml = out / "brain.yaml"
    yaml.write_text(
        yaml.read_text().replace("transcripts: ~/.claude/projects", f"transcripts: {tmp_path}/p")
    )
    folder = project_dir(tmp_path / "p", out)
    folder.mkdir(parents=True)
    line = {
        "type": "user",
        "uuid": "u1",
        "sessionId": "old-session",
        "timestamp": "2026-10-03T10:00:00Z",
        "message": {"content": "ModuleNotFoundError: No module named mcp, fixed by uv sync"},
    }
    (folder / "old-session.jsonl").write_text(json.dumps(line) + "\n")

    r = runner.invoke(
        app, ["recall", "ModuleNotFoundError mcp", "--scope", "transcripts", "--path", str(out)]
    )
    assert r.exit_code == 0 and r.stdout.startswith("[transcript] 2026-10-03 transcript://old-")
    assert runner.invoke(app, ["recall", "", "--path", str(out)]).exit_code == 1

    payload = {"session_id": "new-session", "error": "Exit code 1\nModuleNotFoundError: mcp"}
    r = runner.invoke(app, ["recall", "--hook", "--path", str(out)], input=json.dumps(payload))
    assert r.exit_code == 0, r.stdout
    ctx = json.loads(r.stdout)["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PostToolUseFailure"
    assert "fixed by uv sync" in ctx["additionalContext"]
    # the error that just happened is not its own precedent; no history means no output
    payload["session_id"] = "old-session"
    r = runner.invoke(app, ["recall", "--hook", "--path", str(out)], input=json.dumps(payload))
    assert r.exit_code == 0 and r.stdout == ""
    r = runner.invoke(app, ["recall", "--hook", "--path", str(out)], input='{"error": ""}')
    assert r.exit_code == 0 and r.stdout == ""


# ── index ────────────────────────────────────────────────────────────────────


def test_index_loads_vault_facts_into_sqlite_with_their_date(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "bot", "--path", str(tmp_path)])
    facts = tmp_path / "vault" / "facts.md"
    facts.write_text(facts.read_text() + "\n- an old fact from the vault (2026-04-01)\n")

    result = runner.invoke(app, ["index", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "0 already there" in result.stdout

    from brain_core.agent import Agent

    with Agent.from_config(tmp_path / "brain.yaml") as agent:
        row = agent.db.fetchone("SELECT created_at FROM facts WHERE content LIKE 'an old fact%'")
        assert row is not None and row["created_at"].startswith("2026-04-01")
        hit = agent.brain_recall("old fact from the vault", scope="sqlite")["results"][0]
        assert hit["source"].startswith("facts.md:")  # cites the vault line, not a row id

    again = runner.invoke(app, ["index", str(tmp_path)])
    assert "0 new" in again.stdout
