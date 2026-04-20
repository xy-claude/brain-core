"""``brain export`` — dump agent state as human-readable markdown.

Exposes :func:`export_agent` as the pure implementation.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import typer

from central_brain.agent import Agent
from central_brain.memory.structured import Fact


def export_agent(
    path: Path,
    fact_limit: int = 100,
    decision_limit: int = 50,
    event_limit: int = 50,
) -> None:
    """Dump agent state at ``path`` to stdout as markdown.

    Exits non-zero if brain.yaml is missing or invalid.
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
        caps = agent.config.capabilities
        lines: list[str] = [
            f"# {agent.name}",
            "",
            f"_Exported from {agent.data_dir}_",
            "",
            f"**Capabilities:** {', '.join(caps)}",
            "",
        ]

        if "memory" in caps:
            lines.extend(_facts_section(agent, fact_limit))

        if "decisions" in caps:
            lines.extend(_decisions_section(agent, decision_limit))

        if "memory" in caps:
            lines.extend(_events_section(agent, event_limit))

        typer.echo("\n".join(lines))
    finally:
        agent.close()


def _facts_section(agent: Agent, limit: int) -> list[str]:
    facts = agent.recall(limit=limit)
    lines: list[str] = ["## Facts", ""]
    if not facts:
        lines.append("_No facts remembered yet._")
        lines.append("")
        return lines

    by_kind: dict[str, list[Fact]] = defaultdict(list)
    for f in facts:
        by_kind[f.kind].append(f)

    for kind in sorted(by_kind):
        items = by_kind[kind]
        lines.append(f"### {kind} ({len(items)})")
        lines.append("")
        for f in items:
            tags_suffix = f"  _tags: {', '.join(f.tags)}_" if f.tags else ""
            lines.append(f"- {f.content}{tags_suffix}")
        lines.append("")
    return lines


def _decisions_section(agent: Agent, limit: int) -> list[str]:
    decisions = agent.list_decisions(limit=limit)
    lines: list[str] = ["## Decisions", ""]
    if not decisions:
        lines.append("_No decisions logged yet._")
        lines.append("")
        return lines

    for d in decisions:
        reversibility = "reversible" if d.reversible else "IRREVERSIBLE"
        header = (
            f"- **[{d.status}]** {d.action} _({reversibility}, risk={d.risk}, conf={d.confidence})_"
        )
        lines.append(header)
        if d.reasoning:
            lines.append(f"    - reasoning: {d.reasoning}")
        if d.reversed_by is not None:
            lines.append(f"    - replaced by decision #{d.reversed_by}")
    lines.append("")
    return lines


def _events_section(agent: Agent, limit: int) -> list[str]:
    events = agent.recent_events(limit=limit)
    lines: list[str] = ["## Recent events", ""]
    if not events:
        lines.append("_No events logged yet._")
        lines.append("")
        return lines

    for e in events:
        session = f" session={e.session_id}" if e.session_id else ""
        lines.append(f"- `{e.occurred_at.isoformat()}` **{e.event_type}**{session}")
    lines.append("")
    return lines
