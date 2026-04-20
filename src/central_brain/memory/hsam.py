"""HSAM — Hyperthymesia-style daily archive.

One markdown file per day, appended continuously throughout the session.
``hsam_days`` table holds metadata only (path, word count, last write time)
so callers can query "what days do we have archives for" cheaply without
scanning the filesystem. The prose body always lives on disk.

File layout::

    <workspace>/hsam/YYYY-MM-DD.md

The first write of a new day emits an ``# YYYY-MM-DD`` header. Subsequent
writes append verbatim.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Final

from central_brain.storage.db import Database

_DEFAULT_SUBDIR: Final[str] = "hsam"


@dataclass(frozen=True, slots=True)
class HSAMDay:
    """Metadata for one day's archive."""

    date: Date
    archive_path: str  # relative to workspace
    word_count: int
    last_written: datetime


def append_today(
    db: Database,
    workspace: Path,
    text: str,
    *,
    subdir: str = _DEFAULT_SUBDIR,
    today: Date | None = None,
) -> HSAMDay:
    """Append ``text`` to today's archive file. Returns the updated HSAMDay.

    Creates the archive file + directory + index row on first write of a day.
    Subsequent writes append and update the word count.

    ``today`` parameter is primarily for tests; defaults to ``date.today()``.

    Raises:
        ValueError: if ``text`` is empty (whitespace-only counts as empty).
    """
    if not text.strip():
        raise ValueError("text must not be empty")

    day = today if today is not None else Date.today()
    archive_dir = workspace / subdir
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_file = archive_dir / f"{day.isoformat()}.md"

    is_new_day = not archive_file.exists()
    with archive_file.open("a", encoding="utf-8") as f:
        if is_new_day:
            f.write(f"# {day.isoformat()}\n\n")
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")

    word_count = len(archive_file.read_text(encoding="utf-8").split())
    relative = _relative_path(archive_file, workspace)

    db.execute(
        "INSERT INTO hsam_days (date, archive_path, word_count) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(date) DO UPDATE SET "
        "  archive_path = excluded.archive_path, "
        "  word_count = excluded.word_count, "
        "  last_written = CURRENT_TIMESTAMP",
        (day.isoformat(), relative, word_count),
    )
    row = db.fetchone("SELECT * FROM hsam_days WHERE date = ?", (day.isoformat(),))
    if row is None:  # pragma: no cover — defensive
        raise RuntimeError(f"hsam_days row missing after upsert: date={day}")
    return _row_to_hsam_day(row)


def _relative_path(archive_file: Path, workspace: Path) -> str:
    try:
        return str(archive_file.relative_to(workspace))
    except ValueError:
        return str(archive_file)


def _row_to_hsam_day(row: sqlite3.Row) -> HSAMDay:
    return HSAMDay(
        date=Date.fromisoformat(str(row["date"])),
        archive_path=str(row["archive_path"]),
        word_count=int(row["word_count"]),
        last_written=datetime.fromisoformat(row["last_written"]),
    )
