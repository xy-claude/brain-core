"""brain_recall over fake stores: merge, dedup, scope, caps, error isolation."""

from __future__ import annotations

from datetime import date

import pytest

from brain_core.recall import brain_recall
from brain_core.stores import MemoryStore
from brain_core.stores.base import Kind, Record

TODAY = date(2026, 11, 2)


class RankedStore(MemoryStore):
    """A store that orders by query itself (like Hindsight) and ignores kind."""

    name = "hindsight"
    ranked = True

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        return self.records[:limit] if kind == "fact" else []


class BrokenStore(MemoryStore):
    name = "graph"

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        raise ConnectionError("kuzu locked")


def vault() -> MemoryStore:
    v = MemoryStore()
    v.name = "vault"
    v.write(
        "fact",
        "Hindsight self-hosted: LaunchAgent io.vectorize.hindsight on 127.0.0.1:8888",
        when=date(2026, 11, 1),
    )
    v.write(
        "fact",
        "Two GitHub accounts isolated via ssh aliases github-work and github-personal",
        when=date(2026, 11, 2),
    )
    v.write(
        "decision", "2026-11-01 Hindsight cloud → self-hosted on the Mac", when=date(2026, 11, 1)
    )
    v.write("pattern", "Self-host before paying", when=date(2026, 4, 1))
    return v


def test_merges_dedups_and_ranks_by_overlap() -> None:
    h = RankedStore()
    h.write(
        "fact",
        "Hindsight self-hosted: LaunchAgent io.vectorize.hindsight on 127.0.0.1:8888",
        when=date(2026, 11, 1),
    )
    out = brain_recall([vault(), h], "hindsight self-hosted launchagent", today=TODAY)
    texts = [r["text"] for r in out["results"]]
    assert texts[0].startswith("Hindsight self-hosted: LaunchAgent")
    assert texts.count(texts[0]) == 1, "same record from two stores must appear once"
    assert "github" not in " ".join(texts).lower()
    assert out["stores"] == {"vault": 3, "hindsight": 0}  # "self-host" matches by part
    assert set(out["results"][0]) == {"name", "kind", "date", "source", "text"}


def test_scope_by_kind_and_by_store() -> None:
    out = brain_recall([vault()], "hindsight", scope="decision", today=TODAY)
    assert [r["kind"] for r in out["results"]] == ["decision"]
    h = RankedStore()
    h.write("fact", "hindsight note from hindsight", when=TODAY)
    out = brain_recall([vault(), h], "hindsight", scope="hindsight", fmt="detailed", today=TODAY)
    assert {r["store"] for r in out["results"]} == {"hindsight"} and "score" in out["results"][0]
    with pytest.raises(ValueError, match="scope must be"):
        brain_recall([vault()], "x", scope="nope")


def test_broken_store_is_reported_not_raised() -> None:
    out = brain_recall([vault(), BrokenStore()], "github accounts", today=TODAY)
    assert out["stores"]["graph"].startswith("error: ConnectionError")
    assert out["results"][0]["text"].startswith("Two GitHub accounts")


def test_truncation_adds_steering_note() -> None:
    v = MemoryStore()
    for i in range(40):
        v.write("fact", f"budget item {i} " + "word " * 200, when=TODAY)
    out = brain_recall([v], "budget item", limit=40, max_tokens=2000, today=TODAY)
    assert 0 < len(out["results"]) < 40 and "narrow `scope`" in out["note"]
    assert brain_recall([v], "zzz", today=TODAY)["note"].startswith("no hits")


def test_two_banners_sharing_a_prefix_are_both_returned() -> None:
    v = MemoryStore()
    v.name = "vault"
    head = (
        "**⚠ Fact changed 2026-11-02:** The self-hosted Hindsight API on this Mac listens on port"
    )
    v.write("fact", f"{head} 8887 for MCP", when=date(2026, 11, 1))
    v.write("fact", f"{head} 8888 for MCP", when=date(2026, 11, 2))
    texts = [r["text"] for r in brain_recall([v], "hindsight port", today=TODAY)["results"]]
    assert any("8887" in t for t in texts) and any("8888" in t for t in texts)


def test_transcript_line_ranks_below_written_memory_of_equal_relevance() -> None:
    v = MemoryStore()
    v.name = "vault"
    v.write("fact", "launchctl kickstart restarts the Hindsight service", when=TODAY)
    t = MemoryStore()
    t.name = "transcripts"
    t.write("transcript", "[user] launchctl kickstart restarts the Hindsight service?", when=TODAY)
    out = brain_recall([t, v], "launchctl kickstart Hindsight", fmt="detailed", today=TODAY)
    assert [r["kind"] for r in out["results"]] == ["fact", "transcript"]
    assert out["results"][1]["score"] < out["results"][0]["score"]
