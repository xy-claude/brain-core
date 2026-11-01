"""``brain init`` — scaffold a new agent repo.

Exposes :func:`init_agent` as the pure implementation; the ``typer`` command
lives in :mod:`brain_core.cli.main`.
"""

from __future__ import annotations

from pathlib import Path

import typer

from brain_core.cli.templates import BRAIN_YAML, CLAUDE_MD, GITIGNORE, MCP_JSON


def init_agent(name: str, path: Path, force: bool) -> None:
    """Scaffold a new brain-core agent repo.

    Writes brain.yaml, CLAUDE.md, .mcp.json, .gitignore and creates data/.
    Raises :class:`typer.Exit` with non-zero code on any failure.
    """
    if not name.strip():
        typer.echo("Error: name must not be empty.", err=True)
        raise typer.Exit(code=1)

    target = path.resolve()
    target.mkdir(parents=True, exist_ok=True)

    files = {
        "brain.yaml": BRAIN_YAML.substitute(name=name),
        "CLAUDE.md": CLAUDE_MD.substitute(name=name),
        ".mcp.json": MCP_JSON.substitute(name=name),
        ".gitignore": GITIGNORE.substitute(name=name),
    }

    if not force:
        existing = [f for f in files if (target / f).exists()]
        if existing:
            typer.echo(
                f"Error: these files already exist: {existing}. Use --force to overwrite.",
                err=True,
            )
            raise typer.Exit(code=1)

    for filename, content in files.items():
        (target / filename).write_text(content, encoding="utf-8")
        typer.echo(f"  created {filename}")

    (target / "data").mkdir(exist_ok=True)
    typer.echo("  created data/")

    typer.echo(f"\nAgent '{name}' scaffolded at {target}")
    typer.echo("")
    typer.echo("Next steps:")
    typer.echo("  1. Review brain.yaml and CLAUDE.md")
    typer.echo("  2. pip install brain-core")
    typer.echo("  3. Start building — see CLAUDE.md for the Agent API")
