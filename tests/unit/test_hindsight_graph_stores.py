"""HindsightStore and GraphStore against fakes (no network, no Kuzu)."""

from __future__ import annotations

from datetime import date
from typing import Any

from brain_core.storage.db import Database
from brain_core.stores.graph import GraphStore
from brain_core.stores.hindsight import HindsightStore


class FakeHindsight(HindsightStore):
    """Replace the HTTP layer with a scripted server."""

    def __init__(self, ops: list[str]) -> None:
        super().__init__("http://127.0.0.1:1", "test-bank", "XYCLAUDE", timeout=2)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.ops = ops  # statuses returned by successive get_operation calls

    def call(self, tool: str, **args: Any) -> Any:
        self.calls.append((tool, args))
        if tool == "retain":
            return {"status": "accepted", "operation_id": "op-1"}
        if tool == "get_operation":
            return {"status": self.ops.pop(0)}
        if tool == "recall":
            return {
                "results": [
                    {
                        "id": "m1",
                        "text": "Sir prefers short commits",
                        "tags": ["type:pattern", "domain:system"],
                        "occurred_start": "2026-11-01T00:00:00+00:00",
                        "context": "user-feedback",
                        "fact_type": "world",
                    }
                ]
            }
        raise AssertionError(tool)


def test_hindsight_write_polls_until_completed() -> None:
    h = FakeHindsight(["pending", "completed"])
    r = h.write(
        "decision", "Self-host Hindsight", domain="System", when=date(2026, 11, 1), impact="high"
    )
    assert r.status == "written" and r.detail == "op op-1"
    tool, args = h.calls[0]
    assert tool == "retain" and args["context"] == "session-decision"
    assert args["tags"] == [
        "agent:xyclaude",
        "type:decision",
        "session:2026-11-01",
        "domain:system",
    ]
    assert args["document_id"] == "session-2026-11-01" and args["metadata"]["impact"] == "high"


def test_hindsight_write_reports_failed_and_pending() -> None:
    assert FakeHindsight(["failed"]).write("fact", "x").status == "failed"
    slow = FakeHindsight(["pending"] * 50)
    slow.timeout = 0.6
    assert slow.write("fact", "y").status == "pending"


def test_hindsight_read_maps_tags_to_record() -> None:
    r = FakeHindsight([]).read("pattern", "commits")[0]
    assert r.kind == "pattern" and r.domain == "system" and r.date == date(2026, 11, 1)
    assert r.path == "hindsight://test-bank/m1" and r.extra["context"] == "user-feedback"


def test_hindsight_health_when_down() -> None:
    ok, detail = HindsightStore("http://127.0.0.1:1", "b").health()
    assert ok is False and "unreachable" in detail


def test_graph_write_read_import_in_sqlite(db: Database) -> None:
    g = GraphStore(db)
    assert g.write("relation", "", subject="A", predicate="b", object="C").status == "written"
    assert g.write("relation", "A —[b]→ C").status == "exists"
    assert g.write("fact", "nope").status == "refused"
    assert g.write("relation", "no arrow here").status == "refused"
    rs = g.read("relation", "C")
    assert [r.text for r in rs] == ["A —[b]→ C"] and rs[0].extra["object"] == "C"
    assert g.read("fact") == [] and g.health() == (True, "graph relations=1")
    counts = g.import_dump(
        "  XYCLAUDE —[uses]→ Hindsight  (2026-04-11)\n  A —[b]→ C  (2026-01-01)\n82 relationships\n"
    )
    assert counts == {"written": 1, "exists": 1, "skipped": 1}
    assert g.read("relation", "hindsight")[0].date == date(2026, 4, 11)
