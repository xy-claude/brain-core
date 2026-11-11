"""One FTS5 index (bm25, stemmed) over every record a markdown store parses.

The files stay the truth. A file whose size or mtime changed is parsed again on the next
search, a file that is gone loses its rows, and dropping both tables loses nothing: the next
search rebuilds them. Stores that share this index share one bm25 scale, so their hits can be
merged by ``Record.score``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path

from brain_core.storage.db import Database
from brain_core.stores.base import Kind, Record, full_text

_TERM = re.compile(r"\d{4}-\d{2}-\d{2}|[^\W_]+")
# question and filler words match most records and say nothing about which one is wanted
_STOP = frozenset(
    [
        "a",
        "about",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "should",
        "so",
        "than",
        "that",
        "the",
        "their",
        "then",
        "there",
        "this",
        "to",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)


def match_query(query: str) -> str:
    """Every word as an OR term, quoted so FTS5 syntax cannot break the match. A date stays
    whole (``"2026-11-02"`` is a phrase of its three numbers)."""
    terms = dict.fromkeys(t for t in _TERM.findall(query.lower()) if len(t) > 1 and t not in _STOP)
    return " OR ".join(f'"{t}"' for t in terms)


class RecordIndex:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.keys: dict[str, str] = {}  # record id -> its search keys, see set_keys

    def set_keys(self, keys: dict[str, str]) -> None:
        """Search keys by record id (any prefix length the caller uses consistently). They are
        indexed beside the text and never returned. Only rows whose keys differ are rewritten."""
        self.keys = keys
        n = len(next(iter(keys), ""))
        for row in self.db.fetchall("SELECT rowid, rid, keys FROM records_fts"):
            new = keys.get(row["rid"][:n], "") if n else ""
            if new != row["keys"]:
                self.db.execute("UPDATE records_fts SET keys = ? WHERE rowid = ?", (new, row[0]))

    def sync(
        self, store: str, files: Mapping[Path, Kind], parse: Callable[[Kind, Path], list[Record]]
    ) -> None:
        """Bring the rows of ``store`` in line with ``files``. Only a changed file is parsed."""
        known = {
            r["path"]: r["sig"]
            for r in self.db.fetchall("SELECT path, sig FROM index_files WHERE store = ?", (store,))
        }
        seen: set[str] = set()
        for p, kind in files.items():
            key = str(p)
            seen.add(key)
            try:
                st = p.stat()
                sig = f"{st.st_mtime_ns}:{st.st_size}"
                if known.get(key) == sig:
                    continue
                records = parse(kind, p)
            except OSError:
                continue  # a file a sync service has evicted: keep the rows it has
            with self.db.transaction():
                self.db.execute(
                    "DELETE FROM records_fts WHERE store = ? AND path = ?", (store, key)
                )
                for r in records:
                    # the heading and the date are searchable; the record keeps its own text
                    body = f"{r.domain} {full_text(r)} {r.date.isoformat()}"
                    row = {**asdict(r), "date": r.date.isoformat()}
                    n = len(next(iter(self.keys), ""))
                    self.db.execute(
                        "INSERT INTO records_fts (body, keys, store, kind, path, rid, record) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            body,
                            self.keys.get(r.id[:n], "") if n else "",
                            store,
                            r.kind,
                            key,
                            r.id,
                            json.dumps(row),
                        ),
                    )
                self.db.execute(
                    "INSERT INTO index_files (store, path, sig) VALUES (?, ?, ?) "
                    "ON CONFLICT (store, path) DO UPDATE SET sig = excluded.sig",
                    (store, key, sig),
                )
        for key in known.keys() - seen:
            with self.db.transaction():
                self.db.execute(
                    "DELETE FROM records_fts WHERE store = ? AND path = ?", (store, key)
                )
                self.db.execute(
                    "DELETE FROM index_files WHERE store = ? AND path = ?", (store, key)
                )

    def search(self, store: str, kinds: Sequence[Kind], query: str, limit: int) -> list[Record]:
        """The best ``limit`` records of ``store`` for ``query``, bm25 order, score on each."""
        q = match_query(query)
        if not q or not kinds:
            return []
        marks = ",".join("?" * len(kinds))
        rows = self.db.fetchall(
            "SELECT record, bm25(records_fts) AS rank FROM records_fts "
            f"WHERE records_fts MATCH ? AND store = ? AND kind IN ({marks}) "
            "ORDER BY rank LIMIT ?",
            (q, store, *kinds, limit),
        )
        out: list[Record] = []
        for row in rows:
            d = json.loads(row["record"])
            d["date"] = date.fromisoformat(d["date"])
            d["score"] = -float(row["rank"])  # FTS5 bm25 is negative, best first
            out.append(Record(**d))
        return out
