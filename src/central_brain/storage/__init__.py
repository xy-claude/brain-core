"""SQLite storage layer for brain-core.

Public API:
    Database — connection + transaction primitive
    migrate  — forward-only schema migrator
"""

from central_brain.storage.db import Database
from central_brain.storage.migrator import migrate

__all__ = ["Database", "migrate"]
