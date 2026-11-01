"""Entity graph in SQLite (M17): relationships only, no vector search.

Replaces the Kuzu CLI adapter. A relation is ``subject —[predicate]→ object``; its id is the
sha256 of that text, so vault, Hindsight and graph agree on what "the same relation" is.
``import_dump`` loads the ``entity_graph.py all`` format from the old Kuzu store once.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date

from brain_core.storage.db import Database
from brain_core.stores.base import Kind, Record, WriteResult, record_id

_LINE = re.compile(r"^\s*(.+?) —\[(.+?)\]→ (.+?)\s+\((\d{4}-\d{2}-\d{2})\)\s*$")
_ARROW = re.compile(r"^(.+?)\s+—\[(.+?)\]→\s+(.+)$")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def relation_text(s: str, p: str, o: str) -> str:
    return f"{s} —[{p}]→ {o}"


class GraphStore:
    name = "graph"

    def __init__(self, db: Database) -> None:
        self.db = db

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        if kind != "relation":
            return []
        sql = "SELECT id, subject, predicate, object, created_at FROM relations"
        params: list[str] = []
        words = _WORD.findall(query or "")
        if words:
            # any word in any column; brain_recall re-scores by token overlap afterwards
            clauses = []
            for w in words:
                clauses.append("(subject LIKE ? OR predicate LIKE ? OR object LIKE ?)")
                params += [f"%{w}%"] * 3
            sql += " WHERE " + " OR ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        rows = self.db.fetchall(sql, (*params, limit))
        return [
            Record(
                r["id"],
                "relation",
                relation_text(r["subject"], r["predicate"], r["object"]),
                date.fromisoformat(str(r["created_at"])[:10]),
                r["predicate"],
                "graph://relations",
                0,
                {"subject": r["subject"], "predicate": r["predicate"], "object": r["object"]},
            )
            for r in rows
        ]

    def write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        if kind != "relation":
            return WriteResult(self.name, "", "refused", "graph stores relations only")
        s, p, o = extra.get("subject"), extra.get("predicate"), extra.get("object")
        if not (s and p and o):
            m = _ARROW.match(text.strip())
            if not m:
                return WriteResult(
                    self.name, "", "refused", "give subject/predicate/object or 'S —[p]→ O'"
                )
            s, p, o = (x.strip() for x in m.groups())
        return self.add(s, p, o, when)

    def add(self, s: str, p: str, o: str, when: date | None = None) -> WriteResult:
        rid = record_id(relation_text(s, p, o))
        stamp = (when or date.today()).isoformat()
        try:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO relations (id, subject, predicate, object, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (rid, s, p, o, stamp),
            )
        except sqlite3.Error as e:
            return WriteResult(self.name, rid, "failed", str(e)[:200])
        if cur.rowcount:
            return WriteResult(self.name, rid, "written", relation_text(s, p, o))
        return WriteResult(self.name, rid, "exists", relation_text(s, p, o))

    def health(self) -> tuple[bool, str]:
        try:
            n = self.db.fetchone("SELECT COUNT(*) AS n FROM relations")
        except sqlite3.Error as e:
            return (False, f"graph: {e}")
        return (True, f"graph relations={n['n'] if n else 0}")

    def import_dump(self, text: str) -> dict[str, int]:
        """Load lines in the ``entity_graph.py all`` format: ``S —[p]→ O  (YYYY-MM-DD)``."""
        counts = {"written": 0, "exists": 0, "skipped": 0}
        for ln in text.splitlines():
            m = _LINE.match(ln)
            if not m:
                if ln.strip():
                    counts["skipped"] += 1
                continue
            s, p, o, d = m.groups()
            r = self.add(s.strip(), p.strip(), o.strip(), date.fromisoformat(d))
            counts[r.status if r.status in counts else "skipped"] += 1
        return counts
