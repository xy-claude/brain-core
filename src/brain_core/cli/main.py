"""``brain`` CLI — top-level app wiring the subcommands."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Annotated

import typer

from brain_core import __version__
from brain_core.agent import Agent
from brain_core.cli.init import init_agent
from brain_core.stores.vault import VaultStore

if (
    sys.platform == "win32"
):  # hooks and MCP clients read UTF-8; the Windows console default is cp1252
    for _stream in (sys.stdout, sys.stderr):
        if isinstance(_stream, io.TextIOWrapper):
            _stream.reconfigure(encoding="utf-8")

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
    lite: Annotated[
        bool,
        typer.Option("--lite", help="Vault + SQLite only, no Hindsight; upgrade later."),
    ] = False,
) -> None:
    """Write a whole agent: brain.yaml, CLAUDE.md, rules, skills, hooks, .mcp.json, vault."""
    init_agent(name=name, path=path, force=force, user=user, profile=profile, lite=lite)


@app.command("adopt")
def adopt_cmd(
    path: Annotated[Path, typer.Argument(help="Existing agent folder (has a CLAUDE.md).")],
    vault: Annotated[Path, typer.Option("--vault", help="The agent's markdown vault folder.")],
    name: Annotated[
        str | None, typer.Option("--name", help="Agent name; default: folder name.")
    ] = None,
    user: Annotated[
        str, typer.Option("--user", help="How the agent addresses its user.")
    ] = "the user",
    bank: Annotated[
        str | None, typer.Option("--bank", help="Hindsight bank; omit for lite.")
    ] = None,
    hindsight_url: Annotated[str, typer.Option("--hindsight-url")] = "http://127.0.0.1:8888",
    mental_model: Annotated[
        list[str] | None, typer.Option("--mental-model", help="Repeatable.")
    ] = None,
    peers: Annotated[
        str | None, typer.Option("--peers", help="Glob of other agents' sync files.")
    ] = None,
    queue: Annotated[str | None, typer.Option("--queue", help="Hindsight queue file.")] = None,
    marker: Annotated[str | None, typer.Option("--marker", help="Clean-close marker file.")] = None,
    transcripts: Annotated[str, typer.Option("--transcripts")] = "~/.claude/projects",
    rules: Annotated[
        str, typer.Option("--rules", help="Template rule files to render, comma-separated.")
    ] = "04-memory.md",
    force: Annotated[
        bool, typer.Option("--force", help="Rewrite brain.yaml, the MCP entry and the rules.")
    ] = False,
) -> None:
    """Put an existing agent folder on brain-core: brain.yaml, the `brain` MCP server, the four
    hooks, the memory rule, then `brain index`. CLAUDE.md, skills and the vault are not touched."""
    from brain_core.cli.adopt import adopt_agent
    from brain_core.stores.vault import VaultStore as _VS

    out = adopt_agent(
        path,
        name=name or path.resolve().name,
        user=user,
        vault=vault.expanduser().resolve(),
        bank=bank,
        hindsight_url=hindsight_url,
        mental_models=mental_model,
        peers=peers,
        queue=queue,
        marker=marker,
        transcripts=transcripts,
        rules=[r.strip() for r in rules.split(",") if r.strip()],
        force=force,
    )
    for k, v in out.items():
        typer.echo(f"  {k:22} {v}")
    with _open(path) as agent:
        v = next((s for s in agent.stores if isinstance(s, _VS)), None)
        sq = agent.stores[0]
        n = 0
        if v is not None:
            for kind in ("fact", "pattern"):
                for r in v.read(kind, limit=1_000_000):
                    res = sq.write(kind, r.text, domain=r.domain, path=r.path, line=str(r.line))
                    if res.status == "written":
                        agent.db.execute(
                            "UPDATE facts SET created_at = ?, updated_at = ? WHERE id = ?",
                            (f"{r.date} 00:00:00", f"{r.date} 00:00:00", res.detail.split("/")[1]),
                        )
                        n += 1
        st = agent.brain_status()
    up = sum(1 for s in st["stores"].values() if s["ok"])
    typer.echo(f"  index                  {n} new rows")
    tokens = st["context"]["tokens"]
    typer.echo(f"  stores                 {up}/{len(st['stores'])} OK · context {tokens} tokens")


@app.command("daily")
def daily_cmd(
    path: Annotated[Path, typer.Argument(help="Agent directory or brain.yaml.")] = Path(),
    shadow: Annotated[
        bool,
        typer.Option(
            "--shadow",
            help="Write <brief>.shadow.md beside a brief another tool owns and list its sections "
            "missing here; no health line, no backup.",
        ),
    ] = False,
) -> None:
    """Tier 1 cron: write the daily brief, a health line, and back up Hindsight."""
    from brain_core.cron import daily

    with _open(path) as agent:
        out = daily(agent, shadow=True) if shadow else daily(agent)
    typer.echo(f"brief: {out['brief']} (~{out['brief_tokens']} tokens)")
    if shadow:
        miss = out["missing_sections"]
        typer.echo(f"parity vs {out['shadow_of']}: {len(miss)} section(s) missing here")
        for m in miss:
            typer.echo(f"  missing: {m}")
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
    """Register `brain daily` and `brain weekly`: launchd, crontab (Linux) or Task Scheduler."""
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


@app.command("index")
def index_cmd(
    path: Annotated[
        Path,
        typer.Argument(help="Path to agent directory (contains brain.yaml)."),
    ] = Path(),
) -> None:
    """Load the vault's facts.md and patterns.md into the SQLite FTS index. Idempotent."""
    with _open(path) as agent:
        vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
        if vault is None:
            typer.echo("ERROR: no vault configured in brain.yaml", err=True)
            raise typer.Exit(code=1)
        sqlite = agent.stores[0]
        written = exists = 0
        for kind in ("fact", "pattern"):
            for r in vault.read(kind, limit=1_000_000):
                res = sqlite.write(kind, r.text, domain=r.domain, path=r.path, line=str(r.line))
                if res.status != "written":
                    exists += 1
                    continue
                # keep the vault date, or recall's recency term would rank an old fact as new
                agent.db.execute(
                    "UPDATE facts SET created_at = ?, updated_at = ? WHERE id = ?",
                    (f"{r.date} 00:00:00", f"{r.date} 00:00:00", res.detail.split("/")[1]),
                )
                written += 1
    typer.echo(f"indexed {written} new, {exists} already there")


@app.command("brief")
def brief_cmd(
    path: Annotated[
        Path, typer.Option("--path", "-p", help="Agent directory or brain.yaml.")
    ] = Path(),
    hook: Annotated[
        bool,
        typer.Option("--hook", help="SessionStart mode: print the brief as additionalContext."),
    ] = False,
) -> None:
    """Print the daily brief. With --hook it is injected into context at SessionStart and
    `brain_session('start')` then omits it instead of repeating it. When the session start
    follows a compaction, a task checkpoint read from the transcript goes in first."""
    import json
    import sys

    from brain_core.capture import checkpoint

    payload = json.loads(sys.stdin.read() or "{}") if hook else {}
    resume = ""
    if payload.get("source") == "compact" and payload.get("transcript_path"):
        resume = checkpoint(Path(str(payload["transcript_path"])).expanduser())
    with _open(path) as agent:
        vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
        brief = (vault.root / agent.config.session.brief) if vault else None
        text = brief.read_text(encoding="utf-8") if brief and brief.exists() else ""
        if not text.strip() and not resume:
            return
        if not hook:
            typer.echo(text)
            return
        if text.strip():
            agent.log_event(
                "brief_injected",
                {"session_id": str(payload.get("session_id", "")), "brief": str(brief)},
            )
        if resume:
            agent.log_event(
                "checkpoint_injected",
                {"session_id": str(payload.get("session_id", "")), "chars": len(resume)},
            )
    parts = [resume]
    if text.strip():
        parts.append(f"Daily brief (injected by brain brief --hook):\n{text}")
    typer.echo(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "\n\n".join(p for p in parts if p),
                }
            }
        )
    )


@app.command("capture")
def capture_cmd(
    path: Annotated[
        Path, typer.Option("--path", "-p", help="Agent directory or brain.yaml.")
    ] = Path(),
    transcript: Annotated[
        Path | None,
        typer.Option(
            "--transcript", help="Transcript .jsonl to scan; default: the hook JSON on stdin."
        ),
    ] = None,
) -> None:
    """Stop / PreCompact hook: file every user message and URL from the transcript into
    today's session file (sections "Said (hook)" and "Links (hook)"), from where the last run
    stopped, deduplicated."""
    import json
    import sys

    from brain_core.capture import capture

    sid = ""
    if transcript is None:
        payload = json.loads(sys.stdin.read() or "{}")
        if payload.get("stop_hook_active") or not payload.get("transcript_path"):
            return
        transcript, sid = Path(str(payload["transcript_path"])), str(payload.get("session_id", ""))
        with _open(path) as agent:
            capture(agent, transcript.expanduser(), sid)
        return  # a hook prints nothing; plain stdout would be ignored anyway
    with _open(path) as agent:
        out = capture(agent, transcript.expanduser(), sid)
    typer.echo(
        f"captured {out['written']} new, {out['duplicate']} already there, "
        f"{out['scanned']} transcript lines scanned"
    )


@app.command("lessons")
def lessons_cmd(
    prompt: Annotated[str, typer.Argument(help="The request to match corrections against.")] = "",
    path: Annotated[
        Path, typer.Option("--path", "-p", help="Agent directory or brain.yaml.")
    ] = Path(),
    hook: Annotated[
        bool,
        typer.Option(
            "--hook",
            help="UserPromptSubmit mode: read the hook JSON from stdin and print the matching "
            "corrections as additionalContext, each one once per session.",
        ),
    ] = False,
) -> None:
    """Past corrections that match a request: the one or two from corrections.md that share
    enough words with it. Not wired by default; add it as a UserPromptSubmit hook to turn it
    on. Without --hook it prints the matches and why, for tuning."""
    import json
    import sys

    from brain_core.lessons import lessons, render
    from brain_core.stores.vault import FILES

    payload = json.loads(sys.stdin.read() or "{}") if hook else {}
    sid = str(payload.get("session_id", ""))
    if hook:
        prompt = str(payload.get("prompt", ""))
    with _open(path) as agent:
        vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
        source = (vault.root / FILES["correction"]) if vault else None
        text = source.read_text(encoding="utf-8") if source and source.exists() else ""
        hits = lessons(text, prompt)
        if hook and sid:  # a thread on one subject would otherwise repeat the lesson every turn
            told = {
                t
                for e in agent.recent_events(session_id=sid, event_type="lessons_injected")
                for t in e.payload.get("titles", [])
            }
            hits = [h for h in hits if h["title"] not in told]
        if hook and hits:
            agent.log_event(
                "lessons_injected",
                {"titles": [h["title"] for h in hits], "scores": [h["score"] for h in hits]},
                session_id=sid or None,
            )
    if not hook:
        for h in hits:
            typer.echo(
                f"{h['score']:.3f} [{h['date']}] {h['title']} (shared: {', '.join(h['shared'])})"
            )
        if not hits:
            typer.echo("no correction matches")
        return
    if hits:
        typer.echo(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": render(hits),
                    }
                }
            )
        )


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
    tools = st.get("tools", {}).get("per_tool", {})
    if tools:
        typer.echo(
            "  tools      "
            + " · ".join(
                f"{n} {m['calls']}× {m['avg_ms']}ms {m['avg_tokens']}tok {m['errors']}err"
                for n, m in tools.items()
            )
        )
    for h in st.get("tools", {}).get("hints", []):
        typer.echo(f"  hint       {h}")
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
