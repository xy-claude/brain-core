"""M1c: data/journal.db, the history no Markdown file holds. One ledger row per version of a
record at an occurrence (a source, a record, the k-th copy), with when the vault held it."""

from __future__ import annotations

import os
import sqlite3
import stat
import sys
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from brain_core.journal import Journal, occurrence_id
from brain_core.storage import Database, migrate
from brain_core.stores.base import record_id
from brain_core.stores.index import RecordIndex
from brain_core.stores.vault import VaultStore

T0 = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def tick(self, hours: float = 1) -> None:
        self.now += timedelta(hours=hours)


def facts(root: Path, *lines: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    body = "".join(f"- {ln}\n" for ln in lines)
    (root / "facts.md").write_text(f"# Facts\n\n## General\n{body}")


def setup(tmp_path: Path) -> tuple[Journal, Database, VaultStore, Clock]:
    clock = Clock()
    j = Journal(tmp_path / "data" / "journal.db", clock=clock)
    db = Database.connect(tmp_path / "brain.db")
    migrate(db)
    return j, db, VaultStore(tmp_path / "vault", index=RecordIndex(db, j)), clock


def sync(v: VaultStore) -> None:
    v.read("fact", "sync")


def rows(j: Journal) -> list[tuple[str, str, str, str | None, str]]:
    return [
        tuple(r)
        for r in j.db.fetchall(
            "SELECT o.record_id, l.content_hash, l.seen_from, l.seen_to, l.via "
            "FROM record_ledger l "
            "JOIN ledger_occurrences o USING (occ_id) ORDER BY l.seen_from, o.record_id"
        )
    ]


def occ(text: str, k: int = 1, source: str = "vault:facts.md") -> str:
    return occurrence_id(source, record_id(text), k)


def test_a_new_record_is_recorded_when_the_vault_first_holds_it(tmp_path: Path) -> None:
    j, _db, v, clock = setup(tmp_path)
    facts(v.root, "Port is 8888")
    sync(v)
    ((rid, _h, seen_from, seen_to, via),) = rows(j)
    assert (rid, seen_from, seen_to, via) == (
        record_id("Port is 8888"),
        j.stamp(T0),
        None,
        "ingest",
    )
    clock.tick()
    sync(v)  # nothing changed: nothing recorded
    assert len(rows(j)) == 1


def test_a_removed_line_closes_and_a_returning_one_keeps_its_first_time(tmp_path: Path) -> None:
    j, _db, v, clock = setup(tmp_path)
    facts(v.root, "Port is 8888", "Host is mini")
    sync(v)
    clock.tick()
    facts(v.root, "Host is mini")
    sync(v)
    clock.tick()
    facts(v.root, "Port is 8888", "Host is mini")
    sync(v)
    port = [r for r in rows(j) if r[0] == record_id("Port is 8888")]
    assert [(r[2], r[3]) for r in port] == [
        (j.stamp(T0), j.stamp(T0 + timedelta(hours=1))),
        (j.stamp(T0 + timedelta(hours=2)), None),
    ]
    h = port[0][1]
    assert j.recorded_at(occ("Port is 8888"), h) == j.stamp(T0)


def test_an_edited_knowledge_section_is_a_new_version_at_the_same_occurrence(
    tmp_path: Path,
) -> None:
    j, _db, v, clock = setup(tmp_path)
    page = v.root / "knowledge" / "x.md"
    page.parent.mkdir(parents=True)
    page.write_text("# X\n\n## Deploy\nrsync\n")
    v.read("knowledge", "sync")
    clock.tick()
    page.write_text("# X\n\n## Deploy\nrsync, then restart\n")
    v.read("knowledge", "sync")
    versions = rows(j)
    assert len({r[0] for r in versions}) == 1 and len({r[1] for r in versions}) == 2
    assert versions[0][3] == versions[1][2]  # the old closes when the new opens


def test_a_copy_in_the_same_file_is_its_own_occurrence(tmp_path: Path) -> None:
    j, _db, v, clock = setup(tmp_path)
    facts(v.root, "Port is 8888")
    sync(v)
    clock.tick()
    facts(v.root, "Port is 8888", "Port is 8888")
    sync(v)
    occs = {r[0] for r in j.db.fetchall("SELECT occ_id FROM record_ledger WHERE seen_to IS NULL")}
    assert occs == {occ("Port is 8888", 1), occ("Port is 8888", 2)}


def test_an_unambiguous_move_keeps_its_recording_time(tmp_path: Path) -> None:
    j, _db, v, clock = setup(tmp_path)
    (v.root / "patterns.md").parent.mkdir(parents=True, exist_ok=True)
    facts(v.root, "Ships on Fridays")
    (v.root / "patterns.md").write_text("# Patterns\n\n## General\n")
    sync(v)
    clock.tick()
    facts(v.root)
    (v.root / "patterns.md").write_text("# Patterns\n\n## General\n- Ships on Fridays\n")
    v.read("pattern", "sync")
    moved = j.db.fetchone(
        "SELECT occ_id, content_hash, via FROM record_ledger WHERE seen_to IS NULL"
    )
    assert moved is not None and moved["via"] == "move"
    assert j.recorded_at(moved["occ_id"], moved["content_hash"]) == j.stamp(T0)


def test_an_ambiguous_move_inherits_nothing(tmp_path: Path) -> None:
    j, _db, v, clock = setup(tmp_path)
    facts(v.root, "Ships on Fridays", "Ships on Fridays")
    (v.root / "patterns.md").write_text("# Patterns\n\n## General\n")
    sync(v)
    clock.tick()
    facts(v.root)
    (v.root / "patterns.md").write_text("# Patterns\n\n## General\n- Ships on Fridays\n")
    v.read("pattern", "sync")
    opened = j.db.fetchall("SELECT via FROM record_ledger WHERE seen_to IS NULL")
    assert [r["via"] for r in opened] == ["ingest"]


def test_rebuilding_brain_db_adds_no_history(tmp_path: Path) -> None:
    j, db, v, clock = setup(tmp_path)
    facts(v.root, "Port is 8888")
    sync(v)
    before = rows(j)
    db.close()
    (tmp_path / "brain.db").unlink()
    clock.tick()
    db2 = Database.connect(tmp_path / "brain.db")
    migrate(db2)
    v2 = VaultStore(v.root, index=RecordIndex(db2, j))
    sync(v2)
    assert rows(j) == before


def test_a_crash_between_the_journal_and_brain_db_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j, db, v, clock = setup(tmp_path)
    facts(v.root, "Port is 8888")
    real = Database.transaction

    def crash(self):  # the journal has committed; brain.db is killed before its commit
        raise KeyboardInterrupt

    monkeypatch.setattr(Database, "transaction", crash)
    with pytest.raises(KeyboardInterrupt):
        sync(v)
    monkeypatch.setattr(Database, "transaction", real)
    assert len(rows(j)) == 1
    clock.tick()
    sync(v)
    assert len(rows(j)) == 1 and rows(j)[0][2] == j.stamp(T0)  # the first sync's time, kept
    assert db.fetchone("SELECT count(*) FROM records_fts")[0] == 1  # type: ignore[index]


def test_one_occurrence_has_at_most_one_open_version(tmp_path: Path) -> None:
    j = Journal(tmp_path / "journal.db")
    ins = "INSERT INTO record_ledger VALUES (?, ?, ?, NULL, 'ingest', NULL)"
    j.db.execute(ins, ("o1", "h1", "2026-11-23T09:00:00.000000Z"))
    with pytest.raises(sqlite3.IntegrityError):
        j.db.execute(ins, ("o1", "h2", "2026-11-23T10:00:00.000000Z"))


def test_the_journal_commits_durably(tmp_path: Path) -> None:
    j = Journal(tmp_path / "journal.db")
    assert j.db.fetchone("PRAGMA synchronous")[0] == 2  # type: ignore[index]  # FULL


def test_a_lost_journal_commit_records_a_gap_and_reads_everything_again(tmp_path: Path) -> None:
    j, db, v, clock = setup(tmp_path)
    facts(v.root, "Port is 8888")
    sync(v)
    older = tmp_path / "journal-older.db"
    with sqlite3.connect(older) as dst:  # the journal as it was after the first sync
        j.db.backup(dst)
    dst.close()
    clock.tick()
    facts(v.root, "Port is 8888", "Host is mini")
    sync(v)
    j.db.close()
    os.replace(older, j.path)  # power loss: the journal lost its last commit
    clock.tick()
    j2 = Journal(j.path, clock=clock)
    v2 = VaultStore(v.root, index=RecordIndex(db, j2))
    sync(v2)
    gaps = j2.db.fetchall("SELECT cause, gap_from, gap_to FROM ledger_gaps ORDER BY gap_from")
    assert [g["cause"] for g in gaps] == ["epoch", "restore"]
    assert gaps[1]["gap_to"] == j2.stamp(clock.now)
    assert record_id("Host is mini") in {r[0] for r in rows(j2)}  # read again, recorded now


def test_a_new_journal_beside_an_old_brain_db_starts_an_epoch(tmp_path: Path) -> None:
    j, db, v, clock = setup(tmp_path)
    facts(v.root, "Port is 8888")
    sync(v)
    j.db.close()
    j.path.unlink()
    clock.tick()
    j2 = Journal(j.path, clock=clock)
    sync(VaultStore(v.root, index=RecordIndex(db, j2)))
    ((_rid, _h, seen_from, _to, _via),) = rows(j2)
    assert seen_from == j2.stamp(clock.now)  # late, never early
    gap = j2.db.fetchone("SELECT cause, gap_to FROM ledger_gaps")
    assert (gap["cause"], gap["gap_to"]) == ("epoch", j2.stamp(clock.now))  # type: ignore[index]


def test_two_writers_take_turns(tmp_path: Path) -> None:
    a = Journal(tmp_path / "journal.db")
    b = Journal(tmp_path / "journal.db")
    order: list[str] = []

    def second() -> None:
        with b.locked():
            order.append("b")

    with a.locked():
        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.2)
        order.append("a")
    t.join(5)
    assert order == ["a", "b"]


def test_a_file_edited_during_the_sync_is_left_for_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j, _db, v, clock = setup(tmp_path)
    facts(v.root, "Port is 8888")
    real = VaultStore._parse

    def edit_while_reading(self, kind, path, full=False):
        out = real(self, kind, path, full)
        if path.name == "facts.md" and not getattr(self, "_edited", False):
            self._edited = True
            facts(self.root, "Port is 8889")  # Obsidian saves mid-sync
        return out

    monkeypatch.setattr(VaultStore, "_parse", edit_while_reading)
    sync(v)
    assert rows(j) == []  # never recorded half-old
    monkeypatch.setattr(VaultStore, "_parse", real)
    clock.tick()
    sync(v)
    assert [r[0] for r in rows(j)] == [record_id("Port is 8889")]


def test_a_save_is_recorded_as_a_write(tmp_path: Path) -> None:
    j, _db, v, _clock = setup(tmp_path)
    v.write("fact", "Port is 8888", when=date(2026, 11, 23))
    assert [r[4] for r in rows(j)] == ["write"]


def test_the_daily_backup_is_checked_private_and_pruned(tmp_path: Path) -> None:
    j, _db, v, _clock = setup(tmp_path)
    facts(v.root, "Port is 8888")
    sync(v)
    folder = tmp_path / "backups" / "agent"
    for d in range(1, 5):
        j.backup(folder, keep=3, today=date(2026, 11, d))
    kept = sorted(p.name for p in folder.glob("journal-*.db"))
    assert kept == ["journal-2026-11-02.db", "journal-2026-11-03.db", "journal-2026-11-04.db"]
    assert sys.platform == "win32" or stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert sys.platform == "win32" or stat.S_IMODE((folder / kept[-1]).stat().st_mode) == 0o600
    copy = sqlite3.connect(folder / kept[-1])
    assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert copy.execute("SELECT count(*) FROM record_ledger").fetchone()[0] == 1


def test_a_restore_merges_history_and_records_the_gap(tmp_path: Path) -> None:
    j, db, v, clock = setup(tmp_path)
    facts(v.root, "Port is 8888")
    sync(v)
    clock.tick()
    backup = j.backup(tmp_path / "b", keep=14, today=date(2026, 11, 23))
    taken = j.taken_at(backup)
    j.db.close()
    j.path.unlink()  # the journal is lost
    clock.tick(5)
    j2 = Journal(j.path, clock=clock)
    sync(VaultStore(v.root, index=RecordIndex(db, j2)))
    report = j2.restore(backup)
    assert report["merged"] >= 1
    first = j2.db.fetchone(
        "SELECT min(seen_from) FROM record_ledger l JOIN ledger_occurrences o USING (occ_id) "
        "WHERE o.record_id = ?",
        (record_id("Port is 8888"),),
    )
    assert first[0] == j2.stamp(T0)  # type: ignore[index]  # history before the loss is back
    gaps = {
        g["cause"]: (g["gap_from"], g["gap_to"])
        for g in j2.db.fetchall("SELECT * FROM ledger_gaps")
    }
    assert gaps["restore"][0] == taken


def test_a_corrupt_backup_is_refused(tmp_path: Path) -> None:
    j = Journal(tmp_path / "journal.db")
    bad = tmp_path / "journal-2026-11-23.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    with pytest.raises(ValueError, match="not a sound journal"):
        j.restore(bad)
