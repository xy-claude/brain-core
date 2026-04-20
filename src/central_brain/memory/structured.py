"""Structured memory: facts, patterns, preferences, constraints.

Persistence model:
  * Content-addressed. ``content_hash`` (SHA-256 over whitespace-normalized
    content) is the dedup key. ``remember()`` is idempotent — calling it with
    identical content twice returns the same Fact.
  * ``tags`` and ``metadata`` are JSON-encoded at rest but exposed as
    ``list[str]`` and ``dict[str, Any]`` to callers.
  * ``supersede()`` creates a new fact and links the old one via
    ``superseded_by`` — history is preserved, not overwritten.

Retrieval:
  * ``recall(query=...)`` uses the FTS5 index for ranked text search.
  * ``recall(query=None)`` returns the most recent non-superseded facts.
  * Both support ``kind`` and ``limit`` filters.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from central_brain.storage.db import Database

FactKind = str  # Literal["fact", "pattern", "preference", "constraint"]
_VALID_KINDS: Final[frozenset[str]] = frozenset({"fact", "pattern", "preference", "constraint"})


@dataclass(frozen=True, slots=True)
class Fact:
    """A single remembered fact."""

    id: int
    content: str
    kind: FactKind
    tags: list[str]
    metadata: dict[str, Any]
    content_hash: str
    created_at: datetime
    updated_at: datetime
    superseded_by: int | None


def remember(
    db: Database,
    content: str,
    kind: FactKind = "fact",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Fact:
    """Remember a fact. Idempotent — re-calling with identical content returns
    the existing Fact without inserting a duplicate.

    Raises:
        ValueError: if ``kind`` is not one of the allowed fact kinds.
        ValueError: if ``content`` is empty after whitespace normalization.
    """
    if kind not in _VALID_KINDS:
        raise ValueError(f"kind must be one of {sorted(_VALID_KINDS)}, got {kind!r}")
    normalized = _normalize_whitespace(content)
    if not normalized:
        raise ValueError("content must not be empty")

    content_hash = _compute_content_hash(normalized)
    tags_json = json.dumps(tags) if tags else None
    metadata_json = json.dumps(metadata) if metadata else None

    db.execute(
        "INSERT OR IGNORE INTO facts "
        "(content, kind, tags, metadata, content_hash) "
        "VALUES (?, ?, ?, ?, ?)",
        (content, kind, tags_json, metadata_json, content_hash),
    )
    row = db.fetchone("SELECT * FROM facts WHERE content_hash = ?", (content_hash,))
    if row is None:  # pragma: no cover — defensive
        raise RuntimeError(f"fact vanished after INSERT OR IGNORE: hash={content_hash}")
    return _row_to_fact(row)


def recall(
    db: Database,
    query: str | None = None,
    kind: FactKind | None = None,
    limit: int = 10,
    include_superseded: bool = False,
) -> list[Fact]:
    """Retrieve facts.

    If ``query`` is given, runs an FTS5 search ranked by bm25. Otherwise
    returns the most recently created facts (DESC). Both modes support
    filtering by ``kind`` and respect ``limit``.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")

    sql, params = _build_recall_query(query, kind, limit, include_superseded)
    rows = db.fetchall(sql, params)
    return [_row_to_fact(r) for r in rows]


def supersede(
    db: Database,
    old_fact_id: int,
    new_content: str,
    kind: FactKind = "fact",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Fact:
    """Mark an existing fact as superseded by a new one.

    Writes the new fact via :func:`remember` (idempotent), then updates the
    old fact's ``superseded_by`` pointer. Returns the new Fact.

    Raises:
        ValueError: if ``old_fact_id`` does not exist.
    """
    existing = db.fetchone("SELECT id FROM facts WHERE id = ?", (old_fact_id,))
    if existing is None:
        raise ValueError(f"no fact with id={old_fact_id}")

    new_fact = remember(db, new_content, kind=kind, tags=tags, metadata=metadata)
    if new_fact.id == old_fact_id:
        # Caller tried to supersede with identical content — return unchanged.
        return new_fact

    db.execute(
        "UPDATE facts SET superseded_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_fact.id, old_fact_id),
    )
    return new_fact


# ── internal helpers ─────────────────────────────────────────────────────────


def _build_recall_query(
    query: str | None,
    kind: FactKind | None,
    limit: int,
    include_superseded: bool,
) -> tuple[str, tuple[Any, ...]]:
    where: list[str] = []
    params: list[Any] = []

    if not include_superseded:
        where.append("f.superseded_by IS NULL")
    if kind is not None:
        where.append("f.kind = ?")
        params.append(kind)

    if query is None:
        sql = "SELECT f.* FROM facts f"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY f.created_at DESC, f.id DESC LIMIT ?"
        params.append(limit)
        return sql, tuple(params)

    # FTS5 path — rank by bm25, filter through joined facts row.
    where.insert(0, "facts_fts MATCH ?")
    params.insert(0, query)
    sql = (
        "SELECT f.* FROM facts_fts "
        "JOIN facts f ON facts_fts.rowid = f.id "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY bm25(facts_fts), f.created_at DESC LIMIT ?"
    )
    params.append(limit)
    return sql, tuple(params)


def _row_to_fact(row: sqlite3.Row) -> Fact:
    return Fact(
        id=int(row["id"]),
        content=str(row["content"]),
        kind=str(row["kind"]),
        tags=json.loads(row["tags"]) if row["tags"] else [],
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        content_hash=str(row["content_hash"]),
        created_at=_parse_timestamp(row["created_at"]),
        updated_at=_parse_timestamp(row["updated_at"]),
        superseded_by=(int(row["superseded_by"]) if row["superseded_by"] is not None else None),
    )


def _parse_timestamp(value: str) -> datetime:
    """SQLite ``CURRENT_TIMESTAMP`` returns ``'YYYY-MM-DD HH:MM:SS'``.

    Python 3.11+ ``fromisoformat`` handles both space- and T-separated forms.
    """
    return datetime.fromisoformat(value)


def _normalize_whitespace(content: str) -> str:
    """Collapse internal whitespace to single spaces, strip ends.

    Used for dedup hashing only — the original content is stored verbatim.
    """
    return " ".join(content.split())


def _compute_content_hash(normalized_content: str) -> str:
    return hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
