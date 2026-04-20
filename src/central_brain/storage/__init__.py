"""SQLite storage layer for central-brain.

Public API:
    Database — connection + transaction primitive
    migrate  — forward-only schema migrator
"""

from central_brain.storage.db import Database
from central_brain.storage.migrator import migrate

__all__ = ["Database", "migrate"]
