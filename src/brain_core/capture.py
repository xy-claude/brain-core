"""Stop / PreCompact hook: file every user message and URL from the live transcript into
today's session file, incrementally and deduplicated.

This is the floor under the agent's discipline, not a replacement for it: decisions,
corrections, facts and patterns still need `brain_remember` with their kind. The hook never
talks to Hindsight: captures reach it through the session queue (drained at session end);
without a queue they stay in the vault, where recall still finds them.

`checkpoint` is the other half: after a compaction the SessionStart hook reads the stretch
that was just summarised and puts the user's last requests, the files edited and the last
reply back into context.
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
REQUESTS, FILES = 3, 6  # how many of each a checkpoint keeps, newest last
REQUEST_CHARS, REPLY_CHARS = 200, 240
STRETCH_LINES = 4000  # a compacted stretch is read back at most this far
_EDIT = re.compile(r"^\[(?:Edit|Write|MultiEdit|NotebookEdit)\] (\S.*)$")


def checkpoint(transcript: Path) -> str:
    """After a compaction: what the user last asked, which files were edited and where the
    agent stopped, read from the stretch of the transcript the compaction just summarised.
    A summary keeps the gist; this keeps the exact words and paths. Call it only from
    SessionStart with ``source: compact``; empty when the transcript holds no speech."""
    try:
        lines = transcript.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return ""
    cuts = [
        i
        for i, raw in enumerate(lines)
        if "compact_boundary" in raw and _meta(raw).get("subtype") == "compact_boundary"
    ]
    # Claude Code writes this compaction's boundary after the SessionStart hook has run (seen
    # live, 2026-11-06), so the stretch just summarised is the tail of the file. A tail with
    # no speech means the boundary did land first: step back one stretch.
    last = cuts[-1] if cuts else -1
    asked, files, reply = _stretch(lines[last + 1 :], transcript.stem)
    if cuts and not (asked or files or reply):
        before = cuts[-2] + 1 if len(cuts) > 1 else 0
        asked, files, reply = _stretch(lines[before:last], transcript.stem)
    if not (asked or files or reply):
        return ""
    out = ["Task checkpoint (brain-core, read from the transcript before this compaction):"]
    if asked:
        out.append("Last requests from the user, oldest first:")
        out += [f"- {a}" for a in asked[-REQUESTS:]]
    if files:
        out.append("Files edited: " + ", ".join(files[-FILES:]))
    if reply:
        out.append(f"Last reply before the compaction: {reply}")
    return "\n".join(out)


def _stretch(lines: list[str], stem: str) -> tuple[list[str], list[str], str]:
    """The user's requests, the files edited and the last reply in `lines`."""
    asked: list[str] = []
    files: list[str] = []
    reply = ""
    for raw in lines[-STRETCH_LINES:]:
        if "isCompactSummary" in raw and _meta(raw).get("isCompactSummary"):
            continue  # the previous compaction's summary is not something the user said
        for _rid, _sess, _ts, role, text in _rows(raw.encode("utf-8"), stem):
            edit = _EDIT.match(text)
            if edit and role == "assistant":
                files = [f for f in files if f != edit.group(1)] + [edit.group(1)]
            elif text.startswith(("$ ", "[", "→")):
                continue  # tool rows are not speech
            elif role == "user":
                asked.append(_cut(text, REQUEST_CHARS))
            else:
                reply = _cut(text, REPLY_CHARS)
    return asked, files, reply


def _meta(raw: str) -> dict[str, Any]:
    try:
        obj = json.loads(raw)
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def capture(agent: Agent, transcript: Path, session_id: str = "") -> dict[str, Any]:
    key = str(transcript)
    row = agent.db.fetchone(
        "SELECT json_extract(payload, '$.line') AS line FROM events WHERE event_type = 'capture' "
        "AND json_extract(payload, '$.transcript') = ? ORDER BY id DESC LIMIT 1",
        (key,),
    )
    cursor = end = int(row["line"] or 0) if row else 0
    lines = transcript.read_text(encoding="utf-8").splitlines() if transcript.exists() else []
    items: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for raw in lines[cursor:]:
        if len(items) >= MAX_ITEMS:
            break  # the cursor stops here; the next run takes the rest
        end += 1
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
    queue = agent.config.session.queue
    stores = [s for s in agent.stores if not isinstance(s, HindsightStore)]
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
        {"transcript": key, "line": end, "written": written, "duplicate": duplicate},
        session_id=session_id or None,
    )
    return {
        "transcript": key,
        "scanned": end - cursor,
        "written": written,
        "duplicate": duplicate,
        "queued": len(queued) if queue else 0,
    }
