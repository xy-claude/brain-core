"""Read-only index of the Claude Code session transcripts of this agent's folder.

Claude Code writes every session to ``~/.claude/projects/<cwd with non-alphanumerics as
dashes>/<session>.jsonl``. Those files hold what the agent never wrote down: the commands it
ran, the errors it hit, what the user asked. Indexing them makes recall useful on day one,
before the agent has remembered anything on purpose.

Only text reaches the index: user and assistant text blocks, Bash commands as ``$ cmd``, other
tool calls as ``[Tool] target``, and the first 400 characters of a tool result. Thinking,
images and hook chatter are skipped; anything that looks like a secret is redacted before it
is stored. A reindex reads each file from the byte offset it stopped at last time.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from brain_core.storage.db import Database
from brain_core.stores.base import Kind, Record, WriteResult
from brain_core.stores.sqlite import fts_query
from brain_core.stores.vault import _SECRET

RECENT_MINUTES = 10  # transcript lines younger than this are the running conversation

_RESULT_CHARS = 400
_TEXT_CHARS = 2_000
_MIN_CHARS = 12
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
# transcripts carry whole command lines: the value after a password/token flag and any bare
# 16-hex token (recovery codes) go too; over-redacting a session line costs nothing
_CLI_SECRET = re.compile(
    r"(?i)((?:^|\s)(?:-w|-p|--password|--token|--api-key|--secret)|"
    r"\b(?:password|passwd|token|secret|api[_-]?key)\s*[=:])\s*['\"]?[^\s'\"]{4,}"
    r"|\b[0-9a-f]{16}\b"
)
_WS = re.compile(r"\s+")


def project_dir(projects_root: Path, agent_root: Path) -> Path:
    """Claude Code's folder for a cwd: every non-alphanumeric character becomes a dash. Older
    versions kept underscores; that folder is used when it exists and the new one does not."""
    root = projects_root.expanduser()
    full = str(agent_root.resolve())
    new = root / re.sub(r"[^A-Za-z0-9]", "-", full)
    legacy = root / re.sub(r"[^A-Za-z0-9_]", "-", full)
    return legacy if not new.is_dir() and legacy.is_dir() else new


def index(db: Database, projects_root: Path, agent_root: Path) -> dict[str, int]:
    """Index new transcript bytes for the agent's folder. Returns files seen and rows added."""
    folder = project_dir(projects_root, agent_root)
    files, added = 0, 0
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        files += 1
        st = path.stat()
        row = db.fetchone("SELECT offset, mtime FROM transcript_files WHERE path = ?", (str(path),))
        offset = int(row["offset"]) if row and st.st_size >= int(row["offset"]) else 0
        if row and offset == st.st_size and float(row["mtime"]) == st.st_mtime:
            continue
        with path.open("rb") as fh, db.transaction():
            fh.seek(offset)
            for raw in fh:
                if not raw.endswith(b"\n"):
                    break  # a line still being written; pick it up next time
                offset += len(raw)
                for rid, session, ts, role, text in _rows(raw, path.stem):
                    cur = db.execute(
                        "INSERT OR IGNORE INTO transcripts (id, session, ts, role, text) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (rid, session, ts, role, text),
                    )
                    added += cur.rowcount
            db.execute(
                "INSERT OR REPLACE INTO transcript_files (path, offset, mtime) VALUES (?, ?, ?)",
                (str(path), offset, st.st_mtime),
            )
    return {"files": files, "added": added}


def _rows(raw: bytes, stem: str) -> list[tuple[str, str, str, str, str]]:
    try:
        obj = json.loads(raw)
    except ValueError:
        return []
    role = obj.get("type")
    if role not in ("user", "assistant") or obj.get("isMeta"):
        return []
    message = obj.get("message") or {}
    uuid = str(obj.get("uuid") or "")
    session = str(obj.get("sessionId") or stem)
    ts = str(obj.get("timestamp") or "")
    out = []
    for i, text in enumerate(_texts(message.get("content"))):
        text = _REMINDER.sub("", text)
        text = _WS.sub(" ", text).strip()
        if len(text) < _MIN_CHARS or text.startswith("<"):
            continue
        text = _CLI_SECRET.sub(r"\1 [redacted]", _SECRET.sub("[redacted]", text))[:_TEXT_CHARS]
        out.append((f"{uuid}:{i}" if uuid else f"{stem}:{ts}:{i}", session, ts, role, text))
    return out


def _texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    out: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            out.append(str(block.get("text") or ""))
        elif kind == "tool_use":
            name = str(block.get("name") or "tool")
            inp: dict[str, Any] = block["input"] if isinstance(block.get("input"), dict) else {}
            if name == "Bash" and inp.get("command"):
                out.append(f"$ {inp['command']}")
            else:
                target = next(
                    (
                        str(inp[k])
                        for k in ("description", "file_path", "query", "url")
                        if inp.get(k)
                    ),
                    "",
                )
                out.append(f"[{name}] {target}")
        elif kind == "tool_result":
            body = block.get("content")
            if isinstance(body, list):
                body = " ".join(str(b.get("text") or "") for b in body if isinstance(b, dict))
            if body:
                out.append("→ " + str(body)[:_RESULT_CHARS])
    return out


class TranscriptStore:
    """Recall over the indexed transcripts. Indexes new bytes once per process, on first read."""

    name = "transcripts"
    ranked = True  # FTS5 bm25 order
    whole = True  # one read covers the only kind it has

    def __init__(self, db: Database, projects_root: Path, agent_root: Path) -> None:
        self.db = db
        self.projects_root = projects_root
        self.agent_root = agent_root
        self._indexed = False

    def index(self) -> dict[str, int]:
        self._indexed = True
        return index(self.db, self.projects_root, self.agent_root)

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        # `whole`: recall asks once with any kind and drops records whose kind it did not want
        if not self._indexed:
            self.index()
        q = fts_query(query) if query else ""
        if query and not q:
            return []
        # a line younger than this is the conversation asking, not memory: skip it
        cutoff = (datetime.now(UTC) - timedelta(minutes=RECENT_MINUTES)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        if q:
            rows = self.db.fetchall(
                "SELECT t.id, t.session, t.ts, t.role, t.text FROM transcripts_fts f "
                "JOIN transcripts t ON t.rowid = f.rowid WHERE transcripts_fts MATCH ? "
                "AND t.ts < ? ORDER BY bm25(transcripts_fts) LIMIT ?",
                (q, cutoff, limit),
            )
        else:
            rows = self.db.fetchall(
                "SELECT id, session, ts, role, text FROM transcripts WHERE ts < ? "
                "ORDER BY ts DESC LIMIT ?",
                (cutoff, limit),
            )
        return [
            Record(
                r["id"],
                "transcript",
                f"[{r['role']}] {r['text']}",
                _day(r["ts"]),
                "",
                f"transcript://{r['session'][:8]}",
                0,
                {"session": r["session"], "ts": r["ts"]},
            )
            for r in rows
        ]

    def write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        return WriteResult(self.name, "", "refused", "transcripts are indexed, never written")

    def health(self) -> tuple[bool, str]:
        try:
            n = self.db.fetchone("SELECT COUNT(*) AS n FROM transcripts")
            f = self.db.fetchone("SELECT COUNT(*) AS n FROM transcript_files")
        except sqlite3.Error as e:
            return (False, f"transcripts: {e}")
        folder = project_dir(self.projects_root, self.agent_root)
        if not folder.is_dir():
            return (True, f"transcripts: no sessions yet at {folder}")
        return (True, f"transcripts rows={n['n'] if n else 0} files={f['n'] if f else 0}")


def _day(ts: str) -> date:
    try:
        return date.fromisoformat(ts[:10])
    except ValueError:
        return date.today()
