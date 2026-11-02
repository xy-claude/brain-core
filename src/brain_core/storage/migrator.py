"""Forward-only schema migrator.

Migrations live in ``brain_core.storage.migrations`` as numbered SQL files::

    001_initial.sql
    002_add_thing.sql
    ...

On each call to :func:`migrate`, the migrator:
  1. Ensures the ``schema_version`` table exists (self-bootstraps)
  2. Discovers migration files via :mod:`importlib.resources`
  3. Applies any whose version is not yet recorded, in numeric order
  4. Records each successful migration in ``schema_version``

There are no down migrations. A rollback is a new forward migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable

from brain_core.storage.db import Database

_MIGRATIONS_PACKAGE = "brain_core.storage.migrations"


@dataclass(frozen=True, slots=True)
class Migration:
    """A single schema migration file."""

    version: int
    name: str
    sql: str

    @classmethod
    def from_traversable(cls, entry: Traversable) -> Migration:
        """Parse a ``NNN_name.sql`` file into a Migration."""
        filename = entry.name
        if not filename.endswith(".sql"):
            raise ValueError(f"not a .sql file: {filename}")
        stem = filename[:-4]
        num_str, sep, name = stem.partition("_")
        if not sep or not num_str.isdigit():
            raise ValueError(f"migration filename must be 'NNN_name.sql': {filename}")
        return cls(
            version=int(num_str),
            name=name,
            sql=entry.read_text(encoding="utf-8"),
        )


def discover_migrations() -> list[Migration]:
    """Return all migrations in the migrations package, sorted by version."""
    package = files(_MIGRATIONS_PACKAGE)
    migrations = [
        Migration.from_traversable(entry)
        for entry in package.iterdir()
        if entry.is_file() and entry.name.endswith(".sql") and not entry.name.startswith("_")
    ]
    migrations.sort(key=lambda m: m.version)
    return migrations


def _ensure_version_table(db: Database) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, "
        "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ")"
    )


def _applied_versions(db: Database) -> set[int]:
    rows = db.fetchall("SELECT version FROM schema_version")
    return {int(row["version"]) for row in rows}


def migrate(db: Database) -> list[int]:
    """Apply any pending migrations in version order.

    Returns the list of versions applied in this call. Safe to call repeatedly
    — already-applied migrations are skipped.

    Atomicity note: ``sqlite3.Cursor.executescript`` implicitly commits before
    running its script, so a single BEGIN/COMMIT around a migration is not
    possible with the stdlib driver. Migrations must be written idempotently
    (``CREATE TABLE IF NOT EXISTS``, etc.) so that a partial failure followed
    by a retry converges to the desired state.
    """
    _ensure_version_table(db)
    applied = _applied_versions(db)
    pending = [m for m in discover_migrations() if m.version not in applied]
    newly_applied: list[int] = []
    for migration in pending:
        db.executescript(migration.sql)
        db.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (migration.version,),
        )
        newly_applied.append(migration.version)
    return newly_applied
