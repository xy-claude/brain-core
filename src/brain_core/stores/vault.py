"""Markdown vault adapter. Contract: docs/VAULT_SCHEMA.md.

Reads the layout the XYCLAUDE vault already has (legacy-compatible), writes only the
dated, idempotent, append-only forms the schema defines.
"""

from __future__ import annotations

import fcntl
import os
import re
import time
from datetime import date
from pathlib import Path

from brain_core.stores.base import Kind, Record, WriteResult, record_id

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)
_HEADING = re.compile(r"^(#{1,3}) (.+?)\s*$")
_BULLET = re.compile(r"^- (.+?)(?:\s*\((\d{4}-\d{2}-\d{2})\))?\s*$")
_DECISION = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+?)\s*$")
_CORRECTION = re.compile(r"^### \[(\d{4}-\d{2}-\d{2})\] (.+?)\s*$")
_SECRET = re.compile(
    r"hsk_[A-Za-z0-9]{8,}|(?i:bearer)\s+[A-Za-z0-9._-]{16,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
)

FILES: dict[Kind, str] = {
    "fact": "facts.md",
    "pattern": "patterns.md",
    "decision": "decisions_log.md",
    "correction": "corrections.md",
}
HSAM_SECTIONS = (
    "What We Discussed",
    "URLs & Links Shared",
    "Decisions Made",
    "Facts & Numbers",
    "Ideas & Possibilities",
    "Sir's Questions",
    "Tools/Services/Products",
    "Files & Resources",
    "Sir's Mood & Context",
    "Corrections & Feedback",
    "Open loops",
)


class VaultStore:
    name = "vault"

    def __init__(self, root: Path | str, owner: str = "agent") -> None:
        self.root = Path(root).expanduser()
        self.owner = owner

    # ── read ────────────────────────────────────────────────────────────────

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        if kind == "note":
            paths = sorted((self.root / "sessions").glob("????-??-??.md"), reverse=True)
        elif kind == "raw":
            paths = sorted((self.root / "raw").glob("*.md"), reverse=True)
        elif kind in FILES:
            paths = [self.root / FILES[kind]]
        else:
            return []
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

    def _parse(self, kind: Kind, path: Path) -> list[Record]:
        text = path.read_text(encoding="utf-8")
        fm = self._frontmatter(text)
        fallback = _parse_date(fm.get("updated")) or date.fromtimestamp(path.stat().st_mtime)
        rel = str(path.relative_to(self.root))
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
                        date.fromisoformat(m.group(1)),
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
                        date.fromisoformat(m.group(1)),
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
                        date.fromisoformat(d) if d else fallback,
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
        if _SECRET.search(text):
            return WriteResult(self.name, "", "refused", "text looks like it contains a secret")
        when = when or date.today()
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
            body = (
                f"- **{title}** — {text} ({when.isoformat()})"
                if title
                else f"- {text} ({when.isoformat()})"
            )
            return self._append_bullet(
                self.root / FILES[kind], rid, body, domain or "General", when, kind
            )
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
                return WriteResult(self.name, rid, "exists", str(path.relative_to(self.root)))
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
        return WriteResult(self.name, rid, "written", f"{path.relative_to(self.root)} › {section}")

    def _insert_entry(
        self, path: Path, rid: str, block: str, when: date, after_heading: str | None
    ) -> WriteResult:
        kind: Kind = "correction" if after_heading else "decision"
        with self._locked(path):
            if not path.exists():
                self._save(path, self._new_file(kind, when, ""), when)
            if rid in {r.id for r in self._parse(kind, path)}:
                return WriteResult(self.name, rid, "exists", str(path.relative_to(self.root)))
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
        return WriteResult(self.name, rid, "written", str(path.relative_to(self.root)))

    def _write_raw(self, body: str, when: date, meta: dict[str, str]) -> WriteResult:
        slug = re.sub(r"[^a-z0-9]+", "-", meta.get("title", "untitled").lower()).strip("-")[:60]
        path = self.root / "raw" / f"{when.isoformat()}-{slug}.md"
        sha = record_id(body)
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
        return WriteResult(self.name, sha, "written", str(path.relative_to(self.root)))

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
        return _Lock(path.with_name(f".{path.name}.lock"))

    @staticmethod
    def _frontmatter(text: str) -> dict[str, str]:
        m = _FRONTMATTER.match(text)
        if not m:
            return {}
        out: dict[str, str] = {}
        for ln in m.group(1).splitlines():
            if ":" in ln and not ln.startswith(" "):
                k, _, v = ln.partition(":")
                out[k.strip()] = v.strip().strip("'\"")
        return out

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


class _Lock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd = -1

    def __enter__(self) -> _Lock:
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc: object) -> None:
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


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None
