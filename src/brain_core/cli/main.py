"""``brain`` CLI — top-level app wiring the subcommands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from brain_core import __version__
from brain_core.agent import Agent
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
        str, typer.Option("--user", help="How the agent addresses its user, e.g. 'Alex'.")
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
            for job, state in cron.status(agent, launch_dir).items():
                typer.echo(f"  {job}: {state}")
        else:
            typer.echo("action must be install | uninstall | status", err=True)
            raise typer.Exit(code=1)


def _open(path: Path) -> Agent:
    cfg = path if path.is_file() else path / "brain.yaml"
    if not cfg.exists():
        typer.echo(f"ERROR: no brain.yaml at {cfg}", err=True)
        raise typer.Exit(code=1)
    return Agent.from_config(cfg)


@app.command("hindsight")
def hindsight_cmd(
    action: Annotated[str, typer.Argument(help="install | status")],
    dashboard: Annotated[
        bool, typer.Option("--dashboard", help="Also install the control-plane UI on :9999.")
    ] = False,
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help="LLM provider: anthropic (default) | openai | claude-code (personal use only)",
        ),
    ] = "anthropic",
    model: Annotated[str, typer.Option("--model")] = "claude-sonnet-5-5",
    api_key_env: Annotated[
        str | None, typer.Option("--api-key-env", help="Env var holding the provider key.")
    ] = None,
    port: Annotated[int, typer.Option("--port")] = 8888,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Write plists only; no install, no launchctl.")
    ] = False,
    launch_dir: Annotated[
        Path | None, typer.Option("--launch-dir", help="Default ~/Library/LaunchAgents.")
    ] = None,
) -> None:
    """Install the self-hosted Hindsight server as a launchd service, or report its health."""
    from brain_core import installer

    if action == "status":
        typer.echo(f"hindsight on :{port}: {'healthy' if installer.health(port) else 'DOWN'}")
        return
    if action != "install":
        typer.echo("action must be install | status", err=True)
        raise typer.Exit(code=1)
    out = installer.install_hindsight(
        port=port,
        provider=provider,
        model=model,
        api_key_env=api_key_env,
        dashboard=dashboard,
        run=not dry_run,
        launch_dir=launch_dir,
    )
    for k, v in out.items():
        typer.echo(f"  {k}: {v}")
    if out.get("service", "").startswith("not healthy"):
        raise typer.Exit(code=1)


@app.command("graph")
def graph_cmd(
    action: Annotated[str, typer.Argument(help="import | stats")],
    path: Annotated[Path, typer.Argument(help="Agent directory or brain.yaml.")] = Path(),
    dump: Annotated[
        Path | None, typer.Option("--dump", help="File in `S —[p]→ O  (YYYY-MM-DD)` format.")
    ] = None,
) -> None:
    """Entity graph in brain.db. `import` loads a dump, or the legacy Kuzu graph from brain.yaml."""
    import subprocess

    from brain_core.stores.graph import GraphStore

    with _open(path) as agent:
        g = GraphStore(agent.db)
        if action == "stats":
            typer.echo(g.health()[1])
            return
        if action != "import":
            typer.echo("action must be import | stats", err=True)
            raise typer.Exit(code=1)
        if dump is not None:
            text = dump.read_text(encoding="utf-8")
        elif agent.config.stores.graph is not None:
            legacy = agent.config.stores.graph
            cp = subprocess.run(
                [str(Path(legacy.python).expanduser()), str(agent.resolve(legacy.script)), "all"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if cp.returncode != 0:
                typer.echo(f"ERROR: legacy graph dump failed: {cp.stderr[-200:]}", err=True)
                raise typer.Exit(code=1)
            text = cp.stdout
        else:
            typer.echo("ERROR: pass --dump FILE or set stores.graph in brain.yaml", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"import: {g.import_dump(text)}")


@app.command("doctor")
def doctor_cmd(
    path: Annotated[
        Path,
        typer.Argument(help="Path to agent directory (contains brain.yaml)."),
    ] = Path(),
) -> None:
    """Health check: brain_status in one call (stores, lint, context, session)."""
    with _open(path) as agent:
        typer.echo(f"Agent: {agent.name}  config: {agent.config_path}")
        st = agent.brain_status()
    for name, s in st["stores"].items():
        typer.echo(f"  store {name:9} {'OK  ' if s['ok'] else 'DOWN'} {s['detail'][:70]}")
    k = st.get("knowledge", {})
    typer.echo(
        f"  knowledge  {k.get('pages', 0)} pages, {k.get('raw', 0)} raw, "
        f"{k.get('issue_count', 0)} lint issue(s)"
    )
    typer.echo(f"  context    {st['context']['tokens']} always-loaded tokens")
    ses = st["session"]
    flag = "  UNCLOSED" if ses["unclosed"] else ""
    typer.echo(
        f"  session    last start {ses['last_start'] or '-'} · "
        f"last close {ses['last_close'] or '-'}{flag}"
    )
    typer.echo(f"  pending    {st.get('pending_decisions', 0)} decision(s)")
    grown = [t["name"] for t in st.get("traits", {}).values() if t["grown"]]
    typer.echo(
        f"  traits     {len(grown)}/{len(st.get('traits', {}))} grown: {', '.join(grown) or '-'}"
    )
    typer.echo(f"Brain: {'OK' if st['ok'] else 'ATTENTION'}")


@app.command("recall")
def recall_cmd(
    query: Annotated[str, typer.Argument(help="Free-text search; keywords beat sentences.")] = "",
    scope: Annotated[str, typer.Option("--scope", help="all, a kind, or a store.")] = "all",
    limit: Annotated[int, typer.Option("--limit", help="Max results after dedup.")] = 10,
    path: Annotated[
        Path, typer.Option("--path", "-p", help="Agent directory or brain.yaml.")
    ] = Path(),
    hook: Annotated[
        bool,
        typer.Option(
            "--hook",
            help="PostToolUseFailure mode: read the hook JSON from stdin, search the transcripts "
            "for the error, print additionalContext JSON when past sessions hit it.",
        ),
    ] = False,
) -> None:
    """brain_recall from the shell: one line per hit, `[kind] date source: text`."""
    import json
    import sys

    if hook:
        payload = json.loads(sys.stdin.read() or "{}")
        # "Exit code 1\nModuleNotFoundError: ..." -> the first line that says what went wrong
        lines = [ln.strip() for ln in str(payload.get("error", "")).splitlines()]
        query = next((ln for ln in lines if ln and not ln.startswith("Exit code")), "")[:200]
        scope, limit = "transcripts", 3  # the store, so no other store is asked
    if not query.strip():
        if hook:
            return
        typer.echo("ERROR: query is empty", err=True)
        raise typer.Exit(code=1)
    with _open(path) as agent:
        out = agent.brain_recall(query, scope=scope, fmt="detailed", limit=limit)
    hits = out["results"]
    if hook:
        # the failure that just happened is in this session's transcript too; skip it
        hits = [h for h in hits if h["extra"].get("session") != payload.get("session_id")]
        if hits:
            body = "\n".join(f"{h['date']} {h['text'][:300]}" for h in hits)
            typer.echo(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUseFailure",
                            "additionalContext": f"Past sessions hit this error:\n{body}",
                        }
                    }
                )
            )
        return
    for h in hits:
        typer.echo(f"[{h['kind']}] {h['date']} {h['source']}: {h['text']}")
    if not hits:
        typer.echo(out.get("note", "no hits"))


@app.command("serve")
def serve_cmd(
    path: Annotated[
        Path,
        typer.Argument(help="Path to agent directory (contains brain.yaml)."),
    ] = Path(),
) -> None:
    """Run the MCP server for the agent at ``path``."""
    config_path = path if path.is_file() else path / "brain.yaml"  # a dir, or a yaml file
    if not config_path.exists():
        typer.echo(f"ERROR: no brain.yaml at {config_path}", err=True)
        raise typer.Exit(code=1)

    from brain_core.mcp.server import run_server

    run_server(config_path)


@app.command("version")
def version_cmd() -> None:
    """Print the installed brain-core version."""
    typer.echo(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
