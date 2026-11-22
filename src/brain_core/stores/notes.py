"""Read-only markdown folders recall also searches: a vault ``shared/`` folder other agents
write, or Claude Code's own memory folder (``~/.claude/projects/<slug>/memory``). Each file
is read like a knowledge page: one record per ``## section``, or one for the whole body.

M1b: a record's id hashes ``<store>:<root name>/<file>#heading``, so moving a folder keeps its
ids. The root name is the folder's own, or the ``name:`` brain.yaml gives it. Two folders of
one store with the same name keep the 0.10 ids (their absolute paths) until each is named.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from brain_core.stores.base import Kind, Record, WriteResult
from brain_core.stores.index import RecordIndex
from brain_core.stores.vault import _parse_date, frontmatter, knowledge_records, read_text


class NotesStore:
    name = "notes"

    def __init__(
        self, dirs: Sequence[Path | tuple[Path, str | None]], index: RecordIndex | None = None
    ) -> None:
        self.roots: dict[Path, str] = {}
        for d in dirs:
            path, name = d if isinstance(d, tuple) else (d, None)
            path = Path(path).expanduser()
            self.roots[path] = name or path.name
        self.dirs = list(self.roots)
        counts = Counter(self.roots.values())
        self.clash = sorted(n for n, c in counts.items() if c > 1)  # names two folders share
        self.index = index
        self.ranked = index is not None  # with an index a query comes back in bm25 order

    def _source(self, p: Path) -> str | None:
        """The store-relative source id the record ids hash, or None to keep the path ids."""
        root = next((d for d in self.roots if p.parent == d), None)
        if root is None or self.roots[root] in self.clash:
            return None
        return f"{self.name}:{self.roots[root]}/{p.relative_to(root).as_posix()}"

    def _records(self, p: Path, cap: int | None = 600, shown: str | None = None) -> list[Record]:
        text = read_text(p)
        when = _parse_date(frontmatter(text).get("updated")) or date.fromtimestamp(
            p.stat().st_mtime
        )
        return knowledge_records(text, shown or str(p), when, cap, self._source(p))

    def id_map(self, old_roots: Mapping[str, Path] | None = None) -> dict[str, str]:
        """Old record id -> new one, for every record of a named folder whose id changes.
        ``old_roots`` gives a folder's former location by root name, for keys written there."""
        out: dict[str, str] = {}
        for d, name in self.roots.items():
            if name in self.clash or not d.is_dir():
                continue
            base = Path((old_roots or {}).get(name, d)).expanduser()
            for p in sorted(d.glob("*.md")):
                for r in self._records(p, None, str(base / p.relative_to(d))):
                    if was := r.extra.get("was"):
                        out[was] = r.id
        return out

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        if kind != "knowledge":
            return []
        files = [p for d in self.dirs if d.is_dir() for p in sorted(d.glob("*.md"))]
        if query and self.index:
            for d in self.dirs:
                # a folder that held records and is away (a drive not mounted) is not an empty
                # one: the sync would drop its rows and then their vectors. One that was never
                # there has none to lose and is skipped
                if not d.is_dir() and self.index.under(self.name, d):
                    raise FileNotFoundError(f"{self.name} folder missing: {d}")
            self.index.sync(
                self.name, dict.fromkeys(files, kind), lambda _k, p: self._records(p, None)
            )
            return self.index.search(self.name, [kind], query, limit)
        out: list[Record] = []
        q = (query or "").lower()
        for p in files:
            out += [r for r in self._records(p) if not q or q in r.text.lower()]
        out.sort(key=lambda r: r.date, reverse=True)
        return out[:limit]

    readonly = True  # brain_remember never asks it

    def write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        return WriteResult(self.name, "", "refused", "notes folders are read, never written")

    def health(self) -> tuple[bool, str]:
        missing = [str(d) for d in self.dirs if not d.is_dir()]
        n = sum(len(list(d.glob("*.md"))) for d in self.dirs if d.is_dir())
        if missing:
            return (False, f"notes: folder missing: {', '.join(missing)}")
        clash = (
            f"; folders named alike ({', '.join(self.clash)}) keep path ids: give each a `name:`"
            if self.clash
            else ""
        )
        return (True, f"notes files={n} folders={len(self.dirs)}{clash}")


class ArchiveStore(NotesStore):
    """Folders of older memory copied in from another tool (``stores.archive``). Read like
    notes; recall ranks them below the agent's own records, so a copy never outranks the line
    it was copied from and an old value never outranks the one that replaced it."""

    name = "archive"
