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
from dataclasses import replace
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
# hand-written logs nest them, and put a time or a note between the date and the dash
_DECISION = re.compile(r"^###? (\d{4}-\d{2}-\d{2})[^—]*— (.+?)\s*$")
_CORRECTION = re.compile(r"^### \[(\d{4}-\d{2}-\d{2})\] (.+?)\s*$")
_FIELD = re.compile(r"^(?:- )?\*\*(\w[\w ]*):\*\*\s*(.*)$")
# a line that only names what follows it: bold, ending in a colon, or a deeper heading
_LABEL = re.compile(r"\*\*[^*]{1,60}\*\*:?$|[A-Za-z][^.]{0,40}:$|#{4,6} .{0,60}$")
# fields that file an entry, not what it says: two entries that differ only here are one entry
_STATE = ("title", "classification", "confidence", "theme", "promoted")
# Any key format the list below does not know: a label, then one unbroken value of 16 or more
# characters in which a letter and a digit touch. After "password" or "secret" one touch is
# enough; after key, token, auth, licence, credential, pass or pw it takes two, because one
# touch is a name there (oauth2-client-credentials, transcripts_fts_v2, id_ed25519_laptop).
# An env name may go on after the label in capitals (SECRET_KEY_BASE=, DEPLOY_TOKEN_V2=). A
# slug that ends in a year (risk-model-2026), a path, a URL, a date and a version are not such
# a value. The label may end a longer name
# (API_KEY, authToken), may be followed by a short note in brackets ("key (staging): ...") and
# may stand in the table cell before the value's. The rest of the value's run goes with it
# (base64 has / in it, a JWT has dots) up to a space, a quote or one of , ; & so the next
# field of a list or a query string stays readable. The value starts at a letter or digit and
# the touch is looked for in its first 64 characters: unbounded, a line of "=" or of
# "key=key=" after a label took seconds (16,000 characters: 1.4 s), and this pattern reads
# every record at index time.
_LABELLED = (
    r"(?P<label>(?:(?P<strong>(?i:secret|password|passwd|pwd))|(?i:key|token|licen[cs]e|auth"
    r"|credential|pass(?:phrase|code)?|pw))s?(?:_[A-Z0-9]{1,8}){0,2}"
    r"(?:\s*\([^()\n]{1,24}\))?[\s\"'`*:=|]+(?:(?i:is)[\s\"'`*]+)?)(?=[A-Za-z0-9])"
    r"(?=[A-Za-z0-9_+=-]{0,64}?(?:[A-Za-z]\d|\d[A-Za-z]))"
    r"(?(strong)|(?=(?:[A-Za-z0-9_+=-]{0,64}?(?:[A-Za-z]\d|\d[A-Za-z])){2}))"
    r"(?P<value>[A-Za-z0-9_+=-]{16,})[^\s\"'`,;&]*"
)
# What a pattern cannot see: a short password, a passphrase of words, digits alone, a value
# with a / in its first 16 characters (one AWS secret key in four), and a random string with
# neither a label nor a vendor's prefix.
_SECRET = re.compile(
    r"hsk_[A-Za-z0-9]{8,}|(?i:bearer)\s+(?P<bearer>(?=[A-Za-z0-9._-]*\d)[A-Za-z0-9._-]{16,})"
    r"|(?i:basic)\s+(?P<basic>(?=[A-Za-z0-9+/]*\d)[A-Za-z0-9+/]{16,}={0,2})"
    r"|\bsk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
    # a JWT. Not looked for inside a longer run: tried from every "eyJ" of one, 128,000
    # characters took 3 s
    r"|(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    # a key block with all that stands between its two lines (a quote mark, a line break
    # written as \n, Proc-Type or PGP armor lines). With no END line (a tool result is cut
    # short) its base64 runs, so a sentence that only names the header keeps its words
    r"|-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"
    r"(?:(?:(?!-----BEGIN )[\s\S]){0,8000}?-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"
    r"|(?:(?:\\+[nr]|[\s>])*(?:[A-Za-z0-9+/=]{16,}|(?:Proc-Type|DEK-Info): ?[^\s\\]+))*)"
    # Stripe, Google, Telegram, Hugging Face, npm, PyPI, GitLab, SendGrid, DigitalOcean, Slack
    r"|\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}|whsec_[A-Za-z0-9]{24,}|AIza[0-9A-Za-z_-]{35}"
    r"|GOCSPX-[A-Za-z0-9_-]{28}|\b\d{8,10}:AA[A-Za-z0-9_-]{33}|\bhf_[A-Za-z0-9]{30,}"
    r"|\bnpm_[A-Za-z0-9]{36}|pypi-AgEI[A-Za-z0-9_-]{50,}|glpat-[A-Za-z0-9_-]{20,}"
    r"|SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}|dop_v1_[a-f0-9]{64}"
    r"|https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}"
    # HashiCorp Vault, Google OAuth access and refresh tokens: a dot or slash stands early
    r"|\bhvs\.[A-Za-z0-9_-]{24,}|\bya29\.[A-Za-z0-9_-]{20,}|\b1//[A-Za-z0-9_-]{30,}"
    # user:password@ in a URL; a comma is not in one ("http://localhost:8080,admin@example.com")
    r"|(?<=://)[^\s/:@,]{0,40}:(?P<urlpw>[^\s/@,]{3,})(?=@)"
    # a licence key wherever it stands: 4 to 6 dash-joined groups of capitals and digits, at
    # least two of them mixing both. A ticket, an order number or an asset tag has one such
    # group at most (CASE-2026-1114-0001, LAPT-0042-2026-MBP1); an advisory id is named
    r"|(?<![A-Za-z0-9-])(?!GHSA-)"
    r"(?=(?:[A-Z0-9]{4,6}-){0,5}?(?=[A-Z0-9]{0,5}[A-Z])(?=[A-Z0-9]{0,5}\d)[A-Z0-9]{4,6}-"
    r"(?:[A-Z0-9]{4,6}-){0,4}?(?=[A-Z0-9]{0,5}[A-Z])(?=[A-Z0-9]{0,5}\d)[A-Z0-9]{4,6}(?![A-Za-z0-9]))"
    r"[A-Z0-9]{4,6}(?:-[A-Z0-9]{4,6}){3,5}(?![A-Za-z0-9-])"
    r"|" + _LABELLED
)


def has_secret(text: str) -> bool:
    """True when ``text`` holds something that looks like a credential."""
    return bool(_SECRET.search(text))


def redact(text: str) -> str:
    """``text`` with every credential-shaped run replaced, for indexing and for replies.
    A label stays, so "the staging password" still finds the line that held one."""
    values = {
        m.group("value") or m.group("bearer") or m.group("basic") or m.group("urlpw") or m.group(0)
        for m in _SECRET.finditer(text)
    }
    text = _SECRET.sub(lambda m: (m.group("label") or "") + "[redacted]", text)
    # the same value again, where no label or prefix marks it. One pass: a replace per value
    # took 1.4 s on a text of 16,000 different matches
    again = sorted((v for v in values if len(v) >= 8), key=len, reverse=True)
    return re.compile("|".join(map(re.escape, again))).sub("[redacted]", text) if again else text


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
        self.unread: dict[str, str] = {}  # file -> why it could not be read cleanly, for health

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
                    grows = k in ("keys", "learned", "supersedes") and k in d
                    d[k] = f"{d[k]}; {v}" if grows else v
        return out

    def learn(self, rid: str, words: str, when: date | None = None) -> None:
        """A question that missed and was then answered by record ``rid``: its words become
        search keys of that record (``learned`` in record_meta.md, apart from written keys)."""
        self._note_meta(rid, when or date.today(), {"learned": words})

    def replaced(self) -> dict[str, str]:
        """Old record id -> the id of the record that replaced it (16 characters each), from
        the ``supersedes`` fields. A record can replace several."""
        out: dict[str, str] = {}
        for new, d in self.meta().items():
            for old in d.get("supersedes", "").replace(";", " ").split():
                if old[:16] != new[:16]:
                    out[old[:16]] = new[:16]
        return out

    def retired(self) -> set[str]:
        """Ids (16 characters) of records a newer one replaced."""
        return set(self.replaced())

    def supersede(self, new: str, old: str, when: date | None = None) -> None:
        """Record that ``new`` replaces ``old``: recall then never shows the old one above it."""
        self._note_meta(new, when or date.today(), {"supersedes": old[:16]})

    def _note_meta(self, rid: str, when: date, extra: dict[str, str]) -> None:
        fields = {
            k: " ".join(str(extra[k]).replace("|", "/").split())
            for k in ("keys", "learned", "source", "mission", "supersedes")
            if extra.get(k)
        }
        if not fields:
            return
        path = self.root / META
        line = f"- {rid[:16]} | " + " | ".join(f"{k}: {v}" for k, v in fields.items())
        with self._locked(path):
            text = read_text(path, "surrogateescape") or (
                f"---\ntype: index\nowner: {self.owner}\nstatus: active\n"
                f"updated: {when.isoformat()}\n---\n# Record meta\n\n"
                "Search keys, source and mission of each record, by record id. "
                "Written by brain_remember; append-only.\n\n"
            )
            if line not in text.splitlines():
                self._save(path, text.rstrip("\n") + "\n" + line + "\n", when)

    def _sync(self) -> None:
        """Bring the record index in line with the files, as every search does first."""
        assert self.index is not None
        if not self.root.is_dir():
            # a drive that is not mounted is not an empty vault: raised before the sync
            # below, which would drop every row (and then every vector) of the files it
            # cannot see. One missing file cannot be told from a deleted one, and is read
            # as deleted
            raise FileNotFoundError(f"vault root missing: {self.root}")
        meta = self.root / META
        try:
            sig = meta.stat().st_mtime_ns if meta.exists() else 0
            if sig != self._meta_sig:  # keys changed on disk: bring the index in line
                self.index.set_keys(
                    {
                        i: "; ".join(d[k] for k in ("keys", "learned") if k in d)
                        for i, d in self.meta().items()
                        if "keys" in d or "learned" in d
                    }
                )
                self._meta_sig = sig
            self.unread.pop(META, None)
        except OSError as e:
            # the keys already loaded stay; the records are still searched
            self.unread[META] = type(e).__name__
        files = {p: k for k in _INDEXED for p in self._paths(k) if p.exists()}
        if not files and self.index.files(self.name):
            # an empty folder where the vault stood (a mount point without its drive, a folder
            # some writer made again) would drop every row and vector the same way
            raise FileNotFoundError(
                f"vault holds no file, though the index knows some: {self.root}"
            )
        self.index.sync(self.name, files, lambda k, p: self._parse(k, p, full=True))

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        if query and self.index:
            self._sync()
            return self.index.search(self.name, [kind], query, limit)
        paths = self._paths(kind)
        out: list[Record] = []
        q = (query or "").lower()
        for p in paths:
            if not p.exists():
                continue
            try:
                parsed = self._parse(kind, p)
            except OSError:
                continue  # one unreadable file is skipped (health names it), not the store
            for r in parsed:
                if not q or q in r.text.lower() or q in r.domain.lower():
                    out.append(r)
        out.sort(key=lambda r: r.date, reverse=True)
        return out[:limit]

    def _parse(self, kind: Kind, path: Path, full: bool = False) -> list[Record]:
        rel = path.relative_to(self.root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            self.unread.pop(rel, None)
        except (OSError, UnicodeDecodeError) as e:
            self.unread[rel] = (
                "not UTF-8" if isinstance(e, UnicodeDecodeError) else type(e).__name__
            )
            if isinstance(e, OSError):
                raise  # the caller skips this file and keeps the rest
            text = read_text(path)  # a stray byte costs one character, not the file
        fm = self._frontmatter(text)
        fallback = _parse_date(fm.get("updated")) or date.fromtimestamp(path.stat().st_mtime)
        return self._records(kind, text, rel, fallback, full)

    def _records(
        self, kind: Kind, text: str, rel: str, fallback: date, full: bool = False
    ) -> list[Record]:
        fm = self._frontmatter(text)
        if kind == "raw":
            return [
                Record(
                    fm.get("sha256", record_id(text)),
                    "raw",
                    fm.get("title", Path(rel).stem),
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
            fallback = _parse_date(Path(rel).stem) or fallback
        # a correction written in the decisions' heading shape is an entry too, not lost fields
        heads = {"decision": (_DECISION,), "correction": (_CORRECTION, _DECISION)}.get(kind, ())
        records: list[Record] = []
        domain = ""
        entry: dict[str, str] | None = None
        block: list[str] = []  # a run of lines in a session file that are not top-level bullets
        start = 0
        for n, line in enumerate([*text.splitlines(), ""], 1):  # the blank closes a last block
            if m := next(filter(None, (h.match(line) for h in heads)), None):
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
            if entry is not None and re.match(r"#{4,6} ", line):
                entry = None  # any other heading ends an entry, the deeper ones too
            if entry is not None and (m := _FIELD.match(line)):
                entry[m.group(1).lower()] = m.group(2)
                continue
            heading, bullet = _HEADING.match(line), _BULLET.match(line)
            if kind == "note" and domain and not heading and not bullet and line.strip():
                # a paragraph, a numbered or nested list, a quote, a table: one record per block
                if re.search(r"\w", line):  # a rule or a table's |---| row carries nothing
                    start = start if block else n
                    block.append(line.strip())
                continue
            if block:
                body = " ".join(block)
                if len(block) > 1 or not _LABEL.match(body):  # a label alone says nothing
                    records.append(
                        Record(record_id(body), kind, body, fallback, domain, rel, start)
                    )
                block = []
            if heading:
                # a field line under another heading belongs to no entry above it
                domain, entry = heading.group(2), None
            elif kind in ("fact", "pattern", "note") and bullet:
                body, d = bullet.group(1), bullet.group(2)
                undated = not d and kind != "note"  # a note's day is its file's name
                records.append(
                    Record(
                        record_id(body),
                        kind,
                        body,
                        _parse_date(d) or fallback,
                        domain,
                        rel,
                        n,
                        {"legacy": "undated"} if undated else {},
                        undated=undated,
                    )
                )
        return records

    # ── write ───────────────────────────────────────────────────────────────

    def write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        r = self._write(kind, text, domain=domain, when=when, **extra)
        if r.status in ("written", "exists") and r.id:
            try:
                # keys can be added to an old record
                self._note_meta(r.id, when or date.today(), extra)
            except OSError as e:
                # the line is filed: a meta file that cannot be written must not report it lost
                why = f"{META} not written ({type(e).__name__})"
                return replace(r, detail=f"{r.detail}; {why}" if r.detail else why)
        return r

    def _write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        if _SECRET.search(text):
            return WriteResult(self.name, "", "refused", "text looks like it contains a secret")
        # new input must be valid text: `_save` passes a lone surrogate through as a raw byte,
        # which is meant only for a stray byte the file already had
        "".join([text, domain, *map(str, extra.values())]).encode()
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
        # _parse keys these by heading: one line, never empty (a title of spaces is no title)
        title = " ".join(extra.get("title", "").split()) or " ".join(text[:60].split())
        if kind == "decision":
            body = (
                f"**Decision:** {text}\n**Reason:** {extra.get('reason', '')}\n"
                f"**Classification:** {extra.get('classification', 'reversible × low-risk')}\n"
                f"**Confidence:** {extra.get('confidence', 'medium')}\n"
            )
            return self._insert_entry(self.root / FILES[kind], kind, title, body, when)
        if kind == "correction":
            # the text is always on disk: as the error, or beside one that was passed
            said = f"- **Summary:** {text}\n" if extra.get("error", text) != text else ""
            body = (
                f"{said}- **Error:** {extra.get('error', text)}\n"
                f"- **Correction:** {extra.get('correction', '')}\n"
                f"- **Implied rule:** {extra.get('rule', '')}\n"
                f"- **Theme:** {extra.get('theme', 'execution')}\n- **Promoted:** No\n"
            )
            return self._insert_entry(self.root / FILES[kind], kind, title, body, when)
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
                read_text(path, "surrogateescape")
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
        self, path: Path, kind: Kind, title: str, body: str, when: date
    ) -> WriteResult:
        rel = path.relative_to(self.root).as_posix()
        mark = f"## {when.isoformat()} — " if kind == "decision" else f"### [{when.isoformat()}] "
        with self._locked(path):
            if not path.exists():
                self._save(path, self._new_file(kind, when, ""), when)
            old = self._parse(kind, path)
            new = _says(self._records(kind, f"{mark}{title}\n{body}", rel, when)[0])
            name, n, last = title, 1, ""
            # A title that is taken: the same entry again, or a later one with something new to
            # say. The later one is numbered, so it has an id of its own and the first keeps its.
            while same := [r for r in old if r.id == record_id(name)]:
                if any(new <= _says(r) for r in same):
                    return WriteResult(self.name, same[0].id, "exists", rel)
                n, last = n + 1, same[0].id
                name = f"{title} ({n})"
            lines = read_text(path, "surrogateescape").split("\n")
            if kind == "correction":
                after = "## Corrections"
                at = next((i for i, ln in enumerate(lines) if ln.strip() == after), None)
                anchor = (at + 1) if at is not None else len(lines)
                if at is None:
                    lines += ["", after]
                    anchor = len(lines)
            else:  # decisions: newest first, before the first existing level-2 entry
                anchor = next(
                    (i for i, ln in enumerate(lines) if ln[:3] == "## " and _DECISION.match(ln)),
                    len(lines),
                )
            lines[anchor:anchor] = ["", mark + name, *body.rstrip("\n").split("\n")]
            self._save(path, "\n".join(lines).rstrip("\n") + "\n", when)
        if last and kind == "decision":
            # a decision made again under its title replaces the one before it, so recall
            # ranks it above. A correction that recurs is another occurrence: nothing is replaced
            self.supersede(record_id(name), last, when)
        taken = f" (as '{name}': the title was taken)" if last else ""
        return WriteResult(self.name, record_id(name), "written", rel + taken)

    def _write_raw(self, body: str, when: date, meta: dict[str, str]) -> WriteResult:
        slug = re.sub(r"[^a-z0-9]+", "-", meta.get("title", "untitled").lower()).strip("-")[:60]
        sha = record_id(body)
        path = self.root / "raw" / f"{when.isoformat()}-{slug or 'untitled'}.md"
        if path.exists():  # same title, different source: raw/ is immutable, never overwrite
            path = path.with_name(f"{path.stem}-{sha[:8]}.md")
        src = meta.get("source", "")
        # only a URL names one document; a label for pasted text can come back with a new body
        url = src.startswith(("http://", "https://"))
        existing = [
            r
            for r in self.read("raw", limit=10_000)
            if r.id == sha or (url and r.extra.get("source") == src)
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
                # surrogateescape: a stray byte read from the file goes back as it was
                tmp.write_text(text, encoding="utf-8", errors="surrogateescape")
                os.replace(tmp, path)
                return
            except OSError as e:  # iCloud EDEADLK / EAGAIN: back off and retry
                if e.errno not in (11, 35) or attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))

    def _locked(self, path: Path) -> _Lock:
        if not self.root.is_dir() and self.index and self.index.files(self.name):
            # the vault is away (a drive not mounted). Making the folder again would leave an
            # empty vault there: the write fails instead, and a first-run vault is still made
            raise FileNotFoundError(f"vault root missing: {self.root}")
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
        if self.index:
            # a file that cannot be read is tried again at every sync, so a process that has
            # searched nothing yet names it too; only changed files are read
            self._sync()
        bad = ", ".join(
            f"{rel} ({why})"
            for rel, why in sorted(self.unread.items())
            if (self.root / rel).exists()
        )
        notes = sum(1 for _ in self.root.rglob("*.md"))
        return (
            True,
            f"{self.root} ({notes} notes)" + (f"; not read cleanly: {bad}" if bad else ""),
        )


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


def read_text(path: Path, errors: str = "replace") -> str:
    """A vault file as text, empty if missing; a stray non-UTF-8 byte never stops a read. A
    caller that saves the text back passes ``surrogateescape``, which keeps that byte."""
    return path.read_text(encoding="utf-8", errors=errors) if path.exists() else ""


def read_safe(path: Path) -> str:
    """A vault file for a report. One that cannot be read (a sync service evicted it, a folder
    stands in its place) reads as empty. Never for a caller that writes the text back."""
    try:
        return read_text(path)
    except OSError:
        return ""


def _says(r: Record) -> set[str]:
    """What a decision or correction states: its fields, without the ones that only file it."""
    return {" ".join(v.split()) for k, v in r.extra.items() if k not in _STATE and v.strip()}


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def knowledge_records(text: str, rel: str, when: date, cap: int | None = 600) -> list[Record]:
    """One record per `## section` of a page: title › heading: body. The text before the first
    section is a record too (title: text); for a page without `## ` sections (a plain note, a
    Claude Code memory file) that is its whole body. ``cap`` cuts the body for a whole-store
    read; the index passes None so every word is searchable."""
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
    lead: list[str] = []  # a memory file states its rule here, above the detail sections
    for n, line in enumerate(lines, 1):
        if line.startswith("## "):
            if heading:
                records.append(_knowledge_record(title, heading, body, rel, start, when, cap))
            heading, body, start = line[3:].strip(), [], n
        # a rule line is dropped, a key block's two lines are not: without them its body was
        # indexed with nothing left for the secret pattern to find it by
        elif (
            heading
            and line.strip()
            and (not line.startswith("---") or line.startswith(("-----BEGIN ", "-----END ")))
        ):
            body.append(line.strip())
        elif not heading and n > skip and line.strip() and line[0] != "#":
            lead.append(line.strip())
    if heading:
        records.append(_knowledge_record(title, heading, body, rel, start, when, cap))
    if lead:
        records.insert(0, _knowledge_record(title, "", lead, rel, 1, when, cap))
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
