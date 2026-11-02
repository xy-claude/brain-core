"""Unit tests for migration discovery + ordering."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_core.storage import migrator
from brain_core.storage.db import Database
from brain_core.storage.migrator import discover_migrations


def test_discover_returns_at_least_initial() -> None:
    migrations = discover_migrations()
    assert len(migrations) >= 1
    first = migrations[0]
    assert first.version == 1
    assert first.name == "initial"
    assert first.sql.strip(), "initial migration SQL should not be empty"


def test_migrations_sorted_by_version() -> None:
    migrations = discover_migrations()
    versions = [m.version for m in migrations]
    assert versions == sorted(versions)
    assert len(versions) == len(set(versions)), "no duplicate versions"


def test_every_migration_has_version_and_sql() -> None:
    for m in discover_migrations():
        assert m.version > 0
        assert m.name
        assert m.sql.strip()


def test_migrate_tolerates_a_version_row_written_by_another_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = Database.connect(tmp_path / "b.db")
    try:
        applied = set(migrator.migrate(db))
        assert migrator.migrate(db) == []
        # a second process inserted every version between our read and our insert
        monkeypatch.setattr(migrator, "_applied_versions", lambda _db: set())
        assert migrator.migrate(db) == sorted(applied)
    finally:
        db.close()
