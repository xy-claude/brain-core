"""``brain_status``: the agent's health in one call.

Store reachability, knowledge-wiki lint counts, always-loaded context size, last session
close state, and pending decisions. No LLM, no network beyond each store's own health probe.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from brain_core.session import _marker, _sections
from brain_core.stores.vault import VaultStore

if TYPE_CHECKING:
    from brain_core.agent import Agent

_LINK = re.compile(r"\[\[(?:[^\]|]*/)?([^\]|#]+)")
_FM = re.compile(r"^---\n(.*?)\n---", re.S)


def brain_status(agent: Agent) -> dict[str, Any]:
    out: dict[str, Any] = {"agent": agent.name, "ok": True, "stores": {}}
    for s in agent.stores:
        try:
            ok, detail = s.health()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {str(e)[:120]}"
        out["stores"][s.name] = {"ok": ok, "detail": detail}
        out["ok"] = out["ok"] and ok
    vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
    if vault is not None:
        out["knowledge"] = lint(vault.root)
        pending = _sections(
            _read(vault.root / agent.config.session.executive), ("Pending Decisions",)
        )
        out["pending_decisions"] = sum(
            1
            for ln in pending.splitlines()[1:]
            if ln.startswith("- ") or (ln.startswith("|") and not _is_table_chrome(ln))
        )
    out["context"] = _context(agent)
    marker = _marker(agent)
    last_close = marker.read_text().strip() if marker.exists() else ""
    starts = agent.recent_events(event_type="session_start", limit=1)
    last_start = str(starts[0].payload.get("session_id", "")) if starts else ""
    out["session"] = {
        "last_start": last_start,
        "last_close": last_close,
        "current": agent.current_session,
        "unclosed": bool(last_start)
        and last_start != last_close
        and last_start != agent.current_session,
    }
    if out["knowledge"].get("issues") if vault else False:
        out["ok"] = False
    return out


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
        if "sources" not in fm and "## Source" not in p.read_text(
            encoding="utf-8", errors="replace"
        ):
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
            files[str(Path(f).relative_to(base)) if str(f).startswith(str(base)) else f] = (
                len(Path(f).read_bytes()) // 4
            )
    return {"tokens": sum(files.values()), "files": files}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


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
