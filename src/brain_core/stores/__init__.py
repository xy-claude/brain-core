"""Store adapters (v0.2, M9): one interface over the places an agent's memory lives.

* :class:`VaultStore` — markdown vault (`agents/<NAME>/`), see ``docs/VAULT_SCHEMA.md``
* :class:`HindsightStore` — self-hosted Hindsight over its MCP HTTP endpoint
* :class:`GraphStore` — the ``relations`` table in brain.db
* :class:`MemoryStore` — in-memory fake for tests
"""

from brain_core.stores.base import Kind, Record, Store, WriteResult
from brain_core.stores.fakes import MemoryStore
from brain_core.stores.graph import GraphStore
from brain_core.stores.hindsight import HindsightStore
from brain_core.stores.sqlite import SqliteStore
from brain_core.stores.vault import VaultStore

__all__ = [
    "GraphStore",
    "HindsightStore",
    "Kind",
    "MemoryStore",
    "Record",
    "SqliteStore",
    "Store",
    "VaultStore",
    "WriteResult",
]
