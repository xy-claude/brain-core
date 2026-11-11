"""Markdown vault adapter. Contract: docs/VAULT_SCHEMA.md.

Reads the layout a hand-written vault already has (legacy-compatible), writes only the
dated, idempotent, append-only forms the schema defines.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

from brain_core.stores.base import Kind, Record, WriteResult, record_id
from brain_core.stores.index import RecordIndex

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)
_HEADING = re.compile(r"^(#{1,3}) (.+?)\s*$")
_BULLET = re.compile(r"^- (.+?)(?:\s*\((\d{4}-\d{2}-\d{2})\))?\s*$")
_DECISION = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+?)\s*$")
_CORRECTION = re.compile(r"^### \[(\d{4}-\d{2}-\d{2})\] (.+?)\s*$")
_SECRET = re.compile(
    r"hsk_[A-Za-z0-9]{8,}|(?i:bearer)\s+(?=[A-Za-z0-9._-]*\d)[A-Za-z0-9._-]{16,}|\bsk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"  # a JWT
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)

FILES: dict[Kind, str] = {
    "fact": "facts.md",
    "pattern": "patterns.md",
    "decision": "decisions_log.md",
    "correction": "corrections.md",
}
META = "record_meta.md"
_META = re.compile(r"^- ([0-9a-f]{16}) \| (.+)$")
_INDEXED: tuple[Kind, ...] = (
    "fact",
    "pattern",
    "decision",
    "correction",
    "note",
    "raw",
    "knowledge",
)


class VaultStore:
    name = "vault"

    def __init__(
        self, root: Path | str, owner: str = "agent", index: RecordIndex | None = None
    ) -> None:
        self.root = Path(root).expanduser()
        self.owner = owner
        self.index = index
        self.ranked = index is not None  # with an index a query comes back in bm25 order
        self._meta_sig = -1  # mtime of record_meta.md when its keys were last loaded

    # ── read ────────────────────────────────────────────────────────────────

    def _paths(self, kind: Kind) -> list[Path]:
        if kind == "note":
            # rglob: `brain weekly` moves old days into sessions/archive/YYYY-MM/
            return sorted((self.root / "sessions").rglob("????-??-??.md"), reverse=True)
        if kind == "raw":
            return sorted((self.root / "raw").glob("*.md"), reverse=True)
        if kind == "knowledge":
            return sorted(
                p for p in (self.root / "knowledge").glob("*.md") if not p.name.startswith("_")
            )
        return [self.root / FILES[kind]] if kind in FILES else []

    def meta(self) -> dict[str, dict[str, str]]:
        """``record_meta.md``: per record id, the fields the record's own line cannot carry
        (search keys, source, mission). A later line for the same id adds keys and replaces
        the rest."""
        out: dict[str, dict[str, str]] = {}
        for line in read_text(self.root / META).splitlines():
            if m := _META.match(line):
                d = out.setdefault(m.group(1), {})
                for part in m.group(2).split(" | "):
                    k, _, v = part.partition(": ")
                    d[k] = f"{d[k]}; {v}" if k == "keys" and k in d else v
        return out

    def retired(self) -> set[str]:
        """Ids (16 characters) of records a newer one replaced: its ``supersedes`` field."""
        return {d["supersedes"][:16] for d in self.meta().values() if d.get("supersedes")}

    def _note_meta(self, rid: str, when: date, extra: dict[str, str]) -> None:
        fields = {
            k: " ".join(str(extra[k]).replace("|", "/").split())
            for k in ("keys", "source", "mission", "supersedes")
            if extra.get(k)
        }
        if not fields:
            return
        path = self.root / META
        line = f"- {rid[:16]} | " + " | ".join(f"{k}: {v}" for k, v in fields.items())
        with self._locked(path):
            text = read_text(path) or (
                f"---\ntype: index\nowner: {self.owner}\nstatus: active\n"
                f"updated: {when.isoformat()}\n---\n# Record meta\n\n"
                "Search keys, source and mission of each record, by record id. "
                "Written by brain_remember; append-only.\n\n"
            )
            if line not in text.splitlines():
                self._save(path, text.rstrip("\n") + "\n" + line + "\n", when)

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        if query and self.index:
            meta = self.root / META
            sig = meta.stat().st_mtime_ns if meta.exists() else 0
            if sig != self._meta_sig:  # keys changed on disk: bring the index in line
                self.index.set_keys({i: d["keys"] for i, d in self.meta().items() if "keys" in d})
                self._meta_sig = sig
            files = {p: k for k in _INDEXED for p in self._paths(k) if p.exists()}
            self.index.sync(self.name, files, lambda k, p: self._parse(k, p, full=True))
            return self.index.search(self.name, [kind], query, limit)
        paths = self._paths(kind)
        out: list[Record] = []
        q = (query or "").lower()
        for p in paths:
            if not p.exists():
                continue
            for r in self._parse(kind, p):
                if not q or q in r.text.lower() or q in r.domain.lower():
                    out.append(r)
        out.sort(key=lambda r: r.date, reverse=True)
        return out[:limit]

    def _parse(self, kind: Kind, path: Path, full: bool = False) -> list[Record]:
        text = path.read_text(encoding="utf-8")
        fm = self._frontmatter(text)
        fallback = _parse_date(fm.get("updated")) or date.fromtimestamp(path.stat().st_mtime)
        rel = path.relative_to(self.root).as_posix()
        if kind == "raw":
            return [
                Record(
                    fm.get("sha256", record_id(text)),
                    "raw",
                    fm.get("title", path.stem),
                    _parse_date(fm.get("fetched")) or fallback,
                    "",
                    rel,
                    0,
                    fm,
                )
            ]
        if kind == "knowledge":
            return knowledge_records(text, rel, fallback, cap=None if full else 600)
        if kind == "note":
            fallback = _parse_date(path.stem) or fallback
        records: list[Record] = []
        domain = ""
        entry: dict[str, str] | None = None
        for n, line in enumerate(text.splitlines(), 1):
            if kind == "decision" and (m := _DECISION.match(line)):
                entry = {"title": m.group(2)}
                records.append(
                    Record(
                        record_id(m.group(2)),
                        kind,
                        m.group(2),
                        _parse_date(m.group(1)) or fallback,
                        domain,
                        rel,
                        n,
                        entry,
                    )
                )
                continue
            if kind == "correction" and (m := _CORRECTION.match(line)):
                entry = {"title": m.group(2)}
                records.append(
                    Record(
                        record_id(m.group(2)),
                        kind,
                        m.group(2),
                        _parse_date(m.group(1)) or fallback,
                        domain,
                        rel,
                        n,
                        entry,
                    )
                )
                continue
            if (
                kind in ("decision", "correction")
                and entry is not None
                and (m := re.match(r"^(?:- )?\*\*(\w[\w ]*):\*\*\s*(.*)$", line))
            ):
                entry[m.group(1).lower()] = m.group(2)
                continue
            if m := _HEADING.match(line):
                domain = m.group(2)
                continue
            if kind in ("fact", "pattern", "note") and (m := _BULLET.match(line)):
                body, d = m.group(1), m.group(2)
                records.append(
                    Record(
                        record_id(body),
                        kind,
                        body,
                        _parse_date(d) or fallback,
                        domain,
                        rel,
                        n,
                        {} if (d or kind == "note") else {"legacy": "undated"},
                    )
                )
        return records

    # ── write ───────────────────────────────────────────────────────────────

    def write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        r = self._write(kind, text, domain=domain, when=when, **extra)
        if r.status in ("written", "exists") and r.id:
            self._note_meta(r.id, when or date.today(), extra)  # keys can be added to an old record
        return r

    def _write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        if _SECRET.search(text):
            return WriteResult(self.name, "", "refused", "text looks like it contains a secret")
        when = when or date.today()
        if kind != "raw":
            text = " ".join(text.split())  # one bullet line; the id is hashed the same way
        rid = record_id(text)
        if kind == "note":
            path = self.root / "sessions" / f"{when.isoformat()}.md"
            section = extra.get("section", "What We Discussed")
            return self._append_bullet(
                path,
                rid,
                f"- {text}",
                section,
                when,
                kind,
                create_header=f"# Session Archive — {when.isoformat()}",
            )
        if kind == "fact":
            return self._append_bullet(
                self.root / FILES[kind],
                rid,
                f"- {text} ({when.isoformat()})",
                domain or "General",
                when,
                kind,
            )
        if kind == "pattern":
            title = extra.get("title", "")
            bullet = f"**{title}** — {text}" if title else text
            # the id must match what _parse will read back: the whole bullet body
            return self._append_bullet(
                self.root / FILES[kind],
                record_id(bullet),
                f"- {bullet} ({when.isoformat()})",
                domain or "General",
                when,
                kind,
            )
        if kind in ("decision", "correction"):
            rid = record_id(extra.get("title", text[:60]))  # _parse keys these by heading
        if kind == "decision":
            block = (
                f"## {when.isoformat()} — {extra.get('title', text[:60])}\n"
                f"**Decision:** {text}\n**Reason:** {extra.get('reason', '')}\n"
                f"**Classification:** {extra.get('classification', 'reversible × low-risk')}\n"
                f"**Confidence:** {extra.get('confidence', 'medium')}\n"
            )
            return self._insert_entry(self.root / FILES[kind], rid, block, when, after_heading=None)
        if kind == "correction":
            block = (
                f"### [{when.isoformat()}] {extra.get('title', text[:60])}\n"
                f"- **Error:** {extra.get('error', text)}\n"
                f"- **Correction:** {extra.get('correction', '')}\n"
                f"- **Implied rule:** {extra.get('rule', '')}\n"
                f"- **Theme:** {extra.get('theme', 'execution')}\n- **Promoted:** No\n"
            )
            return self._insert_entry(
                self.root / FILES[kind], rid, block, when, after_heading="## Corrections"
            )
        if kind == "raw":
            return self._write_raw(text, when, extra)
        return WriteResult(
            self.name,
            rid,
            "refused",
            f"kind {kind!r} is not a vault kind; see docs/VAULT_SCHEMA.md",
        )

    def _append_bullet(
        self,
        path: Path,
        rid: str,
        line: str,
        section: str,
        when: date,
        kind: Kind,
        create_header: str = "",
    ) -> WriteResult:
        with self._locked(path):
            text = (
                path.read_text(encoding="utf-8")
                if path.exists()
                else self._new_file(kind, when, create_header)
            )
            if rid in {r.id for r in self._parse(kind, path)} if path.exists() else False:
                return WriteResult(self.name, rid, "exists", path.relative_to(self.root).as_posix())
            lines = text.rstrip("\n").split("\n")
            heading = f"## {section}"
            idx = next((i for i, ln in enumerate(lines) if ln.strip() == heading), None)
            if idx is None:
                lines += ["", heading, line]
            else:
                end = next(
                    (j for j in range(idx + 1, len(lines)) if lines[j].startswith("## ")),
                    len(lines),
                )
                while end > idx + 1 and not lines[end - 1].strip():
                    end -= 1
                lines.insert(end, line)
            self._save(path, "\n".join(lines) + "\n", when)
        return WriteResult(
            self.name, rid, "written", f"{path.relative_to(self.root).as_posix()} › {section}"
        )

    def _insert_entry(
        self, path: Path, rid: str, block: str, when: date, after_heading: str | None
    ) -> WriteResult:
        kind: Kind = "correction" if after_heading else "decision"
        with self._locked(path):
            if not path.exists():
                self._save(path, self._new_file(kind, when, ""), when)
            if rid in {r.id for r in self._parse(kind, path)}:
                return WriteResult(self.name, rid, "exists", path.relative_to(self.root).as_posix())
            text = path.read_text(encoding="utf-8")
            lines = text.split("\n")
            if after_heading:
                start = next((i for i, ln in enumerate(lines) if ln.strip() == after_heading), None)
                anchor = (start + 1) if start is not None else len(lines)
                if start is None:
                    lines += ["", after_heading]
                    anchor = len(lines)
            else:  # decisions: newest first, before the first existing entry
                anchor = next((i for i, ln in enumerate(lines) if _DECISION.match(ln)), len(lines))
            lines[anchor:anchor] = ["", *block.rstrip("\n").split("\n")]
            self._save(path, "\n".join(lines).rstrip("\n") + "\n", when)
        return WriteResult(self.name, rid, "written", path.relative_to(self.root).as_posix())

    def _write_raw(self, body: str, when: date, meta: dict[str, str]) -> WriteResult:
        slug = re.sub(r"[^a-z0-9]+", "-", meta.get("title", "untitled").lower()).strip("-")[:60]
        sha = record_id(body)
        path = self.root / "raw" / f"{when.isoformat()}-{slug or 'untitled'}.md"
        if path.exists():  # same title, different source: raw/ is immutable, never overwrite
            path = path.with_name(f"{path.stem}-{sha[:8]}.md")
        existing = [
            r
            for r in self.read("raw", limit=10_000)
            if r.id == sha or r.extra.get("source") == meta.get("source")
        ]
        if existing:
            return WriteResult(self.name, existing[0].id, "exists", existing[0].path)
        fm = {
            "type": "raw",
            "owner": self.owner,
            "source": meta.get("source", ""),
            "title": meta.get("title", ""),
            "author": meta.get("author", "unknown"),
            "published": meta.get("published", "unknown"),
            "fetched": when.isoformat(),
            "sha256": sha,
            "words": str(len(body.split())),
            "compiled_into": "[]",
        }
        head = "---\n" + "\n".join(f"{k}: {v}" for k, v in fm.items()) + "\n---\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked(path):
            self._save(path, head + body, when, bump=False)
        return WriteResult(self.name, sha, "written", path.relative_to(self.root).as_posix())

    # ── helpers ─────────────────────────────────────────────────────────────

    def _new_file(self, kind: Kind, when: date, header: str) -> str:
        ftype = {
            "fact": "reference",
            "pattern": "reference",
            "decision": "log",
            "correction": "log",
            "note": "session",
        }.get(kind, "reference")
        title = header or f"# {FILES.get(kind, kind).replace('.md', '').replace('_', ' ').title()}"
        body = "\n## Corrections\n" if kind == "correction" else ""
        fm = f"type: {ftype}\nowner: {self.owner}\nstatus: active\nupdated: {when.isoformat()}"
        return f"---\n{fm}\n---\n{title}\n{body}"

    def _save(self, path: Path, text: str, when: date, bump: bool = True) -> None:
        if bump:
            text = _bump_updated(text, when)
        tmp = path.with_suffix(path.suffix + ".tmp")
        for attempt in range(5):
            try:
                tmp.write_text(text, encoding="utf-8")
                os.replace(tmp, path)
                return
            except OSError as e:  # iCloud EDEADLK / EAGAIN: back off and retry
                if e.errno not in (11, 35) or attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))

    def _locked(self, path: Path) -> _Lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        return _Lock(self.root / ".brain.lock")  # one lock per vault: nothing accumulates

    @staticmethod
    def _frontmatter(text: str) -> dict[str, str]:
        return frontmatter(text)

    def health(self) -> tuple[bool, str]:
        if not self.root.is_dir():
            return (False, f"vault root missing: {self.root}")
        probe = self.root / ".brain_probe"
        try:
            probe.write_text("ok")
            probe.unlink()
        except OSError as e:
            return (False, f"vault not writable: {e}")
        return (True, f"{self.root} ({sum(1 for _ in self.root.rglob('*.md'))} notes)")


def _lock_dir() -> Path:
    return Path.home() / ".cache" / "brain-core" / "locks"


class _Lock:
    """An exclusive lock named after the path it guards, kept on the local disk.

    The lock file is never inside the vault: a sync service can evict a file there (iCloud turned
    ``.brain.lock`` into a placeholder that a background process could not open, 2026-11-09),
    and every write then failed.
    """

    def __init__(self, path: Path) -> None:
        key = hashlib.sha256(os.path.abspath(path).encode()).hexdigest()[:24]
        self.path = _lock_dir() / f"{key}.lock"
        self.fd = -1

    def __enter__(self) -> _Lock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR)
        if sys.platform == "win32":
            # shortcut: LK_LOCK retries once a second for 10 s then raises, upgrade to a retry
            # loop if a Windows user ever reports a lock error
            msvcrt.locking(self.fd, msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc: object) -> None:
        if sys.platform == "win32":
            msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)


def _bump_updated(text: str, when: date) -> str:
    if (m := _FRONTMATTER.match(text)) and "updated:" in m.group(1):
        return (
            text[: m.start(1)]
            + re.sub(r"(?m)^updated:.*$", f"updated: {when.isoformat()}", m.group(1))
            + text[m.end(1) :]
        )
    return text


def read_text(path: Path) -> str:
    """A vault file as text, empty if missing; a stray non-UTF-8 byte never stops a read."""
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def knowledge_records(text: str, rel: str, when: date, cap: int | None = 600) -> list[Record]:
    """One record per `## section` of a page: title › heading: body. A page without `## `
    sections (a plain note, a Claude Code memory file) is one record of its body. ``cap``
    cuts the body for a whole-store read; the index passes None so every word is searchable."""
    fm = frontmatter(text)
    m = _FRONTMATTER.match(text)
    skip = m.group(0).count("\n") if m else 0  # frontmatter lines: never body, never a title
    lines = text.splitlines()
    title = next(
        (ln[2:].strip() for ln in lines[skip:] if ln.startswith("# ")),
        fm.get("title") or fm.get("name") or rel,
    )
    records: list[Record] = []
    heading, start = "", 0
    body: list[str] = []
    for n, line in enumerate(lines, 1):
        if line.startswith("## "):
            if heading:
                records.append(_knowledge_record(title, heading, body, rel, start, when, cap))
            heading, body, start = line[3:].strip(), [], n
        elif heading and line.strip() and not line.startswith("---"):
            body.append(line.strip())
    if heading:
        records.append(_knowledge_record(title, heading, body, rel, start, when, cap))
    if not records:
        plain = [ln.strip() for ln in lines[skip:] if ln.strip() and ln[0] != "#"]
        if plain:
            records.append(_knowledge_record(title, "", plain, rel, 1, when, cap))
    return records


def _knowledge_record(
    title: str, heading: str, body: list[str], rel: str, line: int, when: date, cap: int | None
) -> Record:
    joined = " ".join(body)[:cap]
    text = f"{title} › {heading}: {joined}" if heading else f"{title}: {joined}"
    return Record(record_id(f"{rel}#{heading}"), "knowledge", text, when, "", rel, line, {})


def frontmatter(text: str) -> dict[str, str]:
    """Top-level `key: value` pairs of a YAML frontmatter block; quotes stripped."""
    m = _FRONTMATTER.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for ln in m.group(1).splitlines():
        if ":" in ln and not ln.startswith(" "):
            k, _, v = ln.partition(":")
            out[k.strip()] = v.strip().strip("'\"")
    return out
