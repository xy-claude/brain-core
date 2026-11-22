"""The entity registry (M2). An entity is a note in ``vault/entities/``: its frontmatter holds a
UUIDv7 ``id`` written once (a rename keeps it), an ``entity_type`` from ``ontology.yaml``, and
``aliases``. brain.db derives a registry from the notes (``entities``, ``aliases``) and the
mentions of each entity in every record: a ``[[wikilink]]``, an alias in the text, a ``#tag``.
No model is asked.

Nothing is merged automatically: ``merged_into`` is written into a note by a person. A merge to
an id that does not exist, or a cycle, is refused and reported, as is an alias two entities
share (it seeds both), a note without an id and an unknown type. Names that relations use but
no note holds are proposed in the inbox, never made into notes.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from brain_core.journal import occurrence_id
from brain_core.storage.db import Database
from brain_core.stores.graph import RELATION_LINE, split_relation

if TYPE_CHECKING:
    from brain_core.stores.vault import VaultStore

_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
_TAG = re.compile(r"(?<![\w#/&])#([A-Za-z][\w/-]*)")
_FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)
_MIN_ALIAS = 3  # a shorter alias names too much in plain text; links and tags still count


def normalize_alias(text: str) -> str:
    """NFKC, casefold, whitespace collapsed: how aliases and link targets are compared."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def uuid7() -> str:
    """A time-ordered UUID (RFC 9562 version 7): 48 bits of Unix milliseconds, then random."""
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms << 80) | (0x7 << 76) | ((rand >> 62) & 0xFFF) << 64 | (0b10 << 62)
    return str(uuid.UUID(int=value | (rand & ((1 << 62) - 1))))


def ontology() -> dict[str, Any]:
    text = resources.files("brain_core").joinpath("ontology.yaml").read_text(encoding="utf-8")
    return dict(yaml.safe_load(text))


class EntityIndex:
    def __init__(self, db: Database, vault: VaultStore) -> None:
        self.db = db
        self.vault = vault
        self._sig: tuple[tuple[str, int, int], ...] | None = None
        self._problems: list[str] = []
        self._aliases: dict[str, set[str]] = {}  # normalised alias -> entity ids
        self._phrase: re.Pattern[str] | None = None

    # ── the notes ────────────────────────────────────────────────────────────

    def _notes(self) -> list[Path]:
        folder = self.vault.root / "entities"
        return sorted(folder.glob("*.md")) if folder.is_dir() else []

    def refresh(self) -> bool:
        """Read the entity notes again when any changed; then every mention is found again.
        Returns whether the registry changed."""
        notes = self._notes()
        sig = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in notes)
        if sig == self._sig:
            return False
        self._sig = sig
        types = set(ontology()["entity_types"])
        problems: list[str] = []
        found: list[dict[str, Any]] = []
        for p in notes:
            rel = p.relative_to(self.vault.root).as_posix()
            text = p.read_text(encoding="utf-8", errors="replace")
            m = _FRONT.match(text)
            try:
                fm = yaml.safe_load(m.group(1)) if m else {}
            except yaml.YAMLError:
                fm = None
            if not isinstance(fm, dict) or not fm.get("id"):
                problems.append(f"{rel}: no `id` in its frontmatter, so it is no entity yet")
                continue
            try:
                uuid.UUID(str(fm["id"]))
            except ValueError:
                problems.append(f"{rel}: `id` {fm['id']!r} is not a UUID")
                continue
            if fm.get("entity_type") not in types:
                problems.append(
                    f"{rel}: entity_type {fm.get('entity_type')!r} is not in ontology.yaml "
                    f"({', '.join(sorted(types))})"
                )
                continue
            title = next(
                (ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), p.stem
            )
            raw = fm.get("aliases") or []
            aliases = [raw] if isinstance(raw, str) else [str(a) for a in raw]
            found.append(
                {
                    "id": str(fm["id"]),
                    "type": fm["entity_type"],
                    "name": title,
                    "source_id": f"vault:{rel}",
                    "merged_into": str(fm["merged_into"]) if fm.get("merged_into") else None,
                    "ontology": int(fm.get("ontology", 1)),
                    "aliases": {normalize_alias(a) for a in [title, p.stem, *aliases] if a.strip()},
                }
            )
        ids = Counter(e["id"] for e in found)
        for eid, n in ids.items():
            if n > 1:
                problems.append(f"{n} notes share the id {eid}: only the first is registered")
        seen: set[str] = set()
        entities = []
        for e in found:
            if e["id"] not in seen:
                seen.add(e["id"])
                entities.append(e)
        merges = self._merges(entities, problems)
        with self.db.transaction():
            self.db.execute("DELETE FROM entities")  # aliases and mentions go with them
            for e in entities:
                self.db.execute(
                    "INSERT INTO entities (id, type, name, source_id, merged_into, ontology) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        e["id"],
                        e["type"],
                        e["name"],
                        e["source_id"],
                        merges.get(e["id"]),
                        e["ontology"],
                    ),
                )
                self.db.executemany(
                    "INSERT OR IGNORE INTO aliases VALUES (?, ?)",
                    [(a, e["id"]) for a in e["aliases"]],
                )
        self._aliases = defaultdict(set)
        for e in entities:
            for a in e["aliases"]:
                self._aliases[a].add(e["id"])
        for a, owners in sorted(self._aliases.items()):
            if len(owners) > 1:
                problems.append(f"alias {a!r} is shared by {len(owners)} entities: it names each")
        long = sorted((a for a in self._aliases if len(a) >= _MIN_ALIAS), key=len, reverse=True)
        self._phrase = (
            re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, long)) + r")(?![\w-])")
            if long
            else None
        )
        self._problems = problems
        self._recompute()
        return True

    @staticmethod
    def _merges(entities: list[dict[str, Any]], problems: list[str]) -> dict[str, str]:
        """``merged_into`` links that hold: to an existing id, with no cycle."""
        names = {e["id"]: e["source_id"].removeprefix("vault:") for e in entities}
        links = {e["id"]: e["merged_into"] for e in entities if e["merged_into"]}
        ok: dict[str, str] = {}
        for src, dst in links.items():
            if dst not in names:
                problems.append(f"{names[src]}: merged_into {dst} names no entity; refused")
                continue
            seen, cur = {src}, dst
            while cur in links and cur not in seen:
                seen.add(cur)
                cur = links[cur]
            if cur in seen:
                problems.append(f"{names[src]}: merged_into makes a cycle; refused")
                continue
            ok[src] = dst
        return ok

    def resolve(self, entity_id: str) -> str:
        """The entity an id stands for now, following merges."""
        seen = {entity_id}
        cur = entity_id
        while True:
            row = self.db.fetchone("SELECT merged_into FROM entities WHERE id = ?", (cur,))
            nxt = row[0] if row else None
            if not nxt or nxt in seen:
                return cur
            seen.add(nxt)
            cur = nxt

    def lookup(self, name: str) -> set[str]:
        """The entities a name or alias names."""
        self.refresh()
        return set(self._aliases.get(normalize_alias(name), set()))

    def problems(self) -> list[str]:
        self.refresh()
        return list(self._problems)

    # ── mentions ─────────────────────────────────────────────────────────────

    def _found(self, source: str, text: str) -> set[tuple[str, str]]:
        """(entity id, how) for one record's text."""
        out: set[tuple[str, str]] = set()
        if source == "vault:relations.md" and (parts := split_relation(text, {})):
            for name in (parts[0], parts[2]):
                out |= {(e, "wikilink") for e in self._aliases.get(normalize_alias(name), ())}
            return out
        for m in _WIKILINK.finditer(text):
            out |= {(e, "wikilink") for e in self._aliases.get(normalize_alias(m.group(1)), ())}
        for m in _TAG.finditer(text):
            out |= {(e, "tag") for e in self._aliases.get(normalize_alias(m.group(1)), ())}
        if self._phrase is not None:
            plain = normalize_alias(_TAG.sub(" ", _WIKILINK.sub(" ", text)))
            for m in self._phrase.finditer(plain):
                out |= {(e, "alias") for e in self._aliases.get(m.group(1), ())}
        return out

    def update(self, batch: Mapping[str, Sequence[tuple[str, str]]]) -> None:
        """The mentions of the changed sources, found again. ``batch`` as the journal takes it:
        source id -> (record id, text) in file order; an empty list is a source that is gone."""
        if not self._aliases and not self._sig:
            self.refresh()
        rows = []
        for source, recs in batch.items():
            seen: Counter[str] = Counter()
            for rid, text in recs:
                seen[rid] += 1
                occ = occurrence_id(source, rid, seen[rid])
                rows += [
                    (occ, source, rid, seen[rid], e, how) for e, how in self._found(source, text)
                ]
        with self.db.transaction():
            for source in batch:
                self.db.execute("DELETE FROM mentions WHERE source_id = ?", (source,))
            self.db.executemany("INSERT OR IGNORE INTO mentions VALUES (?, ?, ?, ?, ?, ?)", rows)

    def _recompute(self) -> None:
        """Every mention again, from the index and relations.md (the aliases changed)."""
        batch: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for row in self.db.fetchall("SELECT rid, record FROM records_fts ORDER BY rowid"):
            rec = json.loads(row["record"])
            if source := (rec.get("extra") or {}).get("source_id"):
                batch[source].append((row["rid"], _text(rec)))
        rel = self.vault.root / "relations.md"
        if rel.exists():
            for ln in rel.read_text(encoding="utf-8", errors="replace").splitlines():
                if m := RELATION_LINE.match(ln):
                    from brain_core.stores.base import record_id
                    from brain_core.stores.graph import relation_text

                    text = relation_text(*m.groups()[:3])
                    batch["vault:relations.md"].append((record_id(text), text))
        self.db.execute("DELETE FROM mentions")
        self.update(batch)

    # ── proposals ────────────────────────────────────────────────────────────

    def propose(self, inbox: Path) -> int:
        """Stage, in the inbox, the names relations use that no entity note holds. Never
        writes a note: a person, or the agent on a person's word, makes each one."""
        self.refresh()
        names: Counter[str] = Counter()
        rel = self.vault.root / "relations.md"  # the truth, not the mirror (M1a)
        lines = (
            rel.read_text(encoding="utf-8", errors="replace").splitlines() if rel.exists() else []
        )
        for ln in lines:
            if m := RELATION_LINE.match(ln):
                for name in (m.group(1), m.group(3)):
                    if not self._aliases.get(normalize_alias(name)):
                        names[name] += 1
        day = date.today().isoformat()
        staged = [
            f"- [ ] [[{n}]] — proposed entity: named by {c} relation(s) ({day})"
            for n, c in sorted(names.items(), key=lambda x: (-x[1], x[0].casefold()))
        ]
        return self.vault.append_section(inbox, "Entity proposals", staged, key=_proposed)


def _proposed(line: str) -> str:
    """What makes two proposal lines the same: the name, not the date or the count."""
    m = _WIKILINK.search(line)
    return normalize_alias(m.group(1)) if m else line


def _text(rec: dict[str, Any]) -> str:
    extra = rec.get("extra") or {}
    if rec.get("kind") in ("decision", "correction"):
        body = " ".join(str(v) for k, v in extra.items() if k not in ("title", "context") and v)
        return f"{rec['text']} — {body}" if body else str(rec["text"])
    return str(rec["text"])
