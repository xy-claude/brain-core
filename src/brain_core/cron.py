"""The cron engine: what the brain does while nobody is talking to it.

``brain daily`` (Tier 1, pure Python, no LLM): writes ``vault/daily_brief.md`` for the next
``brain_session('start')``, appends a health line, backs up Hindsight. ``brain weekly``:
archives session files older than 30 days into monthly folders with a summary, refreshes the
Hindsight mental models. ``brain cron install`` registers both as launchd agents on macOS.
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from brain_core.session import _sections
from brain_core.status import _frontmatter
from brain_core.stores.hindsight import HindsightStore
from brain_core.stores.vault import VaultStore

if TYPE_CHECKING:
    from brain_core.agent import Agent

HOT_DAYS = 14
STALE_DAYS = 30
ARCHIVE_DAYS = 30
PROMOTE_AT = 3  # corrections on one theme before the brief asks for a rule
_CORRECTION = re.compile(r"^### \[(\d{4}-\d{2}-\d{2})\] (.+)$")


# ── daily ─────────────────────────────────────────────────────────────────────


def daily(agent: Agent, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    vault = _vault(agent)
    cfg = agent.config
    status = agent.brain_status()
    parts = [
        f"# Daily Brief — {today.isoformat()}\n\n_Written by `brain daily`. "
        "`brain_session('start')` reads this file; everything else is one `brain_recall` away._\n",
        _agenda(vault.root / "goals" / "mission_queue.md"),
        _hot_corrections(vault.root / "corrections.md", today),
        _lessons(vault.root / cfg.session.critique),
        _executive(vault.root / cfg.session.executive),
        _health(status),
        _stale_knowledge(vault.root / "knowledge", today),
        _warmup(vault.root / "sessions"),
    ]
    brief = "\n".join(p for p in parts if p)
    (vault.root / cfg.session.brief).write_text(brief, encoding="utf-8")
    up = sum(1 for s in status["stores"].values() if s["ok"])
    line = (
        f"- {today.isoformat()} ok={status['ok']} stores={up}/{len(status['stores'])} "
        f"lint={status['knowledge']['issue_count']} context={status['context']['tokens']} "
        f"unclosed={status['session']['unclosed']}"
    )
    log = vault.root / "health_log.md"
    if not log.exists():
        log.write_text("# Health log (one line per `brain daily`)\n\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    out: dict[str, Any] = {
        "brief": str(vault.root / cfg.session.brief),
        "brief_tokens": len(brief) // 4,
        "health": line[2:],
    }
    out["backup"] = backup(agent, today) if cfg.cron.backup.enabled else "disabled"
    return out


def _agenda(path: Path) -> str:
    rows = [
        ln for ln in _read(path).splitlines() if ln.startswith("|") and not ln.startswith("|---")
    ]
    missions = [
        r for r in rows[1:] if r.strip("| ").lower().split("|")[0].strip() not in ("id", "")
    ]
    if not missions:
        return "## Session Agenda\n\n_No missions in goals/mission_queue.md yet._\n"
    body = "\n".join(
        f"- {' · '.join(c.strip() for c in r.strip('|').split('|') if c.strip())}" for r in missions
    )
    return f"## Session Agenda — from mission_queue.md\n\n{body}\n"


def _hot_corrections(path: Path, today: date) -> str:
    text = _read(path)
    hot: list[str] = []
    themes: Counter[str] = Counter()
    current: tuple[str, str] | None = None
    for ln in text.splitlines():
        if m := _CORRECTION.match(ln):
            d = date.fromisoformat(m.group(1))
            current = (m.group(1), m.group(2)) if (today - d).days <= HOT_DAYS else None
            if current:
                hot.append(f"- [{m.group(1)}] {m.group(2)}")
        elif current and ln.startswith("- **Theme:**"):
            themes[ln.split("**Theme:**", 1)[1].strip().lower()] += 1
    if not hot:
        return ""
    promote = [
        f"- theme `{t}` has {n} corrections → promote to a rule?"
        for t, n in themes.items()
        if n >= PROMOTE_AT
    ]
    return (
        f"## Hot Corrections — last {HOT_DAYS} days, apply these NOW\n\n"
        + "\n".join(hot)
        + "\n"
        + ("\n### Promotion candidates\n\n" + "\n".join(promote) + "\n" if promote else "")
    )


def _lessons(path: Path) -> str:
    sec = _sections(_read(path), ("Apply Next Session", "What To Improve"))
    return f"## Session Lessons — from the last critique\n\n{sec}\n" if sec.strip() else ""


def _executive(path: Path) -> str:
    sec = _sections(
        _read(path),
        (
            "Primary Objective",
            "Top Missions",
            "Pending Decisions",
            "Open Loops",
            "Critical Reminders",
        ),
    )
    return f"## Executive State\n\n{sec}\n" if sec.strip() else ""


def _health(st: dict[str, Any]) -> str:
    stores = ", ".join(f"{k} {'OK' if v['ok'] else 'DOWN'}" for k, v in st["stores"].items())
    issues = (
        "".join(f"\n  - {i}" for i in st["knowledge"]["issues"][:5])
        if st["knowledge"]["issue_count"]
        else ""
    )
    return (
        "## Brain Health\n\n"
        f"- Stores: {stores}\n"
        f"- Knowledge lint: {st['knowledge']['issue_count']} issue(s){issues}\n"
        f"- Always-loaded context: {st['context']['tokens']} tokens\n"
        f"- Last session: start `{st['session']['last_start'] or '-'}`, "
        f"close `{st['session']['last_close'] or '-'}`"
        + (" — **UNCLOSED, recover first**" if st["session"]["unclosed"] else "")
        + f"\n- Pending decisions: {st.get('pending_decisions', 0)}\n"
    )


def _stale_knowledge(kdir: Path, today: date) -> str:
    stale = []
    for p in sorted(kdir.glob("*.md")) if kdir.exists() else []:
        if p.name.startswith("_"):
            continue
        fm = _frontmatter(p)
        try:
            upd = date.fromisoformat(fm.get("updated", ""))
        except ValueError:
            upd = date.fromtimestamp(p.stat().st_mtime)
        if (today - upd).days > STALE_DAYS:
            stale.append(f"- {p.name} ({(today - upd).days}d) → `/distill --refresh {p.stem}`")
    return (
        f"## Stale Knowledge — over {STALE_DAYS} days\n\n" + "\n".join(stale) + "\n"
        if stale
        else ""
    )


def _warmup(sdir: Path, n: int = 3, lines: int = 25) -> str:
    files = sorted(sdir.glob("????-??-??.md"), reverse=True)[:n] if sdir.exists() else []
    if not files:
        return ""
    blocks = []
    for f in files:
        body = [ln for ln in _read(f).split("---", 2)[-1].splitlines() if ln.strip()][:lines]
        body = [("#### " + ln.lstrip("# ")) if ln.startswith("#") else ln for ln in body]
        blocks.append(f"### {f.stem}\n" + "\n".join(body))
    return "## Recent Sessions — HSAM warmup\n\n" + "\n\n".join(blocks) + "\n"


# ── backup ────────────────────────────────────────────────────────────────────


def backup(agent: Agent, today: date | None = None) -> str:
    cfg = agent.config.cron.backup
    admin = _admin()
    if admin is None:
        return "skipped: hindsight-admin not found"
    out_dir = Path(cfg.dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"hindsight-{(today or date.today()).isoformat()}.zip"
    env = {**os.environ, "HINDSIGHT_API_DATABASE_URL": cfg.database_url}
    cp = subprocess.run(
        [admin, "backup", str(target)], capture_output=True, text=True, env=env, timeout=600
    )
    if cp.returncode != 0:
        return f"failed: {(cp.stderr or cp.stdout).strip()[-200:]}"
    old = sorted(out_dir.glob("hindsight-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)[
        cfg.keep :
    ]
    for p in old:
        p.unlink()
    size = target.stat().st_size // 1024
    return f"ok: {target.name} ({size} KB), kept {cfg.keep}, pruned {len(old)}"


def _admin() -> str | None:
    found = shutil.which("hindsight-admin")
    fallback = Path("~/.local/bin/hindsight-admin").expanduser()
    return found or (str(fallback) if fallback.exists() else None)


# ── weekly ────────────────────────────────────────────────────────────────────


def weekly(agent: Agent, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    vault = _vault(agent)
    moved = consolidate(vault.root / "sessions", today)
    refreshed: dict[str, str] = {}
    h = next((s for s in agent.stores if isinstance(s, HindsightStore)), None)
    for mid in agent.config.session.mental_models:
        if h is None:
            refreshed[mid] = "no hindsight"
            continue
        try:
            h.call("refresh_mental_model", mental_model_id=mid)
            refreshed[mid] = "refreshed"
        except Exception as e:
            refreshed[mid] = f"error: {str(e)[:80]}"
    return {"archived": moved, "mental_models": refreshed}


def consolidate(sdir: Path, today: date) -> dict[str, int]:
    """Move session files older than ARCHIVE_DAYS into sessions/archive/YYYY-MM/ and index them."""
    moved: Counter[str] = Counter()
    for f in sorted(sdir.glob("????-??-??.md")) if sdir.exists() else []:
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if (today - d).days <= ARCHIVE_DAYS:
            continue
        month = f.stem[:7]
        dest = sdir / "archive" / month
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), dest / f.name)
        moved[month] += 1
    for month in moved:
        folder = sdir / "archive" / month
        lines = [f"# {month} — {len(list(folder.glob('*.md')))} session files\n"]
        for f in sorted(folder.glob("*.md")):
            discussed = _sections(_read(f), ("What We Discussed",)).splitlines()[1:4]
            lines.append(f"## {f.stem}\n" + "\n".join(discussed))
        (sdir / "archive" / f"{month}.md").write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    return dict(moved)


# ── crontab (Linux) ───────────────────────────────────────────────────────────

CRON_TAG = "# brain-core"


def cron_lines(
    agent_dir: Path, brain_bin: str, name: str, daily_at: str, weekly_at: str
) -> list[str]:
    """Two crontab lines, tagged so install/uninstall can find their own."""
    dh, dm = (int(x) for x in daily_at.split(":"))
    wday, wtime = weekly_at.split()
    wh, wm = (int(x) for x in wtime.split(":"))
    weekday = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"].index(wday[:3].lower())
    log = agent_dir / "data" / "logs"
    tag = f"{CRON_TAG} {name.lower()}"
    daily = f"{dm} {dh} * * * {brain_bin} daily {agent_dir} >> {log}/daily.log 2>&1 {tag} daily"
    weekly = f"{wm} {wh} * * {weekday} {brain_bin} weekly {agent_dir} >> {log}/weekly.log 2>&1"
    return [daily, f"{weekly} {tag} weekly"]


def _crontab_merge(current: str, name: str, new_lines: list[str]) -> str:
    """Current crontab text minus this agent's tagged lines, plus ``new_lines``."""
    tag = f"{CRON_TAG} {name.lower()} "
    keep = [ln for ln in current.splitlines() if tag not in ln]
    return "\n".join([*keep, *new_lines]).strip("\n") + ("\n" if keep or new_lines else "")


def _install_crontab(agent: Agent, agent_dir: Path, brain_bin: str) -> list[str]:
    c = agent.config.cron
    lines = cron_lines(agent_dir, brain_bin, agent.name, c.daily, c.weekly)
    cp = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    merged = _crontab_merge(cp.stdout if cp.returncode == 0 else "", agent.name, lines)
    subprocess.run(["crontab", "-"], input=merged, text=True, check=True)
    return lines


# ── launchd ───────────────────────────────────────────────────────────────────


def plists(
    agent_dir: Path, brain_bin: str, name: str, daily_at: str, weekly_at: str
) -> dict[str, dict[str, Any]]:
    """Two launchd job definitions. daily_at like '06:07'; weekly_at like 'Sun 07:13'."""
    dh, dm = (int(x) for x in daily_at.split(":"))
    wday, wtime = weekly_at.split()
    wh, wm = (int(x) for x in wtime.split(":"))
    weekday = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"].index(wday[:3].lower())
    logs = agent_dir / "data" / "logs"
    label = f"io.brain-core.{name.lower()}"
    return {
        f"{label}.daily": {
            "Label": f"{label}.daily",
            "ProgramArguments": [brain_bin, "daily", str(agent_dir)],
            "StartCalendarInterval": {"Hour": dh, "Minute": dm},
            "StandardOutPath": str(logs / "daily.log"),
            "StandardErrorPath": str(logs / "daily.log"),
            "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        },
        f"{label}.weekly": {
            "Label": f"{label}.weekly",
            "ProgramArguments": [brain_bin, "weekly", str(agent_dir)],
            "StartCalendarInterval": {"Weekday": weekday, "Hour": wh, "Minute": wm},
            "StandardOutPath": str(logs / "weekly.log"),
            "StandardErrorPath": str(logs / "weekly.log"),
            "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        },
    }


def install(agent: Agent, launch_dir: Path | None = None, load: bool = True) -> list[str]:
    """Write the plists (and bootstrap them unless ``load=False``). Returns their paths."""
    agent_dir = agent.config_path.parent if agent.config_path else Path.cwd()
    brain_bin = shutil.which("brain") or str(Path(sys.executable).with_name("brain"))
    (agent_dir / "data" / "logs").mkdir(parents=True, exist_ok=True)
    if sys.platform != "darwin" and launch_dir is None:
        return (
            _install_crontab(agent, agent_dir, brain_bin)
            if load
            else cron_lines(
                agent_dir, brain_bin, agent.name, agent.config.cron.daily, agent.config.cron.weekly
            )
        )
    launch_dir = launch_dir or Path("~/Library/LaunchAgents").expanduser()
    launch_dir.mkdir(parents=True, exist_ok=True)
    c = agent.config.cron
    written = []
    for label, body in plists(agent_dir, brain_bin, agent.name, c.daily, c.weekly).items():
        path = launch_dir / f"{label}.plist"
        path.write_bytes(plistlib.dumps(body))
        written.append(str(path))
        if load:
            subprocess.run(
                ["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True
            )
            subprocess.run(
                ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], capture_output=True
            )
    return written


def uninstall(agent: Agent, launch_dir: Path | None = None) -> list[str]:
    if sys.platform != "darwin" and launch_dir is None:
        cp = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        before = cp.stdout if cp.returncode == 0 else ""
        after = _crontab_merge(before, agent.name, [])
        subprocess.run(["crontab", "-"], input=after, text=True, check=True)
        return [ln for ln in before.splitlines() if f"{CRON_TAG} {agent.name.lower()} " in ln]
    launch_dir = launch_dir or Path("~/Library/LaunchAgents").expanduser()
    removed = []
    for suffix in ("daily", "weekly"):
        path = launch_dir / f"io.brain-core.{agent.name.lower()}.{suffix}.plist"
        if path.exists():
            subprocess.run(
                ["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True
            )
            path.unlink()
            removed.append(str(path))
    return removed


# ── helpers ───────────────────────────────────────────────────────────────────


def _vault(agent: Agent) -> VaultStore:
    v = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
    if v is None:
        raise ValueError("brain daily/weekly need stores.vault in brain.yaml")
    return v


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
