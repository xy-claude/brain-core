"""Stop / PreCompact hook: file every user message and URL from the live transcript into
today's session file, incrementally and deduplicated.

This is the floor under the agent's discipline, not a replacement for it: decisions,
corrections, facts and patterns still need `brain_remember` with their kind. Hindsight gets
the captures through the session queue when one is configured (drained at session end), so
the hook never waits on the vector store; without a queue it writes there directly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from brain_core.agent import Agent
from brain_core.remember import brain_remember
from brain_core.stores.hindsight import HindsightStore
from brain_core.stores.transcripts import _rows

_URL = re.compile(r"https?://[^\s)\]>\"']+")
MAX_ITEMS = 50  # per hook run; Stop fires every turn, so the backlog is small
USER_CHARS = 500
SAID, LINKS = "Said (hook)", "Links (hook)"
_LOCAL = re.compile(r"https?://(127\.0\.0\.1|localhost|0\.0\.0\.0)(?::\d+)?(/|$)")
_NOISE = (".svg", ".png", ".gif", ".ico")


def capture(agent: Agent, transcript: Path, session_id: str = "") -> dict[str, Any]:
    key = str(transcript)
    cursor = next(
        (
            int(e.payload.get("line", 0))
            for e in agent.recent_events(event_type="capture", limit=200)
            if e.payload.get("transcript") == key
        ),
        0,
    )
    lines = transcript.read_text(encoding="utf-8").splitlines() if transcript.exists() else []
    items: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for raw in lines[cursor:]:
        for _rid, _sess, _ts, role, text in _rows(raw.encode("utf-8"), transcript.stem):
            # URLs from speech only: shell commands and tool output carry local and asset noise
            for url in [] if text.startswith(("$ ", "→")) else _URL.findall(text):
                url = url.rstrip(".,;:|)\\")
                if url in seen_urls or _LOCAL.match(url) or url.lower().endswith(_NOISE):
                    continue
                seen_urls.add(url)
                items.append((f"URL {url}", LINKS))
            if role == "user" and not text.startswith(("$ ", "[", "→")):
                items.append((text[:USER_CHARS], SAID))
    items = items[:MAX_ITEMS]
    queue = agent.config.session.queue
    stores = [s for s in agent.stores if not (queue and isinstance(s, HindsightStore))]
    written, duplicate, queued = 0, 0, []
    for text, section in items:
        try:
            out = brain_remember(
                stores,
                text,
                "note",
                source=f"hook:{session_id or transcript.stem}",
                section=section,
            )
        except ValueError:  # the secret guard; nothing written anywhere
            continue
        if out["status"] == "written":
            written += 1
            queued.append(text)
        else:
            duplicate += 1
    if queued and queue:
        qp = agent.resolve(queue)
        qp.parent.mkdir(parents=True, exist_ok=True)
        with qp.open("a", encoding="utf-8") as f:
            for t in queued:
                f.write(
                    json.dumps(
                        {
                            "agent": agent.name,
                            "content": t,
                            "context": "hook-capture",
                            "tags": ["hook"],
                        }
                    )
                    + "\n"
                )
    agent.log_event(
        "capture",
        {"transcript": key, "line": len(lines), "written": written, "duplicate": duplicate},
        session_id=session_id or None,
    )
    return {
        "transcript": key,
        "scanned": len(lines) - cursor,
        "written": written,
        "duplicate": duplicate,
        "queued": len(queued) if queue else 0,
    }
