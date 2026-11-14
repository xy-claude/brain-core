"""Common types for store adapters."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

Kind = Literal[
    "fact",
    "pattern",
    "decision",
    "correction",
    "note",
    "raw",
    "relation",
    "knowledge",
    "transcript",  # read-only: indexed from Claude Code session files, never written
]

_DATE_SUFFIX = re.compile(r"\s*\((\d{4}-\d{2}-\d{2})\)\s*$")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Collapse whitespace and drop a trailing ``(YYYY-MM-DD)`` so the same fact hashes the same."""
    return _WS.sub(" ", _DATE_SUFFIX.sub("", text)).strip()


def record_id(text: str) -> str:
    """Stable id: sha256 of the normalised text. Used for idempotent writes across every store."""
    return hashlib.sha256(normalize(text).encode()).hexdigest()


@dataclass(frozen=True)
class Record:
    id: str
    kind: Kind
    text: str
    date: date
    domain: str = ""
    path: str = ""
    line: int = 0
    extra: dict[str, str] = field(default_factory=dict)
    score: float = 0.0  # bm25 from the record index (higher is better); 0 = the store gave none
    # the line carries no date of its own: `date` is only its file's, so it earns no recency,
    # is not found by day, and is shown as undated
    undated: bool = False


def full_text(r: Record) -> str:
    """Title plus every field a decision or correction carries in `extra`, in file order, so
    the rule a correction teaches can be found too. Other kinds are their own text."""
    if r.kind not in ("decision", "correction"):
        return r.text
    # the title is already the text; `context` and `fact_type` are Hindsight's own labels
    body = " ".join(
        v for k, v in r.extra.items() if k not in ("title", "context", "fact_type") and v
    )
    return f"{r.text} — {body}" if body else r.text


def holds(token: str, text: str) -> bool:
    """``token`` stands in ``text`` as a whole word: 8888 is not found inside 18888."""
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text.lower()) is not None


@dataclass(frozen=True)
class WriteResult:
    store: str
    id: str
    status: Literal["written", "exists", "pending", "failed", "refused"]
    detail: str = ""


class Store(Protocol):
    name: str

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]: ...

    def write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult: ...

    def health(self) -> tuple[bool, str]: ...
