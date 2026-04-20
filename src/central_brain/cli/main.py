"""``brain`` CLI — top-level app wiring the subcommands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from central_brain import __version__
from central_brain.cli.doctor import doctor_agent
from central_brain.cli.export import export_agent
from central_brain.cli.init import init_agent

app = typer.Typer(
    help="central-brain — cognitive primitives for AI agents.",
    no_args_is_help=True,
)


@app.command("init")
def init_cmd(
    name: Annotated[str, typer.Argument(help="Agent name (used in brain.yaml + CLAUDE.md).")],
    path: Annotated[
        Path,
        typer.Option(
            "--path",
            "-p",
            help="Directory to scaffold into. Created if missing.",
        ),
    ] = Path(),
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing scaffold files."),
    ] = False,
) -> None:
    """Scaffold a new agent repo (brain.yaml + CLAUDE.md + .mcp.json + data/)."""
    init_agent(name=name, path=path, force=force)


@app.command("doctor")
def doctor_cmd(
    path: Annotated[
        Path,
        typer.Argument(help="Path to agent directory (contains brain.yaml)."),
    ] = Path(),
) -> None:
    """Run a health check on an agent: config validates, DB reachable, row counts."""
    doctor_agent(path=path)


@app.command("export")
def export_cmd(
    path: Annotated[
        Path,
        typer.Argument(help="Path to agent directory (contains brain.yaml)."),
    ] = Path(),
    fact_limit: Annotated[int, typer.Option("--fact-limit", help="Max facts to include.")] = 100,
    decision_limit: Annotated[
        int, typer.Option("--decision-limit", help="Max decisions to include.")
    ] = 50,
    event_limit: Annotated[
        int, typer.Option("--event-limit", help="Max recent events to include.")
    ] = 50,
) -> None:
    """Dump agent state to stdout as human-readable markdown."""
    export_agent(
        path=path,
        fact_limit=fact_limit,
        decision_limit=decision_limit,
        event_limit=event_limit,
    )


@app.command("version")
def version_cmd() -> None:
    """Print the installed central-brain version."""
    typer.echo(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
