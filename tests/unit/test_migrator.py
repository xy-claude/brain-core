"""Unit tests for migration discovery + ordering."""

from __future__ import annotations

from central_brain.storage.migrator import discover_migrations


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
