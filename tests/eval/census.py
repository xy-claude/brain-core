"""Read-only census of an agent's memory: M0 of docs/KNOWLEDGE_ARCHITECTURE_AUDIT.md (section P).

    .venv/bin/python tests/eval/census.py --db PATH/data/brain.db [--names] [--out census.json]

Opens ``brain.db`` with ``mode=ro`` and never writes. Without ``--names`` it reports counts only:
no subject, object, predicate or record text, so its output can go into a public report. With
``--names`` it adds the top predicates and the highest-degree entity strings, for a private file.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

_LINK = re.compile(r"\[\[[^\]]+\]\]")
_TAG = re.compile(r"(?<![\w#/&])#[A-Za-z][\w/-]*")
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
# "since June 2026", "in Aug 2025": a month and a year with no day before or after it
_PARTIAL = re.compile(rf"(?<!\d )(?<!\d)\b{_MON}\s+(?:of\s+)?(?:19|20)\d\d\b(?!-\d)", re.I)
_DAYED = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MON}\s+(?:19|20)\d\d|\b{_MON}\s+\d{{1,2}}", re.I
)


def norm(s: str) -> str:
    """How entity resolution would compare two names (F.5 step 1): NFKC, casefold, one space."""
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split()).strip(" .,:;\"'`*")


def pred_norm(s: str) -> str:
    return re.sub(r"[\s_-]+", "_", norm(s))


def pct(xs: list[int], p: float) -> int:
    if not xs:
        return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(p * (len(xs) - 1)))]


def census(db: sqlite3.Connection, names: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    out["tables"] = {
        t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        for t in sorted(tables)
        if not t.startswith(("records_fts_", "transcripts_fts_", "facts_fts_", "sqlite_"))
    }
    page = (
        db.execute("PRAGMA page_size").fetchone()[0] * db.execute("PRAGMA page_count").fetchone()[0]
    )
    out["db_bytes"] = page

    # ── records ──────────────────────────────────────────────────────────────────────────────
    by: Counter[tuple[str, str]] = Counter()
    occ: Counter[str] = Counter()
    seen: set[str] = set()
    undated = dated = links = tags = partial = 0
    dec_total = dec_links = 0
    link_kinds: Counter[str] = Counter()
    for store, kind, rid, doc in db.execute("SELECT store, kind, rid, record FROM records_fts"):
        occ[rid] += 1
        if rid in seen:
            continue
        seen.add(rid)
        by[(store, kind)] += 1
        rec = json.loads(doc)
        text = " ".join([rec.get("text", ""), *map(str, rec.get("extra", {}).values())])
        if kind in ("fact", "pattern") and store == "vault":
            if rec.get("extra", {}).get("legacy") == "undated":
                undated += 1
            else:
                dated += 1
        if _LINK.search(text):
            links += 1
            link_kinds[kind] += 1
        if _TAG.search(text):
            tags += 1
        if _PARTIAL.search(text) and not _DAYED.search(text):
            partial += 1
        if kind == "decision":
            dec_total += 1
            fields = " ".join(map(str, rec.get("extra", {}).values()))
            dec_links += bool(_LINK.search(fields))
    out["records"] = {
        "distinct": len(seen),
        "by_store_kind": {f"{s}/{k}": n for (s, k), n in sorted(by.items())},
        "ids_in_more_than_one_place": sum(1 for n in occ.values() if n > 1),
        "vault_facts_patterns_undated": undated,
        "vault_facts_patterns_dated": dated,
        "with_wikilink": links,
        "with_wikilink_by_kind": dict(link_kinds),
        "with_tag": tags,
        "with_month_year_only_date": partial,
        "decisions": dec_total,
        "decisions_with_wikilink_in_fields": dec_links,
    }

    # ── relations: predicates, entity strings, degrees ──────────────────────────────────────
    if "relations" in tables:
        rows = db.execute("SELECT subject, predicate, object, created_at FROM relations").fetchall()
        preds = Counter(p for _s, p, _o, _d in rows)
        pgroups: dict[str, set[str]] = {}
        for p in preds:
            pgroups.setdefault(pred_norm(p), set()).add(p)
        ents = Counter[str]()
        raw_names: dict[str, set[str]] = {}
        for s, _p, o, _d in rows:
            for e in (s, o):
                ents[norm(e)] += 1
                raw_names.setdefault(norm(e), set()).add(e)
        deg = list(ents.values())
        rel: dict[str, Any] = {
            "rows": len(rows),
            "predicates": len(preds),
            "predicates_after_normalising": len(pgroups),
            "predicate_spellings_merged": sum(len(v) - 1 for v in pgroups.values()),
            "predicates_used_once": sum(1 for n in preds.values() if n == 1),
            "entity_strings": sum(len(v) for v in raw_names.values()),
            "entities_after_normalising": len(ents),
            "entity_spellings_merged": sum(len(v) - 1 for v in raw_names.values()),
            "self_loops": sum(1 for s, _p, o, _d in rows if norm(s) == norm(o)),
            "degree": {
                "max": max(deg, default=0),
                "p50": pct(deg, 0.5),
                "p90": pct(deg, 0.9),
                "p99": pct(deg, 0.99),
                "mean": round(statistics.fmean(deg), 2) if deg else 0,
                "over_20": sum(1 for d in deg if d > 20),
                "over_50": sum(1 for d in deg if d > 50),
                "over_200": sum(1 for d in deg if d > 200),
                "top20": sorted(deg, reverse=True)[:20],
            },
            "created": [
                min((d for *_x, d in rows), default=""),
                max((d for *_x, d in rows), default=""),
            ],
        }
        if names:
            rel["top_predicates"] = preds.most_common(40)
            rel["top_entities"] = ents.most_common(20)
            rel["predicate_spelling_groups"] = {
                k: sorted(v) for k, v in pgroups.items() if len(v) > 1
            }
        out["relations"] = rel

    if "events" in tables:
        out["events_by_type"] = dict(
            db.execute(
                "SELECT event_type, count(*) FROM events GROUP BY event_type ORDER BY 2 DESC"
            ).fetchall()
        )
    if "record_vectors" in tables:
        out["vectors_by_model"] = {
            m: {"rows": n, "dim": d}
            for m, n, d in db.execute(
                "SELECT model, count(*), max(dim) FROM record_vectors GROUP BY model"
            )
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--names", action="store_true", help="add predicate and entity names (private)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    db = sqlite3.connect(f"file:{a.db.resolve()}?mode=ro", uri=True)
    result = census(db, a.names)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
