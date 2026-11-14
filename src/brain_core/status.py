"""``brain_status``: the agent's health in one call.

Store reachability, knowledge-wiki lint counts, always-loaded context size, last session
close state, pending decisions, and whether recall has been falling back to keywords. No LLM,
no network beyond each store's own health probe.
"""

from __future__ import annotations

import glob
import json
import math
import re
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from brain_core import update
from brain_core.judge import JUDGE_MODEL
from brain_core.session import _marker, _minutes_ago, closed, exec_note
from brain_core.stores.index import RecordIndex
from brain_core.stores.vault import VaultStore, redact
from brain_core.stores.vault import read_safe as _read

if TYPE_CHECKING:
    from brain_core.agent import Agent

_LINK = re.compile(r"\[\[(?:[^\]|]*/)?([^\]|#]+)")
_FM = re.compile(r"^---\n(.*?)\n---", re.S)


def brain_status(agent: Agent) -> dict[str, Any]:
    from brain_core import traits  # local: traits imports this module's parsers

    out: dict[str, Any] = {"agent": agent.name, "ok": True, "stores": {}}
    for s in agent.stores:
        try:
            ok, detail = s.health()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {str(e)[:120]}"
        out["stores"][s.name] = {"ok": ok, "detail": detail}
        out["ok"] = out["ok"] and ok
    vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
    unreadable = ""
    if vault is not None:
        try:
            out["knowledge"] = lint(vault.root)
        except OSError as e:  # a folder that cannot be listed: said under attention below
            out["knowledge"] = {"pages": 0, "raw": 0, "issues": [], "issue_count": 0}
            unreadable = f"knowledge lint not run: {type(e).__name__}: {str(e)[:120]}"
        exec_text = _read(vault.root / agent.config.session.executive)
        if note := exec_note(exec_text, agent.config.session.executive):
            out["executive_state"] = note  # a count of 0 would read as "nothing is waiting"
        else:
            # one rule with the traits: a "- None" line is not a decision
            out["pending_decisions"] = len(traits._pending_rows(exec_text))
    index = next(
        (i for s in agent.stores if isinstance(i := getattr(s, "index", None), RecordIndex)), None
    )
    if index is not None and (masked := index.redacted()):
        # the index and every reply hold them masked; the files still hold the real thing
        out["secrets_masked"] = masked
    attention: list[str] = [unreadable] if unreadable else []
    if vault is not None and (
        lost := sorted(
            f for f, why in vault.unread.items() if why != "not UTF-8" and (vault.root / f).exists()
        )
    ):
        # the store is up, so this is not "down"; but the records of these files are missing
        attention.append(
            f"vault: {len(lost)} file(s) could not be read, their records are missing or old: "
            + ", ".join(lost[:3])
        )
    if agent.vectors is not None:
        out["vectors"] = agent.vectors.stats()  # model, rows, rows waiting, worker up or down
    if agent.config.recall.judge == "model":
        cfg = agent.config.recall
        # the model the judge runs on, as Agent.judge picks it: never the runner's default
        out["judge"] = {"mode": "model", "runner": cfg.runner, "model": cfg.model or JUDGE_MODEL}
    if (fell := recall_degraded(agent))["count"]:
        out["recall_degraded"] = fell
        if fell["last_day"]:
            attention.append(
                f"recall fell back to keywords {fell['last_day']} time(s) in the last day: "
                f"{fell['latest']}"
            )
    v = out.get("vectors", {})
    if v.get("pending") and v.get("worker") != "up" and fell.get("vectors_reason"):
        attention.append(
            f"{v['pending']} record(s) wait for a vector and the embed worker could not "
            f"make one: {fell['vectors_reason']}"
        )
    elif v.get("pending") and not v.get("rows"):
        # said before the first recall falls back: a model name that cannot load looks so
        attention.append(
            f"no record has a vector from {v['model']} and {v['pending']} wait, so recall "
            "answers from keywords alone: run `brain index`, and check the model name"
        )
    out["context"] = _context(agent)
    if agent.config.models is not None:
        from brain_core import models

        out["models"] = models.status(agent)
    out["tools"] = tool_metrics(agent)
    if newer := update.notice(agent.data_dir):  # read from a file `brain daily` wrote; no network
        out["update"] = newer
    if (misses := recall_misses(agent))["count"]:
        out["recall_misses"] = misses
    marker = _marker(agent)
    last_close = marker.read_text().strip() if marker.exists() else ""
    starts = agent.recent_events(event_type="session_start", limit=1)
    last_start = str(starts[0].payload.get("session_id", "")) if starts else ""
    out["session"] = {
        "last_start": last_start,
        "last_close": last_close,
        "current": agent.current_session,
        "unclosed": bool(last_start)
        and last_start not in closed(agent)
        and last_start != agent.current_session,
    }
    if out["knowledge"].get("issues") if vault else False:
        out["ok"] = False
    if attention:
        out["attention"] = attention
        out["ok"] = False
    try:
        out["traits"] = traits.compute(agent, out)
    except OSError as e:  # one folder that cannot be listed must not stop the whole report
        out["traits"] = {}
        out.setdefault("attention", []).append(
            f"traits not computed: {type(e).__name__}: {str(e)[:120]}"
        )
        out["ok"] = False
    return out


def recall_misses(agent: Agent, days: int = 30) -> dict[str, Any]:
    """What written memory could not answer: the queries `brain_recall` logged as misses,
    most asked first. Each is a fact to write or an eval case to add."""
    today = date.today()
    per: dict[str, dict[str, Any]] = {}
    for e in agent.recent_events(event_type="recall_miss", limit=500):
        if (today - e.occurred_at.date()).days > days:
            continue
        # masked here too: a question logged before this release is in the table as asked
        q = redact(str(e.payload.get("query", "")))
        d = per.setdefault(q, {"query": q, "count": 0, "best": e.payload.get("best", 0.0)})
        d["count"] += 1
    top = sorted(per.values(), key=lambda d: -d["count"])[:5]
    return {"window_days": days, "count": sum(d["count"] for d in per.values()), "top": top}


def recall_degraded(agent: Agent, days: int = 7) -> dict[str, Any]:
    """How often recall answered from keywords alone because the vector search or the model
    judge could not be used: the ``recall_degraded`` events `brain_recall` logs, with the
    latest reason. ``vectors_reason`` is the latest one the vector search gave, if any."""
    events = [
        e
        for e in agent.recent_events(event_type="recall_degraded", limit=500)
        if _minutes_ago(e.occurred_at) <= days * 1440
    ]

    def why(e: Any) -> str:
        return f"{e.payload.get('part', '?')}: {str(e.payload.get('reason', ''))[:160]}"

    out: dict[str, Any] = {
        "window_days": days,
        "count": len(events),
        "last_day": sum(1 for e in events if _minutes_ago(e.occurred_at) <= 1440),
    }
    if events:  # newest first; the journal's clock is UTC
        at = events[0].occurred_at.isoformat(sep=" ", timespec="minutes")
        out["latest"] = f"{why(events[0])} ({at} UTC)"
    if vec := next((e for e in events if e.payload.get("part") == "vectors"), None):
        out["vectors_reason"] = str(vec.payload.get("reason", ""))[:160]
    return out


def tool_metrics(agent: Agent, days: int = 30) -> dict[str, Any]:
    """Per-tool calls, runtime, response tokens and errors from `metrics`, with the two
    diagnostics the tool-design guidance names: error rate → clarify descriptions; answers
    near the cap → paginate."""
    rows = agent.db.fetchall(
        "SELECT metric_name, value, tags FROM metrics WHERE metric_name LIKE 'tool.%' "
        "AND recorded_at >= datetime('now', ?)",
        (f"-{days} days",),
    )
    acc: dict[str, dict[str, Any]] = {}
    for r in rows:
        tags = json.loads(r["tags"] or "{}")
        d = acc.setdefault(r["metric_name"][5:], {"ms": [], "tokens": 0, "errors": 0})
        d["ms"].append(float(r["value"]))
        d["tokens"] += int(tags.get("tokens", 0))
        d["errors"] += int(tags.get("error", 0))
    per: dict[str, dict[str, int]] = {}
    hints: list[str] = []
    for name, d in sorted(acc.items()):
        ms = sorted(d["ms"])
        n = len(ms)
        per[name] = {
            "calls": n,
            "avg_ms": round(sum(ms) / n),
            "p95_ms": round(ms[max(0, math.ceil(0.95 * n) - 1)]),  # nearest-rank
            "avg_tokens": d["tokens"] // n,
            "errors": d["errors"],
        }
        if n >= 5 and d["errors"] / n > 0.1:
            hints.append(
                f"{name}: {d['errors']}/{n} calls failed; clarify its parameter descriptions"
            )
        if name == "brain_recall" and n >= 5 and per[name]["avg_tokens"] > 4000:
            hints.append("brain_recall answers run near the cap; lower `limit` or use `offset`")
    return {"window_days": days, "per_tool": per, "hints": hints}


def lint(root: Path) -> dict[str, Any]:
    """Orphans, index drift, pages without sources, raw never compiled (knowledge_tracker port)."""
    kdir, rdir = root / "knowledge", root / "raw"
    issues: list[str] = []
    pages = [p for p in kdir.glob("*.md") if not p.name.startswith("_")] if kdir.exists() else []
    index = _read(kdir / "_index.md")
    for p in pages:
        if p.stem not in index:
            issues.append(f"{p.name} missing from _index.md")
        fm = _frontmatter(p)
        if "sources" not in fm and "## Source" not in _read(p):
            issues.append(f"{p.name} has no sources")
    for link in _LINK.findall(index):
        if not (kdir / f"{link.strip()}.md").exists():
            issues.append(f"_index.md links to missing page {link.strip()}")
    raws = sorted(rdir.glob("*.md")) if rdir.exists() else []
    for r in raws:
        if _frontmatter(r).get("compiled_into", "[]").strip() in ("[]", ""):
            issues.append(f"raw/{r.name} never compiled")
    return {
        "pages": len(pages),
        "raw": len(raws),
        "issues": issues[:20],
        "issue_count": len(issues),
    }


def _context(agent: Agent) -> dict[str, Any]:
    base = agent.config_path.parent if agent.config_path else Path.cwd()
    files: dict[str, int] = {}
    for pat in agent.config.status.context_files:
        p = Path(pat).expanduser()
        for f in sorted(glob.glob(str(p if p.is_absolute() else base / p))):
            files[Path(f).relative_to(base).as_posix() if str(f).startswith(str(base)) else f] = (
                len(Path(f).read_bytes()) // 4
            )
    return {"tokens": sum(files.values()), "files": files}


def _frontmatter(path: Path) -> dict[str, str]:
    m = _FM.match(_read(path))
    if not m:
        return {}
    out: dict[str, str] = {}
    for ln in m.group(1).splitlines():
        if ":" in ln and not ln.startswith((" ", "-")):
            k, v = ln.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _is_table_chrome(line: str) -> bool:
    cells = [c.strip() for c in line.strip("|").split("|")]
    return all(re.fullmatch(r"-+", c) for c in cells if c) or cells[0].lower() in (
        "decision",
        "#",
        "id",
        "title",
    )
