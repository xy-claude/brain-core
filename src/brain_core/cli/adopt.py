"""``brain adopt``: put an existing Claude Code agent folder on brain-core without touching
its CLAUDE.md, skills or vault. Writes brain.yaml, adds the ``brain`` MCP server, merges the
four hooks, renders the memory rule, then backfills the SQLite index. Idempotent: every step
reports written | kept."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from string import Template
from typing import Any

from brain_core.cli.init import PACK

HOOKS: dict[str, str] = {
    "SessionStart": "brief --hook",
    "Stop": "capture",
    "PreCompact": "capture",
    "PostToolUseFailure": "recall --hook",
}


def adopt_agent(
    path: Path,
    *,
    name: str,
    user: str,
    vault: Path,
    bank: str | None,
    hindsight_url: str = "http://127.0.0.1:8888",
    mental_models: list[str] | None = None,
    peers: str | None = None,
    queue: str | None = None,
    marker: str | None = None,
    transcripts: str = "~/.claude/projects",
    rules: list[str] | None = None,
    brain_bin: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    path = path.resolve()
    out: dict[str, Any] = {}
    cfg = path / "brain.yaml"
    if cfg.exists() and not force:
        out["brain.yaml"] = "kept"
    else:
        cfg.write_text(
            _yaml(
                name,
                vault,
                bank,
                hindsight_url,
                mental_models or [],
                peers,
                queue,
                marker,
                transcripts,
                path,
            ),
            encoding="utf-8",
        )
        out["brain.yaml"] = "written"

    binary = brain_bin or _this_brain()
    mcp = path / ".mcp.json"
    servers = json.loads(mcp.read_text()) if mcp.exists() else {"mcpServers": {}}
    if "brain" in servers.setdefault("mcpServers", {}) and not force:
        out[".mcp.json"] = "kept"
    else:
        servers["mcpServers"]["brain"] = {"command": binary, "args": ["serve", str(cfg)]}
        mcp.write_text(json.dumps(servers, indent=2) + "\n", encoding="utf-8")
        out[".mcp.json"] = "written"

    local = path / ".claude" / "settings.local.json"
    target = local if local.exists() else path / ".claude" / "settings.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    settings = json.loads(target.read_text()) if target.exists() else {}
    hooks = settings.setdefault("hooks", {})
    added = []
    for event, sub in HOOKS.items():
        cmd = f'"{binary}" {sub} --path "{cfg}" 2>/dev/null || true'
        groups = hooks.setdefault(event, [])
        if any(
            f" {sub} " in h.get("command", "") and "brain" in h.get("command", "")
            for g in groups
            for h in g.get("hooks", [])
        ):
            continue
        groups.append({"hooks": [{"type": "command", "command": cmd}]})
        added.append(event)
    if added:
        target.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    out[target.name] = f"hooks added: {', '.join(added)}" if added else "kept"

    subs = {"name": name, "user": user, "bank": bank or "", "today": date.today().isoformat()}
    rendered = []
    for rule in rules if rules is not None else ["04-memory.md"]:
        src = PACK / ".claude" / "rules" / rule
        dest = path / ".claude" / "rules" / rule
        if dest.exists() and not force:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            Template(src.read_text(encoding="utf-8")).safe_substitute(subs), encoding="utf-8"
        )
        rendered.append(rule)
    out["rules"] = f"rendered: {', '.join(rendered)}" if rendered else "kept"
    return out


def _this_brain() -> str:
    exe = Path(sys.argv[0]).resolve()
    if exe.name == "brain":
        return str(exe)
    sibling = Path(sys.executable).resolve().parent / "brain"
    return str(sibling) if sibling.exists() else "brain"


def _yaml(
    name: str,
    vault: Path,
    bank: str | None,
    url: str,
    models: list[str],
    peers: str | None,
    queue: str | None,
    marker: str | None,
    transcripts: str,
    path: Path,
) -> str:
    lines = [
        f"# {name} — written by `brain adopt` on {date.today().isoformat()}. "
        "Edit freely; `brain doctor` validates it.",
        f"name: {name}",
        "workspace:",
        "  data_dir: ./data",
        "stores:",
        f"  vault: {vault}",
    ]
    if bank:
        lines += ["  hindsight:", f"    url: {url}", f"    bank: {bank}"]
    lines += [
        f"  transcripts: {transcripts}",
        f"  transcripts_cwd: {path}",
        "session:",
        f"  mental_models: [{', '.join(models)}]",
    ]
    if peers:
        lines.append(f"  peers: ['{peers}']")
    lines.append(f"  queue: {queue or './data/hindsight_queue.jsonl'}")
    lines.append(f"  marker: {marker or './data/last_close.txt'}")
    lines += ["status:", "  context_files: [CLAUDE.md, .claude/rules/*.md]"]
    return "\n".join(lines) + "\n"
