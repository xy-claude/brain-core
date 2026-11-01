"""Structured memory capability tests."""

from __future__ import annotations

import pytest

from brain_core.memory import Fact, recall, remember, supersede
from brain_core.storage import Database


def test_remember_round_trip(db: Database) -> None:
    fact = remember(db, "Sir prefers dark mode", kind="preference")
    assert fact.id > 0
    assert fact.content == "Sir prefers dark mode"
    assert fact.kind == "preference"
    assert fact.tags == []
    assert fact.metadata == {}
    assert fact.superseded_by is None
    assert len(fact.content_hash) == 64  # sha256 hex length


def test_remember_is_idempotent_on_identical_content(db: Database) -> None:
    a = remember(db, "Cats are better than dogs")
    b = remember(db, "Cats are better than dogs")
    assert a.id == b.id
    assert a.content_hash == b.content_hash

    # Still only one row
    rows = db.fetchall("SELECT COUNT(*) AS n FROM facts")
    assert rows[0]["n"] == 1


def test_remember_normalizes_whitespace_for_dedup(db: Database) -> None:
    a = remember(db, "Deploy at 3pm")
    b = remember(db, "   Deploy    at    3pm   ")
    assert a.id == b.id  # whitespace-different but semantically same


def test_remember_preserves_case_in_dedup(db: Database) -> None:
    a = remember(db, "Bug 123")
    b = remember(db, "bug 123")
    assert a.id != b.id  # case matters


def test_remember_with_tags_and_metadata(db: Database) -> None:
    fact = remember(
        db,
        "deployment windows are Tuesdays",
        kind="constraint",
        tags=["ops", "schedule"],
        metadata={"confidence": "high", "source": "team-meeting-2024"},
    )
    assert fact.tags == ["ops", "schedule"]
    assert fact.metadata == {"confidence": "high", "source": "team-meeting-2024"}


def test_remember_rejects_invalid_kind(db: Database) -> None:
    with pytest.raises(ValueError, match="kind must be one of"):
        remember(db, "x", kind="junk")


def test_remember_rejects_empty_content(db: Database) -> None:
    with pytest.raises(ValueError, match="content must not be empty"):
        remember(db, "   \n\t   ")


def test_recall_without_query_returns_recent_first(db: Database) -> None:
    remember(db, "fact one")
    remember(db, "fact two")
    remember(db, "fact three")
    results = recall(db)
    assert [f.content for f in results] == ["fact three", "fact two", "fact one"]


def test_recall_respects_limit(db: Database) -> None:
    for i in range(5):
        remember(db, f"fact {i}")
    assert len(recall(db, limit=3)) == 3


def test_recall_by_kind_filters(db: Database) -> None:
    remember(db, "a fact", kind="fact")
    remember(db, "a pattern", kind="pattern")
    remember(db, "a preference", kind="preference")
    patterns = recall(db, kind="pattern")
    assert len(patterns) == 1
    assert patterns[0].kind == "pattern"


def test_recall_by_query_uses_fts(db: Database) -> None:
    remember(db, "deployment failed because env var was missing", kind="pattern")
    remember(db, "user loves dark mode", kind="preference")
    remember(db, "the deployment went smoothly last time", kind="fact")

    hits = recall(db, query="deployment")
    assert len(hits) == 2
    assert all("deployment" in f.content for f in hits)


def test_recall_query_and_kind_combine(db: Database) -> None:
    remember(db, "deployment failed", kind="pattern")
    remember(db, "deployment succeeded", kind="fact")
    hits = recall(db, query="deployment", kind="pattern")
    assert len(hits) == 1
    assert hits[0].kind == "pattern"


def test_recall_excludes_superseded_by_default(db: Database) -> None:
    old = remember(db, "the old truth")
    supersede(db, old.id, "the new truth")
    results = recall(db)
    contents = [f.content for f in results]
    assert "the new truth" in contents
    assert "the old truth" not in contents


def test_recall_include_superseded_opt_in(db: Database) -> None:
    old = remember(db, "old truth")
    supersede(db, old.id, "new truth")
    results = recall(db, include_superseded=True)
    assert len(results) == 2


def test_recall_limit_must_be_positive(db: Database) -> None:
    with pytest.raises(ValueError):
        recall(db, limit=0)


def test_supersede_links_old_to_new(db: Database) -> None:
    old = remember(db, "the old fact")
    new = supersede(db, old.id, "the new fact")
    assert new.id != old.id

    old_refreshed = db.fetchone("SELECT superseded_by FROM facts WHERE id = ?", (old.id,))
    assert old_refreshed is not None
    assert old_refreshed["superseded_by"] == new.id


def test_supersede_raises_if_old_missing(db: Database) -> None:
    with pytest.raises(ValueError, match="no fact with id"):
        supersede(db, 999999, "new content")


def test_supersede_with_identical_content_is_noop(db: Database) -> None:
    """Superseding with the exact same content returns the existing Fact unchanged."""
    original = remember(db, "same content")
    result = supersede(db, original.id, "same content")
    assert result.id == original.id
    # superseded_by should still be NULL — we didn't point it at itself
    row = db.fetchone("SELECT superseded_by FROM facts WHERE id = ?", (original.id,))
    assert row is not None
    assert row["superseded_by"] is None


def test_fact_dataclass_is_frozen() -> None:
    # Frozen dataclass contract: attempting to mutate raises.
    fact = Fact(
        id=1,
        content="x",
        kind="fact",
        tags=[],
        metadata={},
        content_hash="h",
        created_at=__import__("datetime").datetime(2024, 1, 1),
        updated_at=__import__("datetime").datetime(2024, 1, 1),
        superseded_by=None,
    )
    with pytest.raises(AttributeError):
        fact.content = "mutated"  # type: ignore[misc]
