"""Vectors of the indexed records, searched by cosine: the second net beside the keyword index.

One row per record in ``record_vectors``, made by the shared embed worker (:mod:`brain_core.embed`)
from the same text the keyword index holds. Search is exact: every vector is compared, which at
a few thousand records is a few milliseconds and never misses a neighbour. numpy is needed only
here, and only when ``stores.vectors`` is set.

The table is a cache of the files. A record whose text changed is embedded again, a record that
is gone loses its row, and a change of model replaces every row.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from brain_core.embed import Embedder, EmbedUnavailable
from brain_core.storage.db import Database
from brain_core.stores.base import Record, full_text

BATCH = 16


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class VectorIndex:
    def __init__(self, db: Database, embedder: Embedder) -> None:
        self.db = db
        self.embedder = embedder
        self.model = embedder.model
        self._sig: tuple[int, int] | None = None  # the records_fts state `_todo` was built from
        self._todo: list[tuple[str, str, str]] = []  # (record id, text, text hash) with no vector
        self._matrix: Any = None
        self._ids: list[str] = []
        self._rows = -1

    def _records(self) -> dict[str, tuple[str, str]]:
        """Every indexed record once: id -> (the text to embed, the store that holds it)."""
        out: dict[str, tuple[str, str]] = {}
        for row in self.db.fetchall("SELECT rid, record, store FROM records_fts"):
            if row["rid"] not in out:
                d = json.loads(row["record"])
                d["date"] = date.fromisoformat(d["date"])
                out[row["rid"]] = (full_text(Record(**d)), row["store"])
        return out

    def pending(self) -> list[tuple[str, str, str]]:
        """Records with no vector from this model for their current text. Rows of records that
        are gone, or that another model made, are dropped here."""
        row = self.db.fetchone(
            "SELECT count(*) AS n, coalesce(max(rowid), 0) AS m FROM records_fts"
        )
        sig = (int(row["n"]), int(row["m"])) if row else (0, 0)
        if sig != self._sig:
            recs = self._records()
            have = {
                r["record_id"]: (r["model"], r["text_hash"])
                for r in self.db.fetchall("SELECT record_id, model, text_hash FROM record_vectors")
            }
            gone = [
                rid for rid, (model, _h) in have.items() if rid not in recs or model != self.model
            ]
            if gone:
                with self.db.transaction():
                    for rid in gone:
                        self.db.execute("DELETE FROM record_vectors WHERE record_id = ?", (rid,))
                self._rows = -1
            self._todo = [
                (rid, text, h)
                for rid, (text, _store) in recs.items()
                if text.strip() and have.get(rid) != (self.model, h := _hash(text))
            ]
            self._sig = sig
        return self._todo

    def fill(self, limit: int | None = None, start: bool = True) -> int:
        """Embed up to ``limit`` waiting records. With ``start`` false a worker that is not
        already up is left alone, so a save never waits for a model to load."""
        todo = self.pending()[: limit if limit is not None else None]
        if not todo or (not start and not self.embedder.running()):
            return 0
        done = 0
        for i in range(0, len(todo), BATCH):
            part = todo[i : i + BATCH]
            vecs = self.embedder.embed([text for _rid, text, _h in part], "document")
            with self.db.transaction():
                for (rid, _text, h), vec in zip(part, vecs, strict=True):
                    self.db.execute(
                        "INSERT INTO record_vectors (record_id, model, dim, text_hash, vec) "
                        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (record_id) DO UPDATE SET "
                        "model = excluded.model, dim = excluded.dim, "
                        "text_hash = excluded.text_hash, vec = excluded.vec",
                        (rid, self.model, len(vec) // 4, h, vec),
                    )
            done += len(part)
        self._todo = self._todo[done:]
        self._rows = -1
        return done

    def _load(self) -> None:
        import numpy as np

        row = self.db.fetchone(
            "SELECT count(*) AS n FROM record_vectors WHERE model = ?", (self.model,)
        )
        n = int(row["n"]) if row else 0
        if n == self._rows:
            return
        rows = self.db.fetchall(
            "SELECT record_id, vec FROM record_vectors WHERE model = ?", (self.model,)
        )
        self._ids = [r["record_id"] for r in rows]
        self._matrix = (
            np.frombuffer(b"".join(r["vec"] for r in rows), dtype="<f4").reshape(len(rows), -1)
            if rows
            else None
        )
        self._rows = n

    def search(self, query: str, limit: int) -> list[tuple[Record, str, float]]:
        """The ``limit`` records nearest in meaning to ``query``: (record, its store, cosine).
        Raises :class:`EmbedUnavailable` when no vector can be made."""
        import numpy as np

        self._load()
        if self._matrix is None:
            return []
        q = np.frombuffer(self.embedder.embed([query], "query")[0], dtype="<f4")
        if q.shape[0] != self._matrix.shape[1]:
            raise EmbedUnavailable("the stored vectors have another size; run `brain index`")
        sims = self._matrix @ q
        best = np.argsort(-sims)[:limit]
        out: list[tuple[Record, str, float]] = []
        for i in best:
            row = self.db.fetchone(
                "SELECT record, store FROM records_fts WHERE rid = ? LIMIT 1", (self._ids[int(i)],)
            )
            if row:  # a record removed since its vector was made is skipped
                d = json.loads(row["record"])
                d["date"] = date.fromisoformat(d["date"])
                out.append((Record(**d), row["store"], float(sims[int(i)])))
        return out

    def stats(self) -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT count(*) AS n FROM record_vectors WHERE model = ?", (self.model,)
        )
        return {
            "model": self.model,
            "rows": int(row["n"]) if row else 0,
            "pending": len(self.pending()),
            "worker": "up" if self.embedder.running() else "down",
        }
