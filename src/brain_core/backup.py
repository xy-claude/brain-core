"""Checked, owner-only backups a migration takes before it changes anything (M1a, M1b)."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from brain_core.storage.db import Database


def stamp() -> str:
    """A UTC timestamp to the microsecond, for file names that never collide."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def private_file(path: Path, data: bytes = b"") -> Path:
    """A new file only the owner can read (mode 0600; on Windows the folder's access rules
    apply), never an existing one overwritten."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def backup_db(db: Database, folder: Path, at: str) -> Path:
    """``brain.db`` copied through SQLite's backup API into ``folder`` (made 0700), checked
    with ``integrity_check``. Raises, and the caller changes nothing, if the copy is not sound."""
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    copy = private_file(folder / f"brain-{at}.db")
    with sqlite3.connect(copy) as dst:
        db.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close()
    if ok != "ok":
        raise RuntimeError(f"the backup {copy} failed its integrity check ({ok}): nothing changed")
    return copy
