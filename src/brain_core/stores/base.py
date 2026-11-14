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


def full_text(r: Record) -> str:
    """Title plus the body fields a decision or correction carries in `extra`."""
    body = " ".join(
        v for k, v in r.extra.items() if k in ("decision", "reason", "error", "correction")
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
