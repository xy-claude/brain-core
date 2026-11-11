"""The record index: bm25 over every vault kind, rebuilt from the files, never the truth."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from brain_core.recall import brain_recall
from brain_core.storage import Database, migrate
from brain_core.stores import NotesStore, VaultStore
from brain_core.stores.index import RecordIndex, match_query

DAY = date(2026, 11, 2)


@pytest.fixture
def index(tmp_path: Path) -> RecordIndex:
    db = Database.connect(tmp_path / "brain.db")
    migrate(db)
    return RecordIndex(db)


def vault(tmp_path: Path, index: RecordIndex) -> VaultStore:
    v = VaultStore(tmp_path / "vault", owner="atlas", index=index)
    v.write("fact", "The staging cluster was deployed with a helm chart", when=DAY)
    v.write("fact", "Ana prefers café meetings on Tuesdays", when=DAY)
    v.write(
        "decision",
        "Keep one database per tenant",
        when=DAY,
        title="Tenant isolation",
        reason="a leaked query cannot cross customers",
    )
    v.write("correction", "x", when=DAY, title="Pushed without asking", error="pushed on my own")
    v.write("note", "Reviewed the invoice export with the client", when=DAY)
    return v


def test_every_kind_is_searched_and_stemmed(tmp_path: Path, index: RecordIndex) -> None:
    v = vault(tmp_path, index)
    assert v.ranked
    hit = v.read("fact", "deploying charts")  # deploy/deployed, chart/charts
    assert [r.text for r in hit] == ["The staging cluster was deployed with a helm chart"]
    assert hit[0].score > 0 and hit[0].path == "facts.md" and hit[0].date == DAY
    assert v.read("fact", "cafe")[0].text.startswith("Ana"), "accents fold"
    # the body fields of a decision and a correction are searchable, not only the title
    assert v.read("decision", "leaked customers")[0].text == "Tenant isolation"
    assert v.read("correction", "pushed")[0].extra["error"] == "pushed on my own"
    assert v.read("note", "invoices")[0].kind == "note"
    assert v.read("note", "2026-11-02"), "a record is found by its date"
    assert v.read("fact", "invoice") == [], "a kind filter holds"
    assert v.read("fact", "what is the of") == [], "only stopwords: nothing to match"


def test_index_follows_the_files(tmp_path: Path, index: RecordIndex) -> None:
    v = vault(tmp_path, index)
    assert v.read("fact", "helm")
    facts = v.root / "facts.md"
    facts.write_text(facts.read_text().replace("helm chart", "terraform plan"))
    assert v.read("fact", "helm") == [] and v.read("fact", "terraform"), "a hand edit is seen"
    v.write("fact", "The queue worker restarts nightly", when=DAY)
    assert v.read("fact", "worker"), "a write is searchable at once"
    facts.unlink()
    assert v.read("fact", "terraform") == [], "a deleted file loses its rows"
    # dropping the index loses nothing: the next search rebuilds it from the vault
    index.db.execute("DELETE FROM records_fts")
    index.db.execute("DELETE FROM index_files")
    assert v.read("decision", "tenant")[0].text == "Tenant isolation"


def test_notes_folder_is_indexed_past_the_display_cap(tmp_path: Path, index: RecordIndex) -> None:
    d = tmp_path / "memory"
    d.mkdir()
    (d / "long.md").write_text("# Long note\n\n" + "filler words here. " * 80 + "zanzibar ferry")
    n = NotesStore([d], index)
    assert n.read("knowledge", "zanzibar"), "words past the first 600 characters are searchable"
    assert NotesStore([d]).read("knowledge", "zanzibar") == [], "the unindexed read is capped"


def test_recall_ranks_indexed_records_by_bm25(tmp_path: Path, index: RecordIndex) -> None:
    v = vault(tmp_path, index)
    for i in range(30):  # decoys that share the common word but not the rare one
        v.write("fact", f"cluster note {i} about nothing in particular", when=DAY)
    out = brain_recall([v], "which cluster got deployed with helm?", fmt="detailed", today=DAY)
    assert out["results"][0]["text"].startswith("The staging cluster was deployed")
    assert out["stores"]["vault"] > 1 and "miss" not in out
    assert brain_recall([v], "tenants", scope="decision", today=DAY)["total"] == 1


def test_search_keys_find_a_record_its_own_words_do_not(tmp_path: Path, index: RecordIndex) -> None:
    v = vault(tmp_path, index)
    assert v.read("fact", "kubernetes rollout") == []
    r = v.write(
        "fact",
        "The orders service ships through argo on Fridays",
        when=DAY,
        keys="kubernetes rollout; how do we release",
        source="user",
        mission="M-7",
    )
    hit = v.read("fact", "kubernetes rollout")
    assert [h.id for h in hit] == [r.id] and "kubernetes" not in hit[0].text, "searched, not shown"
    line = (v.root / "record_meta.md").read_text().splitlines()[-1]
    want = "keys: kubernetes rollout; how do we release | source: user | mission: M-7"
    assert line == f"- {r.id[:16]} | {want}"
    # keys can be added to a record that already exists; the old ones stay
    again = v.write("fact", "The orders service ships through argo on Fridays", keys="deploy day")
    assert again.status == "exists" and v.read("fact", "deploy day")[0].id == r.id
    assert v.meta()[r.id[:16]]["keys"] == "kubernetes rollout; how do we release; deploy day"
    assert v.read("fact", "kubernetes")[0].id == r.id
    # a fresh process and a rebuilt index pick the keys up from the vault file
    index.db.execute("DELETE FROM records_fts")
    index.db.execute("DELETE FROM index_files")
    fresh = VaultStore(v.root, owner="atlas", index=RecordIndex(index.db))
    assert fresh.read("fact", "kubernetes")[0].id == r.id


def test_match_query_cannot_be_broken_by_fts_syntax() -> None:
    assert match_query('co-authored-by: "helm" AND (chart*) 2026-11-02') == (
        '"co" OR "authored" OR "helm" OR "chart" OR "2026-11-02"'
    )
    assert match_query("the of and") == ""


def test_weak_match_is_judged_by_the_rare_words(tmp_path: Path, index: RecordIndex) -> None:
    v = vault(tmp_path, index)
    for i in range(30):
        v.write("fact", f"the client asked about note {i} on the cluster", when=DAY)
    # every common word is somewhere, the one rare word ("dentist") is nowhere: a miss
    weak = brain_recall([v], "which dentist did the client ask about?", today=DAY)
    assert weak["results"] and weak["miss"]["best"] < 0.5
    held = brain_recall([v], "which cluster got deployed with helm?", today=DAY)
    assert "miss" not in held
    ids = [r.id for r in v.read("fact", "helm")]
    assert index.cover("helm chart", ids) == 1.0 and index.cover("helm dentist", ids) < 0.5
    assert index.cover("what is the", ids) == 0.0 and index.cover("helm", []) == 0.0


def test_a_changed_fact_retires_the_old_value(tmp_path: Path, index: RecordIndex) -> None:
    from brain_core.remember import brain_remember

    v = VaultStore(tmp_path / "vault", owner="atlas", index=index)
    old = brain_remember([v], "The API server listens on port 8887 for agents", "fact", when=DAY)
    new = brain_remember([v], "The API server listens on port 8888 for agents", "fact", when=DAY)
    assert new["contradiction"]["id"] == old["id"]
    assert v.retired() == {old["id"][:16]}, "the new record names the one it replaces"
    out = brain_recall([v], "API server port agents", fmt="detailed", today=DAY)["results"]
    assert "8888" in out[0]["text"] and "superseded" not in out[0]
    stale = next(r for r in out if r["id"] == old["id"])
    assert stale["superseded"] is True and stale["score"] < out[0]["score"], "kept, ranked below"
    # a record can also be retired by hand: any kind, by id
    d = v.write("decision", "Use Postgres", when=DAY, title="Database choice")
    v.write("decision", "Use SQLite", when=DAY, title="Database choice, revised", supersedes=d.id)
    assert d.id[:16] in v.retired()


def test_miss_repair_teaches_the_record_the_question_that_failed(tmp_path: Path) -> None:
    from brain_core import Agent

    root = tmp_path / "vault"
    root.mkdir()
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(f"name: T\nstores:\n  vault: {root}\n")
    with Agent.from_config(cfg) as a:
        a.brain_remember("PyPI recovery codes are stored in the login Keychain", "fact")
        for i in range(20):
            a.brain_remember(
                f"unrelated note number {i} about the package site", "fact", force=True
            )
        missed = "where are the backup passwords for the python package site?"
        first = a.brain_recall(missed)
        assert "weak_match" in first and "kind='key'" in first["weak_match"]
        found = a.brain_recall("PyPI recovery codes")["results"][0]
        out = a.brain_remember(missed, "key", source=found["source"])
        assert out["status"] == "written" and "backup" in out["learned"]
        again = a.brain_recall(missed)
        assert "weak_match" not in again and again["results"][0]["source"] == found["source"]
        vault = next(s for s in a.stores if s.name == "vault")
        assert "backup" in vault.meta()[out["id"][:16]]["learned"]
        assert a.recent_events(event_type="recall_repair")[0].payload["id"] == out["id"]
        with pytest.raises(ValueError, match="no record has source"):
            a.brain_remember(missed, "key", source="facts.md:9999")
    import sys

    sys.path.insert(0, "tests/eval")
    import from_repairs

    assert from_repairs.questions(str(cfg)) == [
        {"s": "learned", "q": missed, "gold": [out["id"][:16]]}
    ]
