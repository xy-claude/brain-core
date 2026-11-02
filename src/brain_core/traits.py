"""The twelve traits, scored from evidence on disk.

A trait is innate (it ships with ``brain init`` and survives a cold start) and grows with the
vault. Each trait reports signals, never a composite score. A signal's verdict says what it is
worth: ``defensible`` when the answer key comes from a file the agent did not write in the same
session (dated archives, the event journal, the user's corrections); ``cost`` when it is a size or
age, useful but not quality; ``pending`` when the evidence does not exist yet (resolved decisions,
the stratified eval). Ratios are shown as counts until ``n`` reaches ``MIN_N``.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from brain_core.status import _frontmatter, _is_table_chrome
from brain_core.stores.vault import VaultStore
from brain_core.stores.vault import read_text as _read

if TYPE_CHECKING:
    from brain_core.agent import Agent

MIN_N = 20  # below this a ratio is a count, not a percentage (one-user scale)
STALE_DAYS = 30
STALLED_DAYS = 14
PACK_TRAITS = Path(__file__).resolve().parent / "templates" / "agent" / "traits.yaml"
_BANNER = re.compile(
    r"^- \*\*⚠ Fact changed (\d{4}-\d{2}-\d{2}):\*\* .*?\(was: (.+?)\)"
    r"(?:\s*\(\d{4}-\d{2}-\d{2}\))?\s*$",
    re.M,
)
_CORRECTION = re.compile(r"^### \[(\d{4}-\d{2}-\d{2})\] (.+?)\s*$")
_FIELD = re.compile(r"^- \*\*(\w[\w ]*):\*\*\s*(.*)$")
_SOCIAL_THEMES = ("communication", "tone", "format", "delivery", "style")


def load(agent_dir: Path | None) -> list[dict[str, str]]:
    """The trait definitions: the agent's own ``traits.yaml`` if present, else the pack's."""
    path = agent_dir / "traits.yaml" if agent_dir else PACK_TRAITS
    data = yaml.safe_load(_read(path if path.exists() else PACK_TRAITS)) or []
    return [t for t in data if isinstance(t, dict) and "id" in t]


def compute(agent: Agent, status: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Signals per trait. ``status`` is the rest of ``brain_status`` (context, pending, lint)."""
    today = today or date.today()
    vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
    agent_dir = agent.config_path.parent if agent.config_path else Path.cwd()
    out: dict[str, Any] = {}
    if vault is None:
        return out
    root = vault.root
    events = agent.recent_events(limit=5000)
    by_session: dict[str, list[Any]] = defaultdict(list)
    for e in reversed(events):  # oldest first
        if e.session_id:
            by_session[e.session_id].append(e)
    ctx = status.get("context", {})
    knowledge = status.get("knowledge", {})
    pending = _pending_rows(_read(root / agent.config.session.executive))

    signals: dict[str, dict[str, dict[str, Any]]] = {
        "working_memory": {
            "sessions_opened": _opened(by_session),
            "context_tokens": _cost(ctx.get("tokens", 0), "always-loaded tokens"),
        },
        "episodic_memory": _episodic(root / "sessions", today, agent.data_dir),
        "semantic_memory": _semantic(vault, knowledge, agent.data_dir),
        "procedural_memory": _procedural(agent_dir, root / "procedures", today),
        "learning": _learning(root, today),
        "reasoning_planning": {"repeat_cascades": _cascades(by_session)},
        "decision": _decision(vault, pending),
        "metacognition": _metacognition(vault, root / agent.config.session.critique, today),
        "execution": _execution(events, root, agent.config.session.brief, today),
        "goal_management": _goals(root / "goals" / "mission_queue.md", today),
        "user_model": _user_model(root, today),
        "authority": _authority(pending),
    }
    for t in load(agent_dir):
        sig = signals.get(t["id"], {})
        grown = any(s["verdict"] == "defensible" and s.get("n", 0) > 0 for s in sig.values())
        out[t["id"]] = {
            "name": t["name"],
            "kind": t.get("kind", ""),
            "grown": grown,
            **{"signals": sig},
        }
    return out


def one_line(traits: dict[str, Any]) -> str:
    """A compact line for the health log: one key number per trait."""
    bits = []
    for tid, t in traits.items():
        sig = t["signals"]
        first = next((s for s in sig.values() if s["verdict"] == "defensible"), None)
        if first is None:
            first = next(iter(sig.values()), None)
        if first is None:
            continue
        v = first["value"]
        bits.append(f"{tid}={v}/{first['n']}" if first.get("n") else f"{tid}={v}")
    return " ".join(bits)


# ── signals ───────────────────────────────────────────────────────────────────


def _ratio(hits: int, n: int, note: str, verdict: str = "defensible") -> dict[str, Any]:
    better = "lower" if "lower is better" in note else "higher"
    out: dict[str, Any] = {
        "value": hits,
        "n": n,
        "verdict": verdict,
        "better": better,
        "note": note,
    }
    if n >= MIN_N:
        out["pct"] = round(100 * hits / n)
    return out


def _cost(value: Any, note: str) -> dict[str, Any]:
    return {"value": value, "verdict": "cost", "note": note}


def _pending_signal(note: str) -> dict[str, Any]:
    return {"value": None, "n": 0, "verdict": "pending", "note": note}


def _opened(by_session: dict[str, list[Any]]) -> dict[str, Any]:
    with_writes = [
        s for s, ev in by_session.items() if any(e.event_type == "brain_remember" for e in ev)
    ]
    opened = sum(
        1 for s in with_writes if any(e.event_type == "session_start" for e in by_session[s])
    )
    return _ratio(
        opened, len(with_writes), "sessions with writes that called brain_session('start') first"
    )


def _episodic(sdir: Path, today: date, data_dir: Path) -> dict[str, dict[str, Any]]:
    days = sorted(p.stem for p in sdir.glob("????-??-??.md")) if sdir.exists() else []
    archived = len(list((sdir / "archive").glob("*/*.md"))) if (sdir / "archive").exists() else 0
    last = _days_since(days[-1], today) if days else None
    return {
        "archives": _cost(len(days) + archived, "dated session files, live plus archived"),
        "days_since_last": _cost(last, "days since the newest session file"),
        "temporal_recall": _eval_slice(data_dir, "temporal")
        or _pending_signal("temporal items from dated archives, pass^3 (the growth eval)"),
    }


def _semantic(
    vault: VaultStore, knowledge: dict[str, Any], data_dir: Path
) -> dict[str, dict[str, Any]]:
    facts = vault.read("fact", limit=10_000)
    dated = sum(1 for r in facts if r.extra.get("legacy") != "undated")
    pages = int(knowledge.get("pages", 0))
    unsourced = sum(1 for i in knowledge.get("issues", []) if i.endswith("has no sources"))
    return {
        "facts_dated": _ratio(dated, len(facts), "facts carrying their date"),
        "pages_sourced": _ratio(pages - unsourced, pages, "knowledge pages that cite a raw source"),
        "stratified_recall": _eval_slice(
            data_dir, "single-hop", "multi-hop", "update", "abstention"
        )
        or _pending_signal("single-hop, multi-hop, update and abstention slices (the growth eval)"),
    }


def _procedural(agent_dir: Path, pdir: Path, today: date) -> dict[str, dict[str, Any]]:
    rules = len(list((agent_dir / ".claude" / "rules").glob("*.md")))
    skills = len(list((agent_dir / ".claude" / "skills").glob("*/SKILL.md")))
    procs = [p for p in pdir.glob("*.md") if p.name != "README.md"] if pdir.exists() else []
    fresh = 0
    for p in procs:
        v = _frontmatter(p).get("last_validated", "")
        d = _days_since(v, today)
        fresh += 1 if d is not None and d <= STALE_DAYS else 0
    return {
        "rules_and_skills": _cost(rules + skills, "rule files plus skills shipped or added"),
        "procedures_validated": _ratio(
            fresh, len(procs), f"procedures validated within {STALE_DAYS} days"
        ),
    }


def _learning(root: Path, today: date) -> dict[str, dict[str, Any]]:
    corrections = _corrections(_read(root / "corrections.md"))
    promoted_at: dict[str, date] = {}
    for d, _title, fields in corrections:
        if fields.get("promoted", "").lower().startswith("yes"):
            th = fields.get("theme", "").lower()
            promoted_at[th] = min(promoted_at.get(th, d), d)
    recurrences = sum(
        1
        for d, _t, f in corrections
        if f.get("theme", "").lower() in promoted_at and d > promoted_at[f.get("theme", "").lower()]
    )
    recent = sum(1 for d, _t, _f in corrections if (today - d).days <= STALE_DAYS)
    leaks, banners = 0, 0
    sessions = (
        {p.stem: _read(p) for p in (root / "sessions").glob("????-??-??.md")}
        if (root / "sessions").exists()
        else {}
    )
    for m in _BANNER.finditer(_read(root / "facts.md")):
        banners += 1
        old = m.group(2).strip()
        if any(day > m.group(1) and old in text for day, text in sessions.items()):
            leaks += 1
    return {
        "correction_recurrence": _ratio(
            recurrences,
            len(promoted_at),
            "corrections on a theme after its rule was promoted (lower is better)",
        ),
        "fact_update_leaks": _ratio(
            leaks,
            banners,
            "old values that reappear in sessions after a Fact-changed banner (lower is better)",
        ),
        "corrections_30d": _cost(recent, f"corrections in the last {STALE_DAYS} days"),
    }


def _cascades(by_session: dict[str, list[Any]]) -> dict[str, Any]:
    cascades = 0
    for ev in by_session.values():
        run, last = 0, None
        for e in ev:
            if e.event_type != "brain_remember":
                continue
            text = e.payload.get("text", "")
            run = run + 1 if text == last else 1
            last = text
            if run == 3:
                cascades += 1
    return _ratio(
        cascades,
        len(by_session),
        "sessions with the same write repeated three times in a row (lower is better)",
    )


def _decision(vault: VaultStore, pending: list[list[str]]) -> dict[str, dict[str, Any]]:
    decisions = vault.read("decision", limit=10_000)
    classified = sum(1 for r in decisions if r.extra.get("classification"))
    return {
        "classified": _ratio(classified, len(decisions), "decisions carrying a classification"),
        "pending": _cost(len(pending), "decisions waiting for the user"),
        "reversals": _pending_signal(
            "reversal rate per classification cell, once outcomes are logged"
        ),
    }


def _metacognition(vault: VaultStore, critique: Path, today: date) -> dict[str, dict[str, Any]]:
    decisions = vault.read("decision", limit=10_000)
    levels = Counter(
        r.extra.get("confidence", "").lower() for r in decisions if r.extra.get("confidence")
    )
    rated = sum(levels.values())
    off_majority = rated - max(levels.values(), default=0)  # 0 when every decision says the same
    upd = _days_since(_frontmatter(critique).get("updated", ""), today)
    return {
        "confidence_spread": _ratio(
            off_majority,
            rated,
            "decisions whose confidence differs from the majority level; zero means decorative",
        ),
        "critique_age_days": _cost(upd, "days since the session critique was rewritten"),
        "calibration": _pending_signal(
            "Brier score of confidence against outcomes, once decisions resolve"
        ),
    }


def _execution(events: list[Any], root: Path, brief: str, today: date) -> dict[str, dict[str, Any]]:
    writes = [e for e in events if e.event_type == "brain_remember"]
    failed = sum(1 for e in writes if e.payload.get("status") in ("failed", "refused"))
    brief_age = _days_since(
        _frontmatter(root / brief).get("updated", "") or _mtime(root / brief), today
    )
    return {
        "write_failures": _ratio(
            failed,
            len(writes),
            "brain_remember calls that failed or were refused (lower is better)",
        ),
        "brief_age_days": _cost(brief_age, "days since brain daily last wrote the brief"),
    }


def _goals(path: Path, today: date) -> dict[str, dict[str, Any]]:
    rows = [r for r in _read(path).splitlines() if r.startswith("|") and not _is_table_chrome(r)]
    missions = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    missions = [m for m in missions if m and m[0] and m[0].lower() != "id"]
    open_ = [
        m for m in missions if len(m) >= 4 and not m[3].lower().startswith(("done", "complete"))
    ]
    stalled = 0
    for m in open_:
        d = _days_since(m[5], today) if len(m) >= 6 else None
        stalled += 1 if d is not None and d > STALLED_DAYS else 0
    return {
        "missions_stalled": _ratio(
            stalled,
            len(open_),
            f"open missions not reviewed for {STALLED_DAYS} days (lower is better)",
        ),
        "missions_open": _cost(len(open_), "missions not done"),
    }


def _user_model(root: Path, today: date) -> dict[str, dict[str, Any]]:
    corrections = _corrections(_read(root / "corrections.md"))
    recent = [c for c in corrections if (today - c[0]).days <= STALE_DAYS]
    social = sum(1 for _d, _t, f in recent if f.get("theme", "").lower() in _SOCIAL_THEMES)
    return {
        "style_corrections": _ratio(
            social,
            len(recent),
            "recent corrections about tone, format or delivery (lower is better)",
        ),
        "profile_age_days": _cost(
            _days_since(_frontmatter(root / "user_profile.md").get("updated", ""), today),
            "days since the user profile changed",
        ),
    }


def _authority(pending: list[list[str]]) -> dict[str, dict[str, Any]]:
    low = sum(
        1 for r in pending if len(r) >= 3 and "reversible" in r[2].lower() and "low" in r[2].lower()
    )
    return {
        "over_escalation": _ratio(
            low,
            len(pending),
            "reversible low-risk items parked in the pending queue (lower is better)",
        ),
        "boundary_violations": _pending_signal(
            "requires-approval actions without a logged approval; needs the harness event log"
        ),
    }


def _eval_slice(data_dir: Path, *types: str) -> dict[str, Any] | None:
    """The last stratified eval (``run_recall.py --out <data_dir>/eval.json``), by slice."""
    path = data_dir / "eval.json"
    if not path.exists():
        return None
    try:
        data = json.loads(_read(path))
    except ValueError:
        return None
    sl = data.get("by_type", {})
    hits = sum(int(sl[t]["hits"]) for t in types if t in sl)
    n = sum(int(sl[t]["n"]) for t in types if t in sl)
    if n == 0:
        return None
    note = f"recall eval {data.get('date', '')} pass^{data.get('runs', 1)}: " + ", ".join(
        f"{t} {sl[t]['hits']}/{sl[t]['n']}" for t in types if t in sl
    )
    return _ratio(hits, n, note)


# ── parsers ───────────────────────────────────────────────────────────────────


def _corrections(text: str) -> list[tuple[date, str, dict[str, str]]]:
    out: list[tuple[date, str, dict[str, str]]] = []
    for ln in text.splitlines():
        if m := _CORRECTION.match(ln):
            try:
                out.append((date.fromisoformat(m.group(1)), m.group(2), {}))
            except ValueError:
                continue
        elif out and (m := _FIELD.match(ln)):
            out[-1][2][m.group(1).lower()] = m.group(2).strip()
    return out


def _pending_rows(exec_text: str) -> list[list[str]]:
    sec = re.split(r"^(?=## )", exec_text, flags=re.M)
    block = next((p for p in sec if p.startswith("## Pending Decisions")), "")
    rows = []
    for ln in block.splitlines()[1:]:
        if ln.startswith("|") and not _is_table_chrome(ln):
            rows.append([c.strip() for c in ln.strip("|").split("|")])
        elif ln.startswith("- ") and ln[2:].strip().lower() not in ("none", ""):
            rows.append([ln[2:].strip()])
    return rows


def _days_since(value: str | None, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(value)).days if value else None
    except ValueError:
        return None


def _mtime(path: Path) -> str:
    return date.fromtimestamp(path.stat().st_mtime).isoformat() if path.exists() else ""
