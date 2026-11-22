"""The deterministic rules (audit G.1, rows 7-9): the raw rows each source gives, without a
model. A raw row keeps names as written; brain.db resolves them to entities when it computes
the claims, so an alias added later re-resolves it.

Which sources feed claims: ``vault:relations.md`` and relation lines in notes folders
(``relations.md/1``), decision entries whose **Decision:** names one wikilink
(``decision-field/1``), ``record_meta.md`` (times and links) and ``claim_reviews.md``
(reviews). Session files are not read: what the capture hook files there never becomes a claim.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Sequence
from datetime import date
from typing import Any

from brain_core.journal import occurrence_id
from brain_core.stores.base import Record, full_text, record_id

Raw = tuple[str, str, str, int]  # (kind, row_key, row_json, line): line is never versioned
RELATIONS, DECISIONS = "vault:relations.md", "vault:decisions_log.md"
META, REVIEWS = "vault:record_meta.md", "vault:claim_reviews.md"
REFLECTIONS = "vault:knowledge/_reflections.md"  # `brain weekly`'s, never in the index
# a relation written inside a note: [[S]] —[P]→ [[O]], with an optional stated date
_IN_TEXT = re.compile(
    r"\[\[([^\]|#]+)\]\] —\[([^\]]+)\]→ \[\[([^\]|#]+)\]\](?: \((\d{4}-\d{2}-\d{2})\))?"
)
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
_SPEC = re.compile(r"^\[\[(.+?)\]\] —\[(.+?)\]→ (?:\[\[(.+?)\]\]|(\S.*?))$")
_META_LINE = re.compile(r"^- ([0-9a-f]{16})(?:@(\S+)#(\d+))? \| (.+)$")
_REVIEW_LINE = re.compile(r"^- (reject|retract|restore|ack): (.+?)(?: \| (.*))?\s*$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# a relation a reflection draws, with the claims it rests on (THREAT_MODEL gate 3)
_REFLECTED = re.compile(
    r"^- \[\[(.+?)\]\] —\[(.+?)\]→ \[\[(.+?)\]\](?: \(parents: ([0-9a-f, ]+)\))?\s*$"
)


def _date(s: str | None) -> dict[str, Any]:
    """A stated date, checked: ``2026-02-30`` is no day, so the row is undated and says so."""
    if not s:
        return {"stated_date": None}
    try:
        date.fromisoformat(s)
    except ValueError:
        return {"stated_date": None, "bad_date": s}
    return {"stated_date": s}


def _is_day(v: str) -> bool:
    try:
        return bool(_DAY.match(v)) and bool(date.fromisoformat(v))
    except ValueError:
        return False


def norm_predicate(p: str) -> str:
    """``uses``, ``Depends on`` -> ``USES``, ``DEPENDS_ON``: the ontology's spelling."""
    return re.sub(r"[^0-9A-Za-z]+", "_", p).strip("_").upper()


def split_predicate(p: str) -> tuple[str, str]:
    """``USES: graph-database`` -> (``USES``, ``graph-database``): the role qualifies it."""
    name, _, role = p.partition(":")
    return norm_predicate(name), "-".join(role.lower().split())


def accepts(source: str) -> bool:
    return source in (RELATIONS, DECISIONS) or source.startswith("notes:")


def _dump(d: dict[str, Any]) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"))  # canonical: no false versions


def _evidence(source: str, rid: str, k: int, text: str, rule: str, line: int, **row: Any) -> Raw:
    occ = occurrence_id(source, rid, k)
    pred, role = split_predicate(row.pop("raw_predicate"))
    body = {
        "source_id": source,
        "record_id": rid,
        "ordinal": k,
        "rule": rule,
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "predicate": pred,
        "role": role,
        "object_name": None,
        "object_literal": None,
        "stated_date": None,
        "event_date": None,
        "valid_from": None,
        "origin": None,  # None: from the ledger (a write is the agent's, an ingest the user's)
        "verification": "stated",
        **row,
    }
    key = [source, occ, rule, body["subject_name"], pred, role]
    key.append(body["object_name"] if body["object_name"] is not None else body["object_literal"])
    return ("evidence", json.dumps(key), _dump(body), line)


def evidence(source: str, records: Sequence[Record]) -> list[Raw]:
    """Evidence rows of one source's records, numbered as the journal numbers occurrences."""
    if not accepts(source):
        return []
    out: dict[str, Raw] = {}
    seen: Counter[str] = Counter()
    for r in records:
        seen[r.id] += 1
        k, text = seen[r.id], full_text(r)
        rows: list[Raw] = []
        if r.kind == "relation" and source == RELATIONS:
            literal = r.extra.get("literal") == "1"
            obj = {"object_literal": r.extra["object"]} if literal else {
                "object_name": r.extra["object"]
            }  # fmt: skip
            rows.append(
                _evidence(source, r.id, k, text, "relations.md/1", r.line,
                          subject_name=r.extra["subject"], raw_predicate=r.extra["predicate"],
                          quote=text[:300], **_date(r.extra.get("stated")), **obj,
                          # `(recorded: …)` is written by brain-core only: the agent's line
                          origin="agent" if r.extra.get("recorded") else None)
            )  # fmt: skip
        elif source.startswith("notes:"):
            for m in _IN_TEXT.finditer(text):
                rows.append(
                    _evidence(source, r.id, k, text, "relations.md/1", r.line,
                              subject_name=m[1].strip(), raw_predicate=m[2],
                              object_name=m[3].strip(), quote=m[0][:300], **_date(m[4]),
                              # a folder brain-core reads but does not write: who wrote the
                              # line is unknown, so the claim is provisional (THREAT_MODEL
                              # gate 1) until a person states it in relations.md
                              origin="external", verification="unverified")
                )  # fmt: skip
        elif r.kind == "decision" and source == DECISIONS and not r.undated:
            said = r.extra.get("decision", "").strip()
            links = {x.strip() for x in _WIKILINK.findall(said)}
            if len(links) == 1:  # "replace [[A]] with [[B]]" names two: no rule can tell which
                day = r.date.isoformat()
                rows.append(
                    _evidence(source, r.id, k, text, "decision-field/1", r.line,
                              subject_name=f"record:{r.id[:16]}", raw_predicate="SELECTS",
                              object_name=links.pop(), stated_date=day, event_date=day,
                              valid_from=day, origin="markup", verification="derived",
                              quote=said[:300])
                )  # fmt: skip
        for row in rows:
            out.setdefault(row[1], row)  # one occurrence supports one assertion once per rule
    return list(out.values())


def wanted(source: str, text: str) -> list[tuple[int, str]]:
    """(line number, line) of the lines that time, link or review a record: search keys
    and the rest of record_meta.md are not claims' business."""
    return [(n, ln) for n, ln in enumerate(text.splitlines(), 1) if _wanted(source, ln)]


def _lines(source: str, text: str) -> list[tuple[int, str, str, int]]:
    """(line number, line, its record id, its ordinal): a meta or review line is an
    occurrence too, so its ledger time orders it."""
    seen: Counter[str] = Counter()
    out = []
    for n, ln in wanted(source, text):
        rid = record_id(ln)
        seen[rid] += 1
        out.append((n, ln, rid, seen[rid]))
    return out


def ledger_lines(source: str, text: str) -> list[tuple[str, str]]:
    """What the journal's ledger records for a meta or review file: (record id, line)."""
    return [(rid, ln) for _n, ln, rid, _k in _lines(source, text)]


def _wanted(source: str, ln: str) -> bool:
    if source == REVIEWS:
        return bool(_REVIEW_LINE.match(ln))
    if source == REFLECTIONS:
        return bool(_REFLECTED.match(ln))
    m = _META_LINE.match(ln)
    return bool(m) and any(
        part.partition(": ")[0] in ("valid", "until", "event", "supersedes", "was")
        for part in m[4].split(" | ")  # type: ignore[index]
    )


def meta(text: str) -> list[Raw]:
    """record_meta.md: ``valid`` / ``until`` / ``event`` per record or per copy
    (``<rid16>@<source>#<k>``), and ``supersedes`` / ``was`` links. A later line for the same
    record and scope replaces the fields it gives."""
    times: dict[tuple[str, str], dict[str, Any]] = {}
    links: dict[tuple[str, str, str], Raw] = {}
    for n, ln, rid, k in _lines(META, text):
        m = _META_LINE.match(ln)
        if not m:
            continue
        occ = occurrence_id(META, rid, k)
        line_hash = hashlib.sha256(ln.encode()).hexdigest()
        scope = f"{m[2]}#{m[3]}" if m[2] else ""
        for part in m[4].split(" | "):
            f, _, v = part.partition(": ")
            v = v.strip()
            if f in ("valid", "until", "event"):
                t = times.setdefault((m[1], scope), {"rid": m[1], "occ_scope": scope})
                if f == "valid" and v == "always":
                    t.update(timeless=True, valid_from=None)
                elif _is_day(v):
                    col = {"valid": "valid_from", "until": "valid_to", "event": "event_date"}[f]
                    t[col] = v
                    if f == "valid":
                        t["timeless"] = False
                t.update(line_occ=occ, line_hash=line_hash, line=n)
            elif f in ("supersedes", "was"):
                for old in v.replace(";", " ").split():
                    kind = "supersedes" if f == "supersedes" else "was"
                    new_rid, old_rid = m[1], old[:16]  # `was: <old>`: the id it had before
                    body = {"new_rid": new_rid, "old_rid": old_rid, "kind": kind,
                            "line_occ": occ, "line_hash": line_hash}  # fmt: skip
                    key = json.dumps([META, new_rid, old_rid, kind])
                    links[(new_rid, old_rid, kind)] = ("link", key, _dump(body), n)
    out = list(links.values())
    for (rid, scope), t in times.items():
        line = t.pop("line")
        body = {"valid_from": None, "valid_to": None, "event_date": None, "timeless": False, **t}
        out.append(("time", json.dumps([META, rid, scope]), _dump(body), line))
    return out


def reflections(text: str) -> list[Raw]:
    """knowledge/_reflections.md: a relation line is evidence of origin `reflection`. It is
    unverified, so the claim stays a candidate, unless its `(parents: …)` name claims brain-core
    already holds; reconcile checks them."""
    out: list[Raw] = []
    for n, ln, rid, k in _lines(REFLECTIONS, text):
        m = _REFLECTED.match(ln)
        if not m:
            continue
        parents = sorted({p.strip() for p in (m[4] or "").split(",") if p.strip()})
        out.append(
            _evidence(REFLECTIONS, rid, k, ln, "reflection/1", n, subject_name=m[1].strip(),
                      raw_predicate=m[2], object_name=m[3].strip(), quote=ln[2:302],
                      origin="reflection", verification="unverified", parents=parents)
        )  # fmt: skip
    return out


def _spec(text: str) -> dict[str, Any] | None:
    m = _SPEC.match(text.strip())
    if not m:
        return None
    pred, role = split_predicate(m[2])
    return {
        "subject_name": m[1].strip(),
        "predicate": pred,
        "role": role,
        "object_name": m[3].strip() if m[3] else None,
        "object_literal": m[4].strip() if m[4] else None,
    }


def reviews(text: str) -> tuple[list[Raw], list[str]]:
    """claim_reviews.md: ``- reject: [[S]] —[P: role]→ [[O]] | why``, and ``retract``,
    ``restore``, ``ack: <claim> & <claim>``. Returns the rows and the lines it cannot read."""
    out: list[Raw] = []
    bad: list[str] = []
    for n, ln, rid, k in _lines(REVIEWS, text):
        m = _REVIEW_LINE.match(ln)
        if not m:
            continue
        parts = m[2].split(" & ") if m[1] == "ack" else [m[2]]
        specs = [_spec(p) for p in parts]
        if any(s is None for s in specs) or (m[1] == "ack") != (len(specs) == 2):
            bad.append(f"claim_reviews.md:{n}: cannot read {ln[:60]!r}")
            continue
        occ = occurrence_id(REVIEWS, rid, k)
        body = {
            "action": m[1],
            "key": specs[0],
            "other": specs[1] if len(specs) == 2 else None,
            "reason": (m[3] or "").strip(),
            "line_occ": occ,
            "line_hash": hashlib.sha256(ln.encode()).hexdigest(),
        }
        out.append(("review", json.dumps([REVIEWS, occ]), _dump(body), n))
    return out, bad
