"""HindsightStore and GraphStore against fakes (no network, no Kuzu)."""

from __future__ import annotations

import subprocess
from datetime import date
from typing import Any

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


def _runner(stdout: str, rc: int = 0) -> Any:
    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        run.args = args  # type: ignore[attr-defined]
        return subprocess.CompletedProcess(args, rc, stdout, "")

    return run


def test_graph_read_parses_cli_lines() -> None:
    g = GraphStore(
        "x.py",
        runner=_runner("  XYCLAUDE —[uses]→ Hindsight  (2026-04-11)\n  A —[b]→ C  (2026-11-02)\n"),
    )
    rs = g.read("relation", "Hindsight")
    assert [r.text for r in rs] == ["XYCLAUDE —[uses]→ Hindsight", "A —[b]→ C"]
    assert rs[0].extra == {"subject": "XYCLAUDE", "predicate": "uses", "object": "Hindsight"}
    assert rs[0].date == date(2026, 4, 11) and g.read("fact") == []


def test_graph_write_uses_fields_or_arrow_text() -> None:
    run = _runner("added: A —[b]→ C")
    g = GraphStore("x.py", runner=run)
    assert g.write("relation", "", subject="A", predicate="b", object="C").status == "written"
    assert run.args == ["add", "A", "b", "C"]
    assert (
        g.write("relation", "A —[b]→ C").id
        == g.write("relation", "", subject="A", predicate="b", object="C").id
    )
    assert g.write("fact", "nope").status == "refused"
    assert (
        GraphStore("x.py", runner=_runner("boom", rc=1)).write("relation", "A —[b]→ C").status
        == "failed"
    )


def test_graph_health() -> None:
    assert GraphStore("x.py", runner=_runner("Entities: 75\nRelationships: 81\n")).health() == (
        True,
        "Entities: 75 Relationships: 81",
    )
