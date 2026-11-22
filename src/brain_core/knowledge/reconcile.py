"""The claims tier in brain.db (M3, audit G.2): raw rows per source, and the claims computed
from them.

Per sync, for each changed source: the raw rows its rules give go to the journal's
derivation history first, then to ``claim_raw`` in the same brain.db transaction as the
source's records, which marks the tier dirty. Whoever reads claims next recomputes the whole
computed tier from the raw rows (a pure function: ``derive``), so a sync with no change costs
nothing. ``known_at`` derives from the rows the journal says existed then; ``check`` derives
afresh and compares (``brain index --check``).
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from brain_core.entities import normalize_alias, ontology
from brain_core.journal import Journal
from brain_core.knowledge import rules
from brain_core.knowledge.derive import build_periods, canonical, derive
from brain_core.knowledge.model import (
    Claim,
    ClaimKey,
    Conflict,
    Evidence,
    Lifecycle,
    Link,
    Occurrence,
    Redirect,
    Review,
)
from brain_core.knowledge.rules import META, REFLECTIONS, REVIEWS, Raw
from brain_core.storage.db import Database
from brain_core.stores.vault import redact

if TYPE_CHECKING:
    from brain_core.stores.base import Record
    from brain_core.stores.vault import VaultStore

_RANK = {Lifecycle.ACCEPTED: 0, Lifecycle.CANDIDATE: 1, Lifecycle.REJECTED: 2}
# Bumped when a rule of the computed tier changes, so a tier an older version computed is
# computed again. 2 (0.17.0): a reflection with parents stays a candidate
RULES = 2
_TABLES = (
    "claims",
    "claim_periods",
    "claim_conflicts",
    "claim_evidence",
    "identity_redirects",
    "record_times",
    "record_links",
    "claim_reviews",
)


def _day(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _iso(d: date | datetime | None) -> str | None:
    if isinstance(d, datetime):
        return Journal.stamp(d)
    return d.isoformat() if d else None


def _chain(x: str | None, merged: Mapping[str, str]) -> list[str | None]:
    out = [x]
    while x is not None and x in merged and merged[x] not in out:
        x = merged[x]
        out.append(x)
    return out


def _steps(raw: ClaimKey, merged: Mapping[str, str], renames: Mapping[str, str]) -> list[ClaimKey]:
    """Every key between the one written and its canonical form: each subject, object and
    predicate along its chain. Short: a name, its note, the note it was merged into."""
    preds = [raw.predicate] + ([renames[raw.predicate]] if raw.predicate in renames else [])
    return [
        ClaimKey(
            subject=str(s), predicate=p, role=raw.role, object_entity=o,
            object_literal=raw.object_literal, datatype=raw.datatype,
        )
        for s in _chain(raw.subject, merged)
        for o in _chain(raw.object_entity, merged)
        for p in preds
    ]  # fmt: skip


class ClaimIndex:
    def __init__(self, db: Database, journal: Journal, vault: VaultStore) -> None:
        self.db = db
        self.journal = journal
        self.vault = vault
        self.unread: dict[str, str] = {}  # meta / review file -> why it could not be read

    # ── raw rows, per source ─────────────────────────────────────────────────

    @staticmethod
    def extract(source: str, records: Sequence[Record]) -> list[Raw] | None:
        """The raw rows of one source, or None for a source no rule reads."""
        return rules.evidence(source, records) if rules.accepts(source) else None

    def history(self, raws: Mapping[str, Sequence[Raw]]) -> None:
        """The derivation journal first: before brain.db, like the ledger."""
        self.journal.version({s: [r[:3] for r in rows] for s, rows in raws.items()})

    def store(self, source: str, rows: Sequence[Raw]) -> None:
        """Replace a source's raw rows; called inside the brain.db transaction of its file."""
        have = {
            (r["kind"], r["row_key"]): (r["row_json"], r["line"])
            for r in self.db.fetchall(
                "SELECT kind, row_key, row_json, line FROM claim_raw WHERE source_id = ?",
                (source,),
            )
        }
        new = {(k, rk): (rj, ln) for k, rk, rj, ln in rows}
        if have == new:
            return
        self.db.execute("DELETE FROM claim_raw WHERE source_id = ?", (source,))
        self.db.executemany(
            "INSERT OR REPLACE INTO claim_raw (kind, row_key, source_id, row_json, line) "
            "VALUES (?, ?, ?, ?, ?)",
            [(k, rk, source, rj, ln) for k, rk, rj, ln in rows],
        )
        self.mark_dirty()

    def mark_dirty(self) -> None:
        self.db.execute("UPDATE claims_state SET dirty = 1 WHERE id = 1")

    def refresh(self) -> None:
        """record_meta.md and claim_reviews.md: their lines are occurrences in the ledger (a
        review is ordered by its line's ledger time), and their rows raw rows like any other."""
        for source, name in (
            (META, "record_meta.md"),
            (REVIEWS, "claim_reviews.md"),
            (REFLECTIONS, "knowledge/_reflections.md"),
        ):
            path = self.vault.root / name
            try:
                st = path.stat() if path.exists() else None
                sig = f"{st.st_mtime_ns}:{st.st_size}" if st else ""
                row = self.db.fetchone(
                    "SELECT sig FROM index_files WHERE store = 'claims' AND path = ?", (source,)
                )
                if row is not None and str(row[0]).rpartition(":")[0] == sig:
                    continue  # the file's stamp is the one its rows were read at
                text = path.read_text(encoding="utf-8", errors="replace") if st else ""
                # masked as the index masks a record: these lines reach raw rows, the journal
                # (never rebuilt) and replies, and a hand-written line can hold a credential
                text = redact(text)
                self.unread.pop(name, None)
            except OSError as e:
                self.unread[name] = type(e).__name__  # its rows stay as they were
                continue
            lines = [ln for _n, ln in rules.wanted(source, text)]
            digest = hashlib.sha256(json.dumps(lines).encode()).hexdigest()[:16]
            sig = f"{sig}:{digest}"
            if row is not None and str(row[0]).rpartition(":")[2] == digest:
                # a save that added search keys only: no line that times or links a record
                # changed, so the journal has nothing to record
                self.db.execute(
                    "UPDATE index_files SET sig = ? WHERE store = 'claims' AND path = ?",
                    (sig, source),
                )
                continue
            if source == META:
                rows = rules.meta(text)
            elif source == REFLECTIONS:
                rows = rules.reflections(text)
            else:
                rows, bad = rules.reviews(text)
                if bad:
                    self.unread[name] = "; ".join(bad[:3])
            with self.journal.locked():
                seq = self.journal.record({source: rules.ledger_lines(source, text)})
                self.history({source: rows})
                with self.db.transaction():
                    self.store(source, rows)
                    self.db.execute(
                        "INSERT INTO index_files (store, path, sig) VALUES ('claims', ?, ?) "
                        "ON CONFLICT (store, path) DO UPDATE SET sig = excluded.sig",
                        (source, sig),
                    )
                self.journal.mark(self.db, seq)

    # ── the computed tier ───────────────────────────────────────────────────

    def _now(self) -> str:
        return Journal.stamp(self.journal.clock())  # the ledger's own clock

    def _inputs(self) -> str:
        """What resolves names and keys besides the raw rows: the entity registry (a note
        added, an alias, a merge) and the ontology (a rename). A change re-keys claims."""
        if self.vault.entities is not None:
            self.vault.entities.refresh()
        rows = [
            tuple(r)
            for q in (
                "SELECT id, merged_into FROM entities ORDER BY id",
                "SELECT alias, entity_id FROM aliases ORDER BY alias, entity_id",
            )
            for r in self.db.fetchall(q)
        ]
        blob = json.dumps([rows, ontology(), RULES], sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _stale(self) -> bool:
        row = self.db.fetchone("SELECT dirty, inputs FROM claims_state WHERE id = 1")
        return row is not None and bool(row[0] or row[1] != self._inputs())

    def settle(self) -> None:
        """Recompute the claims if a raw row, an entity or the ontology changed since."""
        if self._stale():
            self.recompute(only_if_stale=True)

    def _raws(self) -> tuple[list[tuple[str, str, str]], dict[tuple[str, str], int]]:
        rows = self.db.fetchall("SELECT kind, row_key, row_json, line FROM claim_raw")
        return (
            [(r["kind"], r["row_key"], r["row_json"]) for r in rows],
            {(r["kind"], r["row_key"]): r["line"] for r in rows},
        )

    def recompute(self, only_if_stale: bool = False) -> None:
        """Under the journal's lock, which every writer of raw rows holds: two servers that
        both found the tier stale compute it one after the other, never at once."""
        with self.journal.locked():
            if only_if_stale and not self._stale():
                return  # another process did it while this one waited
            raws, lines = self._raws()
            out = self._rows(*self._compute(raws, self._now(), lines))
            inputs = self._inputs()
            with self.db.transaction():  # starts with a write: no stale read to upgrade
                self._write(out, inputs)

    def _write(self, out: dict[str, Any], inputs: str) -> None:
        for t in _TABLES:
            self.db.execute(f"DELETE FROM {t}")
        for t in _TABLES:
            if out[t]:
                marks = ",".join("?" * len(out[t][0]))
                self.db.executemany(f"INSERT INTO {t} VALUES ({marks})", out[t])
        self.db.execute(
            "UPDATE entities SET degree = (SELECT count(*) FROM claims c WHERE "
            "c.lifecycle <> 'rejected' AND (c.subject = entities.id OR "
            "c.object_entity = entities.id))"
        )
        self.db.execute(
            "UPDATE claims_state SET dirty = 0, report = ?, inputs = ? WHERE id = 1",
            (json.dumps(out["report"]), inputs),
        )

    def _compute(
        self,
        raws: Sequence[tuple[str, str, str]],
        until: str,
        lines: Mapping[tuple[str, str], int] | None = None,
    ) -> tuple[dict[str, Claim], list[Redirect], list[str], dict[str, list[dict[str, Any]]]]:
        """Claims from raw rows, with recording times from the ledger as they were at
        ``until``. Also returns the raw rows by kind, for the tables that show them."""
        onto = ontology()
        preds: dict[str, dict[str, Any]] = onto.get("predicates") or {}
        ents = self.vault.entities
        aliases = ents.alias_map() if ents is not None else {}
        merged = ents.merges() if ents is not None else {}
        report: list[str] = []
        by: dict[str, list[dict[str, Any]]] = defaultdict(list)
        keys: dict[str, tuple[str, str]] = {}
        for kind, rk, rj in raws:
            d = json.loads(rj)
            d["_line"] = (lines or {}).get((kind, rk), 0)
            by[kind].append(d)
            keys[rk] = (kind, rk)

        # a name is a placeholder entity, `name:<alias>`, merged into the note that holds the
        # alias: a note made later re-keys its claims like a merge, old ids redirected (F.5)
        merged = {
            **{f"name:{a}": next(iter(ids)) for a, ids in aliases.items() if len(ids) == 1},
            **merged,
        }

        def resolve(name: str) -> str:
            if name.startswith("record:"):
                return name  # a decision record is the subject of what it selects
            alias = normalize_alias(name)
            if len(aliases.get(alias, ())) > 1:
                report.append(f"ambiguous_name {name!r}: several entities hold it; kept a name")
            return f"name:{alias}"

        def key_of(d: dict[str, Any]) -> ClaimKey:
            lit = d.get("object_literal")
            datatype = (preds.get(d["predicate"]) or {}).get("datatype", "text")
            return ClaimKey(
                subject=resolve(d["subject_name"]),
                predicate=d["predicate"],
                role=d["role"],
                object_entity=None if lit is not None else resolve(d["object_name"]),
                object_literal=lit,
                datatype=datatype if lit is not None else None,
            )

        def seen(occ: str, h: str) -> tuple[str, str] | None:
            got = self.journal.first_seen(occ, h)
            return got if got is not None and got[0] <= until else None

        rec_times: dict[str, dict[str, Any]] = {}
        occ_times: dict[tuple[str, str, int], dict[str, Any]] = {}
        for t in by["time"]:
            if t["occ_scope"]:
                src, _, k = t["occ_scope"].rpartition("#")
                occ_times[(t["rid"], src, int(k))] = t
            else:
                rec_times[t["rid"]] = t
        copies: dict[tuple[str, str], int] = defaultdict(int)
        for d in by["evidence"]:
            at = (d["record_id"][:16], d["source_id"])
            copies[at] = max(copies[at], d["ordinal"])
        for rid, src, k in occ_times:
            if k > copies.get((rid, src), 0):
                report.append(f"occurrence_meta_dangling {rid[:8]}@{src}#{k}: no such copy")

        def times(d: dict[str, Any]) -> dict[str, Any]:
            got = {
                "valid_from": d["valid_from"],
                "valid_to": None,
                "event_date": d["event_date"],
                "timeless": False,
            }
            rid = d["record_id"][:16]
            scoped = occ_times.get((rid, d["source_id"], d["ordinal"]))
            if scoped is not None:
                line = seen(scoped["line_occ"], scoped["line_hash"])
                if line is None or self.journal.copies_changed_since(
                    d["source_id"], d["record_id"], line[0], until
                ):
                    report.append(
                        f"occurrence_meta_ambiguous {rid[:8]}@{d['source_id']}#{d['ordinal']}: "
                        "copies changed since the line was written; the record's meta applies"
                    )
                    scoped = None
            for t in (rec_times.get(rid), scoped):  # the copy's own line over the record's
                if t is None:
                    continue
                if t["timeless"]:
                    got.update(timeless=True, valid_from=None)
                if t["valid_from"]:
                    got.update(valid_from=t["valid_from"], timeless=False)
                for f in ("valid_to", "event_date"):
                    if t[f]:
                        got[f] = t[f]
            return got

        # A reflection must name the claims it rests on; even then it is never evidence
        # enough: a parent that exists need not support the conclusion. It stays a candidate
        # until the relation is stated on its own (relations.md), which a person does
        held_ids = {
            canonical(key_of(d), merged, onto.get("renames") or {}).id()
            for d in by["evidence"]
            if d["origin"] != "reflection"
        }
        rows: list[tuple[ClaimKey, Evidence]] = []
        for d in by["evidence"]:
            if d["origin"] == "reflection":
                parents = d.get("parents") or []
                if not (parents and all(any(h.startswith(p) for h in held_ids) for p in parents)):
                    report.append(
                        f"reflection_unparented {d['subject_name']} —{d['predicate']}→ "
                        f"{d['object_name']}: names no claim held; stays a candidate"
                    )
            if d.get("bad_date"):
                report.append(
                    f"invalid_date {d['source_id']}: {d['bad_date']!r} is no day; read as undated"
                )
            occ = Occurrence(
                source_id=d["source_id"], record_id=d["record_id"], ordinal=d["ordinal"]
            )
            first = seen(occ.id(), d["content_hash"])
            if first is None:
                continue  # not in the ledger yet (or not by `until`): not known then
            base = {
                "occurrence": occ,
                "rule": d["rule"],
                "line": d["_line"],
                "content_hash": d["content_hash"],
                "subject_name": d["subject_name"],
                "object_name": d["object_name"],
                "stated_date": _day(d["stated_date"]),
                "recorded_at": datetime.fromisoformat(first[0].replace("Z", "+00:00")),
                "recorded_by": first[1],
                "origin": d["origin"] or ("agent" if first[1] == "write" else "user"),
                "verification": d["verification"],
                "quote": d["quote"],
            }
            t = times(d)
            try:
                try:
                    ev = Evidence(
                        **base,
                        event_date=_day(t["event_date"]),
                        valid_from=_day(t["valid_from"]),
                        valid_to=_day(t["valid_to"]),
                        timeless=t["timeless"],
                    )
                except ValueError:
                    report.append(
                        f"meta_invalid {d['record_id'][:8]}: its valid / until / always disagree"
                    )
                    ev = Evidence(
                        **base, event_date=_day(d["event_date"]), valid_from=_day(d["valid_from"])
                    )
                rows.append((key_of(d), ev))
            except ValueError as bad:  # one bad row never takes the others down
                report.append(f"evidence_invalid {d['source_id']}: {str(bad).splitlines()[0]}")
        starts: dict[str, date] = {}
        for _k, e in rows:
            s = e.start()[0]
            rid = e.occurrence.record_id[:16]
            if s is not None and (rid not in starts or s < starts[rid]):
                starts[rid] = s
        links: list[Link] = []
        for ln in by["link"]:
            if ln["kind"] != "supersedes" or seen(ln["line_occ"], ln["line_hash"]) is None:
                continue
            start = starts.get(ln["new_rid"]) or self._record_day(ln["new_rid"])
            if start is not None:
                links.append((ln["old_rid"], ln["new_rid"], start))
        reviews: list[Review] = []
        review_rows: list[tuple[Any, ...]] = []
        renames: dict[str, str] = onto.get("renames") or {}
        for r in by["review"]:
            line = seen(r["line_occ"], r["line_hash"])
            if line is None:
                continue
            rv = Review(
                action=r["action"],
                key=key_of(r["key"]),
                other=key_of(r["other"]) if r["other"] else None,
                recorded_at=datetime.fromisoformat(line[0].replace("Z", "+00:00")),
                reason=r["reason"],
            )
            reviews.append(rv)
            review_rows.append((
                r["line_occ"], rv.action, rules._dump(r["key"]),
                rules._dump(r["other"]) if r["other"] else None,
                canonical(rv.key, merged, renames).id(),
                canonical(rv.other, merged, renames).id() if rv.other else None,
                line[0], rv.reason or None,
            ))  # fmt: skip

        def functional(k: ClaimKey) -> bool:
            f = (preds.get(k.predicate) or {}).get("functional")
            return f is True or (f == "per_role" and bool(k.role))

        claims, redirects, rep = derive(rows, links, reviews, merged, renames, functional)
        # every id a claim had on the way: a name before its note, the note before a merge, the
        # predicate before a rename. derive() maps the key as written; these are the steps
        known = {r.old_id for r in redirects}
        for c in claims.values():
            raw_keys = {key for key, e in rows if canonical(key, merged, renames).id() == c.id}
            for raw in raw_keys:
                for step in _steps(raw, merged, renames):
                    if step.id() != c.id and step.id() not in known and step.id() not in claims:
                        known.add(step.id())
                        c.aliases = c.aliases | {step.id()}
                        moved = (step.subject, step.object_entity) != (
                            c.key.subject,
                            c.key.object_entity,
                        )
                        renamed = step.predicate != c.key.predicate
                        cause = (
                            "merge+rename" if moved and renamed else "merge" if moved else "rename"
                        )
                        redirects.append(
                            Redirect(kind="claim", old_id=step.id(), new_id=c.id, cause=cause)  # type: ignore[arg-type]
                        )
        for old in sorted(o for o in merged if not o.startswith("name:")):
            new = old
            seen_ids = {old}
            while new in merged and merged[new] not in seen_ids:
                new = merged[new]
                seen_ids.add(new)
            redirects.append(Redirect(kind="entity", old_id=old, new_id=new, cause="merge"))
        for ln in by["link"]:
            if ln["kind"] == "was" and ln["old_rid"] != ln["new_rid"]:
                redirects.append(
                    Redirect(
                        kind="record", old_id=ln["old_rid"], new_id=ln["new_rid"], cause="id-scheme"
                    )
                )
        by["_review_rows"] = review_rows  # type: ignore[assignment]
        return claims, redirects, report + rep, by

    def _record_day(self, rid16: str) -> date | None:
        """The stated day of a record that supersedes another but asserts no claim."""
        row = self.db.fetchone(
            "SELECT record FROM records_fts WHERE substr(rid, 1, 16) = ? LIMIT 1", (rid16,)
        )
        if row is None:
            return None
        rec = json.loads(row[0])
        if (rec.get("extra") or {}).get("legacy") == "undated" or rec.get("undated"):
            return None
        return _day(rec.get("date"))

    def _rows(
        self,
        claims: dict[str, Claim],
        redirects: list[Redirect],
        report: list[str],
        by: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Every row of the computed tables, in insertion order: what recompute writes and
        what check compares."""
        out: dict[str, Any] = {t: [] for t in _TABLES}
        for c in sorted(claims.values(), key=lambda c: c.id):
            k = c.key
            out["claims"].append((
                c.id, k.subject, k.predicate, k.role, k.object_entity, k.object_literal,
                k.datatype, c.lifecycle.value, c.verification.value, c.confidence,
                _iso(c.retracted_at), _RANK[c.lifecycle],
            ))  # fmt: skip
            for seq, p in enumerate(c.periods):
                out["claim_periods"].append((
                    c.id, seq, _iso(p.true_from), _iso(p.true_to), _iso(p.link_end),
                    int(p.timeless), int(p.undated), int(p.stated), int(p.disputed),
                ))  # fmt: skip
            seqs: dict[str, int] = defaultdict(int)
            for x in c.conflicts:
                if c.id < x.other:  # one row per pair and window, the smaller id first
                    out["claim_conflicts"].append((
                        c.id, x.other, seqs[x.other], x.kind, x.scope, _iso(x.overlap_from),
                        _iso(x.overlap_to), int(x.acknowledged),
                    ))  # fmt: skip
                    seqs[x.other] += 1
            for e in c.evidence:
                o = e.occurrence
                out["claim_evidence"].append((
                    c.id, o.id(), o.source_id, o.record_id, o.ordinal, e.rule, e.line,
                    e.content_hash, e.subject_name, e.object_name, _iso(e.stated_date),
                    _iso(e.event_date), _iso(e.valid_from), _iso(e.valid_to), int(e.timeless),
                    _iso(e.recorded_at), e.recorded_by, e.origin.value, e.verification.value,
                    e.confidence, e.quote,
                ))  # fmt: skip
        out["identity_redirects"] = sorted(
            {(r.kind, r.old_id, r.new_id, r.cause) for r in redirects}
        )
        for t in by["time"]:
            out["record_times"].append((
                t["rid"], t["occ_scope"], t["valid_from"], t["valid_to"], t["event_date"],
                int(t["timeless"]), t["line_occ"],
            ))  # fmt: skip
        for ln in by["link"]:
            out["record_links"].append((ln["new_rid"], ln["old_rid"], ln["kind"], ln["line_occ"]))
        out["claim_reviews"] = list(by["_review_rows"])
        for table in _TABLES:
            out[table].sort(key=lambda row: tuple("" if v is None else str(v) for v in row))
        out["report"] = sorted(set(report))
        return out

    # ── reading ──────────────────────────────────────────────────────────────

    def current(self) -> dict[str, Claim]:
        """The claims brain-core holds now, with their evidence, periods and conflicts."""
        self.settle()
        raws, lines = self._raws()
        return self._compute(raws, self._now(), lines)[0]

    def load(self, ids: Sequence[str]) -> dict[str, Claim]:
        """These claims as brain.db holds them, without deriving the rest: what recall
        needs for the few a walk reached. Periods are split again from the stored evidence
        at the stored link ends, which is exactly how they were split."""
        out: dict[str, Claim] = {}
        for cid in dict.fromkeys(ids):
            row = self.db.fetchone("SELECT * FROM claims WHERE id = ?", (cid,))
            if row is None:
                continue
            evs = [
                Evidence(
                    occurrence=Occurrence(
                        source_id=e["source_id"], record_id=e["record_id"], ordinal=e["ordinal"]
                    ),
                    rule=e["rule"],
                    line=e["line"],
                    content_hash=e["content_hash"],
                    subject_name=e["subject_name"],
                    object_name=e["object_name"],
                    stated_date=_day(e["stated_date"]),
                    event_date=_day(e["event_date"]),
                    valid_from=_day(e["valid_from"]),
                    valid_to=_day(e["valid_to"]),
                    timeless=bool(e["timeless"]),
                    recorded_at=datetime.fromisoformat(e["recorded_at"].replace("Z", "+00:00")),
                    recorded_by=e["recorded_by"],
                    origin=e["origin"],
                    verification=e["verification"],
                    confidence=e["confidence"],
                    quote=e["quote"],
                )
                for e in self.db.fetchall(
                    "SELECT * FROM claim_evidence WHERE claim_id = ? ORDER BY occ_id, rule", (cid,)
                )
            ]
            ends = [
                d
                for (x,) in self.db.fetchall(
                    "SELECT link_end FROM claim_periods WHERE claim_id = ? AND link_end IS NOT "
                    "NULL",
                    (cid,),
                )
                if (d := _day(x))
            ]
            conflicts = [
                Conflict(
                    other=r["claim_b"] if r["claim_a"] == cid else r["claim_a"],
                    kind=r["kind"],
                    scope=r["scope"],
                    overlap_from=_day(r["overlap_from"]),
                    overlap_to=_day(r["overlap_to"]),
                    acknowledged=bool(r["acknowledged"]),
                )
                for r in self.db.fetchall(
                    "SELECT * FROM claim_conflicts WHERE claim_a = ? OR claim_b = ? ORDER BY seq",
                    (cid, cid),
                )
            ]
            if not evs:
                continue
            out[cid] = Claim(
                id=cid,
                key=ClaimKey(
                    subject=row["subject"],
                    predicate=row["predicate"],
                    role=row["role"],
                    object_entity=row["object_entity"],
                    object_literal=row["object_literal"],
                    datatype=row["datatype"],
                ),
                lifecycle=row["lifecycle"],
                verification=row["verification"],
                origins=frozenset(e.origin for e in evs),
                confidence=row["confidence"],
                evidence=evs,
                periods=build_periods(evs, ends),
                conflicts=conflicts,
                retracted_at=(
                    datetime.fromisoformat(row["retracted_at"].replace("Z", "+00:00"))
                    if row["retracted_at"]
                    else None
                ),
            )
        return out

    def known_at(self, when: datetime) -> dict[str, Claim] | None:
        """What brain-core held at ``when`` (transaction time), from the journal alone: the raw
        rows that existed then, derived again. None (unknown) before the derivation journal
        began or inside a ledger gap: an empty answer would claim nothing was known.

        The evidence is that of ``when``; the identities are today's. Entity notes and the
        ontology have no history in the journal, so a merge or rename made after ``when``
        applies to it. This is the evidence of a past moment, not a full snapshot of it."""
        at = Journal.stamp(when)
        started = self.journal.derivation_started()
        if started is None or at < started or self.journal.in_gap(at):
            return None
        return self._compute(self.journal.versions(at), at)[0]

    def check(self) -> list[str]:
        """``brain index --check``: the raw rows against the journal's open versions, and every
        computed table against a fresh derivation. Empty when both agree."""
        self.settle()
        out: list[str] = []
        raws, lines = self._raws()
        mine, theirs = set(raws), set(self.journal.versions())
        if mine != theirs:
            out.append(
                f"raw rows: {len(mine - theirs)} only in brain.db, {len(theirs - mine)} only "
                "in the journal (a sync repairs a crash between the two)"
            )
        fresh = self._rows(*self._compute(raws, self._now(), lines))
        for t in _TABLES:
            have = sorted(
                (tuple(r) for r in self.db.fetchall(f"SELECT * FROM {t}")),
                key=lambda row: tuple("" if v is None else str(v) for v in row),
            )
            if have != fresh[t]:
                out.append(f"{t}: {len(set(have) ^ set(fresh[t]))} row(s) differ from a rebuild")
        return out

    def tables(self) -> dict[str, list[tuple[Any, ...]]]:
        """Every row of the computed tables, sorted: what a rebuild is compared by."""
        self.settle()
        return {
            t: sorted(tuple(r) for r in self.db.fetchall(f"SELECT * FROM {t}")) for t in _TABLES
        }

    def summary(self) -> dict[str, Any]:
        """Counts for brain_status and brain doctor."""
        self.settle()

        def count(sql: str) -> dict[str, int]:
            return {str(r[0]): int(r[1]) for r in self.db.fetchall(sql)}

        n = self.db.fetchone("SELECT count(*) FROM claims")
        waiting = self.db.fetchone(
            "SELECT count(*) FROM claims WHERE subject LIKE 'name:%' OR object_entity LIKE 'name:%'"
        )
        conflicts = self.db.fetchone(
            "SELECT count(DISTINCT claim_a || claim_b) FROM claim_conflicts WHERE acknowledged = 0"
        )
        report = self.db.fetchone("SELECT report FROM claims_state WHERE id = 1")
        return {
            "claims": int(n[0]) if n else 0,
            "lifecycle": count("SELECT lifecycle, count(*) FROM claims GROUP BY lifecycle"),
            "verification": count(
                "SELECT verification, count(*) FROM claims GROUP BY verification"
            ),
            "open_conflicts": int(conflicts[0]) if conflicts else 0,
            "waiting_names": int(waiting[0]) if waiting else 0,
            "report": json.loads(report[0]) if report else [],
            "unread": dict(self.unread),
        }
