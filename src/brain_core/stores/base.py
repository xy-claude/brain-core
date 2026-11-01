"""Common types for store adapters."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

Kind = Literal["fact", "pattern", "decision", "correction", "note", "raw", "relation", "knowledge"]

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
