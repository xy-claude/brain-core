"""Entity graph in SQLite (M17): relationships only, no vector search.

Replaces the Kuzu CLI adapter. A relation is ``subject —[predicate]→ object``; its id is the
sha256 of that text, so vault, Hindsight and graph agree on what "the same relation" is.
``import_dump`` loads the ``entity_graph.py all`` format from the old Kuzu store once.

M1a: beside a vault, once ``vault/relations.md`` exists it is the truth. The ``relations``
table mirrors it (for older versions, until M3), and this store reads only the rows the file
still holds, so a line removed by hand does not come back, and relations rank as in 0.9.1:
they stay out of the keyword index. Until the file exists the table is read as before, and a
relation write waits for ``migrate_relations`` (`brain graph migrate`), which makes the file
behind a backup.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from brain_core.backup import backup_db, private_file, stamp
from brain_core.storage.db import Database
from brain_core.stores.base import Kind, Record, WriteResult, record_id

if TYPE_CHECKING:
    from brain_core.stores.vault import VaultStore

_LINE = re.compile(r"^\s*(.+?) —\[(.+?)\]→ (.+?)\s+\((\d{4}-\d{2}-\d{2})\)\s*$")
_ARROW = re.compile(r"^(.+?)\s+—\[(.+?)\]→\s+(.+)$")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
# a line of vault/relations.md. `recorded` is when brain-core first stored the relation (the
# table's created_at, kept verbatim): provenance only, never the day the relation became true
RELATION_LINE = re.compile(
    r"^- \[\[(.+?)\]\] —\[(.+?)\]→ \[\[(.+?)\]\](?: \(recorded: ([^)]+)\))?\s*$"
)


def relation_text(s: str, p: str, o: str) -> str:
    return f"{s} —[{p}]→ {o}"


def relation_line(s: str, p: str, o: str, recorded: str) -> str:
    return f"- [[{s}]] —[{p}]→ [[{o}]] (recorded: {recorded})"


def split_relation(text: str, extra: dict[str, str]) -> tuple[str, str, str] | None:
    """Subject, predicate and object from the fields, or from ``S —[p]→ O`` text."""
    s, p, o = extra.get("subject"), extra.get("predicate"), extra.get("object")
    if s and p and o:
        return s, p, o
    m = _ARROW.match(text.strip())
    return (m.group(1).strip(), m.group(2).strip(), m.group(3).strip()) if m else None


def unsafe_relation(s: str, p: str, o: str) -> str:
    """Why a relations.md line could not give this relation back exactly, or "". A ``:`` in a
    predicate is kept free for the role M3 adds (``—[p: role]→``)."""
    for name, v, bad in (
        ("subject", s, "[[ ]] |"),
        ("object", o, "[[ ]] |"),
        ("predicate", p, "] :"),
    ):
        if v != v.strip() or "\n" in v or "\r" in v:
            return f"the {name} {v!r} has a line break or spaces at an end"
        if hit := next((b for b in bad.split() if b in v), None):
            return f"the {name} {v!r} holds {hit!r}"
    return ""


def mirror(db: Database, records: Iterable[Record]) -> None:
    """Bring the legacy table up to the file: rows it lacks are added, none is changed or
    removed, so an older version reads every relation the file holds."""
    for r in records:
        if r.kind == "relation":
            db.execute(
                "INSERT OR IGNORE INTO relations (id, subject, predicate, object, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    r.id,
                    r.extra["subject"],
                    r.extra["predicate"],
                    r.extra["object"],
                    r.extra.get("recorded") or r.date.isoformat(),
                ),
            )


class GraphStore:
    name = "graph"

    def __init__(self, db: Database, relations_md: Path | None = None) -> None:
        self.db = db
        self.relations_md = relations_md  # the vault's relations.md, when there is a vault

    @property
    def mirror(self) -> bool:
        """The file holds the relations: the table only mirrors it."""
        return self.relations_md is not None and self.relations_md.exists()

    def _held(self) -> set[str]:
        """Ids of the relations the file holds (read again only when it changed)."""
        assert self.relations_md is not None
        sig = self.relations_md.stat().st_mtime_ns
        if getattr(self, "_sig", None) != sig:
            text = self.relations_md.read_text(encoding="utf-8", errors="replace")
            self._ids = {
                record_id(relation_text(*m.groups()[:3]))
                for ln in text.splitlines()
                if (m := RELATION_LINE.match(ln))
            }
            self._sig = sig
        return self._ids

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
        sql += " ORDER BY created_at DESC"
        if self.mirror:
            # only what the file holds: a row removed by hand must not come back. A row no line
            # can hold is still read here, until it is resolved (brain doctor names it)
            held = self._held()
            rows = [
                r
                for r in self.db.fetchall(sql, tuple(params))
                if r["id"] in held or unsafe_relation(r["subject"], r["predicate"], r["object"])
            ][:limit]
        else:
            rows = self.db.fetchall(sql + " LIMIT ?", (*params, limit))
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
        note = " (mirror of relations.md)" if self.mirror else ""
        return (True, f"graph relations={n['n'] if n else 0}{note}")

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


def migrate_relations(db: Database, vault: VaultStore, backup_dir: Path) -> dict[str, Any]:
    """`brain graph migrate` (M1a): copy the legacy ``relations`` table into relations.md.

    First a backup: ``brain.db`` through SQLite's backup API, checked with ``integrity_check``,
    and relations.md as it was, both readable by the owner only. Then a row the line cannot
    hold is refused and named, only the ids the file lacks are appended (in one atomic write;
    no line is ever dropped), and the file is checked to hold every other row. Run again, it
    adds nothing."""
    at = stamp()
    saved, before = [backup_db(db, backup_dir, at)], ""
    path = vault.root / "relations.md"
    if path.exists():
        data = path.read_bytes()
        before = hashlib.sha256(data).hexdigest()
        saved.append(private_file(backup_dir / f"relations-{at}.md", data))
    rows = db.fetchall("SELECT id, subject, predicate, object, created_at FROM relations")
    refused, items, ids = [], [], []
    for r in rows:
        s, p, o = r["subject"], r["predicate"], r["object"]
        if why := unsafe_relation(s, p, o):
            refused.append(f"{relation_text(s, p, o)}: {why}")
            continue
        items.append((s, p, o, str(r["created_at"])))
        ids.append(r["id"])
    appended = vault.append_relations(items)
    held = {r.id for r in vault.read("relation", limit=10**9)}
    return {
        "rows": len(rows),
        "appended": len(appended),
        "refused": refused,
        "backup": [str(p) for p in saved],
        "relations_md_sha256_before": before,
        "verified": all(i in held for i in ids),
        # a relation the file cannot hold still lives only in brain.db: not done
        "complete": not refused and all(i in held for i in ids),
    }
