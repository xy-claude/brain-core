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

from central_brain.stores.graph import GraphStore
from central_brain.stores.hindsight import HindsightStore

HS_URL = os.environ.get("HINDSIGHT_URL", "http://127.0.0.1:8888")
GRAPH = Path("~/Projects/AI-ORG/scripts/python/entity_graph.py").expanduser()
PY = Path("~/Projects/AI-ORG/venv/bin/python3").expanduser()


@pytest.fixture
def hindsight() -> HindsightStore:
    h = HindsightStore(HS_URL, "brain-test", "central-brain", timeout=40)
    if not h.health()[0]:
        pytest.skip("local Hindsight not running")
    return h


def test_hindsight_round_trip(hindsight: HindsightStore) -> None:
    stamp = f"{time.time():.0f}"
    r = hindsight.write(
        "fact",
        f"On 2026-11-02 central-brain M9 live test {stamp}: the Hindsight adapter "
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
def test_graph_live_read() -> None:
    g = GraphStore(GRAPH, PY)
    ok, detail = g.health()
    assert ok and "Relationships" in detail
    assert any("XYCLAUDE" in r.text for r in g.read("relation", "XYCLAUDE"))
