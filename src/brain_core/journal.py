"""``data/journal.db`` (M1c): the history no Markdown file holds.

One ledger row per version of a record at an occurrence: where (a source, a record, the k-th
copy of it there), which version (the hash of its exact text), and when the vault held it
(transaction time, from the clock, never from the text). brain.db can be deleted and rebuilt;
this file cannot, so it is its own file, written first, committed durably (WAL with
``synchronous=FULL``), backed up daily, and merged back from a backup with the gap recorded.

Rules (docs/KNOWLEDGE_ARCHITECTURE_AUDIT.md, L.5):
- One writer: a sync holds this journal's OS lock across both commits.
- The journal commits first, then brain.db with the file signatures; a crash between them is
  repaired by the next sync, whose journal writes are idempotent.
- A marker (generation, sync_seq) in both files. A brain.db ahead of its journal, or of another
  generation, means lost history: a ``restore`` gap is recorded and every file is read again.
- A move inherits its recording time only when it is unambiguous: one copy left, one arrived.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from brain_core.backup import private_file, stamp
from brain_core.storage.db import Database

EPOCH = "0001-01-01T00:00:00.000000Z"  # the start of an epoch gap: before any observation
SCHEMA = """
CREATE TABLE IF NOT EXISTS record_ledger (
    occ_id       TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    seen_from    TEXT NOT NULL,
    seen_to      TEXT,
    via          TEXT NOT NULL CHECK (via IN ('write', 'ingest', 'move')),
    moved_from   TEXT,
    PRIMARY KEY (occ_id, content_hash, seen_from),
    CHECK (seen_to IS NULL OR seen_to > seen_from),
    CHECK ((via = 'move') = (moved_from IS NOT NULL))
) WITHOUT ROWID;
CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_open ON record_ledger(occ_id) WHERE seen_to IS NULL;
CREATE TABLE IF NOT EXISTS ledger_gaps (
    gap_from TEXT NOT NULL PRIMARY KEY,
    gap_to   TEXT NOT NULL,
    cause    TEXT NOT NULL CHECK (cause IN ('epoch', 'restore')),
    CHECK (gap_to > gap_from)
) WITHOUT ROWID;
-- what an occurrence id names (beside the audit's schema: a sync finds a source's open rows)
CREATE TABLE IF NOT EXISTS ledger_occurrences (
    occ_id    TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    ordinal   INTEGER NOT NULL CHECK (ordinal >= 1)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_occurrence_source ON ledger_occurrences(source_id);
CREATE TABLE IF NOT EXISTS journal_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
"""


def occurrence_id(source_id: str, record_id: str, ordinal: int) -> str:
    """Where a record is: its source (never an absolute path), its id, the k-th copy there."""
    return hashlib.sha256(
        json.dumps(["occ/1", source_id, record_id, ordinal]).encode()
    ).hexdigest()[:32]


class Journal:
    def __init__(self, path: Path, clock: Callable[[], datetime] | None = None) -> None:
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.via = "ingest"  # "write" while brain_remember's own save is synced
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = Database.connect(self.path)
        self.db.execute("PRAGMA synchronous = FULL")  # a committed row survives a power loss
        self.db.executescript(SCHEMA)
        if self._meta("generation") is None:
            now = self.stamp(self.clock())
            with self._tx():
                for k, v in (
                    ("generation", uuid4().hex),
                    ("started", now),
                    ("sync_seq", "0"),
                    ("last_sync", now),
                ):
                    self.db.execute("INSERT OR IGNORE INTO journal_meta VALUES (?, ?)", (k, v))
                self.db.execute(
                    "INSERT OR IGNORE INTO ledger_gaps VALUES (?, ?, 'epoch')", (EPOCH, now)
                )

    # ── time, meta, transactions ───────────────────────────────────────────────

    @staticmethod
    def stamp(when: datetime) -> str:
        return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def _meta(self, key: str) -> str | None:
        row = self.db.fetchone("SELECT value FROM journal_meta WHERE key = ?", (key,))
        return str(row[0]) if row else None

    def _tx(self) -> _Tx:
        return _Tx(self.db)

    def locked(self) -> Any:
        """The one-writer lock: held by a sync from before it reads the signatures until
        brain.db commits. A SQLite lock ends at its commit, so it cannot span both files."""
        from brain_core.stores.vault import _Lock  # vault imports the index, which imports this

        return _Lock(self.path)

    def close(self) -> None:
        self.db.close()

    # ── the ledger ───────────────────────────────────────────────────────────

    def record(self, batch: Mapping[str, Sequence[tuple[str, str]]]) -> int:
        """``batch``: source id -> its records in file order, (record id, exact text); an empty
        list is a source that is gone. In one transaction: close what left, open what came
        (``move`` only when unambiguous), advance sync_seq. Idempotent. Returns sync_seq."""
        now = self.stamp(self.clock())
        cur: dict[str, str] = {}
        occs: list[tuple[str, str, str, int]] = []
        for source, recs in batch.items():
            seen: Counter[str] = Counter()
            for rid, text in recs:
                seen[rid] += 1
                o = occurrence_id(source, rid, seen[rid])
                cur[o] = hashlib.sha256(text.encode()).hexdigest()
                occs.append((o, source, rid, seen[rid]))
        marks = ",".join("?" * len(batch))
        with self._tx():
            opened = (
                {
                    (r[0], r[1])
                    for r in self.db.fetchall(
                        "SELECT l.occ_id, l.content_hash FROM record_ledger l "
                        "JOIN ledger_occurrences o "
                        f"USING (occ_id) WHERE l.seen_to IS NULL AND o.source_id IN ({marks})",
                        tuple(batch),
                    )
                }
                if batch
                else set()
            )
            gone = [k for k in opened if cur.get(k[0]) != k[1]]
            came = [(o, h) for o, h in cur.items() if (o, h) not in opened]
            for o, h in gone:
                self.db.execute(
                    "UPDATE record_ledger SET seen_to = ? WHERE occ_id = ? AND content_hash = ? "
                    "AND seen_to IS NULL",
                    (now, o, h),
                )
            left: dict[str, list[str]] = defaultdict(list)
            for o, h in gone:
                left[h].append(o)
            arrived = Counter(h for _o, h in came)
            for o, h in came:
                src = left.get(h, [])
                moved = len(src) == 1 and arrived[h] == 1 and src[0] != o
                self.db.execute(
                    "INSERT OR IGNORE INTO record_ledger VALUES (?, ?, ?, NULL, ?, ?)",
                    (o, h, now, "move" if moved else self.via, src[0] if moved else None),
                )
            self.db.executemany(
                "INSERT OR IGNORE INTO ledger_occurrences VALUES (?, ?, ?, ?)", occs
            )
            seq = int(self._meta("sync_seq") or 0) + 1
            self.db.execute("UPDATE journal_meta SET value = ? WHERE key = 'sync_seq'", (str(seq),))
            self.db.execute("UPDATE journal_meta SET value = ? WHERE key = 'last_sync'", (now,))
        return seq

    def recorded_at(self, occ_id: str, content_hash: str) -> str | None:
        """When the vault first held this version here, following unambiguous moves back."""
        row = self.db.fetchone(
            "SELECT seen_from, via, moved_from FROM record_ledger WHERE occ_id = ? AND "
            "content_hash = ? ORDER BY seen_from LIMIT 1",
            (occ_id, content_hash),
        )
        if row is None:
            return None
        if row["via"] == "move" and row["moved_from"]:
            return self.recorded_at(row["moved_from"], content_hash) or str(row["seen_from"])
        return str(row["seen_from"])

    # ── the marker ───────────────────────────────────────────────────────────

    def check(self, db: Database) -> bool:
        """Compare brain.db's marker with this journal's. True: every file must be read again
        (brain.db is new, or ahead of this journal, or of another generation; in the last two
        cases history was lost, and a ``restore`` gap says from when)."""
        try:
            row = db.fetchone("SELECT generation, sync_seq FROM journal_state")
        except sqlite3.Error:
            row = None  # a brain.db before 0.12
        if row is None:
            return True
        gen, seq = self._meta("generation"), int(self._meta("sync_seq") or 0)
        if row["generation"] == gen and row["sync_seq"] <= seq:
            return False
        has_history = self.db.fetchone("SELECT 1 FROM record_ledger LIMIT 1") is not None
        if has_history:  # a new journal has its epoch gap already
            now, last = self.stamp(self.clock()), self._meta("last_sync") or EPOCH
            if now > last:
                with self._tx():
                    self.db.execute(
                        "INSERT OR IGNORE INTO ledger_gaps VALUES (?, ?, 'restore')", (last, now)
                    )
        return True

    def mark(self, db: Database, seq: int) -> None:
        """brain.db's side of the marker, written after its own rows."""
        db.execute(
            "INSERT INTO journal_state (id, generation, sync_seq) VALUES (1, ?, ?) "
            "ON CONFLICT (id) "
            "DO UPDATE SET generation = excluded.generation, sync_seq = excluded.sync_seq",
            (self._meta("generation"), seq),
        )

    # ── backup and restore ───────────────────────────────────────────────────

    def backup(self, folder: Path, keep: int = 14, today: date | None = None) -> Path:
        """A checked copy as ``journal-YYYY-MM-DD.db`` in ``folder`` (0700, files 0600),
        through SQLite's backup API into a temp file that is renamed into place. Keeps the
        ``keep`` newest."""
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        day = (today or date.today()).isoformat()
        target, tmp = folder / f"journal-{day}.db", folder / f".journal-{day}-{stamp()}.tmp"
        private_file(tmp)
        with sqlite3.connect(tmp) as dst:
            self.db.backup(dst)
            dst.execute(
                "INSERT OR REPLACE INTO journal_meta VALUES ('taken_at', ?)",
                (self.stamp(self.clock()),),
            )
            dst.commit()
            ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
            dst.execute("PRAGMA journal_mode = DELETE")  # one self-contained file
        dst.close()
        if ok != "ok":
            tmp.unlink()
            raise RuntimeError(f"journal backup failed its integrity check ({ok})")
        os.replace(tmp, target)
        for old in sorted(folder.glob("journal-*.db"))[:-keep]:
            old.unlink()
        return target

    @staticmethod
    def taken_at(file: Path) -> str | None:
        with sqlite3.connect(f"file:{file}?mode=ro", uri=True) as c:
            row = c.execute("SELECT value FROM journal_meta WHERE key = 'taken_at'").fetchone()
        c.close()
        return str(row[0]) if row else None

    def restore(self, file: Path) -> dict[str, Any]:
        """Merge a backup: its rows join this journal's (a union), its open rows close when the
        backup was taken (nothing after was observed), and the time from then to this journal's
        start is a ``restore`` gap. Refuses a file that is not a sound journal backup."""
        try:
            src = sqlite3.connect(f"file:{file}?mode=ro", uri=True)
            ok = src.execute("PRAGMA integrity_check").fetchone()[0]
            taken = src.execute("SELECT value FROM journal_meta WHERE key = 'taken_at'").fetchone()
            started = src.execute("SELECT value FROM journal_meta WHERE key = 'started'").fetchone()
            rows = src.execute("SELECT * FROM record_ledger").fetchall()
            occs = src.execute("SELECT * FROM ledger_occurrences").fetchall()
            gaps = src.execute("SELECT * FROM ledger_gaps WHERE cause = 'restore'").fetchall()
            src.close()
        except sqlite3.Error as e:
            raise ValueError(f"{file} is not a sound journal backup: {e}") from e
        if ok != "ok" or taken is None or started is None:
            raise ValueError(f"{file} is not a sound journal backup (integrity {ok})")
        mine = self._meta("started") or EPOCH
        if taken[0] >= mine:
            raise ValueError(
                "this journal already covers the time of the backup: there is nothing to restore"
            )
        merged = 0
        with self._tx():
            for occ_id, h, seen_from, seen_to, via, moved_from in rows:
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO record_ledger VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        occ_id,
                        h,
                        seen_from,
                        seen_to if seen_to is not None else taken[0],
                        via,
                        moved_from,
                    ),
                )
                merged += cur.rowcount
            self.db.executemany(
                "INSERT OR IGNORE INTO ledger_occurrences VALUES (?, ?, ?, ?)", occs
            )
            self.db.execute("DELETE FROM ledger_gaps WHERE cause = 'epoch'")
            self.db.execute(
                "INSERT OR IGNORE INTO ledger_gaps VALUES (?, ?, 'epoch')", (EPOCH, started[0])
            )
            self.db.executemany("INSERT OR IGNORE INTO ledger_gaps VALUES (?, ?, ?)", gaps)
            self.db.execute(
                "INSERT OR IGNORE INTO ledger_gaps VALUES (?, ?, 'restore')", (taken[0], mine)
            )
            self.db.execute(
                "UPDATE journal_meta SET value = ? WHERE key = 'started'", (started[0],)
            )
        return {"merged": merged, "gap": (taken[0], mine)}

    def status(self) -> dict[str, Any]:
        n = self.db.fetchone("SELECT count(*), sum(seen_to IS NULL) FROM record_ledger")
        return {
            "rows": int(n[0]) if n else 0,
            "open": int(n[1] or 0) if n else 0,
            "generation": (self._meta("generation") or "")[:8],
            "started": self._meta("started"),
            "integrity": str(self.db.fetchone("PRAGMA quick_check")[0]),  # type: ignore[index]
        }


class _Tx:
    """BEGIN IMMEDIATE … COMMIT on the journal's own connection (not Database.transaction, so a
    failure injected into brain.db's transactions never reaches the journal's)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def __enter__(self) -> None:
        self.db.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type: object, *_: object) -> None:
        self.db.execute("ROLLBACK" if exc_type else "COMMIT")
