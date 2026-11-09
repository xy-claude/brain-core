"""brain daily / weekly / cron install on a freshly initialised agent."""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
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
        if tool == "reflect":
            return {
                "text": "You claim done before the output is pasted.  Three corrections say so."
            }
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
    assert "- Stores: sqlite OK, vault OK, graph OK, transcripts OK, hindsight OK" in brief
    assert "old-page.md (62d) → `/distill --refresh old-page`" in brief
    assert "### 2026-11-01\n#### Session Archive — 2026-11-01" in brief and "fresh topic" in brief
    assert out["backup"].startswith("skipped")
    log = (tmp_path / "atlas" / "vault" / "health_log.md").read_text()
    assert "- 2026-11-02 ok=True stores=5/5 lint=0 context=" in log


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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX paths in launchd plists")
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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX paths in crontab lines")
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


@pytest.mark.skipif(sys.platform == "win32", reason="runs a #!/bin/sh stand-in for hindsight-admin")
def test_backup_keeps_only_the_newest_n(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    admin = tmp_path / "hindsight-admin"
    admin.write_text('#!/bin/sh\n: > "$2"\n')
    admin.chmod(0o755)
    monkeypatch.setattr(cron, "_admin", lambda: str(admin))
    bk = tmp_path / "bk"
    bk.mkdir()
    for i, day in enumerate(("2026-10-28", "2026-10-29", "2026-10-30")):
        p = bk / f"hindsight-{day}.zip"
        p.write_text("old")
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
    agent = make(tmp_path)
    agent.config.cron.backup.dir = str(bk)
    agent.config.cron.backup.keep = 2
    with agent:
        out = cron.backup(agent, TODAY)
    assert out.startswith("ok") or "hindsight-2026-11-02.zip" in out
    assert sorted(p.name for p in bk.glob("*.zip")) == [
        "hindsight-2026-10-30.zip",
        "hindsight-2026-11-02.zip",
    ]


def test_crontab_install_status_uninstall_on_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("brain_core.cron.sys.platform", "linux")
    tab = {"text": "0 3 * * * backup.sh\n"}

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=tab["text"], stderr="")
        if cmd == ["crontab", "-"]:
            tab["text"] = kw["input"]
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr("brain_core.cron.subprocess.run", fake_run)
    agent = make(tmp_path)
    with agent:
        lines = cron.install(agent)
        assert len(lines) == 2 and tab["text"].startswith("0 3 * * * backup.sh\n")
        assert tab["text"].count("# brain-core atlas") == 2
        assert cron.status(agent) == {
            "daily": "installed (crontab)",
            "weekly": "installed (crontab)",
        }
        removed = cron.uninstall(agent)
    assert len(removed) == 2 and tab["text"] == "0 3 * * * backup.sh\n"


def test_task_scheduler_install_status_uninstall_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("brain_core.cron.sys.platform", "win32")
    tasks: dict[str, str] = {}

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        name = cmd[cmd.index("/TN") + 1]
        if cmd[1] == "/Create":
            tasks[name] = cmd[cmd.index("/TR") + 1]
        elif cmd[1] == "/Delete":
            del tasks[name]
        return subprocess.CompletedProcess(cmd, 0 if name in tasks else 1, stdout="", stderr="")

    monkeypatch.setattr("brain_core.cron.subprocess.run", fake_run)
    monkeypatch.setattr("brain_core.cron.shutil.which", lambda _: r"C:\b\brain.exe")
    agent = make(tmp_path)
    with agent:
        names = cron.install(agent)
        assert names == ["brain-core.atlas.daily", "brain-core.atlas.weekly"]
        assert (
            tasks["brain-core.atlas.daily"].startswith('cmd /c ""')
            and ' daily "' in tasks["brain-core.atlas.daily"]
        )
        assert cron.status(agent) == {
            "daily": "installed (Task Scheduler)",
            "weekly": "installed (Task Scheduler)",
        }
        removed = cron.uninstall(agent)
    assert removed == names and tasks == {}


def test_task_scheduler_that_never_answers_is_reported_not_waited_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("brain_core.cron.sys.platform", "win32")
    seen: list[dict[str, Any]] = []

    def hangs(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen.append(kw)
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr("brain_core.cron.subprocess.run", hangs)
    monkeypatch.setattr("brain_core.cron.shutil.which", lambda _: r"C:\b\brain.exe")
    agent = make(tmp_path)
    with (
        agent,
        pytest.raises(RuntimeError, match=r"did not create brain-core\.atlas\.daily: no answer"),
    ):
        cron.install(agent)
    assert seen[0]["stdin"] == subprocess.DEVNULL and seen[0]["timeout"] == 60


def test_schtasks_commands_carry_the_schedule() -> None:
    cmds = cron.schtasks_commands(
        Path(r"C:\Agents\My A"), r"C:\b\brain.exe", "A", "06:07", "Sun 07:13"
    )
    daily, weekly = cmds["brain-core.a.daily"], cmds["brain-core.a.weekly"]
    assert daily[daily.index("/ST") + 1] == "06:07" and "DAILY" in daily
    assert weekly[weekly.index("/D") + 1] == "SUN" and weekly[weekly.index("/ST") + 1] == "07:13"
    # the log path joins with the host separator, so only its ends are pinned here
    assert daily[-1].startswith(
        'cmd /c ""C:\\b\\brain.exe" daily "C:\\Agents\\My A" >> "C:\\Agents\\My A'
    )
    assert daily[-1].endswith('daily.log" 2>&1"')


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX quoting")
def test_cron_lines_quote_a_path_with_a_space() -> None:
    lines = cron.cron_lines(Path("/h/My Agents/a"), "/b/brain", "A", "06:07", "Sun 07:13")
    assert "daily '/h/My Agents/a' >> '/h/My Agents/a/data/logs/daily.log'" in lines[0]


@pytest.mark.skipif(sys.platform == "win32", reason="launchd path calls os.getuid")
def test_launchd_install_and_uninstall_call_launchctl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("brain_core.cron.sys.platform", "darwin")
    calls: list[list[str]] = []
    monkeypatch.setattr("brain_core.cron.subprocess.run", lambda cmd, **kw: calls.append(cmd))
    agent = make(tmp_path)
    la = tmp_path / "la"
    with agent:
        paths = cron.install(agent, launch_dir=la, load=True)
        assert [c[1] for c in calls] == ["bootout", "bootstrap", "bootout", "bootstrap"]
        assert cron.status(agent, la)["daily"].startswith("installed")
        removed = cron.uninstall(agent, la)
    assert removed == paths and not list(la.glob("*.plist"))
    assert [c[1] for c in calls][4:] == ["bootout", "bootout"]


def test_weekly_removes_per_file_locks_left_by_old_versions(tmp_path: Path) -> None:
    agent = make(tmp_path)
    sdir = tmp_path / "atlas" / "vault" / "sessions"
    (sdir / ".2026-09-20.md.lock").write_text("")
    with agent:
        cron.consolidate(sdir, TODAY)
    assert not (sdir / ".2026-09-20.md.lock").exists()


def test_growth_section_names_rules_missions_and_old_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cron, "_admin", lambda: None)
    agent = make(tmp_path)
    vault = tmp_path / "atlas" / "vault"
    corr = vault / "corrections.md"
    corr.write_text(
        corr.read_text().replace(
            "### [2026-10-25] Trusted a green test\n- **Error:** e\n- **Correction:** c\n"
            "- **Implied rule:** r\n- **Theme:** verification\n- **Promoted:** No",
            "### [2026-10-25] Trusted a green test\n- **Error:** e\n- **Correction:** c\n"
            "- **Implied rule:** r\n- **Theme:** verification\n- **Promoted:** Yes",
        )
    )
    (vault / "goals" / "mission_queue.md").write_text(
        "---\ntype: log\n---\n# Mission Queue\n\n"
        "| ID | Mission | Priority | Status | Next step | Last reviewed |\n"
        "|---|---|---|---|---|---|\n"
        "| M-001 | fresh | P1 | active | x | 2026-11-01 |\n"
        "| M-002 | stalled | P2 | blocked | y | 2026-09-01 |\n"
    )
    (vault / "executive_state.md").write_text(
        "---\ntype: log\n---\n# Executive State\n\n## Pending Decisions (Ada)\n"
        "| Decision | Why | Classification |\n|---|---|---|\n"
        "| buy the domain | money | irreversible × low-risk |\n"
    )
    seen = tmp_path / "atlas" / "data" / "pending_seen.json"
    seen.parent.mkdir(parents=True, exist_ok=True)
    seen.write_text(json.dumps({"buy the domain": "2026-10-01", "gone decision": "2026-09-01"}))
    with agent:
        brief = Path(cron.daily(agent, TODAY)["brief"]).read_text()
    growth = brief.split("## Growth")[1].split("\n## ")[0]
    assert "theme `verification` recurred 2× since its rule was promoted on 2026-10-25" in growth
    assert "M-002 stalled (blocked) not reviewed for 62 days" in growth and "M-001" not in growth
    assert "pending decision `buy the domain` has waited 32 days" in growth
    assert json.loads(seen.read_text()) == {"buy the domain": "2026-10-01"}, "gone ones are dropped"


def test_reinforce_lists_decisions_at_the_spaced_intervals(tmp_path: Path) -> None:
    agent = make(tmp_path)
    (tmp_path / "atlas" / "vault" / "decisions_log.md").write_text(
        "# Decisions\n\n## 2026-10-30 — Three days old\n**Decision:** a\n\n"
        "## 2026-10-28 — Five days old\n**Decision:** b\n\n## 2026-10-03 — Thirty days old\n"
    )
    brief = Path(cron.daily(agent, TODAY)["brief"]).read_text()
    assert "## Reinforce" in brief
    assert "- day 3: Three days old (2026-10-30)" in brief
    assert "- day 30: Thirty days old (2026-10-03)" in brief
    assert "Five days old" not in brief


def test_weekly_drafts_a_rule_per_recurring_theme_and_reflects(tmp_path: Path) -> None:
    agent = make(tmp_path)
    agent._stores = [*agent.stores, FakeHindsight()]
    out = cron.weekly(agent, TODAY)
    vault = tmp_path / "atlas" / "vault"
    draft = vault / "procedures" / "_drafts" / "rule-verification.md"
    assert out["rule_drafts"] == [str(draft)]  # authority has 1 correction, verification 4
    body = draft.read_text()
    assert "theme: verification" in body and body.count("\n- ") == 4
    draft.write_text("edited by the agent\n")
    assert cron.weekly(agent, TODAY)["rule_drafts"] == []  # never overwritten
    assert draft.read_text() == "edited by the agent\n"
    assert out["reflection"] == "written"
    refl = (vault / "knowledge" / "_reflections.md").read_text()
    assert "## 2026-11-02" in refl and "You claim done before the output is pasted. Three" in refl
    brief = Path(cron.daily(agent, TODAY)["brief"]).read_text()
    assert (
        "draft rule `rule-verification.md`" in brief and "wrote a reflection on 2026-11-02" in brief
    )


def test_daily_shadow_leaves_the_live_brief_alone_and_reports_missing(tmp_path: Path) -> None:
    import textwrap

    from brain_core.agent import Agent
    from brain_core.cron import daily

    vault = tmp_path / "vault"
    (vault / "sessions").mkdir(parents=True)
    (vault / "corrections.md").write_text(
        f"# Corrections\n\n### [{date.today().isoformat()}] Shipped untested\n"
        "**Rule:** test first\n"
    )
    (vault / "daily_brief.md").write_text(
        "# Daily Brief\n\n## Hot Corrections — Apply These NOW\n- a\n\n"
        "## Cron Highlights — Items\n- b\n"
    )
    (tmp_path / "brain.yaml").write_text(textwrap.dedent(f"name: T\nstores:\n  vault: {vault}\n"))
    with Agent.from_config(tmp_path / "brain.yaml") as agent:
        out = daily(agent, shadow=True)
    assert (vault / "daily_brief.shadow.md").exists()
    assert "Cron Highlights" in (vault / "daily_brief.md").read_text()  # untouched
    assert out["missing_sections"] == ["Cron Highlights — Items"]  # Hot Corrections matched by key
    assert out["backup"].startswith("skipped")


def test_brief_names_blocked_missions_correction_patterns_and_recall_misses(tmp_path: Path) -> None:
    import textwrap

    from brain_core.agent import Agent
    from brain_core.cron import daily

    vault = tmp_path / "vault"
    (vault / "sessions").mkdir(parents=True)
    (vault / "goals").mkdir()
    (vault / "goals" / "mission_queue.md").write_text(
        "| ID | Mission | Priority | Status | Next step | Last reviewed |\n"
        "|---|---|---|---|---|---|\n"
        "| M-1 | Ship it | P1 | blocked | wait for keys | 2026-11-01 |\n"
        "| M-2 | Sell it | P1 | active | call | 2026-11-01 |\n"
        "| M-3 | Fix it | P1 | active | patch | 2026-11-01 |\n"
    )
    (vault / "corrections.md").write_text(
        "# Corrections\n\n"
        + "".join(
            f"### [2026-10-{10 + i}] Slip {i}\n- **Theme:** haste\n- **Promoted:** No\n\n"
            for i in range(3)
        )
    )
    (tmp_path / "brain.yaml").write_text(textwrap.dedent(f"name: T\nstores:\n  vault: {vault}\n"))
    with Agent.from_config(tmp_path / "brain.yaml") as agent:
        assert agent.brain_recall("nothing matches this at all")["results"] == []
        assert (
            agent.recent_events(event_type="recall_miss")[0].payload["query"].startswith("nothing")
        )
        daily(agent, today=date(2026, 11, 3))
    brief = (vault / "daily_brief.md").read_text()
    assert "## Missions — blocked, stalled, competing" in brief
    assert "- blocked: M-1 Ship it → next: wait for keys" in brief
    assert "3 missions at P1" in brief
    assert "## Correction Patterns" in brief and "`haste` ×3 → no rule yet" in brief
    assert "1 recall miss(es) this week (`nothing matches this at all`)" in brief
