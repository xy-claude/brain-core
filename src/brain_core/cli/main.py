"""``brain`` CLI — top-level app wiring the subcommands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from brain_core import __version__
from brain_core.agent import Agent
from brain_core.cli.doctor import doctor_agent
from brain_core.cli.export import export_agent
from brain_core.cli.init import init_agent

app = typer.Typer(
    help="brain-core — cognitive primitives for AI agents.",
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
        typer.Option("--force", "-f", help="Overwrite an existing agent in that directory."),
    ] = False,
    user: Annotated[
        str, typer.Option("--user", help="How the agent addresses its user, e.g. 'Sir'.")
    ] = "the user",
    profile: Annotated[
        Path | None,
        typer.Option("--profile", help="Directory copied over the generic pack (your own rules)."),
    ] = None,
) -> None:
    """Write a whole agent: brain.yaml, CLAUDE.md, rules, skills, hooks, .mcp.json, vault."""
    init_agent(name=name, path=path, force=force, user=user, profile=profile)


@app.command("daily")
def daily_cmd(
    path: Annotated[Path, typer.Argument(help="Agent directory or brain.yaml.")] = Path(),
) -> None:
    """Tier 1 cron: write the daily brief, a health line, and back up Hindsight."""
    from brain_core.cron import daily

    with _open(path) as agent:
        out = daily(agent)
    typer.echo(f"brief: {out['brief']} (~{out['brief_tokens']} tokens)")
    typer.echo(f"health: {out['health']}")
    typer.echo(f"backup: {out['backup']}")


@app.command("weekly")
def weekly_cmd(
    path: Annotated[Path, typer.Argument(help="Agent directory or brain.yaml.")] = Path(),
) -> None:
    """Tier 2 cron: archive sessions older than 30 days, refresh Hindsight mental models."""
    from brain_core.cron import weekly

    with _open(path) as agent:
        out = weekly(agent)
    typer.echo(f"archived: {out['archived'] or 'nothing'}")
    typer.echo(f"mental models: {out['mental_models']}")


@app.command("cron")
def cron_cmd(
    action: Annotated[str, typer.Argument(help="install | uninstall | status")],
    path: Annotated[Path, typer.Argument(help="Agent directory or brain.yaml.")] = Path(),
    launch_dir: Annotated[
        Path | None,
        typer.Option(
            "--launch-dir", help="Where to write plists (default ~/Library/LaunchAgents)."
        ),
    ] = None,
    no_load: Annotated[
        bool, typer.Option("--no-load", help="Write plists without launchctl.")
    ] = False,
) -> None:
    """Register `brain daily` and `brain weekly` with launchd (macOS)."""
    from brain_core import cron

    with _open(path) as agent:
        if action == "install":
            for p in cron.install(agent, launch_dir, load=not no_load):
                typer.echo(f"  wrote {p}")
        elif action == "uninstall":
            for p in cron.uninstall(agent, launch_dir):
                typer.echo(f"  removed {p}")
        elif action == "status":
            base = launch_dir or Path("~/Library/LaunchAgents").expanduser()
            for suffix in ("daily", "weekly"):
                plist = base / f"io.brain-core.{agent.name.lower()}.{suffix}.plist"
                state = "installed" if plist.exists() else "not installed"
                typer.echo(f"  {suffix}: {state} ({plist})")
        else:
            typer.echo("action must be install | uninstall | status", err=True)
            raise typer.Exit(code=1)


def _open(path: Path) -> Agent:
    cfg = path if path.is_file() else path / "brain.yaml"
    if not cfg.exists():
        typer.echo(f"ERROR: no brain.yaml at {cfg}", err=True)
        raise typer.Exit(code=1)
    return Agent.from_config(cfg)


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


@app.command("serve")
def serve_cmd(
    path: Annotated[
        Path,
        typer.Argument(help="Path to agent directory (contains brain.yaml)."),
    ] = Path(),
) -> None:
    """Run the MCP server for the agent at ``path``.

    Requires the ``mcp`` extra: ``pip install brain-core[mcp]``.
    """
    config_path = path if path.is_file() else path / "brain.yaml"  # a dir, or a yaml file
    if not config_path.exists():
        typer.echo(f"ERROR: no brain.yaml at {config_path}", err=True)
        raise typer.Exit(code=1)

    try:
        from brain_core.mcp.server import run_server
    except ImportError as e:
        typer.echo(
            "ERROR: MCP extras not installed. Run: pip install 'brain-core[mcp]'",
            err=True,
        )
        raise typer.Exit(code=1) from e

    run_server(config_path)


@app.command("version")
def version_cmd() -> None:
    """Print the installed brain-core version."""
    typer.echo(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
