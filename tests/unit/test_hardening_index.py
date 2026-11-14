"""Hardening of the record index, the vector store and the embed worker, one test a finding:
what the index stores (masked text, undated lines), what an upgrade keeps (every vector), and
what the vector search does when a part of it is missing (it says so and never crashes)."""

from __future__ import annotations

import contextlib
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
import types
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from brain_core.embed import EmbedUnavailable, FakeEmbedder, Role, WorkerEmbedder
from brain_core.embed_worker import ModelBackend
from brain_core.recall import brain_recall
from brain_core.storage import Database, migrate
from brain_core.stores import NotesStore, VaultStore
from brain_core.stores.base import Record, record_id
from brain_core.stores.index import FORMAT, RecordIndex, days_asked, iso_dates, terms
from brain_core.stores.vectors import VectorIndex
from tests.test_vectors import FACTS, Down, _agent, _index

DAY = date(2026, 11, 13)
KEY = "sk-ant-" + "REDACTED" * 3  # shaped like a key; built here so no scanner stops the file
VECTORS = "SELECT record_id, model, text_hash, vec FROM record_vectors ORDER BY record_id"
unix = pytest.mark.skipif(sys.platform == "win32", reason="the worker needs Unix sockets")


@pytest.fixture
def index(tmp_path: Path) -> RecordIndex:
    db = Database.connect(tmp_path / "brain.db")
    migrate(db)
    return RecordIndex(db)


def _vectors(db: Database) -> int:
    return len(db.fetchall("SELECT 1 FROM record_vectors"))


class Heard(FakeEmbedder):
    """Keeps every text it is asked to embed."""

    def __init__(self) -> None:
        super().__init__("fake")
        self.texts: list[str] = []

    def embed(self, texts: Sequence[str], role: Role = "document") -> list[bytes]:
        self.texts += texts
        return super().embed(texts, role)


# ── what the index stores ────────────────────────────────────────────────────


def test_a_credential_is_masked_in_the_index_and_the_record_keeps_its_id(
    tmp_path: Path, index: RecordIndex
) -> None:
    # CONTENT-1, session-missed-1, ops-missed-1: the write path refuses a secret, but a notes
    # folder and a line typed into the vault by hand never passed through it
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "keys.md").write_text(f"# Shared\n\n## API Keys\n| Anthropic API | {KEY} |\n")
    root = tmp_path / "vault"
    root.mkdir()
    (root / "facts.md").write_text(f"# Facts\n\n## system\n- The deploy token is {KEY}\n")
    (root / "decisions_log.md").write_text(
        f"# Decisions\n\n## 2026-11-13 — Key rotation\n- **Reason:** it leaked as {KEY}\n"
    )
    vault = VaultStore(root, owner="atlas", index=index)
    notes = NotesStore([shared], index)
    page = notes.read("knowledge", "anthropic api keys")[0]
    fact = vault.read("fact", "deploy token")[0]
    decision = vault.read("decision", "key rotation leaked")[0]
    assert "[redacted]" in page.text and "[redacted]" in fact.text
    assert decision.extra["reason"] == "it leaked as [redacted]"
    # the id is the original text's: search keys and links in record_meta.md still point here
    assert page.id == NotesStore([shared]).read("knowledge")[0].id
    assert fact.id == record_id(f"The deploy token is {KEY}")
    assert index.redacted() == 3
    row = index.db.fetchone(
        "SELECT count(*) AS n FROM records_fts WHERE instr(body, ?) OR instr(record, ?)",
        (KEY, KEY),
    )
    assert row is not None and row["n"] == 0, "the key is in no column of the index"
    heard = Heard()
    assert VectorIndex(index.db, heard).fill() == 3
    assert not any(KEY in t for t in heard.texts), "the embed worker gets the masked text"


def test_an_undated_record_is_not_found_by_its_files_date(
    tmp_path: Path, index: RecordIndex
) -> None:
    # RECALL-2: both lines carry the file's day, only the first was written with it
    f = tmp_path / "facts.md"
    f.write_text("two lines")
    new = Record(record_id("new"), "fact", "The gateway moved to port 8888", DAY)
    old = Record(record_id("old"), "fact", "The gateway listens on port 8887", DAY, undated=True)
    index.sync("vault", {f: "fact"}, lambda _kind, _path: [new, old])
    assert [r.id for r in index.search("vault", ["fact"], "2026-11-13", 5)] == [new.id]
    assert [r.id for r, _store in index.dated("2026-11-13", 10)] == [new.id]
    # a record read back from the index says which it is
    by_words = {r.id: r.undated for r in index.search("vault", ["fact"], "gateway port", 5)}
    assert by_words == {new.id: False, old.id: True}
    got = index.get(old.id)
    assert got is not None and got[0].undated


def test_a_word_that_starts_like_a_month_is_not_a_date() -> None:
    # recall-missed-4
    today = date(2026, 11, 14)
    for q in (
        "what were the 3 decisions we made about pricing",
        "top 5 marketing channels for the app",
        "mark 3 of the device",
        "mayhem 12 times over",
        "decision 5",
        "2 separate issues",
        "4 junior hires",
        "2 novel ideas, maybe 3",
    ):
        assert iso_dates(q, today) == q and days_asked(q, today) == [], q
    assert terms("top 5 marketing channels for the app") == ["top", "marketing", "channels", "app"]
    # a month's name and its short forms are still read
    assert (
        iso_dates("sept 3, june 5th, 4 july 2026 and dec. 25", today)
        == "2026-09-03, 2026-06-05, 2026-07-04 and 2025-12-25"
    )


# ── an upgrade keeps every vector ────────────────────────────────────────────


def test_an_index_from_before_is_read_again_and_keeps_every_vector(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        heard = FakeEmbedder("fake")
        v = _index(agent, heard)
        v.fill()
        before = [tuple(r) for r in agent.db.fetchall(VECTORS)]
        # an index as 0.8.0 left it: a stamp with no format version, rows from the old reader
        st = (tmp_path / "vault" / "facts.md").stat()
        agent.db.execute("UPDATE index_files SET sig = ?", (f"{st.st_mtime_ns}:{st.st_size}",))
        agent.db.execute("UPDATE records_fts SET body = 'left by the old reader'")
        agent.brain_sync()
        assert agent.stores[1].read("fact", "database port"), "the unchanged file was read again"
        sig = agent.db.fetchone("SELECT sig FROM index_files")
        assert sig is not None and sig["sig"].startswith(f"{FORMAT}:")
        # ids are stable: the re-read deleted no vector, orphaned none and asked for no new one
        assert v.pending() == [] and v.fill() == 0 and heard.calls == 1
        assert [tuple(r) for r in agent.db.fetchall(VECTORS)] == before


def test_an_emptied_index_costs_no_vector(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        heard = FakeEmbedder("fake")
        v = _index(agent, heard)
        v.fill()
        # the index is a cache that may be dropped; until it is rebuilt no record is known gone
        agent.db.execute("DELETE FROM records_fts")
        agent.db.execute("DELETE FROM index_files")
        assert v.fill() == 0 and _vectors(agent.db) == 4
        agent.brain_sync()
        assert v.pending() == [] and v.stats()["rows"] == 4 and heard.calls == 1


# ── the vector store ─────────────────────────────────────────────────────────


def test_vector_search_fetches_its_records_in_one_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # recall-missed-3, LIVE-9, RAG-11: `rid` has no index, so every query on it is a full scan
    with _agent(tmp_path) as agent:
        v = _index(agent)
        v.fill()
        asked: list[str] = []
        for name in ("fetchone", "fetchall"):
            real = getattr(agent.db, name)

            def spy(sql: str, params: Any = (), real: Any = real) -> Any:
                asked.append(sql)
                return real(sql, params)

            monkeypatch.setattr(agent.db, name, spy)
        assert len(v.search("database port", 4)) == 4
        assert sum("FROM records_fts" in sql for sql in asked) == 1


def test_a_model_that_cannot_load_deletes_no_vector_and_says_so(tmp_path: Path) -> None:
    # LIVE-3
    with _agent(tmp_path) as agent:
        _index(agent).fill()
        typo = VectorIndex(agent.db, Down("no-such-model"))
        # the health check only reads: every record waits for this model, which has made none
        assert typo.stats() == {
            "model": "no-such-model",
            "rows": 0,
            "pending": 4,
            "worker": "down",
        }
        with pytest.raises(EmbedUnavailable):
            typo.fill()
        with pytest.raises(EmbedUnavailable, match="no vectors"):  # not "0 found"
            typo.search("database port", 4)
        out = brain_recall(agent.stores, "database port", vectors=typo)
        assert out["stores"]["vectors"].startswith("unavailable") and out["results"]
        assert _vectors(agent.db) == 4
        # the name is put right: the old vectors are all there and nothing waits
        back = VectorIndex(agent.db, FakeEmbedder("fake"))
        assert back.pending() == [] and len(back.search("database port", 4)) == 4
        # a model that does load takes a row over only once it has made that row's vector
        assert VectorIndex(agent.db, FakeEmbedder("other", dim=32)).fill(limit=1) == 1
        rows = agent.db.fetchall(
            "SELECT model, count(*) AS n FROM record_vectors GROUP BY model ORDER BY model"
        )
        assert [(r["model"], r["n"]) for r in rows] == [("fake", 3), ("other", 1)]


def test_a_bad_vector_or_no_numpy_is_unavailable_and_never_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # OPS-6
    with _agent(tmp_path) as agent:
        _index(agent).fill()
        rid = agent.db.fetchall("SELECT record_id FROM record_vectors")[0]["record_id"]
        agent.db.execute(
            "UPDATE record_vectors SET vec = substr(vec, 1, 100) WHERE record_id = ?", (rid,)
        )
        cut = VectorIndex(agent.db, FakeEmbedder("fake"))
        found = cut.search("database port", 4)
        # one vector of another length: skipped and counted, the other three still answer
        assert cut.bad == 1 and len(found) == 3 and rid not in {r.id for r, _s, _sim in found}
        agent.db.execute("UPDATE record_vectors SET vec = substr(vec, 1, 7)")
        with pytest.raises(EmbedUnavailable, match="ValueError"):  # no vector can be read
            VectorIndex(agent.db, FakeEmbedder("fake")).search("database port", 4)
        monkeypatch.setitem(sys.modules, "numpy", None)  # the base install has none
        bare = VectorIndex(agent.db, FakeEmbedder("fake"))
        with pytest.raises(EmbedUnavailable, match="numpy"):
            bare.search("database port", 4)
        out = brain_recall(agent.stores, "database port", vectors=bare)
        assert out["stores"]["vectors"].startswith("unavailable") and out["results"]


def test_a_line_edited_in_place_gets_a_new_vector(tmp_path: Path) -> None:
    # RECALL-6: one file, the same number of records, so neither the row count of the index
    # nor its highest row number moves
    with _agent(tmp_path) as agent:
        v = _index(agent)
        v.fill()
        facts = tmp_path / "vault" / "facts.md"
        facts.write_text(FACTS.replace("descaled monthly", "descaled every second week"))
        agent.brain_sync()
        assert [text for _rid, text, _hash in v.pending()] == [
            "The office coffee machine is descaled every second week"
        ]
        # the new line is embedded and the vector of the line it replaced is gone
        assert v.fill() == 1 and v.stats()["rows"] == 4 and _vectors(agent.db) == 4
        assert "second week" in v.search("coffee machine descaled every second week", 1)[0][0].text


def test_a_vector_remade_by_another_server_is_seen_without_a_restart(tmp_path: Path) -> None:
    # RECALL-6: the count of vectors is the same before and after
    with _agent(tmp_path) as agent:
        v = _index(agent)
        v.fill()
        ask = "when do deploys go out"
        last = v.search(ask, 4)[-1][0]
        vec = FakeEmbedder("fake").embed([ask], "query")[0]
        agent.db.execute(
            "UPDATE record_vectors SET vec = ?, text_hash = 'remade' WHERE record_id = ?",
            (vec, last.id),
        )
        record, _store, sim = v.search(ask, 4)[0]
        assert record.id == last.id and sim == pytest.approx(1.0)


# ── the embed worker ─────────────────────────────────────────────────────────


def test_the_worker_loads_a_model_from_disk_before_it_asks_the_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # LIVE-1, RAG-10
    import numpy as np

    loads: list[tuple[str, bool]] = []

    class Model:
        prompts = None
        max_seq_length = 0

        def __init__(self, name: str, device: str | None = None, local_files_only: bool = False):
            loads.append((name, local_files_only))
            if local_files_only and name == "never-downloaded":
                raise OSError("not in the local cache")

        def encode(self, texts: list[str], **_kw: Any) -> list[Any]:
            return [np.zeros(4, dtype="<f4") for _ in texts]

    mps = types.SimpleNamespace(is_available=lambda: False)
    torch = types.SimpleNamespace(backends=types.SimpleNamespace(mps=mps))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=Model)
    )
    backend = ModelBackend()
    assert len(backend.embed("on-disk", ["one"], "document")) == 1
    assert loads == [("on-disk", True)], "a model on disk is loaded with no call to the hub"
    backend.embed("never-downloaded", ["one"], "document")
    assert loads[1:] == [("never-downloaded", True), ("never-downloaded", False)]


@pytest.fixture
def embed_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    # a Unix socket path is capped near 100 bytes: a relative home keeps it short
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BRAIN_EMBED_HOME", "eh")
    monkeypatch.setenv("BRAIN_EMBED_FAKE", "1")
    yield tmp_path / "eh"
    with contextlib.suppress(OSError, ValueError):
        pid = int((tmp_path / "eh" / "embed.lock").read_text())
        if pid > 0:
            os.kill(pid, signal.SIGKILL)


@unix
def test_a_worker_that_did_not_start_is_not_started_again_for_five_minutes(
    embed_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # rag-missed-4
    starts: list[int] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: starts.append(1))  # never comes up
    e = WorkerEmbedder("fake", start_timeout=0.3)
    with pytest.raises(EmbedUnavailable, match="did not start; see"):
        e.embed(["one"])
    began = time.monotonic()
    with pytest.raises(EmbedUnavailable, match="next try in"):
        e.embed(["one"])
    assert starts == [1] and time.monotonic() - began < 0.25, "no second start, no second wait"
    long_ago = time.time() - 301
    os.utime(embed_home / "embed.failed", (long_ago, long_ago))
    with pytest.raises(EmbedUnavailable, match="did not start; see"):
        e.embed(["one"])
    assert starts == [1, 1], "five minutes on, the next call tries again"


@unix
def test_a_call_that_lands_as_the_worker_exits_is_asked_again(embed_home: Path) -> None:
    # ops-missed-3: a worker on its way out still listens, then closes without answering
    embed_home.mkdir()
    leaving = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    leaving.bind("eh/embed.sock")
    leaving.listen(1)

    def leave() -> None:
        select.select([leaving], [], [], 10)  # the call has connected
        time.sleep(0.05)
        os.unlink("eh/embed.sock")
        leaving.close()

    t = threading.Thread(target=leave)
    t.start()
    vecs = WorkerEmbedder("fake", idle_minutes=0).embed(["one"])
    t.join()
    assert vecs == FakeEmbedder("fake").embed(["one"])
