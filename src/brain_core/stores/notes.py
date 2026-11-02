"""Read-only markdown folders recall also searches: a vault ``shared/`` folder other agents
write, or Claude Code's own memory folder (``~/.claude/projects/<slug>/memory``). Each file
is read like a knowledge page: one record per ``## section``, or one for the whole body.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from brain_core.stores.base import Kind, Record, WriteResult
from brain_core.stores.vault import _parse_date, frontmatter, knowledge_records, read_text


class NotesStore:
    name = "notes"

    def __init__(self, dirs: list[Path]) -> None:
        self.dirs = [Path(d).expanduser() for d in dirs]

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        if kind != "knowledge":
            return []
        out: list[Record] = []
        q = (query or "").lower()
        for d in self.dirs:
            for p in sorted(d.glob("*.md")) if d.is_dir() else []:
                text = read_text(p)
                when = _parse_date(frontmatter(text).get("updated")) or date.fromtimestamp(
                    p.stat().st_mtime
                )
                out += [
                    r for r in knowledge_records(text, str(p), when) if not q or q in r.text.lower()
                ]
        out.sort(key=lambda r: r.date, reverse=True)
        return out[:limit]

    def write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        return WriteResult(self.name, "", "refused", "notes folders are read, never written")

    def health(self) -> tuple[bool, str]:
        missing = [str(d) for d in self.dirs if not d.is_dir()]
        n = sum(len(list(d.glob("*.md"))) for d in self.dirs if d.is_dir())
        if missing:
            return (False, f"notes: folder missing: {', '.join(missing)}")
        return (True, f"notes files={n} folders={len(self.dirs)}")
