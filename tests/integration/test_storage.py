"""Storage layer durability + schema enforcement tests.

These are integration tests — they open real SQLite databases in tmp paths.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from brain_core.storage import Database, migrate


def test_round_trip_persistence(tmp_path: Path) -> None:
    """Write, close, reopen, read — state survives process lifecycle."""
    db_path = tmp_path / "brain.db"

    with Database.connect(db_path) as db:
        versions = migrate(db)
        assert versions == [1], "initial migration should apply on first open"
        db.execute(
            "INSERT INTO facts (content, kind, content_hash) VALUES (?, ?, ?)",
            ("Sir prefers dark mode", "preference", "hash-1"),
        )

    with Database.connect(db_path) as db:
        versions = migrate(db)
        assert versions == [], "no pending migrations on second open"
        row = db.fetchone(
            "SELECT content, kind FROM facts WHERE content_hash = ?",
            ("hash-1",),
        )
        assert row is not None
        assert row["content"] == "Sir prefers dark mode"
        assert row["kind"] == "preference"


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    """Calling migrate twice in the same session returns [] on the second call."""
    db_path = tmp_path / "brain.db"
    with Database.connect(db_path) as db:
        first = migrate(db)
        second = migrate(db)
    assert first == [1]
    assert second == []


def test_wal_journal_mode(tmp_path: Path) -> None:
    """Connections open in WAL mode for better concurrency + recovery."""
    db_path = tmp_path / "brain.db"
    with Database.connect(db_path) as db:
        row = db.fetchone("PRAGMA journal_mode")
        assert row is not None
        assert row[0].lower() == "wal"


def test_foreign_keys_enforced(tmp_path: Path) -> None:
    """SQLite default is FK=OFF; we force it ON. Verify with a bad reference."""
    db_path = tmp_path / "brain.db"
    with Database.connect(db_path) as db:
        migrate(db)
        with pytest.raises(sqlite3.IntegrityError), db.transaction():
            db.execute(
                "INSERT INTO facts (content, kind, content_hash, superseded_by) "
                "VALUES (?, ?, ?, ?)",
                ("x", "fact", "hash-fk", 999999),  # no such fact id
            )


def test_transaction_rolls_back_on_exception(tmp_path: Path) -> None:
    """Exception inside transaction() must roll back all writes in the block."""
    db_path = tmp_path / "brain.db"
    with Database.connect(db_path) as db:
        migrate(db)
        with pytest.raises(RuntimeError), db.transaction():
            db.execute(
                "INSERT INTO facts (content, kind, content_hash) VALUES (?, ?, ?)",
                ("should-rollback", "fact", "hash-rb"),
            )
            raise RuntimeError("boom")

        row = db.fetchone("SELECT id FROM facts WHERE content_hash = ?", ("hash-rb",))
        assert row is None


def test_content_hash_uniqueness_enforced(tmp_path: Path) -> None:
    """facts.content_hash is UNIQUE — dedup guard at schema level."""
    db_path = tmp_path / "brain.db"
    with Database.connect(db_path) as db:
        migrate(db)
        db.execute(
            "INSERT INTO facts (content, kind, content_hash) VALUES (?, ?, ?)",
            ("first", "fact", "same-hash"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO facts (content, kind, content_hash) VALUES (?, ?, ?)",
                ("second", "fact", "same-hash"),
            )


def test_fts_search_via_trigger(tmp_path: Path) -> None:
    """FTS5 index is auto-populated by triggers and returns matches."""
    db_path = tmp_path / "brain.db"
    with Database.connect(db_path) as db:
        migrate(db)
        db.execute(
            "INSERT INTO facts (content, kind, content_hash) VALUES (?, ?, ?)",
            ("deployment failed due to missing env var", "pattern", "h1"),
        )
        db.execute(
            "INSERT INTO facts (content, kind, content_hash) VALUES (?, ?, ?)",
            ("user loves dark mode", "preference", "h2"),
        )

        rows = db.fetchall(
            "SELECT f.content FROM facts_fts fts "
            "JOIN facts f ON fts.rowid = f.id "
            "WHERE facts_fts MATCH ?",
            ("deployment",),
        )
    assert len(rows) == 1
    assert "deployment failed" in rows[0]["content"]


def test_check_constraint_on_fact_kind(tmp_path: Path) -> None:
    """facts.kind enforces its allowed set via CHECK."""
    db_path = tmp_path / "brain.db"
    with Database.connect(db_path) as db:
        migrate(db)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO facts (content, kind, content_hash) VALUES (?, ?, ?)",
                ("bad", "garbage-kind", "h-bad"),
            )


def test_all_v0_tables_exist(tmp_path: Path) -> None:
    """Every table the v0 spec promises is created by the initial migration."""
    db_path = tmp_path / "brain.db"
    with Database.connect(db_path) as db:
        migrate(db)
        rows = db.fetchall(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE 'facts_fts%'"
        )
    table_names = {row["name"] for row in rows}
    expected = {
        "schema_version",
        "facts",
        "decisions",
        "events",
        "hsam_days",
        "reflections",
        "metrics",
    }
    assert expected.issubset(table_names), f"missing tables: {expected - table_names}"
