"""brain_remember: order, per-layer status, duplicate skip, contradiction banner, dead store."""

from __future__ import annotations

from datetime import date

import pytest

from brain_core.remember import brain_remember
from brain_core.stores import MemoryStore
from brain_core.stores.base import Kind, Record, WriteResult
from brain_core.stores.hindsight import HindsightStore

TODAY = date(2026, 11, 2)


def named(name: str, *, healthy: bool = True) -> MemoryStore:
    s = MemoryStore(healthy=healthy)
    s.name = name
    return s


class GraphOnly(MemoryStore):
    name = "graph"

    def write(self, kind: Kind, text: str, **kw: object) -> WriteResult:
        if kind != "relation":
            return WriteResult(self.name, "", "refused", "relations only")
        return super().write(kind, text)


def test_writes_in_order_with_per_layer_status() -> None:
    stores = [named("hindsight"), named("sqlite"), named("vault")]
    out = brain_remember(stores, "Hindsight runs on port 8888", "fact", domain="system", when=TODAY)
    assert out["status"] == "written"
    assert list(out["layers"]) == ["vault", "sqlite", "hindsight"]
    assert all(v["status"] == "written" for v in out["layers"].values())
    again = brain_remember(stores, "Hindsight runs on port 8888", "fact", when=TODAY)
    assert again["status"] == "duplicate" and again["duplicate_of"]["text"].endswith("8888")


def test_dead_layer_is_reported_not_swallowed() -> None:
    down = named("hindsight", healthy=False)
    out = brain_remember([named("vault"), down], "Ada prefers short commits", "pattern", when=TODAY)
    assert out["status"] == "partial"
    assert out["layers"]["hindsight"] == {"status": "failed", "detail": "store down"}
    assert out["layers"]["vault"]["status"] == "written"


def test_real_hindsight_unreachable_is_failed_with_detail() -> None:
    h = HindsightStore("http://127.0.0.1:1", "b", timeout=1)
    out = brain_remember([named("vault"), h], "x marks the spot", "fact", when=TODAY)
    assert out["layers"]["hindsight"]["status"] == "failed"
    assert (
        "Connection" in out["layers"]["hindsight"]["detail"]
        or "refused" in out["layers"]["hindsight"]["detail"]
        or "timed out" in out["layers"]["hindsight"]["detail"]  # Windows: closed port times out
    )


def test_changed_value_gets_banner_and_keeps_old() -> None:
    v = named("vault")
    brain_remember(
        [v], "Hindsight API listens on port 8887 on this Mac", "fact", when=date(2026, 11, 1)
    )
    out = brain_remember([v], "Hindsight API listens on port 8888 on this Mac", "fact", when=TODAY)
    assert out["status"] == "written" and out["contradiction"]["text"].endswith("8887 on this Mac")
    assert out["text"].startswith(
        "**⚠ Fact changed 2026-11-02:** Hindsight API listens on port 8888"
    )
    assert len(v.records) == 2, "old line kept"
    long = "On 2026-11-02 the self-hosted Hindsight API on this Mac mini listens on port {} for MCP"
    brain_remember([v], long.format(8887), "fact", when=TODAY)
    out = brain_remember([v], long.format(8888), "fact", when=TODAY)
    assert out["status"] == "written" and "contradiction" in out, "value change beats dedup"


def test_relation_goes_to_graph_and_others_refuse() -> None:
    g = GraphOnly()
    out = brain_remember(
        [named("vault"), g], "", "relation", subject="A", predicate="uses", object="B"
    )
    assert out["layers"]["graph"]["status"] == "written"
    assert out["status"] == "written" and out["text"] == "A —[uses]→ B"


def test_empty_text_rejected() -> None:
    with pytest.raises(ValueError):
        brain_remember([named("vault")], "   ", "fact")


def test_mission_and_source_reach_extra() -> None:
    v = named("vault")
    brain_remember([v], "the parser uses laya", "fact", source="session", mission="M-7", when=TODAY)
    r: Record = v.records[0]
    assert r.extra == {"source": "session", "mission": "M-7"}


def test_secret_in_an_extra_field_is_refused() -> None:
    v = named("vault")
    with pytest.raises(ValueError, match="secret"):
        brain_remember(
            [v], "used the wrong token", "correction", correction="use ghp_" + "a1B2" * 9
        )
    assert not v.records


def test_one_changed_word_in_a_long_fact_is_a_change_not_a_duplicate() -> None:
    v = named("vault")
    fact = (
        "The user {} wants every production release approved by the team lead "
        "before merging into main"
    )
    brain_remember([v], fact.format("always"), "fact", when=TODAY)
    out = brain_remember([v], fact.format("never"), "fact", when=TODAY)
    assert out["status"] == "written" and "contradiction" in out and len(v.records) == 2
    again = brain_remember([v], fact.format("never"), "fact", when=TODAY)
    assert again["status"] == "duplicate"
