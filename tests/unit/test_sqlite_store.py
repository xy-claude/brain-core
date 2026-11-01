"""SqliteStore: FTS-safe queries, exists vs written, kinds it refuses."""

from __future__ import annotations

from brain_core.storage.db import Database
from brain_core.stores import SqliteStore
from brain_core.stores.sqlite import fts_query


def test_fts_query_quotes_syntax_characters() -> None:
    assert (
        fts_query("io.vectorize-hindsight: 127.0.0.1")
        == '"io" OR "vectorize" OR "hindsight" OR "127" OR "0" OR "0" OR "1"'
    )


def test_write_then_read_with_hyphenated_query(db: Database) -> None:
    s = SqliteStore(db)
    assert (
        s.write("fact", "Hindsight self-hosted on 127.0.0.1:8888", domain="system").status
        == "written"
    )
    assert s.write("fact", "Hindsight self-hosted on 127.0.0.1:8888").status == "exists"
    assert s.write("decision", "nope").status == "refused"
    hits = s.read("fact", "self-hosted 127.0.0.1:8888")
    assert (
        len(hits) == 1 and hits[0].domain == "system" and hits[0].path.startswith("sqlite://facts/")
    )
    assert s.read("decision", "x") == [] and s.health() == (True, "sqlite facts=1")
