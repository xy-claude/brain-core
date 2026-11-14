"""Vectors of the indexed records, searched by cosine: the second net beside the keyword index.

One row per record in ``record_vectors``, made by the shared embed worker (:mod:`brain_core.embed`)
from the same text the keyword index holds. Search is exact: every vector is compared, which at
a few thousand records is a few milliseconds and never misses a neighbour. numpy is needed only
here, and only when ``stores.vectors`` is set.

The table is a cache of the files. A record whose text changed is embedded again, a record that
is gone loses its row, and after a change of model each row is replaced as the new model fills
it: a model name that cannot load costs no vector.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from brain_core.embed import Embedder, EmbedUnavailable
from brain_core.storage.db import Database
from brain_core.stores.base import Record, full_text
from brain_core.stores.index import stored

BATCH = 16


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class VectorIndex:
    def __init__(self, db: Database, embedder: Embedder) -> None:
        self.db = db
        self.embedder = embedder
        self.model = embedder.model
        self.bad = 0  # stored vectors the last load skipped: another length than the rest
        self._sig: list[tuple[Any, ...]] | None = None  # the index state `_todo` was built from
        self._todo: list[tuple[str, str, str]] = []  # (record id, text, text hash) with no vector
        self._gone = False  # some vector's record has left the index
        self._matrix: Any = None
        self._ids: list[str] = []
        self._have: list[tuple[Any, ...]] | None = None  # the vectors `_matrix` was built from

    def _records(self) -> dict[str, tuple[str, str]]:
        """Every indexed record once: id -> (the text to embed, the store that holds it)."""
        out: dict[str, tuple[str, str]] = {}
        for row in self.db.fetchall("SELECT rid, record, store FROM records_fts"):
            if row["rid"] not in out:
                out[row["rid"]] = (full_text(stored(row["record"])), row["store"])
        return out

    def pending(self) -> list[tuple[str, str, str]]:
        """Records with no vector from this model for their current text. It only reads: a
        health check, or a model name that cannot load, deletes nothing."""
        # every indexed file's stamp: a page edited in place changes it, the row count may not
        sig = [
            tuple(r)
            for r in self.db.fetchall(
                "SELECT store, path, sig FROM index_files ORDER BY store, path"
            )
        ]
        if sig != self._sig:
            recs = self._records()
            have = {
                r["record_id"]: (r["model"], r["text_hash"])
                for r in self.db.fetchall("SELECT record_id, model, text_hash FROM record_vectors")
            }
            self._todo = [
                (rid, text, h)
                for rid, (text, _store) in recs.items()
                if text.strip() and have.get(rid) != (self.model, h := _hash(text))
            ]
            self._gone = any(rid not in recs for rid in have)
            self._sig = sig
        return self._todo

    def fill(self, limit: int | None = None, start: bool = True) -> int:
        """Embed up to ``limit`` waiting records. With ``start`` false a worker that is not
        already up is left alone, so a save never waits for a model to load."""
        todo = self.pending()[: limit if limit is not None else None]
        if self._gone:
            # a record that left the index loses its vector. Asked of the tables as they are
            # now, and never of an empty index: that is one being rebuilt, not an empty vault
            self.db.execute(
                "DELETE FROM record_vectors WHERE record_id NOT IN (SELECT rid FROM records_fts) "
                "AND EXISTS (SELECT 1 FROM records_fts)"
            )
            self._gone = False
        if not todo or (not start and not self.embedder.running()):
            return 0
        done = 0
        for i in range(0, len(todo), BATCH):
            part = todo[i : i + BATCH]
            vecs = self.embedder.embed([text for _rid, text, _h in part], "document")
            with self.db.transaction():
                for (rid, _text, h), vec in zip(part, vecs, strict=True):
                    # a row another model made is replaced here, once this model has its vector
                    self.db.execute(
                        "INSERT INTO record_vectors (record_id, model, dim, text_hash, vec) "
                        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (record_id) DO UPDATE SET "
                        "model = excluded.model, dim = excluded.dim, "
                        "text_hash = excluded.text_hash, vec = excluded.vec",
                        (rid, self.model, len(vec) // 4, h, vec),
                    )
            done += len(part)
        self._todo = self._todo[done:]
        return done

    def _load(self) -> None:
        import numpy as np

        # which records have a vector, and of which text: a re-embed by another server on this
        # database changes it though the count stays the same
        have = [
            tuple(r)
            for r in self.db.fetchall(
                "SELECT record_id, text_hash FROM record_vectors WHERE model = ?", (self.model,)
            )
        ]
        if have == self._have:
            return
        rows = self.db.fetchall(
            "SELECT record_id, vec FROM record_vectors WHERE model = ?", (self.model,)
        )
        # a vector of another length than most (a cut row, a worker that ran another model
        # under this name) is skipped and counted; the rest still answer
        size = Counter(len(r["vec"]) for r in rows).most_common(1)[0][0] if rows else 0
        good = [r for r in rows if len(r["vec"]) == size]
        self.bad = len(rows) - len(good)
        self._ids = [r["record_id"] for r in good]
        self._matrix = (
            np.frombuffer(b"".join(r["vec"] for r in good), dtype="<f4").reshape(len(good), -1)
            if good
            else None
        )
        self._have = have

    def search(self, query: str, limit: int) -> list[tuple[Record, str, float]]:
        """The ``limit`` records nearest in meaning to ``query``: (record, its store, cosine).
        Raises :class:`EmbedUnavailable`, and nothing else, when the search cannot be made: no
        worker, no numpy, stored vectors that cannot be read. Recall then answers from keywords."""
        try:
            return self._search(query, limit)
        except EmbedUnavailable:
            raise
        except Exception as e:
            raise EmbedUnavailable(f"{type(e).__name__}: {e}") from e

    def _search(self, query: str, limit: int) -> list[tuple[Record, str, float]]:
        import numpy as np

        self._load()
        if self._matrix is None:
            if waiting := len(self.pending()):
                # never filled, or a model name that cannot load: say so, not "0 found"
                raise EmbedUnavailable(
                    f"no vectors from {self.model} yet, {waiting} records wait; run `brain index`"
                )
            return []
        q = np.frombuffer(self.embedder.embed([query], "query")[0], dtype="<f4")
        if q.shape[0] != self._matrix.shape[1]:
            raise EmbedUnavailable("the stored vectors have another size; run `brain index`")
        sims = self._matrix @ q
        best = [int(i) for i in np.argsort(-sims)[:limit]]
        # one query for all of them: `rid` has no index, so each lookup reads the whole table
        rows: dict[str, Any] = {}
        for row in self.db.fetchall(
            "SELECT rid, record, store FROM records_fts "
            f"WHERE rid IN ({','.join('?' * len(best))}) ORDER BY rowid",
            [self._ids[i] for i in best],
        ):
            rows.setdefault(row["rid"], row)
        out: list[tuple[Record, str, float]] = []
        for i in best:
            if hit := rows.get(self._ids[i]):  # a record removed since its vector was made
                out.append((stored(hit["record"]), hit["store"], float(sims[i])))
        return out

    def stats(self) -> dict[str, Any]:
        """Counts only: nothing is written or deleted here."""
        row = self.db.fetchone(
            "SELECT count(*) AS n FROM record_vectors "
            "WHERE model = ? AND record_id IN (SELECT rid FROM records_fts)",
            (self.model,),
        )
        return {
            "model": self.model,
            "rows": int(row["n"]) if row else 0,
            "pending": len(self.pending()),
            "worker": "up" if self.embedder.running() else "down",
            # vectors the last search skipped for their length; absent until one was
            **({"bad": self.bad} if self.bad else {}),
        }
