"""brain daily / weekly / cron install on a freshly initialised agent."""

from __future__ import annotations

import plistlib
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from brain_core import Agent, cron
from brain_core.cli.init import init_agent
from brain_core.stores.hindsight import HindsightStore

TODAY = date(2026, 11, 2)


class FakeHindsight(HindsightStore):
    def __init__(self) -> None:
        super().__init__("http://127.0.0.1:1", "t", "T")
        self.refreshed: list[str] = []

    def call(self, tool: str, **args: Any) -> Any:
        if tool == "refresh_mental_model":
            self.refreshed.append(args["mental_model_id"])
            return {"status": "ok"}
        if tool == "recall":
            return {"results": []}
        raise AssertionError(tool)

    def health(self) -> tuple[bool, str]:
        return (True, "fake")


def make(tmp_path: Path) -> Agent:
    init_agent("Atlas", tmp_path / "atlas", False, user="Ada")
    vault = tmp_path / "atlas" / "vault"
    corr = "\n".join(
        f"### [{d}] {t}\n- **Error:** e\n- **Correction:** c\n- **Implied rule:** r\n"
        f"- **Theme:** {th}\n- **Promoted:** No\n"
        for d, t, th in (
            ("2026-11-01", "Claimed done without output", "verification"),
            ("2026-10-30", "Pushed without approval", "authority"),
            ("2026-10-28", "Eyeballed a layout", "verification"),
            ("2026-10-25", "Trusted a green test", "verification"),
            ("2026-09-01", "Ancient one", "verification"),
        )
    )
    (vault / "corrections.md").write_text(
        "---\ntype: log\n---\n# Corrections\n\n## Corrections\n\n" + corr
    )
    (vault / "session_critique.md").write_text(
        "---\ntype: log\n---\n# Session Critique\n\n## What Went Well\n- x\n\n"
        "## Apply Next Session\n- wait for CI before calling a push done\n"
    )
    (vault / "knowledge" / "old-page.md").write_text(
        "---\nupdated: 2026-09-01\nsources: [raw/x.md]\n---\n# Old\n"
    )
    (vault / "knowledge" / "_index.md").write_text("| [[old-page]] | | | |\n")
    (vault / "sessions" / "2026-09-20.md").write_text(
        "---\ntype: session\n---\n# Session Archive — 2026-09-20\n\n"
        "## What We Discussed\n- ancient topic\n"
    )
    (vault / "sessions" / "2026-11-01.md").write_text(
        "---\ntype: session\n---\n# Session Archive — 2026-11-01\n\n"
        "## What We Discussed\n- fresh topic\n"
    )
    agent = Agent.from_config(tmp_path / "atlas" / "brain.yaml")
    agent.stores[:] = [s for s in agent.stores if not isinstance(s, HindsightStore)] + [
        FakeHindsight()
    ]
    return agent


def test_daily_writes_brief_health_and_skips_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cron, "_admin", lambda: None)
    agent = make(tmp_path)
    with agent:
        out = cron.daily(agent, TODAY)
    brief = Path(out["brief"]).read_text()
    assert brief.startswith("# Daily Brief — 2026-11-02")
    assert "- M-001 · first mission · P1" in brief
    assert "[2026-11-01] Claimed done without output" in brief and "Ancient one" not in brief
    assert "theme `verification` has 3 corrections → promote to a rule?" in brief
    assert "wait for CI before calling a push done" in brief
    assert "## Executive State" in brief and "## Primary Objective" in brief
    assert "- Stores: sqlite OK, vault OK, graph OK, hindsight OK" in brief
    assert "old-page.md (62d) → `/distill --refresh old-page`" in brief
    assert "### 2026-11-01\n#### Session Archive — 2026-11-01" in brief and "fresh topic" in brief
    assert out["backup"].startswith("skipped")
    log = (tmp_path / "atlas" / "vault" / "health_log.md").read_text()
    assert "- 2026-11-02 ok=True stores=4/4 lint=0 context=" in log


def test_weekly_archives_old_sessions_and_refreshes_models(tmp_path: Path) -> None:
    agent = make(tmp_path)
    with agent:
        out = cron.weekly(agent, TODAY)
    assert out["archived"] == {"2026-09": 1} and out["mental_models"] == {
        "active-priorities": "refreshed"
    }
    sessions = tmp_path / "atlas" / "vault" / "sessions"
    assert (
        not (sessions / "2026-09-20.md").exists()
        and (sessions / "archive" / "2026-09" / "2026-09-20.md").exists()
    )
    assert (sessions / "2026-11-01.md").exists(), "recent file stays"
    summary = (sessions / "archive" / "2026-09.md").read_text()
    assert summary.startswith("# 2026-09 — 1 session files") and "- ancient topic" in summary


def test_cron_install_writes_launchd_plists(tmp_path: Path) -> None:
    agent = make(tmp_path)
    with agent:
        paths = cron.install(agent, launch_dir=tmp_path / "la", load=False)
    assert [Path(p).name for p in paths] == [
        "io.brain-core.atlas.daily.plist",
        "io.brain-core.atlas.weekly.plist",
    ]
    daily = plistlib.loads(Path(paths[0]).read_bytes())
    weekly = plistlib.loads(Path(paths[1]).read_bytes())
    assert daily["ProgramArguments"][1:] == ["daily", str(tmp_path / "atlas")]
    assert daily["StartCalendarInterval"] == {"Hour": 6, "Minute": 7}
    assert weekly["StartCalendarInterval"] == {"Weekday": 0, "Hour": 7, "Minute": 13}
    assert daily["StandardOutPath"].endswith("data/logs/daily.log")


def test_cron_lines_and_crontab_merge(tmp_path: Path) -> None:
    lines = cron.cron_lines(tmp_path / "a", "/usr/local/bin/brain", "Atlas", "06:07", "Sun 07:13")
    assert lines[0].startswith(f"7 6 * * * /usr/local/bin/brain daily {tmp_path / 'a'}")
    assert lines[1].startswith(f"13 7 * * 0 /usr/local/bin/brain weekly {tmp_path / 'a'}")
    assert all("# brain-core atlas" in ln for ln in lines)
    current = "0 3 * * * backup.sh\n7 6 * * * old brain daily x # brain-core atlas daily\n"
    merged = cron._crontab_merge(current, "Atlas", lines)
    assert merged.splitlines()[0] == "0 3 * * * backup.sh" and "old brain" not in merged
    assert merged.count("# brain-core atlas") == 2
    assert cron._crontab_merge(merged, "Atlas", []) == "0 3 * * * backup.sh\n"


def test_daily_survives_a_typo_date_in_corrections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cron, "_admin", lambda: None)
    agent = make(tmp_path)
    corr = tmp_path / "atlas" / "vault" / "corrections.md"
    corr.write_text(corr.read_text() + "\n### [2026-13-01] Typed by hand\n- **Theme:** x\n")
    with agent:
        out = cron.daily(agent, TODAY)
    assert "[2026-11-01] Claimed done without output" in Path(out["brief"]).read_text()
