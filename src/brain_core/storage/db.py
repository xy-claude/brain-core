"""SQLite connection + transaction primitive.

Wraps ``sqlite3.Connection`` with opinionated defaults:
  * WAL journal mode (better concurrency, crash recovery)
  * Foreign keys ON (SQLite defaults to OFF — we always want them ON)
  * ``sqlite3.Row`` factory (column access by name)
  * Manual transaction management (autocommit; use ``transaction()`` context)

No ORM. Tables are accessed via raw SQL. Capability modules build typed
dataclasses on top of the Row results.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Self, cast

SqliteValue = str | int | float | bytes | None
Params = Sequence[SqliteValue] | Mapping[str, SqliteValue]


class Database:
    """Thin wrapper around ``sqlite3.Connection`` with safe defaults."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def connect(cls, path: str | Path) -> Self:
        """Open (or create) the database at ``path`` with opinionated pragmas.

        The connection is in autocommit mode — use :meth:`transaction` for
        atomic writes.
        """
        conn = sqlite3.connect(
            str(path),
            isolation_level=None,  # autocommit; we manage transactions
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")
        return cls(conn)

    def execute(self, sql: str, params: Params = ()) -> sqlite3.Cursor:
        """Execute a single statement with parameters."""
        return self._conn.execute(sql, params)

    def executescript(self, sql: str) -> sqlite3.Cursor:
        """Execute multiple statements separated by semicolons (DDL/migrations).

        Note: executescript implicitly commits any pending transaction. Use
        :meth:`execute` inside :meth:`transaction` for atomic DML.
        """
        return self._conn.executescript(sql)

    def fetchone(self, sql: str, params: Params = ()) -> sqlite3.Row | None:
        """Run a query and return the first row, or None."""
        row = self._conn.execute(sql, params).fetchone()
        return cast("sqlite3.Row | None", row)

    def fetchall(self, sql: str, params: Params = ()) -> list[sqlite3.Row]:
        """Run a query and return all rows."""
        rows = self._conn.execute(sql, params).fetchall()
        return cast("list[sqlite3.Row]", list(rows))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Atomic transaction. Rolls back on exception, commits on clean exit."""
        self._conn.execute("BEGIN")
        try:
            yield
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
