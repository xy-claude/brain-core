"""The cron engine: what the brain does while nobody is talking to it.

``brain daily`` (Tier 1, pure Python, no LLM): writes ``vault/daily_brief.md`` for the next
``brain_session('start')``, appends a health line, backs up Hindsight. ``brain weekly``:
archives session files older than 30 days into monthly folders with a summary, refreshes the
Hindsight mental models. ``brain cron install`` registers both as launchd agents on macOS.
"""

from __future__ import annotations

import importlib
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import threading
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from brain_core import traits
from brain_core.session import _sections
from brain_core.status import _frontmatter
from brain_core.stores.hindsight import HindsightStore
from brain_core.stores.transcripts import TranscriptStore
from brain_core.stores.vault import _DECISION, VaultStore, _parse_date
from brain_core.stores.vault import read_text as _read

if TYPE_CHECKING:
    from brain_core.agent import Agent

REINFORCE_DAYS = (1, 3, 7, 30)  # spaced repetition for decisions
DRAFT_AFTER = 3  # unpromoted corrections on one theme before a draft rule is written
REFLECT_QUERY = (
    "Across recent sessions, what should change in how I work? Name the pattern and the evidence."
)
HOT_DAYS = 14
STALE_DAYS = 30
ARCHIVE_DAYS = 30
PROMOTE_AT = 3  # corrections on one theme before the brief asks for a rule
_CORRECTION = re.compile(r"^### \[(\d{4}-\d{2}-\d{2})\] (.+)$")


# ── daily ─────────────────────────────────────────────────────────────────────


def daily(agent: Agent, today: date | None = None, shadow: bool = False) -> dict[str, Any]:
    """``shadow=True`` writes ``<brief>.shadow.md`` beside a brief another tool still owns and
    reports which of its sections are missing here, so a migration never loses a section."""
    today = today or date.today()
    vault = _vault(agent)
    cfg = agent.config
    status = agent.brain_status()
    parts = [
        f"# Daily Brief — {today.isoformat()}\n\n_Written by `brain daily`. "
        "`brain_session('start')` reads this file; everything else is one `brain_recall` away._\n",
        _agenda(vault.root / "goals" / "mission_queue.md"),
        _hot_corrections(vault.root / "corrections.md", today),
        _correction_patterns(vault.root, today),
        _missions_watch(vault.root / "goals" / "mission_queue.md", today),
        _reinforce(vault.root / "decisions_log.md", today),
        _lessons(vault.root / cfg.session.critique),
        _executive(vault.root / cfg.session.executive),
        _health(status),
        _traits(status.get("traits", {})),
        _growth(agent, vault.root, today),
        _stale_knowledge(vault.root / "knowledge", today),
        _warmup(vault.root / "sessions"),
    ]
    brief = "\n".join(p for p in parts if p)
    live = vault.root / cfg.session.brief
    target = live.with_name(f"{live.stem}.shadow.md") if shadow else live
    target.write_text(brief, encoding="utf-8")
    if shadow:
        old = _read(live) if live.exists() else ""
        mine = {_section_key(ln) for ln in brief.splitlines() if ln.startswith("## ")}
        theirs = [ln for ln in old.splitlines() if ln.startswith("## ")]
        missing = [ln[3:] for ln in theirs if _section_key(ln) not in mine]
        return {
            "brief": str(target),
            "brief_tokens": len(brief) // 4,
            "shadow_of": str(live),
            "missing_sections": missing,
            "health": "shadow run: no health line, no backup",
            "backup": "skipped (shadow)",
        }
    up = sum(1 for s in status["stores"].values() if s["ok"])
    line = (
        f"- {today.isoformat()} ok={status['ok']} stores={up}/{len(status['stores'])} "
        f"lint={status['knowledge']['issue_count']} context={status['context']['tokens']} "
        f"unclosed={status['session']['unclosed']} {traits.one_line(status.get('traits', {}))}"
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
    for s in agent.stores:
        if isinstance(s, TranscriptStore):
            out["transcripts"] = s.index()
    return out


def _section_key(heading: str) -> str:
    """'## Hot Corrections — Apply These NOW' and '## Hot Corrections — last 14 days' are one."""
    return re.split(r"\s+[—(\-]", heading[3:].strip(), maxsplit=1)[0].strip().lower()


def _agenda(path: Path) -> str:
    missions = traits.missions(path)
    if not missions:
        return (
            "## Session Agenda\n\n"
            "_No missions yet (goals/mission_queue.md or goals/missions/*.md)._\n"
        )
    body = "\n".join(f"- {' · '.join(v for v in m.values() if v)}" for m in missions)
    return f"## Session Agenda — missions\n\n{body}\n"


def _hot_corrections(path: Path, today: date) -> str:
    text = _read(path)
    hot: list[str] = []
    themes: Counter[str] = Counter()
    current: tuple[str, str] | None = None
    for ln in text.splitlines():
        if m := _CORRECTION.match(ln):
            try:
                d = date.fromisoformat(m.group(1))
            except ValueError:  # a hand-typed heading must not take the brief down
                current = None
                continue
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


def _traits(tr: dict[str, Any]) -> str:
    """One line per trait: the first defensible signal, or the first cost signal."""
    if not tr:
        return ""
    lines = []
    for t in tr.values():
        sig = t["signals"]
        s = next((s for s in sig.values() if s["verdict"] == "defensible"), None) or next(
            iter(sig.values())
        )
        shown = f"{s['value']}/{s['n']}" if s.get("n") else f"{s['value']}"
        if "pct" in s:
            shown += f" ({s['pct']}%)"
        lines.append(f"- {t['name']}: {shown} — {s['note']}")
    return "## Traits — evidence on disk\n\n" + "\n".join(lines) + "\n"


def _growth(agent: Agent, root: Path, today: date) -> str:
    """Three read-only nudges: rules not landing, missions stalled, decisions waiting too long."""
    lines: list[str] = []
    promoted: dict[str, tuple[date, int]] = {}
    for d, _t, f in traits._corrections(_read(root / "corrections.md")):
        th = f.get("theme", "").lower()
        if f.get("promoted", "").lower().startswith("yes"):
            promoted[th] = (min(promoted.get(th, (d, 0))[0], d), promoted.get(th, (d, 0))[1])
    for d, _t, f in traits._corrections(_read(root / "corrections.md")):
        th = f.get("theme", "").lower()
        if th in promoted and d > promoted[th][0]:
            promoted[th] = (promoted[th][0], promoted[th][1] + 1)
    for th, (since, n) in promoted.items():
        if n:
            lines.append(
                f"- theme `{th}` recurred {n}× since its rule was promoted on {since.isoformat()} "
                "→ the rule is not landing; reread it at session start or rewrite it"
            )
    for mi, days in traits.stalled(root / "goals" / "mission_queue.md", today):
        lines.append(
            f"- {mi['id']} {mi['mission']} ({mi['status']}) not reviewed for {days} days "
            "→ advance, block with a reason, or drop it"
        )
    pending = traits._pending_rows(_read(root / agent.config.session.executive))
    ages = _track_pending(agent.data_dir, pending, today)
    for key, days in sorted(ages.items(), key=lambda kv: -kv[1]):
        if days >= traits.STALLED_DAYS:
            lines.append(
                f"- pending decision `{key[:60]}` has waited {days} days "
                "→ ask again, or decide it is not needed"
            )
    for p in sorted((root / "procedures" / "_drafts").glob("rule-*.md")):
        lines.append(
            f"- draft rule `{p.name}` waits for your decision "
            "→ approve into a rule file, or delete it"
        )
    latest = _latest_reflection(root / "knowledge" / "_reflections.md")
    if latest and (today - latest).days <= 7:
        lines.append(
            f"- `brain weekly` wrote a reflection on {latest.isoformat()} "
            "→ read knowledge/_reflections.md; "
            "cite a vault source before acting on it"
        )
    misses = [
        e
        for e in agent.recent_events(event_type="recall_miss", limit=200)
        if (today - e.occurred_at.date()).days <= 7
    ]
    if misses:
        seen: list[str] = []
        for e in misses:
            q = str(e.payload.get("query", ""))
            if q and q not in seen:
                seen.append(q)
        shown = "; ".join(f"`{q[:50]}`" for q in seen[:3])
        lines.append(
            f"- {len(misses)} recall miss(es) this week ({shown}) "
            "→ write the fact if it is known, or add the query to the eval set"
        )
    if not lines:
        return ""
    return "## Growth — what the traits say to do today\n\n" + "\n".join(lines) + "\n"


def _missions_watch(path: Path, today: date) -> str:
    """Blocked missions, missions not reviewed for 14 days, and too many P1s at once."""
    lines: list[str] = []
    for m in traits.missions(path):
        st = m.get("status", "").lower()
        if st.startswith("block"):
            lines.append(f"- blocked: {m['id']} {m['mission']} → next: {m.get('next') or '-'}")
    for m, days in traits.stalled(path, today):
        lines.append(f"- stalled {days}d: {m['id']} {m['mission']} ({m['status']})")
    p1 = [m["id"] for m in traits.missions(path) if m.get("priority", "").upper() == "P1"]
    if len(p1) > 2:
        lines.append(f"- {len(p1)} missions at P1 ({', '.join(p1)}) → they compete; rank them")
    if not lines:
        return ""
    return "## Missions — blocked, stalled, competing\n\n" + "\n".join(lines) + "\n"


def _correction_patterns(root: Path, today: date) -> str:
    """A theme with three or more corrections is a pattern: name it and whether a rule exists."""
    counts: dict[str, int] = {}
    promoted: set[str] = set()
    for _d, _t, f in traits._corrections(_read(root / "corrections.md")):
        th = f.get("theme", "").lower().strip()
        if th:
            counts[th] = counts.get(th, 0) + 1
            if f.get("promoted", "").lower().startswith("yes"):
                promoted.add(th)
    lines = []
    for th, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if n >= 3:
            draft = root / "procedures" / "_drafts" / f"rule-{th}.md"
            if th in promoted:
                state = "rule promoted, still recurring: rewrite it"
            elif draft.exists():
                state = "draft rule waits"
            else:
                state = "no rule yet"
            lines.append(f"- `{th}` ×{n} → {state}; fix the cause, not the instance")
    if not lines:
        return ""
    return "## Correction Patterns\n\n" + "\n".join(lines) + "\n"


def _reinforce(path: Path, today: date) -> str:
    """Spaced repetition for decisions: resurface each one at 1, 3, 7 and 30 days."""
    lines = []
    for ln in _read(path).splitlines():
        if (m := _DECISION.match(ln)) and (d := _parse_date(m.group(1))):
            age = (today - d).days
            if age in REINFORCE_DAYS:
                lines.append(f"- day {age}: {m.group(2)} ({d.isoformat()})")
    if not lines:
        return ""
    return "## Reinforce — decisions due for a second look\n\n" + "\n".join(lines) + "\n"


def rule_drafts(root: Path, today: date) -> list[str]:
    """A theme with DRAFT_AFTER or more unpromoted corrections gets one draft rule file in
    procedures/_drafts/. Never overwritten: the agent edits, approves or deletes it."""
    by_theme: dict[str, list[tuple[date, str, dict[str, str]]]] = {}
    for d, t, f in traits._corrections(_read(root / "corrections.md")):
        th = f.get("theme", "").strip().lower()
        if th and not f.get("promoted", "").lower().startswith("yes"):
            by_theme.setdefault(th, []).append((d, t, f))
    written = []
    for th, items in sorted(by_theme.items()):
        if len(items) < DRAFT_AFTER:
            continue
        p = root / "procedures" / "_drafts" / f"rule-{re.sub(r'[^a-z0-9]+', '-', th).strip('-')}.md"
        if p.exists():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        rules = "\n".join(
            f"- {f.get('implied rule') or f.get('rule') or t} ({d.isoformat()})"
            for d, t, f in items
        )
        p.write_text(
            f"---\ntype: draft-rule\ntheme: {th}\nstatus: draft\n"
            f"created: {today.isoformat()}\n---\n"
            f"# Draft rule — {th} ({len(items)} corrections)\n\n{rules}\n\n"
            "Approve: write the rule in one line in your own rule file and set `Promoted: Yes` on "
            "each correction above. Reject: delete this file.\n",
            encoding="utf-8",
        )
        written.append(str(p))
    return written


def reflect(agent: Agent, today: date) -> str:
    """One Hindsight reflection a week, appended to knowledge/_reflections.md as unverified."""
    h = next((s for s in agent.stores if isinstance(s, HindsightStore)), None)
    if h is None:
        return "no hindsight"
    try:
        res = h.call("reflect", query=REFLECT_QUERY, budget="mid")
    except Exception as e:
        return f"error: {str(e)[:80]}"
    text = (res.get("text") or res.get("answer") or "") if isinstance(res, dict) else str(res)
    text = " ".join(str(text).split())[:1500]
    if not text:
        return "empty"
    p = _vault(agent).root / "knowledge" / "_reflections.md"
    if not p.exists():
        p.write_text(
            "# Reflections (written by `brain weekly`)\n\n_Unverified synthesis from Hindsight "
            "reflect. Cite a vault source before acting on any line._\n",
            encoding="utf-8",
        )
    with p.open("a", encoding="utf-8") as f:
        f.write(f"\n## {today.isoformat()}\n\n{text}\n")
    return "written"


def _latest_reflection(path: Path) -> date | None:
    dates = [
        d for ln in _read(path).splitlines() if ln.startswith("## ") and (d := _parse_date(ln[3:]))
    ]
    return max(dates) if dates else None


def _track_pending(data_dir: Path, pending: list[list[str]], today: date) -> dict[str, int]:
    """Keep the first-seen date per pending decision in data/pending_seen.json; return ages."""
    path = data_dir / "pending_seen.json"
    try:
        seen = json.loads(_read(path)) if path.exists() else {}
    except ValueError:
        seen = {}
    keys = {r[0] for r in pending if r}
    seen = {k: v for k, v in seen.items() if k in keys}
    for k in keys:
        seen.setdefault(k, today.isoformat())
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, indent=1, ensure_ascii=False), encoding="utf-8")
    return {k: (today - date.fromisoformat(v)).days for k, v in seen.items()}


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
    exe = "hindsight-admin.exe" if sys.platform == "win32" else "hindsight-admin"
    fallback = Path("~/.local/bin").expanduser() / exe
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
    return {
        "archived": moved,
        "mental_models": refreshed,
        "rule_drafts": rule_drafts(vault.root, today),
        "reflection": reflect(agent, today),
    }


def consolidate(sdir: Path, today: date) -> dict[str, int]:
    """Move session files older than ARCHIVE_DAYS into sessions/archive/YYYY-MM/ and index them."""
    moved: Counter[str] = Counter()
    for stale in sdir.glob(".*.md.lock") if sdir.exists() else []:
        stale.unlink()  # per-file locks from 0.2.2 and earlier
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
    b, d = shlex.quote(brain_bin), shlex.quote(str(agent_dir))  # a space in $HOME is common
    dl, wl = shlex.quote(str(log / "daily.log")), shlex.quote(str(log / "weekly.log"))
    daily = f"{dm} {dh} * * * {b} daily {d} >> {dl} 2>&1 {tag} daily"
    weekly = f"{wm} {wh} * * {weekday} {b} weekly {d} >> {wl} 2>&1"
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


# ── Task Scheduler (Windows) ──────────────────────────────────────────────────
#
# Through Windows' COM interface, inside this process, never by launching ``schtasks``. On a
# real PC with a third-party antivirus, ``schtasks /Create`` started from Python (directly, through
# cmd or through PowerShell) got no answer at all; started from PowerShell alone it took 0.1 s, and
# this interface took 0.4 s (2026-11-09).


def task_specs(
    agent_dir: Path, brain_bin: str, name: str, daily_at: str, weekly_at: str
) -> dict[str, tuple[str, int | None, str]]:
    """Task name → (HH:MM, weekday 0=Sunday or None for daily, arguments for ``cmd``)."""
    wday, wtime = weekly_at.split()
    weekday = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"].index(wday[:3].lower())
    task = f"brain-core.{name.lower()}"
    log = agent_dir / "data" / "logs"

    def run(sub: str) -> str:
        # cmd strips the outer pair of quotes, which is what lets the inner ones quote paths
        return f'/c ""{brain_bin}" {sub} "{agent_dir}" >> "{log / f"{sub}.log"}" 2>&1"'

    return {
        f"{task}.daily": (daily_at, None, run("daily")),
        f"{task}.weekly": (wtime, weekday, run("weekly")),
    }


def _connect() -> tuple[Any, Any]:
    """Task Scheduler's service object and its root folder, for the calling thread."""
    pythoncom = importlib.import_module("pythoncom")
    client = importlib.import_module("win32com.client")
    pythoncom.CoInitialize()
    service = client.Dispatch("Schedule.Service")
    service.Connect()
    return service, service.GetFolder("\\")


def _task_scheduler(work: Callable[[Any, Any], str], timeout: float = 60.0) -> str:
    """Run ``work(service, root_folder)`` against Task Scheduler in a worker thread. A call that
    never returns becomes an error after ``timeout`` seconds instead of a wait."""
    result: dict[str, Any] = {}

    def run() -> None:
        try:
            result["value"] = work(*_connect())
        except Exception as e:  # a COM error carries Windows' own text
            result["error"] = e

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise RuntimeError(f"no answer from Task Scheduler in {timeout:.0f} seconds")
    if "error" in result:
        raise RuntimeError(str(result["error"])) from result["error"]
    return str(result["value"])


def _create_task(task: str, at: str, weekday: int | None, arguments: str) -> None:
    def work(service: Any, root: Any) -> str:
        d = service.NewTask(0)
        d.RegistrationInfo.Description = "brain-core"
        d.Settings.StartWhenAvailable = True  # a PC that was off at the hour runs it when it wakes
        d.Settings.DisallowStartIfOnBatteries = False  # a laptop on battery still gets its brief
        d.Settings.StopIfGoingOnBatteries = False
        trigger = d.Triggers.Create(2 if weekday is None else 3)  # daily | weekly
        trigger.StartBoundary = f"{date.today().isoformat()}T{at}:00"
        if weekday is None:
            trigger.DaysInterval = 1
        else:
            trigger.DaysOfWeek = 1 << weekday  # Sunday is bit 0
            trigger.WeeksInterval = 1
        action = d.Actions.Create(0)  # run a program
        action.Path = "cmd"
        action.Arguments = arguments
        # 6 = create or update; 3 = as the logged-on user, no stored password
        root.RegisterTaskDefinition(task, d, 6, None, None, 3)
        return "created"

    _task_scheduler(work)


def _task_installed(task: str) -> bool:
    def work(service: Any, root: Any) -> str:
        try:
            root.GetTask("\\" + task)
        except Exception:  # Windows answers "file not found" for a task that is not there
            return "absent"
        return "present"

    return _task_scheduler(work) == "present"


def _delete_task(task: str) -> None:
    _task_scheduler(lambda service, root: str(root.DeleteTask(task, 0)))


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


def install(
    agent: Agent,
    launch_dir: Path | None = None,
    load: bool = True,
    say: Callable[[str], None] | None = None,
) -> list[str]:
    """Write the plists (and bootstrap them unless ``load=False``). Returns their paths.
    ``say`` receives one line before each slow step, so a caller can show what is happening."""
    agent_dir = agent.config_path.parent if agent.config_path else Path.cwd()
    brain_bin = shutil.which("brain") or str(Path(sys.executable).with_name("brain"))
    (agent_dir / "data" / "logs").mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32" and launch_dir is None:
        c = agent.config.cron
        tasks = task_specs(agent_dir, brain_bin, agent.name, c.daily, c.weekly)
        if load:
            for task, (at, weekday, arguments) in tasks.items():
                if say:
                    say(f"Task Scheduler: creating {task}")
                try:
                    _create_task(task, at, weekday, arguments)
                except RuntimeError as e:
                    raise RuntimeError(f"Task Scheduler did not create {task}: {e}") from e
        return list(tasks)
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


def status(agent: Agent, launch_dir: Path | None = None) -> dict[str, str]:
    """installed | not installed per job: Task Scheduler, crontab (Linux) or plists (macOS)."""
    if sys.platform == "win32" and launch_dir is None:
        out = {}
        for s in ("daily", "weekly"):
            state = (
                "installed"
                if _task_installed(f"brain-core.{agent.name.lower()}.{s}")
                else "not installed"
            )
            out[s] = f"{state} (Task Scheduler)"
        return out
    if sys.platform != "darwin" and launch_dir is None:
        cp = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        tab = cp.stdout if cp.returncode == 0 else ""
        tag = f"{CRON_TAG} {agent.name.lower()} "
        return {
            s: "installed (crontab)" if f"{tag}{s}" in tab else "not installed (crontab)"
            for s in ("daily", "weekly")
        }
    base = launch_dir or Path("~/Library/LaunchAgents").expanduser()
    out = {}
    for s in ("daily", "weekly"):
        p = base / f"io.brain-core.{agent.name.lower()}.{s}.plist"
        out[s] = f"{'installed' if p.exists() else 'not installed'} ({p})"
    return out


def uninstall(agent: Agent, launch_dir: Path | None = None) -> list[str]:
    if sys.platform == "win32" and launch_dir is None:
        tasks = [f"brain-core.{agent.name.lower()}.{s}" for s in ("daily", "weekly")]
        removed = [t for t in tasks if _task_installed(t)]
        for t in removed:
            _delete_task(t)
        return removed
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


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
