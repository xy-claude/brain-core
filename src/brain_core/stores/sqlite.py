"""The v0.1 SQLite/FTS5 fact table as a store adapter (always on)."""

from __future__ import annotations

import re
import sqlite3
from datetime import date

from brain_core.memory import structured
from brain_core.storage.db import Database
from brain_core.stores.base import Kind, Record, WriteResult, record_id

_KINDS: dict[Kind, str] = {"fact": "fact", "pattern": "pattern"}
_WORD = re.compile(r"[A-Za-z0-9_]+")


def fts_query(query: str) -> str:
    """Quote every word so FTS5 syntax characters (``-``, ``:``) cannot break the match."""
    return " OR ".join(f'"{w}"' for w in _WORD.findall(query))


class SqliteStore:
    name = "sqlite"
    ranked = True  # FTS5 bm25 orders results; recall needs one call per kind

    def __init__(self, db: Database) -> None:
        self.db = db

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        if kind not in _KINDS:
            return []
        q = fts_query(query) if query else None
        if query and not q:
            return []
        facts = structured.recall(self.db, query=q, kind=_KINDS[kind], limit=limit)
        return [
            Record(
                record_id(f.content),
                kind,
                f.content,
                f.created_at.date(),
                next((t.split(":", 1)[1] for t in f.tags if t.startswith("domain:")), ""),
                f.metadata.get("path", f"sqlite://facts/{f.id}"),
                int(f.metadata.get("line", 0)),
                {"fact_id": str(f.id)},
            )
            for f in facts
        ]

    def write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        if kind not in _KINDS:
            return WriteResult(self.name, "", "refused", f"sqlite holds fact|pattern, not {kind}")
        rid = record_id(text)
        before = self.db.fetchone("SELECT COUNT(*) AS n FROM facts")
        tags = [f"domain:{domain}"] if domain else []
        fact = structured.remember(self.db, text, kind=_KINDS[kind], tags=tags, metadata=extra)
        after = self.db.fetchone("SELECT COUNT(*) AS n FROM facts")
        grew = bool(before and after and after["n"] > before["n"])
        return WriteResult(self.name, rid, "written" if grew else "exists", f"facts/{fact.id}")

    def health(self) -> tuple[bool, str]:
        try:
            n = self.db.fetchone("SELECT COUNT(*) AS n FROM facts")
        except sqlite3.Error as e:
            return (False, f"sqlite: {e}")
        return (True, f"sqlite facts={n['n'] if n else 0}")
