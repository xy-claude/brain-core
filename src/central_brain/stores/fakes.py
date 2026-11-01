"""In-memory store for tests. Same contract, no disk, no network."""

from __future__ import annotations

from datetime import date

from central_brain.stores.base import Kind, Record, WriteResult, record_id


class MemoryStore:
    name = "memory"

    def __init__(self, *, healthy: bool = True) -> None:
        self.records: list[Record] = []
        self.healthy = healthy

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        hits = [
            r
            for r in self.records
            if r.kind == kind and (not query or query.lower() in r.text.lower())
        ]
        return sorted(hits, key=lambda r: r.date, reverse=True)[:limit]

    def write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        if not self.healthy:
            return WriteResult(self.name, "", "failed", "store down")
        rid = record_id(text)
        if any(r.id == rid for r in self.records):
            return WriteResult(self.name, rid, "exists")
        self.records.append(
            Record(rid, kind, text, when or date.today(), domain, extra=dict(extra))
        )
        return WriteResult(self.name, rid, "written")

    def health(self) -> tuple[bool, str]:
        return (self.healthy, "ok" if self.healthy else "store down")
