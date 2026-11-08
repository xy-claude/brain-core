"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from brain_core.storage import Database, migrate

# On Windows a bare `bash` is the WSL launcher; the hooks and install.sh need Git Bash, which is
# what Claude Code itself uses there.
BASH = (
    r"C:\Program Files\Git\bin\bash.exe"
    if sys.platform == "win32" and Path(r"C:\Program Files\Git\bin\bash.exe").exists()
    else shutil.which("bash") or "bash"
)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    """A freshly-migrated Database in a tmp dir. Closes after each test."""
    with Database.connect(tmp_path / "brain.db") as database:
        migrate(database)
        yield database


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A fresh workspace dir (for capabilities that touch the filesystem)."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws
