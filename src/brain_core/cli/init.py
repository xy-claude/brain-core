"""``brain init`` — scaffold a whole agent from the template pack.

The pack lives in ``brain_core/templates/agent/``: brain.yaml, CLAUDE.md, five generic rule
files, three skills, the bash guard hook, ``.mcp.json`` pointing at ``brain serve``, and a vault
skeleton. ``$name``, ``$bank``, ``$owner``, ``$user`` and ``$today`` are substituted in text
files. An optional ``--profile DIR`` is copied over the result last, so a user's own doctrine
(their rules, skills, user profile) overrides the generic default without living in this repo.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from string import Template

import typer

PACK = Path(__file__).resolve().parent.parent / "templates" / "agent"
_TEXT = {".md", ".yaml", ".yml", ".json", ".txt"}
_CORE = ("brain.yaml", "CLAUDE.md", ".mcp.json")  # presence of these means "already an agent"


def init_agent(
    name: str,
    path: Path,
    force: bool,
    *,
    user: str = "the user",
    profile: Path | None = None,
) -> list[Path]:
    """Write the pack into ``path``; return the files written. ``typer.Exit(1)`` on error."""
    name = name.strip()
    if not name:
        typer.echo("Error: name must not be empty.", err=True)
        raise typer.Exit(code=1)
    target = path.resolve()
    if not force and any((target / f).exists() for f in _CORE):
        typer.echo(
            f"Error: an agent already exists at {target} ({', '.join(_CORE)}). Use --force.",
            err=True,
        )
        raise typer.Exit(code=1)
    if profile is not None and not profile.is_dir():
        typer.echo(f"Error: profile {profile} is not a directory.", err=True)
        raise typer.Exit(code=1)

    subs = {
        "name": name,
        "bank": f"{name.lower()}-brain",
        "owner": name.lower(),
        "user": user,
        "today": date.today().isoformat(),
    }
    written: list[Path] = []
    for src in sorted(p for p in PACK.rglob("*") if p.is_file()):
        rel = src.relative_to(PACK)
        # stored as _gitignore so the pack's own ignore rules do not apply inside this repo
        dest = target / (rel.with_name(".gitignore") if rel.name == "_gitignore" else rel)
        if rel.parts[0] == "vault" and dest.exists():
            continue  # --force refreshes rules and skills, never the user's memory
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in _TEXT:
            dest.write_text(
                Template(src.read_text(encoding="utf-8")).safe_substitute(subs), encoding="utf-8"
            )
        else:
            shutil.copyfile(src, dest)
        if src.suffix == ".sh":
            dest.chmod(0o755)
        written.append(dest)
    if profile is not None:
        for src in sorted(p for p in profile.rglob("*") if p.is_file()):
            dest = target / src.relative_to(profile)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            written.append(dest)

    typer.echo(f"Agent '{name}' written to {target}: {len(written)} files")
    typer.echo(f"  memory: vault/ · data/brain.db · Hindsight bank {subs['bank']}")
    typer.echo("  next: `brain doctor` here, then open Claude Code in this folder")
    return written
