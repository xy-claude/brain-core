"""One FTS5 index (bm25, stemmed) over every record a markdown store parses.

The files stay the truth. A file whose size or mtime changed is parsed again on the next
search, a file that is gone loses its rows, and dropping both tables loses nothing: the next
search rebuilds them. Stores that share this index share one bm25 scale, so their hits can be
merged by ``Record.score``.

The index holds a masked copy: a credential-shaped run in a file is stored, searched, returned
and embedded as ``[redacted]``. The file itself is never touched.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from brain_core.knowledge.rules import Raw, accepts
from brain_core.storage.db import Database
from brain_core.stores.base import Kind, Record, full_text, holds

_TERM = re.compile(r"\d{4}-\d{2}-\d{2}|[^\W_]+")
# question and filler words match most records and say nothing about which one is wanted
_STOP = frozenset(
    [
        "a",
        "about",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "should",
        "so",
        "than",
        "that",
        "the",
        "their",
        "then",
        "there",
        "this",
        "to",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)


_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
# a month's name or its usual short form, nothing longer: "mark 3" and "3 decisions" are not dates
_MON = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?:,?\s+(\d{4}))?"
_SPOKEN = re.compile(  # "august 21 2026", "nov 1st", "21 august 2026"
    rf"\b(?:{_MON}\s+{_DAY}{_YEAR}|{_DAY}\s+(?:of\s+)?{_MON}{_YEAR})\b"
)


def iso_dates(query: str, today: date | None = None) -> str:
    """A date written in words becomes the ISO date records carry ("August 21 2026" →
    "2026-08-21"). With no year it is the latest such day that is not in the future."""
    today = today or date.today()

    def fix(m: re.Match[str]) -> str:
        mon, day, year = (m[1], m[2], m[3]) if m[1] else (m[5], m[4], m[6])
        month = _MONTHS.index(mon[:3]) + 1
        try:
            d = date(int(year) if year else today.year, month, int(day))
            if not year and d > today:
                d = d.replace(year=d.year - 1)
        except ValueError:  # "may 40", 29 feb of a common year: leave the words alone
            return m[0]
        return d.isoformat()

    return _SPOKEN.sub(fix, query.lower())


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_RELATIVE = re.compile(
    r"\b(today|yesterday|(\d{1,2}) days ago|(?:last|on|this past) "
    r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b"
)


def days_asked(query: str, today: date | None = None) -> list[str]:
    """The days a question names, as ISO dates: written out ("2026-11-01", "November 1st") or
    relative to today ("yesterday", "3 days ago", "last Tuesday": the latest one before today)."""
    today = today or date.today()
    out = re.findall(r"\d{4}-\d{2}-\d{2}", iso_dates(query, today))
    for m in _RELATIVE.finditer(query.lower()):
        if m[1] == "today":
            d = today
        elif m[1] == "yesterday":
            d = today - timedelta(days=1)
        elif m[2]:
            d = today - timedelta(days=int(m[2]))
        else:
            back = (today.weekday() - _WEEKDAYS.index(m[3])) % 7 or 7
            d = today - timedelta(days=back)
        out.append(d.isoformat())
    return list(dict.fromkeys(out))


def terms(query: str) -> list[str]:
    """The words of a query that carry meaning, once each. A date stays whole."""
    return list(
        dict.fromkeys(t for t in _TERM.findall(iso_dates(query)) if len(t) > 1 and t not in _STOP)
    )


def match_query(query: str) -> str:
    """Every word as an OR term, quoted so FTS5 syntax cannot break the match
    (``"2026-11-02"`` is a phrase of its three numbers)."""
    return " OR ".join(f'"{t}"' for t in terms(query))


# Bumped when the reader or what the index stores changes: it is part of every file's stamp, so
# the next sync reads every file again. Rows come back under the same record ids, which is why
# a re-read costs no stored vector. 4 (M1b): notes and archive records take store-relative
# ids; their vectors follow with `brain index --migrate-ids`, or are made again
if TYPE_CHECKING:
    from brain_core.entities import EntityIndex
    from brain_core.journal import Journal
    from brain_core.knowledge.reconcile import ClaimIndex

# 5 (M2): each row names its source id, for the mentions. 6 (M3): every source is read once
# more, so its claim rows exist; the texts, and so the journal's ledger, are unchanged
FORMAT = 6


def _sig(st: os.stat_result) -> str:
    """A file's stamp: the index format, its modified time and its size."""
    return f"{FORMAT}:{st.st_mtime_ns}:{st.st_size}"


def _masked(r: Record) -> Record:
    """``r`` with every credential-shaped run replaced: what the index stores, returns and
    hands to the embed worker. The id stays that of the original text."""
    from brain_core.stores.vault import redact  # vault imports this module

    return replace(
        r,
        text=redact(r.text),
        domain=redact(r.domain),
        # a field's name is its label: "**Password:** value" reaches here as name and value,
        # and the value alone is not a labelled one
        extra={k: redact(f"{k}: {v}").partition(": ")[2] for k, v in r.extra.items()},
    )


def stored(doc: str, score: float = 0.0) -> Record:
    """A row of the index back as a record. ``undated`` is read off the parser's mark."""
    d = json.loads(doc)
    d["date"] = date.fromisoformat(d["date"])
    d["extra"].pop("source_id", None)  # the row's bookkeeping (M2), not the record's
    return Record(**{**d, "score": score, "undated": d["extra"].get("legacy") == "undated"})


class RecordIndex:
    def __init__(self, db: Database, journal: Journal | None = None) -> None:
        self.db = db
        self.keys: dict[str, str] = {}  # record id -> its search keys, see set_keys
        self.journal = journal  # data/journal.db (M1c): what the vault held, and when
        self.entities: EntityIndex | None = None  # set by the vault store (M2): mentions
        self.claims: ClaimIndex | None = None  # set by the vault store (M3): raw claim rows
        if journal is not None and journal.check(db):
            # brain.db is new, or saw history its journal lost: every file is read again, so
            # the journal records every version the files hold now (late, never early)
            db.execute("DELETE FROM index_files")

    def files(self, store: str) -> set[str]:
        """The files of ``store`` the index has read. An empty folder where they stood is a
        drive that is not mounted, not a store whose every file was deleted."""
        rows = self.db.fetchall("SELECT path FROM index_files WHERE store = ?", (store,))
        return {r["path"] for r in rows}

    def _keys(self, rid: str, was: str = "") -> str:
        """The keys of ``rid``, and of the id it had before M1b (``was``), if any."""
        n = len(next(iter(self.keys), ""))
        if not n:
            return ""
        # once each: after the migration the new id's keys already hold the old id's (`was:`)
        parts = (self.keys.get(rid[:n], ""), self.keys.get(was[:n], ""))
        return "; ".join(dict.fromkeys(k for p in parts for k in p.split("; ") if k))

    def under(self, store: str, folder: Path) -> bool:
        """Whether ``store`` has indexed a file under ``folder``."""
        stem = f"{folder}{os.sep}"
        return any(f.startswith(stem) for f in self.files(store))

    def set_keys(self, keys: dict[str, str]) -> None:
        """Search keys by record id (any prefix length the caller uses consistently). They are
        indexed beside the text and never returned. Only rows whose keys differ are rewritten."""
        from brain_core.stores.vault import redact  # vault imports this module

        self.keys = keys
        for row in self.db.fetchall("SELECT rowid, rid, keys, record FROM records_fts"):
            was = json.loads(row["record"]).get("extra", {}).get("was", "") if keys else ""
            new = redact(self._keys(row["rid"], was))
            if new != row["keys"]:
                self.db.execute("UPDATE records_fts SET keys = ? WHERE rowid = ?", (new, row[0]))

    def sync(
        self,
        store: str,
        files: Mapping[Path, Kind],
        parse: Callable[[Kind, Path], list[Record]],
        source: Callable[[Path], str] | None = None,
    ) -> None:
        """Bring the rows of ``store`` in line with ``files``. Only a changed file is parsed,
        and every file once after ``FORMAT`` changed. With a journal: under its lock, the
        journal records the changed files first (``source`` names each), then brain.db."""
        with self.journal.locked() if self.journal is not None else contextlib.nullcontext():
            self._sync(store, files, parse, source or (lambda p: f"{store}:{p}"))

    def _sync(
        self,
        store: str,
        files: Mapping[Path, Kind],
        parse: Callable[[Kind, Path], list[Record]],
        source: Callable[[Path], str],
    ) -> None:
        known = {
            r["path"]: r["sig"]
            for r in self.db.fetchall("SELECT path, sig FROM index_files WHERE store = ?", (store,))
        }
        seen: set[str] = set()
        changed: list[tuple[str, str, list[Record], Path]] = []
        for p, kind in files.items():
            key = str(p)
            seen.add(key)
            try:
                sig = _sig(p.stat())
                if known.get(key) == sig:
                    continue
                try:
                    before: bytes | None = hashlib.sha256(p.read_bytes()).digest()
                except OSError:
                    before = None  # the parser names an unreadable file (health), then raises
                records = [_masked(r) for r in parse(kind, p)]
                # changed while it was read: the next sync reads it whole. The bytes too, as a
                # coarse file clock (Windows) keeps the stamp of an edit of the same size
                if _sig(p.stat()) != sig or (
                    before is not None and hashlib.sha256(p.read_bytes()).digest() != before
                ):
                    continue
            except OSError:
                continue  # a file a sync service has evicted: keep the rows it has
            changed.append((key, sig, records, p))
        gone: list[str] = []
        for key in known.keys() - seen:
            try:
                os.stat(key)
            except PermissionError:
                continue  # under a folder that cannot be opened: not listed is not deleted
            except OSError:
                pass
            gone.append(key)
        seq = 0
        batch = {source(p): [(r.id, full_text(r)) for r in recs] for _k, _s, recs, p in changed}
        batch |= {source(Path(key)): [] for key in gone}
        if self.journal is not None and batch:
            # the journal first: a crash before brain.db commits leaves the old signatures, so
            # the next sync derives again, and finds its journal rows already there
            seq = self.journal.record(batch)
        raws: dict[str, list[Raw]] = {}
        if self.claims is not None:
            for _k, _s, recs, p in changed:
                if (got := self.claims.extract(source(p), recs)) is not None:
                    raws[source(p)] = got
            raws |= {source(Path(k)): [] for k in gone if accepts(source(Path(k)))}
            self.claims.history(raws)  # the derivation journal, before brain.db too (M3)
        for key, sig, records, p in changed:
            with self.db.transaction():
                self.db.execute(
                    "DELETE FROM records_fts WHERE store = ? AND path = ?", (store, key)
                )
                for r in records:
                    if r.kind == "relation":
                        continue  # journaled and mentioned, never keyword-ranked (M1a)
                    # the heading and the date are searchable; the record keeps its own text.
                    # An undated line has only its file's date, which is not a day to find it by
                    body = f"{r.domain} {full_text(r)}"
                    if not r.undated:
                        body += f" {r.date.isoformat()}"
                    row = {**asdict(r), "date": r.date.isoformat()}
                    # the source id the mentions need (M2), inside `extra`: 0.8.0 builds a
                    # Record from the row's top-level keys and knows no other
                    row["extra"] = {**row["extra"], "source_id": source(p)}
                    # 0.8.0 reads these rows too and its Record has no `undated`: the mark
                    # the parser leaves in `extra` carries it, see `stored`
                    if row.pop("undated"):
                        row["extra"] = {**row["extra"], "legacy": "undated"}
                    self.db.execute(
                        "INSERT INTO records_fts (body, keys, store, kind, path, rid, record) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            body,
                            self._keys(r.id, r.extra.get("was", "")),
                            store,
                            r.kind,
                            key,
                            r.id,
                            json.dumps(row),
                        ),
                    )
                if self.claims is not None and source(p) in raws:
                    self.claims.store(source(p), raws[source(p)])
                self.db.execute(
                    "INSERT INTO index_files (store, path, sig) VALUES (?, ?, ?) "
                    "ON CONFLICT (store, path) DO UPDATE SET sig = excluded.sig",
                    (store, key, sig),
                )
        for key in gone:
            with self.db.transaction():
                if self.claims is not None and source(Path(key)) in raws:
                    self.claims.store(source(Path(key)), [])
                self.db.execute(
                    "DELETE FROM records_fts WHERE store = ? AND path = ?", (store, key)
                )
                self.db.execute(
                    "DELETE FROM index_files WHERE store = ? AND path = ?", (store, key)
                )
        if seq:
            self.journal.mark(self.db, seq)  # type: ignore[union-attr]
        if self.entities is not None and batch:
            self.entities.update(batch)

    def cover(self, query: str, rids: Sequence[str]) -> float:
        """How much of what was asked the best of ``rids`` holds, 0 to 1. Each query word
        weighs its rarity (idf), so a record that has the common words of a question and
        lacks its one rare word scores low. Text and search keys both count."""
        words = terms(query)
        if not words or not rids:
            return 0.0
        row = self.db.fetchone("SELECT count(*) AS n FROM records_fts")
        n = row["n"] if row else 0
        marks = ",".join("?" * len(rids))
        held = dict.fromkeys(rids, 0.0)
        total = 0.0
        for w in words:
            q = f'"{w}"'
            row = self.db.fetchone(
                "SELECT count(*) AS n FROM records_fts WHERE records_fts MATCH ?", (q,)
            )
            df = row["n"] if row else 0
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            total += idf
            for r in self.db.fetchall(
                "SELECT DISTINCT rid FROM records_fts "
                f"WHERE records_fts MATCH ? AND rid IN ({marks})",
                (q, *rids),
            ):
                held[r["rid"]] += idf
        return max(held.values()) / total if total else 0.0

    def find(self, source: str) -> str:
        """The id of the record a recall result names as its ``source`` (``path:line``)."""
        path, _, line = source.rpartition(":")
        if not line.isdigit():
            path, line = source, "0"
        row = self.db.fetchone(
            "SELECT rid FROM records_fts WHERE json_extract(record, '$.path') = ? "
            "AND json_extract(record, '$.line') = ?",
            (path, int(line)),
        )
        return str(row["rid"]) if row else ""

    def get(self, rid: str) -> tuple[Record, str] | None:
        """The record whose id starts with ``rid``, with its store."""
        row = self.db.fetchone(
            "SELECT record, store FROM records_fts WHERE rid LIKE ? LIMIT 1", (rid + "%",)
        )
        if not row:
            return None
        return stored(row["record"]), row["store"]

    def redacted(self) -> int:
        """How many indexed records had a credential masked: their stored text says so."""
        row = self.db.fetchone(
            "SELECT count(DISTINCT rid) AS n FROM records_fts WHERE instr(record, '[redacted]')"
        )
        return int(row["n"]) if row else 0

    def dated(self, day: str, limit: int) -> list[tuple[Record, str]]:
        """Records dated ``day`` (ISO), with their store, in file order. A record with no date
        of its own is left out: its file's date says nothing about the day it was written."""
        out: list[tuple[Record, str]] = []
        seen: set[str] = set()
        for row in self.db.fetchall(
            "SELECT record, store, rid FROM records_fts "
            "WHERE json_extract(record, '$.date') = ? "
            "AND coalesce(json_extract(record, '$.extra.legacy'), '') != 'undated' LIMIT ?",
            (day, limit * 2),
        ):
            if row["rid"] not in seen and len(out) < limit:
                seen.add(row["rid"])
                out.append((stored(row["record"]), row["store"]))
        return out

    def holding(self, token: str, limit: int) -> list[tuple[Record, str]]:
        """Records whose text holds ``token`` exactly (lowercase), with their store. The index
        narrows by the token's words; the text itself decides."""
        q = " ".join(_TERM.findall(token))
        if not q:
            return []
        out: list[tuple[Record, str]] = []
        seen: set[str] = set()
        for row in self.db.fetchall(
            "SELECT record, store, rid FROM records_fts WHERE records_fts MATCH ? LIMIT ?",
            (f'body : "{q}"', limit * 5),
        ):
            r = stored(row["record"])
            if row["rid"] not in seen and holds(token, full_text(r)):
                seen.add(row["rid"])
                out.append((r, row["store"]))
                if len(out) >= limit:
                    break
        return out

    def search(self, store: str, kinds: Sequence[Kind], query: str, limit: int) -> list[Record]:
        """The best ``limit`` records of ``store`` for ``query``, bm25 order, score on each."""
        q = match_query(query)
        if not q or not kinds:
            return []
        marks = ",".join("?" * len(kinds))
        rows = self.db.fetchall(
            "SELECT record, bm25(records_fts) AS rank FROM records_fts "
            f"WHERE records_fts MATCH ? AND store = ? AND kind IN ({marks}) "
            "ORDER BY rank LIMIT ?",
            (q, store, *kinds, limit),
        )
        # FTS5 bm25 is negative, best first
        return [stored(row["record"], -float(row["rank"])) for row in rows]
