"""``brain_session``: the START block and the END writes in one call each.

START reads what cron and the last session left behind (daily brief, executive state, mental
models, inbox) and recalls the active missions. END drains the Hindsight queue, finalises the
HSAM day file, rewrites critique and cross-agent sync (from the agent's text or a stub built
from this session's ``brain_remember`` events), and writes the clean-close marker.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from brain_core.stores.hindsight import HindsightStore
from brain_core.stores.vault import _SECRET, VaultStore, _Lock
from brain_core.stores.vault import read_text as _read

if TYPE_CHECKING:
    from brain_core.agent import Agent

START_TOKENS = 6_000
_SECTION = re.compile(r"^## (.+)$", re.M)
_BRIEF_DATE = re.compile(r"Daily Brief — (\d{4}-\d{2}-\d{2})")


def session_start(agent: Agent, session_id: str | None = None) -> dict[str, Any]:
    today = date.today()
    sid = session_id or f"s-{today.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
    cfg, vault = agent.config.session, _vault(agent)
    prev = agent.recent_events(event_type="session_start", limit=1)
    marker = _marker(agent)
    last_close = marker.read_text().strip() if marker.exists() else ""
    recovery = None
    if prev and prev[0].payload.get("session_id") not in (last_close, sid):
        recovery = {
            "unclosed": prev[0].payload.get("session_id"),
            "started": prev[0].occurred_at.isoformat(),
        }
    agent.start_session(sid)
    agent.log_event("session_start", {"session_id": sid})
    _snapshot_traits(agent, sid)

    out: dict[str, Any] = {"session_id": sid, "date": today.isoformat(), "recovery": recovery}
    if vault is None:
        out["note"] = "no vault configured (stores.vault); only recovery state available"
        return out
    brief = _read(vault.root / cfg.brief)
    m = _BRIEF_DATE.search(brief)
    out["brief"] = brief or f"missing: {cfg.brief}"
    out["brief_stale"] = m is not None and (today - date.fromisoformat(m.group(1))).days > 1
    exec_text = _read(vault.root / cfg.executive)
    out["executive_state"] = _sections(
        exec_text, ("Primary Objective", "Top Missions", "Pending Decisions")
    )
    inbox = _read(vault.root / cfg.inbox)
    out["inbox"] = (
        0
        if "**Empty**" in inbox
        else sum(1 for ln in inbox.splitlines() if ln.startswith(("- ", "### ")))
    )
    out["mental_models"] = _mental_models(agent, cfg.mental_models)
    missions = _mission_lines(exec_text)
    out["missions"] = {q: agent.brain_recall(q, limit=3)["results"] for q in missions[:2]}
    _cap(out, START_TOKENS)
    return out


def session_end(
    agent: Agent,
    session_id: str | None = None,
    *,
    executive_state: str | None = None,
    critique: str | None = None,
    sync: str | None = None,
) -> dict[str, Any]:
    sid = session_id or agent.current_session
    if not sid:
        raise ValueError("no active session: pass session_id or call brain_session('start') first")
    today, now = date.today(), datetime.now().strftime("%H:%M")
    cfg, vault = agent.config.session, _vault(agent)
    writes = [
        e.payload
        for e in agent.recent_events(session_id=sid, event_type="brain_remember", limit=500)
    ]
    out: dict[str, Any] = {"session_id": sid, "writes": len(writes)}
    out["queue_drained"] = _drain_queue(agent, cfg.queue)
    if vault is not None:
        kinds = ", ".join(f"{k}×{n}" for k, n in sorted(_count(writes).items())) or "none"
        out["traits_moved"] = _traits_moved(agent, sid)
        moved = f", {len(out['traits_moved'])} trait signal(s) moved" if out["traits_moved"] else ""
        hs = vault.write(
            "note",
            f"Session {sid} closed {now}: {len(writes)} brain writes ({kinds}){moved}",
            when=today,
        )
        out["hsam"] = hs.status
        out["executive_state"] = _put(
            vault, cfg.executive, executive_state, today, "unchanged (pass executive_state=...)"
        )
        out["critique"] = _put(
            vault,
            cfg.critique,
            critique or _critique_stub(sid, writes, today),
            today,
            "",
            stub=critique is None,
        )
        out["sync"] = _put(
            vault,
            cfg.sync,
            sync or _sync_stub(agent.name, writes, today),
            today,
            "",
            stub=sync is None,
        )
    marker = _marker(agent)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(sid + "\n")
    out["marker"] = str(marker)
    agent.log_event("session_end", {"session_id": sid, "writes": len(writes)})
    agent.end_session()
    return out


# ── helpers ───────────────────────────────────────────────────────────────────


def _trait_values(agent: Agent) -> dict[str, list[int]]:
    """Defensible signals as {trait.signal: [value, n]}, from files only (no store probes)."""
    from brain_core import traits
    from brain_core.status import lint

    vault = _vault(agent)
    if vault is None:
        return {}
    st = {"knowledge": lint(vault.root)}
    out: dict[str, list[int]] = {}
    for tid, t in traits.compute(agent, st).items():
        for sid, s in t["signals"].items():
            if s["verdict"] == "defensible" and s.get("n"):
                out[f"{tid}.{sid}"] = [s["value"], s["n"]]
    return out


def _snapshot_traits(agent: Agent, sid: str) -> None:
    path = agent.data_dir / "traits_start.json"
    with contextlib.suppress(Exception):  # a snapshot must never block a session start
        path.write_text(json.dumps({"session_id": sid, "values": _trait_values(agent)}))


def _traits_moved(agent: Agent, sid: str) -> list[str]:
    path = agent.data_dir / "traits_start.json"
    if not path.exists():
        return []
    try:
        start = json.loads(_read(path))
    except ValueError:
        return []
    if start.get("session_id") != sid:
        return []
    before, after = start.get("values", {}), _trait_values(agent)
    moved = []
    for key, (v, n) in after.items():
        b = before.get(key)
        if b is None or (b[0], b[1]) != (v, n):
            moved.append(
                f"{key}: {b[0]}/{b[1] if b else 0} → {v}/{n}" if b else f"{key}: new {v}/{n}"
            )
    return moved


def _vault(agent: Agent) -> VaultStore | None:
    return next((s for s in agent.stores if isinstance(s, VaultStore)), None)


def _hindsight(agent: Agent) -> HindsightStore | None:
    return next((s for s in agent.stores if isinstance(s, HindsightStore)), None)


def _marker(agent: Agent) -> Path:
    m = agent.config.session.marker
    return agent.resolve(m) if m else agent.data_dir / "last_close.txt"


def _sections(text: str, wanted: tuple[str, ...]) -> str:
    parts, keep = re.split(r"^(?=## )", text, flags=re.M), []
    for p in parts:
        if any(p.startswith(f"## {w}") for w in wanted):
            keep.append(p.rstrip())
    return "\n\n".join(keep)


def _mission_lines(exec_text: str) -> list[str]:
    block = _sections(exec_text, ("Top Missions",))
    out = []
    for ln in block.splitlines()[1:]:
        ln = re.sub(r"[*_`|#]+", " ", ln).strip(" -")
        if len(ln) > 8 and not ln.lower().startswith(("mission", "status")):
            out.append(" ".join(ln.split()[:12]))
    return out


def _mental_models(agent: Agent, ids: list[str]) -> dict[str, str]:
    h = _hindsight(agent)
    if h is None:
        return {"note": "hindsight not configured"}
    out: dict[str, str] = {}
    for mid in ids:
        try:
            r = h.call("get_mental_model", mental_model_id=mid)
            body = (
                r.get("content") or r.get("summary") or r.get("text") if isinstance(r, dict) else r
            )
            out[mid] = str(body or r)[:1500]
        except Exception as e:
            out[mid] = f"error: {type(e).__name__}: {str(e)[:120]}"
    return out


def _cap(out: dict[str, Any], max_tokens: int) -> None:
    for key in ("brief", "missions", "mental_models", "executive_state"):
        if len(json.dumps(out, default=str)) // 4 <= max_tokens:
            return
        if key == "brief" and isinstance(out.get(key), str):
            out[key] = out[key][: max_tokens * 2] + "\n…(brief cut; open the file for the rest)"
        else:
            out[key] = (
                f"omitted to stay under {max_tokens} tokens; read the file or call brain_recall"
            )
    out["note"] = "start block capped; sections replaced with pointers"


def _drain_queue(agent: Agent, queue: str | None) -> int:
    if not queue:
        return 0
    path = agent.resolve(queue)
    if not path.exists():
        return 0
    with _Lock(path.with_name(f".{path.name}.lock")):
        return _drain_locked(agent, path)


def _drain_locked(agent: Agent, path: Path) -> int:
    h = _hindsight(agent)
    mine: list[str] = []
    others: list[str] = []
    drained = 0
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            others.append(ln)
            continue
        (mine if str(e.get("agent", "")).lower() == agent.name.lower() else others).append(ln)
    for ln in mine:
        e = json.loads(ln)
        if _SECRET.search(str(e.get("content", ""))):
            continue  # a queued secret is dropped, never retained or kept on disk
        if h is None:
            others.append(ln)  # keep it; nothing to drain into
            continue
        try:
            h.call(
                "retain",
                content=e["content"],
                context=e.get("context", "hsam-conversation"),
                tags=e.get("tags", []),
                document_id=e.get("document_id", f"session-{date.today().isoformat()}"),
            )
            drained += 1
        except Exception:
            others.append(ln)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(others) + ("\n" if others else ""), encoding="utf-8")
    os.replace(tmp, path)  # a crash mid-write must not truncate the queue
    return drained


def _put(
    vault: VaultStore, rel: str, body: str | None, today: date, unchanged: str, stub: bool = False
) -> str:
    if body is None:
        return unchanged
    if _SECRET.search(body):
        return "refused: looks like it contains a secret"
    fm = (
        f"---\ntype: log\nowner: {vault.owner}\ndomain: system\nstatus: active\n"
        f"updated: {today.isoformat()}\n---\n"
    )
    vault._save(vault.root / rel, fm + body.strip() + "\n", today)
    return "stub" if stub else "rewritten"


def _count(writes: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for w in writes:
        out[w.get("kind", "?")] = out.get(w.get("kind", "?"), 0) + 1
    return out


def _critique_stub(sid: str, writes: list[dict[str, Any]], today: date) -> str:
    changed = [w for w in writes if w.get("contradiction")]
    return (
        f"# Session Critique — {today.isoformat()}\n\n## What Went Well\n"
        f"- {len(writes)} brain writes through brain_remember in session {sid}.\n\n"
        f"## What To Improve\n- (stub: the agent did not pass critique=...)\n\n"
        f"## Facts Changed\n"
        + ("".join(f"- {w.get('text', '')[:160]}\n" for w in changed) or "- none\n")
    )


def _sync_stub(agent_name: str, writes: list[dict[str, Any]], today: date) -> str:
    decisions = [w.get("text", "")[:140] for w in writes if w.get("kind") == "decision"][:4]
    changed = [w.get("text", "")[:140] for w in writes if w.get("contradiction")][:4]
    return (
        f"## {agent_name} — Session Sync ({today.isoformat()})\n"
        f"**Key decisions:** {'; '.join(decisions) or 'none logged'}\n"
        f"**Facts changed:** {'; '.join(changed) or 'none'}\n"
        f"**Status:** {len(writes)} brain writes this session.\n"
    )
