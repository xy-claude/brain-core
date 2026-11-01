"""Live checks against the real local stores. Skipped when they are not present.

Hindsight writes go to a throwaway bank (``brain-test``) so the agent's own bank stays clean.
The graph is read-only here; writes are covered by the unit fakes.
"""

from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path

import pytest

from brain_core.stores.graph import GraphStore
from brain_core.stores.hindsight import HindsightStore

HS_URL = os.environ.get("HINDSIGHT_URL", "http://127.0.0.1:8888")
GRAPH = Path("~/Projects/AI-ORG/scripts/python/entity_graph.py").expanduser()
PY = Path("~/Projects/AI-ORG/venv/bin/python3").expanduser()


@pytest.fixture
def hindsight() -> HindsightStore:
    h = HindsightStore(HS_URL, "brain-test", "brain-core", timeout=40)
    if not h.health()[0]:
        pytest.skip("local Hindsight not running")
    return h


def test_hindsight_round_trip(hindsight: HindsightStore) -> None:
    stamp = f"{time.time():.0f}"
    r = hindsight.write(
        "fact",
        f"On 2026-11-02 brain-core M9 live test {stamp}: the Hindsight adapter "
        "retained a fact and polled the operation to completion.",
        domain="system",
        when=date(2026, 11, 2),
    )
    assert r.status == "written", r
    hits = hindsight.read("fact", f"M9 live test {stamp}")
    assert any(stamp in h.text for h in hits), [h.text[:60] for h in hits]


@pytest.mark.skipif(
    not (GRAPH.exists() and PY.exists()), reason="AI-ORG entity graph not on this machine"
)
def test_graph_import_from_legacy_kuzu_dump(tmp_path: Path) -> None:
    import subprocess

    from brain_core.storage.db import Database
    from brain_core.storage.migrator import migrate

    dump = subprocess.run([str(PY), str(GRAPH), "all"], capture_output=True, text=True, timeout=120)
    with Database.connect(tmp_path / "g.db") as db:
        migrate(db)
        g = GraphStore(db)
        counts = g.import_dump(dump.stdout)
        assert counts["written"] > 50 and counts["exists"] == 0
        assert g.read("relation"), "import produced readable relations"
        assert g.import_dump(dump.stdout)["written"] == 0, "second import is a no-op"
