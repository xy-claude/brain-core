"""FastMCP server wiring: the five ``brain_*`` tools (v0.2).

One process per agent, spawned by Claude Code via .mcp.json::

    {"mcpServers": {"brain-core": {"command": "brain", "args": ["serve", "."]}}}

The v0.1 one-tool-per-function surface (remember, recall, decide, …) stays available as the
Python API in :mod:`brain_core.mcp.tools`; the MCP no longer exposes it. Five consolidated
workflow tools beat fourteen endpoint mirrors for an agent choosing what to call.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from brain_core.agent import Agent

_SESSION_PREFIX = "mcp-"


def build_server(agent: Agent) -> FastMCP:
    """Register the five brain tools on a FastMCP instance. Exposed for testing."""
    server = FastMCP(name=f"brain-core:{agent.name}")

    @server.tool()
    def brain_recall(
        query: str,
        scope: str = "all",
        format: str = "concise",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search the agent's whole memory with one query: facts, patterns, decisions,
        corrections, session notes, raw sources and entity relations across every store
        (SQLite, markdown vault, Hindsight, graph). Results are deduplicated, ranked by
        relevance and recency, and capped at ~6k tokens. `scope` narrows to one kind
        (fact|pattern|decision|correction|note|raw|relation) or one store
        (sqlite|vault|hindsight|graph). `format='detailed'` adds ids, scores and store names
        for chained calls. `stores` in the reply shows hits per store or the error if one
        was unreachable."""
        return agent.brain_recall(query, scope=scope, fmt=format, limit=limit)

    @server.tool()
    def brain_remember(
        text: str,
        kind: str,
        domain: str = "",
        source: str = "",
        mission: str | None = None,
        force: bool = False,
        extra: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Remember one thing in every store at once, in order: markdown vault, SQLite,
        Hindsight, and the entity graph (relations only). `kind` is one of
        fact|pattern|decision|correction|note|raw|relation. A near-duplicate fact is skipped
        (`status: duplicate`, with the existing one); a changed value is written with a
        `⚠ Fact changed` banner and the old line kept (`contradiction` in the reply). `layers`
        reports each store as written|exists|pending|failed|refused with detail, so a dead
        store is never silent. `extra` carries kind-specific fields: decision → title, reason,
        classification, confidence; correction → title, error, correction, rule, theme;
        relation → subject, predicate, object (or text 'S —[p]→ O'); note → section."""
        return agent.brain_remember(
            text,
            kind,
            domain=domain,
            source=source,
            mission=mission,
            force=force,
            **cast(dict[str, Any], extra or {}),
        )

    @server.tool()
    def brain_session(
        phase: str,
        session_id: str | None = None,
        executive_state: str | None = None,
        critique: str | None = None,
        sync: str | None = None,
    ) -> dict[str, Any]:
        """Open or close a session in one call. `phase='start'` returns the whole start block:
        the cron daily brief (with a stale flag), executive state (objective, missions, pending
        decisions), the configured Hindsight mental models, a recall for each top mission, the
        staged-inbox count, and `recovery` if the previous session never closed. `phase='end'`
        drains the Hindsight queue, appends a close line to today's HSAM file, rewrites
        executive_state / session_critique / cross-agent sync from the text you pass (or writes
        a stub built from this session's brain_remember calls), and writes the clean-close
        marker. Pass `executive_state`, `critique` and `sync` as full markdown bodies."""
        return agent.brain_session(
            phase, session_id, executive_state=executive_state, critique=critique, sync=sync
        )

    @server.tool()
    def brain_distill(
        source: str,
        text: str | None = None,
        title: str | None = None,
        author: str | None = None,
        published: str | None = None,
    ) -> dict[str, Any]:
        """Capture a source into the agent's immutable `raw/` folder (step 1 of /distill).
        `source` is a URL (web page via defuddle with a stdlib fallback, GitHub repo README,
        YouTube subtitles via yt-dlp, PDF saved as bytes), a local file path, or a name for
        pasted `text`. Writes `raw/YYYY-MM-DD-<slug>.md` with source, title, author, published,
        sha256 and word count; `status: exists` means the same source or body was captured
        before. A `note` says when the capture looks thin (JS or paywalled page) so you can
        fetch it in the browser and pass `text=`. Compiling the knowledge page is your job."""
        return agent.brain_distill(
            source, text=text, title=title, author=author, published=published
        )

    @server.tool()
    def brain_status() -> dict[str, Any]:
        """Health in one call: every store's reachability, knowledge-wiki lint (pages not in
        _index, index links to missing pages, pages without sources, raw files never compiled),
        always-loaded context size in tokens per file, last session start/close ids with an
        `unclosed` flag, and the count of pending decisions in executive state. `ok` is false
        when any store is down or lint found issues."""
        return agent.brain_status()

    return server


def run_server(config_path: Path) -> None:
    """Entry point for ``brain serve``: open the agent, run on stdio, close on exit."""
    agent = Agent.from_config(config_path)
    session_id = f"{_SESSION_PREFIX}{uuid.uuid4().hex[:12]}"
    agent.start_session(session_id)
    try:
        build_server(agent).run()  # stdio by default
    finally:
        agent.close()
