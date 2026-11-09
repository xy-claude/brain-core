"""FastMCP server wiring: the five ``brain_*`` tools (v0.2).

One process per agent, spawned by Claude Code via .mcp.json::

    {"mcpServers": {"brain-core": {"command": "brain", "args": ["serve", "."]}}}

The v0.1 one-tool-per-function surface (remember, recall, decide, …) stays available as the
Python API in :mod:`brain_core.mcp.tools`; the MCP no longer exposes it. Five consolidated
workflow tools beat fourteen endpoint mirrors for an agent choosing what to call.

Each tool carries MCP annotations and a description per parameter: the description is the
only thing an agent reads before it picks a tool, so it says what the tool does, when to use
it instead of its siblings, and what it does that the schema cannot show.
"""

from __future__ import annotations

import contextlib
import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, cast

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from brain_core.agent import Agent

_SESSION_PREFIX = "mcp-"
_KINDS = "fact|pattern|decision|correction|note|raw|relation"


def build_server(agent: Agent) -> FastMCP:
    """Register the five brain tools on a FastMCP instance. Exposed for testing."""
    server = FastMCP(name=f"brain-core:{agent.name}")

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        )
    )
    def brain_recall(
        query: Annotated[str, Field(description="Free-text search; keywords beat sentences.")],
        scope: Annotated[
            str,
            Field(
                description=f"'all' (default), one kind ({_KINDS}|transcript) or one store "
                "(sqlite|vault|hindsight|graph|transcripts|notes)."
            ),
        ] = "all",
        format: Annotated[
            str,
            Field(
                description="'concise' (default) for text to quote; 'detailed' adds ids, "
                "scores and store names for chained calls."
            ),
        ] = "concise",
        limit: Annotated[int, Field(description="Max results after dedup; default 10.")] = 10,
        offset: Annotated[
            int, Field(description="Skip this many ranked results; use the reply's `next_offset`.")
        ] = 0,
    ) -> dict[str, Any]:
        """Search the agent's long-term memory: facts, patterns, decisions, corrections,
        session notes, raw sources, entity relations and the Claude Code session transcripts
        of this folder, across SQLite, the markdown vault, Hindsight and the graph, returned
        as one deduplicated list ranked by relevance and recency and capped at about 6k
        tokens. scope='transcript' searches only what past sessions said and ran. `total`
        counts every hit; when more remain, `next_offset` says where to continue.

        Use it before answering anything about past sessions, earlier decisions or the user's
        preferences, and before brain_remember to avoid writing a duplicate. Not for health
        checks (brain_status) and not for reading a file you already know the path of.

        Read-only. Partial results are normal: `stores` lists hits per store and names any store
        that was unreachable instead of failing the call. A value a `⚠ Fact changed` banner
        superseded is returned but ranked below the banner."""
        return _timed(
            agent,
            "brain_recall",
            lambda: agent.brain_recall(query, scope=scope, fmt=format, limit=limit, offset=offset),
        )

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
        )
    )
    def brain_remember(
        text: Annotated[str, Field(description="The memory itself, one item, plain text.")],
        kind: Annotated[str, Field(description=f"One of {_KINDS}.")],
        domain: Annotated[
            str, Field(description="Topic tag such as 'trading' or 'system'; empty = none.")
        ] = "",
        source: Annotated[
            str, Field(description="Where it came from: a URL, file path or 'user'.")
        ] = "",
        mission: Annotated[
            str | None, Field(description="Mission id to tag, e.g. 'M-012'.")
        ] = None,
        force: Annotated[
            bool, Field(description="Write even when a near-duplicate exists.")
        ] = False,
        extra: Annotated[
            dict[str, str] | None,
            Field(
                description="Kind-specific fields. decision: title, reason, classification, "
                "confidence. correction: title, error, correction, rule, theme. relation: "
                "subject, predicate, object (or text 'S —[p]→ O'). note: section."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Write one memory item to every store in one call, in order: markdown vault, SQLite,
        Hindsight, and the entity graph (relations only).

        Use it the moment the user states a fact, decision, correction, preference or
        relationship worth keeping across sessions; one call per item. Not for whole documents
        or web pages (brain_distill) and not for the end-of-session summary (brain_session).

        Never deletes. A near-duplicate fact returns `status: duplicate` with the existing entry
        and writes nothing. A changed value is appended under a `⚠ Fact changed` banner with the
        old line kept, reported as `contradiction`. `layers` reports each store as
        written|exists|pending|failed|refused, so a dead store is visible, never silent. Text
        that looks like a secret is refused."""
        return _timed(
            agent,
            "brain_remember",
            lambda: agent.brain_remember(
                text,
                kind,
                domain=domain,
                source=source,
                mission=mission,
                force=force,
                **cast(dict[str, Any], extra or {}),
            ),
        )

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
        )
    )
    def brain_session(
        phase: Annotated[str, Field(description="'start' or 'end'.")],
        session_id: Annotated[
            str | None,
            Field(description="Caller's session id; omit to keep the one the server opened."),
        ] = None,
        executive_state: Annotated[
            str | None,
            Field(description="end only: full markdown body that replaces executive_state."),
        ] = None,
        critique: Annotated[
            str | None,
            Field(description="end only: full markdown body that replaces session_critique."),
        ] = None,
        sync: Annotated[
            str | None,
            Field(description="end only: full markdown body of the cross-agent sync note."),
        ] = None,
    ) -> dict[str, Any]:
        """Open or close the agent's working session. Call phase='start' once at the beginning
        of every conversation, before any other brain tool; call phase='end' once when the user
        signals they are done. Not for single facts (brain_remember).

        start returns the whole context block: the cron daily brief with a stale flag,
        executive state (objective, missions, pending decisions), the configured Hindsight
        mental models, a recall per top mission, the staged-inbox count, and `recovery` when
        the previous session never closed.

        end drains the Hindsight queue, appends a close line to today's session archive,
        replaces executive_state, session_critique and the cross-agent sync file with the
        bodies you pass (or a stub built from this session's brain_remember calls), reports
        which trait signals moved, and writes the clean-close marker. A second end overwrites
        the first."""
        return _timed(
            agent,
            "brain_session",
            lambda: agent.brain_session(
                phase, session_id, executive_state=executive_state, critique=critique, sync=sync
            ),
        )

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
        )
    )
    def brain_distill(
        source: Annotated[
            str,
            Field(
                description="A URL (web page, GitHub repo, YouTube video, PDF), a local file "
                "path, or a short name for pasted `text`."
            ),
        ],
        text: Annotated[
            str | None,
            Field(description="The body itself, when you already have it; skips fetching."),
        ] = None,
        title: Annotated[str | None, Field(description="Override the detected title.")] = None,
        author: Annotated[str | None, Field(description="Override the detected author.")] = None,
        published: Annotated[
            str | None, Field(description="Publication date YYYY-MM-DD, if known.")
        ] = None,
    ) -> dict[str, Any]:
        """Capture an external source into the agent's immutable raw/ folder as a dated
        markdown file with provenance: source, title, author, published, sha256, word count.
        This is step 1 of /distill; compiling the knowledge page from the raw file is your job
        afterwards.

        Use it for a web page (defuddle with a stdlib fallback), a GitHub repo README, YouTube
        subtitles via yt-dlp, a PDF saved as bytes, a local file, or pasted text. Not for short
        facts (brain_remember).

        Fetches over the network for URLs. The same source or body a second time returns
        `status: exists` and writes nothing. A `note` flags a thin capture (JS-only or paywalled
        page) so you can read it in a browser and call again with `text`."""
        return _timed(
            agent,
            "brain_distill",
            lambda: agent.brain_distill(
                source, text=text, title=title, author=author, published=published
            ),
        )

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        )
    )
    def brain_status() -> dict[str, Any]:
        """Report the agent's health in one read-only call: reachability of every store (vault,
        SQLite, Hindsight, graph), knowledge-wiki lint (pages missing from _index, index links
        to missing pages, pages without sources, raw files never compiled), always-loaded
        context size in tokens per file, the last session start and close ids with an
        `unclosed` flag, the pending-decision count, the twelve trait signals, and
        `recall_misses`: the queries of the last 30 days that written memory could not answer.

        Use it when a store seems down, before maintenance, or when the user asks how the
        memory is doing. Not a search (brain_recall). `ok` is false when any store is down or
        lint found issues; `stores` names the failing one."""
        return _timed(agent, "brain_status", agent.brain_status)

    return server


def _timed(agent: Agent, name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run one tool call and record runtime, response tokens and error flag in `metrics`."""
    t0, err, out = time.perf_counter(), 1, None
    try:
        out = fn()
        err = 0
        return out
    finally:
        ms = round((time.perf_counter() - t0) * 1000, 1)
        tokens = len(json.dumps(out, default=str)) // 4 if out is not None else 0
        tags = {"tokens": tokens, "error": err, "session": agent.current_session}
        with contextlib.suppress(Exception):  # metrics must never break a tool call
            agent.db.execute(
                "INSERT INTO metrics (metric_name, value, tags) VALUES (?, ?, ?)",
                (f"tool.{name}", ms, json.dumps(tags)),
            )


def run_server(config_path: Path) -> None:
    """Entry point for ``brain serve``: open the agent, run on stdio, close on exit."""
    agent = Agent.from_config(config_path)
    session_id = f"{_SESSION_PREFIX}{uuid.uuid4().hex[:12]}"
    agent.start_session(session_id)
    try:
        build_server(agent).run()  # stdio by default
    finally:
        agent.close()
