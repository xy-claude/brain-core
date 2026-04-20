"""HSAM daily archive tests."""

from __future__ import annotations

from datetime import date as Date
from pathlib import Path

import pytest

from central_brain.memory import append_today
from central_brain.storage import Database


def test_append_today_creates_file_and_index_row(db: Database, workspace: Path) -> None:
    fixed = Date(2026, 4, 20)
    result = append_today(db, workspace, "first line of the day.", today=fixed)

    archive_file = workspace / "hsam" / "2026-04-20.md"
    assert archive_file.exists()
    body = archive_file.read_text(encoding="utf-8")
    assert body.startswith("# 2026-04-20\n\n")
    assert "first line of the day." in body

    assert result.date == fixed
    assert result.archive_path == "hsam/2026-04-20.md"
    assert result.word_count == len(body.split())


def test_append_today_appends_within_same_day(db: Database, workspace: Path) -> None:
    fixed = Date(2026, 4, 20)
    append_today(db, workspace, "first line.", today=fixed)
    result = append_today(db, workspace, "second line.", today=fixed)

    archive_file = workspace / "hsam" / "2026-04-20.md"
    body = archive_file.read_text(encoding="utf-8")
    # Header is written once, not duplicated
    assert body.count("# 2026-04-20") == 1
    assert "first line." in body
    assert "second line." in body
    assert result.word_count == len(body.split())


def test_append_today_different_days_separate_files(db: Database, workspace: Path) -> None:
    append_today(db, workspace, "monday stuff.", today=Date(2026, 4, 20))
    append_today(db, workspace, "tuesday stuff.", today=Date(2026, 4, 21))

    monday = workspace / "hsam" / "2026-04-20.md"
    tuesday = workspace / "hsam" / "2026-04-21.md"
    assert monday.exists()
    assert tuesday.exists()
    assert "monday stuff." in monday.read_text(encoding="utf-8")
    assert "tuesday stuff." in tuesday.read_text(encoding="utf-8")

    rows = db.fetchall("SELECT date FROM hsam_days ORDER BY date")
    assert [r["date"] for r in rows] == ["2026-04-20", "2026-04-21"]


def test_append_today_rejects_empty_text(db: Database, workspace: Path) -> None:
    with pytest.raises(ValueError, match="text must not be empty"):
        append_today(db, workspace, "   \n   ")


def test_append_today_uses_today_by_default(db: Database, workspace: Path) -> None:
    """Without an explicit ``today`` arg, uses date.today()."""
    today = Date.today()
    result = append_today(db, workspace, "auto-dated line.")
    assert result.date == today


def test_append_today_custom_subdir(db: Database, workspace: Path) -> None:
    fixed = Date(2026, 4, 20)
    append_today(db, workspace, "custom.", subdir="journal", today=fixed)
    assert (workspace / "journal" / "2026-04-20.md").exists()
    assert not (workspace / "hsam").exists()


def test_append_today_updates_last_written(db: Database, workspace: Path) -> None:
    fixed = Date(2026, 4, 20)
    first = append_today(db, workspace, "one.", today=fixed)
    second = append_today(db, workspace, "two.", today=fixed)
    assert second.last_written >= first.last_written
