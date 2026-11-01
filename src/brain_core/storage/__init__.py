"""SQLite storage layer for brain-core.

Public API:
    Database — connection + transaction primitive
    migrate  — forward-only schema migrator
"""

from brain_core.storage.db import Database
from brain_core.storage.migrator import migrate

__all__ = ["Database", "migrate"]
