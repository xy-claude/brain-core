"""``brain doctor`` — health check an agent's state.

Exposes :func:`doctor_agent` as the pure implementation.
"""

from __future__ import annotations

from pathlib import Path

import typer

from central_brain.agent import Agent

_ROW_COUNT_TABLES = (
    "facts",
    "decisions",
    "events",
    "reflections",
    "hsam_days",
    "metrics",
)


def doctor_agent(path: Path) -> None:
    """Run a health check on an agent at ``path``.

    Exits non-zero on missing brain.yaml, invalid config, or DB access error.
    """
    config_path = path / "brain.yaml"
    if not config_path.exists():
        typer.echo(f"ERROR: no brain.yaml at {config_path}", err=True)
        raise typer.Exit(code=1)

    try:
        agent = Agent.from_config(config_path)
    except Exception as e:
        typer.echo(f"ERROR: failed to load agent: {e}", err=True)
        raise typer.Exit(code=1) from e

    try:
        typer.echo(f"Agent: {agent.name}")
        typer.echo(f"  config: {config_path}")
        typer.echo(f"  data_dir: {agent.data_dir}")
        typer.echo(f"  capabilities: {', '.join(agent.config.capabilities)}")
        typer.echo("")
        typer.echo("Row counts:")
        for table in _ROW_COUNT_TABLES:
            row = agent.db.fetchone(f"SELECT COUNT(*) AS n FROM {table}")
            count = int(row["n"]) if row is not None else 0
            typer.echo(f"  {table:<12} {count:>6}")

        if agent.config.memory.hsam.enabled:
            typer.echo("")
            hsam_row = agent.db.fetchone(
                "SELECT COUNT(*) AS days, COALESCE(SUM(word_count), 0) AS words FROM hsam_days"
            )
            if hsam_row is not None:
                typer.echo(
                    f"HSAM: {int(hsam_row['days'])} days archived, "
                    f"{int(hsam_row['words'])} words total"
                )

        typer.echo("")
        typer.echo("Health check: OK")
    finally:
        agent.close()
