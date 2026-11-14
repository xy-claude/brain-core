"""The vector net: vectors kept in step with the records, joined into recall, never in its way."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from brain_core import Agent
from brain_core.embed import EmbedUnavailable, FakeEmbedder, Role
from brain_core.recall import brain_recall, identifiers
from brain_core.stores.vectors import VectorIndex

FACTS = """# Facts

## system
- The database listens on port 5432 on the office server (2026-05-01)
- Deploys go out every Friday afternoon after the review (2026-05-02)
- The office coffee machine is descaled monthly (2026-05-03)
- Old gateway listened on port 15432 before the move (2026-04-01)
"""


class Down(FakeEmbedder):
    def running(self) -> bool:
        return False

    def embed(self, texts: Sequence[str], role: Role = "document") -> list[bytes]:
        raise EmbedUnavailable("no worker")


def _agent(tmp_path: Path, vectors: bool = True) -> Agent:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "facts.md").write_text(FACTS)
    extra = "  vectors: {model: fake}\n" if vectors else ""
    (tmp_path / "brain.yaml").write_text(f"name: T\nstores:\n  vault: ./vault\n{extra}")
    return Agent.from_config(tmp_path / "brain.yaml")


def _index(agent: Agent, embedder: FakeEmbedder | None = None) -> VectorIndex:
    agent._vectors = VectorIndex(agent.db, embedder or FakeEmbedder("fake"))
    agent.brain_sync()
    return agent._vectors


def test_fill_then_nothing_pending_and_a_changed_file_is_embedded_again(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        v = _index(agent)
        assert len(v.pending()) == 4
        assert v.fill() == 4 and v.pending() == [] and v.fill() == 0
        assert v.stats() == {"model": "fake", "rows": 4, "pending": 0, "worker": "up"}
        facts = tmp_path / "vault" / "facts.md"
        facts.write_text(
            facts.read_text().replace(
                "- The office coffee", "- A new line here\n- The office coffee"
            )
        )
        agent.brain_sync()
        assert len(v.pending()) == 1 and v.fill() == 1
        facts.write_text(
            FACTS.replace(
                "- Deploys go out every Friday afternoon after the review (2026-05-02)\n", ""
            )
        )
        agent.brain_sync()
        assert (
            v.pending() == [] and v.stats()["rows"] == 3
        )  # rows of records that are gone are dropped


def test_notes_and_archive_records_get_vectors_too(tmp_path: Path) -> None:
    for name in ("notes", "old"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "a.md").write_text(f"# {name} page\n\nSomething kept in {name}.\n")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "facts.md").write_text(FACTS)
    (tmp_path / "brain.yaml").write_text(
        "name: T\nstores:\n  vault: ./vault\n  notes: [./notes]\n  archive: [./old]\n"
        "  vectors: {model: fake}\n"
    )
    with Agent.from_config(tmp_path / "brain.yaml") as agent:
        v = _index(agent)
        assert v.fill() == 6
        stores = {s for _r, s, _sim in v.search("something kept", 6)}
        assert stores == {"vault", "notes", "archive"}


def test_another_model_replaces_every_vector(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        _index(agent).fill()
        other = _index(agent, FakeEmbedder("other", dim=32))
        assert len(other.pending()) == 4 and other.fill() == 4
        rows = agent.db.fetchall("SELECT DISTINCT model, dim FROM record_vectors")
        assert [(r["model"], r["dim"]) for r in rows] == [("other", 32)]


def test_vector_net_finds_and_tags_and_keyword_only_is_unchanged(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        plain = brain_recall(agent.stores, "when do deploys go out", fmt="detailed")
        v = _index(agent)
        v.fill()
        both = brain_recall(agent.stores, "when do deploys go out", fmt="detailed", vectors=v)
        assert both["results"][0]["text"].startswith("Deploys go out")
        assert both["results"][0]["found_by"] == ["keyword", "vector"]
        assert both["stores"]["vectors"] == 4
        # without the vector net the call is today's call: same results, no new fields
        again = brain_recall(agent.stores, "when do deploys go out", fmt="detailed")
        assert again == plain and "found_by" not in plain["results"][0]


def test_exact_identifier_is_pinned_first_as_a_whole_token(tmp_path: Path) -> None:
    assert identifiers("which service is on port 5432?") == ["5432"]
    assert identifiers("what did we do on 2026-05-01 and in 2026?") == []
    with _agent(tmp_path) as agent:
        v = _index(agent)
        v.fill()
        out = brain_recall(agent.stores, "what is 5432", fmt="detailed", vectors=v)
        first = out["results"][0]
        assert "port 5432 on" in first["text"] and "exact" in first["found_by"]
        # 15432 holds the digits but not the token, so it is not pinned
        assert all("exact" not in r.get("found_by", []) for r in out["results"][1:])


def test_no_embedder_falls_back_to_keywords_and_says_so(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        plain = brain_recall(agent.stores, "database port", fmt="detailed")
        good = _index(agent)
        good.fill()
        down = VectorIndex(agent.db, Down("fake"))
        out = brain_recall(agent.stores, "database port", fmt="detailed", vectors=down)
        assert out["stores"]["vectors"].startswith("unavailable")
        assert [r["id"] for r in out["results"]][:2] == [r["id"] for r in plain["results"]][:2]


def test_a_save_reports_its_vector_and_never_waits_for_a_worker(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        _index(agent).fill()
        out = agent.brain_remember("The staging server restarts at 03:00 daily", "fact")
        assert out["layers"]["vectors"] == {"status": "written", "detail": "fake"}
        calls = Down("fake")
        _index(agent, calls)
        out = agent.brain_remember("Backups are copied offsite every Sunday night", "fact")
        assert out["layers"]["vectors"]["status"] == "pending" and calls.calls == 0
        assert out["status"] in ("written", "partial")


def test_vectors_off_by_default(tmp_path: Path) -> None:
    with _agent(tmp_path, vectors=False) as agent:
        assert agent.vectors is None
        assert "vectors" not in agent.brain_remember("Plain fact with no vectors", "fact")["layers"]
        assert "vectors" not in agent.brain_status()


@pytest.mark.parametrize("scope", ["transcript", "sqlite"])
def test_scopes_without_vectors_skip_the_net(tmp_path: Path, scope: str) -> None:
    with _agent(tmp_path) as agent:
        v = _index(agent)
        v.fill()
        try:
            out = brain_recall(agent.stores, "database port", scope=scope, vectors=v)
        except ValueError:
            return  # that store is not configured here
        assert "vectors" not in out["stores"]
