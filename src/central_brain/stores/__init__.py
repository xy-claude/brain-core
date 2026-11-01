"""Store adapters (v0.2, M9): one interface over the places an agent's memory lives.

* :class:`VaultStore` — markdown vault (`agents/<NAME>/`), see ``docs/VAULT_SCHEMA.md``
* :class:`HindsightStore` — self-hosted Hindsight over its MCP HTTP endpoint
* :class:`GraphStore` — Kuzu entity graph via ``entity_graph.py``
* :class:`MemoryStore` — in-memory fake for tests
"""

from central_brain.stores.base import Kind, Record, Store, WriteResult
from central_brain.stores.fakes import MemoryStore
from central_brain.stores.graph import GraphStore
from central_brain.stores.hindsight import HindsightStore
from central_brain.stores.vault import VaultStore

__all__ = [
    "GraphStore",
    "HindsightStore",
    "Kind",
    "MemoryStore",
    "Record",
    "Store",
    "VaultStore",
    "WriteResult",
]
