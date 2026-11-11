"""``brain_recall``: one query across every store, deduplicated, ranked, capped.

Stores that rank by query themselves (the record index, Hindsight, SQLite FTS) are asked with
the query. A record from the index carries its bm25 score, and all of them share one scale, so
they are ranked by it. A store that only filters (the graph, a vault with no index) is read
whole and scored here by token overlap. A store that raises is reported in ``stores`` and never
aborts the call.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date
from typing import Any, get_args

from brain_core.stores.base import Kind, Record, Store, full_text, normalize

KINDS: tuple[Kind, ...] = get_args(Kind)
DEFAULT_TOKENS = 6_000
MAX_TOKENS = 25_000
_CONCISE_CHARS = 600
# Below this share of the query's words in the best written record, recall is a miss. Measured
# 2026-11-09 on one live agent: 11 real queries scored 0.50 to 0.92, 8 absent topics 0.00 to 0.40.
# "No results" cannot be the test: a vector store returns its nearest records for any query.
_MISS_BELOW = 0.5
_STOP = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "by",
        "at",
        "from",
        "as",
        "it",
        "this",
        "that",
        "we",
        "our",
    ]
)
# separators only inside a token: "commit." -> commit, "co-authored-by" and "127.0.0.1" stay whole
_WORD = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")
_WAS = re.compile(r"\(was: (.+?)\)(?:\s*\(\d{4}-\d{2}-\d{2}\))?\s*$")


def tokens(text: str) -> set[str]:
    """Lowercase words minus stopwords, plus a naive singular so "commits" meets "commit"."""
    text = text.lower().replace("'s", "").replace("'", "")
    out = {w for w in _WORD.findall(text) if len(w) > 1 and w not in _STOP}
    # a compound like includes_merchant or co-authored-by also matches by its parts
    parts = {p for w in out if "_" in w or "-" in w for p in re.split(r"[_-]", w) if len(p) > 2}
    out |= parts - _STOP
    return out | {w[:-1] for w in out if w.endswith("s") and len(w) > 3}


def recency(when: date, today: date) -> float:
    return 1.0 / (1.0 + max((today - when).days, 0) / 90.0)


def brain_recall(
    stores: Sequence[Store],
    query: str,
    scope: str = "all",
    fmt: str = "concise",
    limit: int = 10,
    max_tokens: int = DEFAULT_TOKENS,
    today: date | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    today = today or date.today()
    names = [s.name for s in stores]
    if scope == "all":
        kinds, chosen = KINDS, list(stores)
    elif scope in KINDS:
        kinds, chosen = (scope,), list(stores)
    elif scope in names:
        kinds, chosen = KINDS, [s for s in stores if s.name == scope]
    else:
        raise ValueError(
            f"scope must be 'all', a kind ({'|'.join(KINDS)}) or a store ({'|'.join(names)})"
        )
    if fmt not in ("concise", "detailed"):
        raise ValueError("format must be 'concise' or 'detailed'")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    max_tokens = min(max_tokens, MAX_TOKENS)

    q_norm, q_tok = normalize(query).lower(), tokens(query)
    # a transcript line holding the query's words is often the same question, asked before
    count_transcripts = scope in ("transcript", "transcripts")
    report: dict[str, Any] = {}
    found: dict[str, list[tuple[Record, float]]] = {}  # store -> (record, its place in the list)
    for store in chosen:
        ranked = bool(getattr(store, "ranked", False))
        found[store.name] = []
        try:
            # a store that ranks the whole bank by query (Hindsight) is asked once, not per kind
            whole = bool(getattr(store, "whole", False))
            for kind in kinds[:1] if whole else kinds:
                want = (offset + limit) * 2 if ranked else 10**6
                recs = store.read(kind, query if ranked else None, want)
                found[store.name] += [
                    (r, (1.0 - i / (len(recs) + 1)) * 0.6 if ranked else 0.0)
                    for i, r in enumerate(recs)
                    if not whole or r.kind in kinds
                ]
        except Exception as e:  # a dead store must not kill recall
            report[store.name] = f"error: {type(e).__name__}: {str(e)[:120]}"
            found[store.name] = []

    # index records share one bm25 scale: each is worth its share of the best one
    top = max((r.score for rs in found.values() for r, _ in rs), default=0.0)
    hits: dict[str, tuple[Record, str, float]] = {}
    best = 0.0
    seen_text: set[str] = set()
    for name, rs in found.items():
        n = 0
        for r, place in rs:
            full = full_text(r)
            overlap = len(q_tok & tokens(full)) / len(q_tok) if q_tok else 0.0
            if count_transcripts or r.kind != "transcript":
                best = max(best, overlap)
            phrase = 0.5 if q_norm and q_norm in full.lower() else 0.0
            rel = r.score / top + phrase if r.score > 0 else max(overlap + phrase, place)
            if rel <= 0:
                continue
            score = 0.75 * min(rel, 1.5) / 1.5 + 0.25 * recency(r.date, today)
            key = normalize(r.text).lower()
            if r.id in hits or key in seen_text:
                if r.id in hits and score > hits[r.id][2]:
                    hits[r.id] = (r, name, score)
                continue
            hits[r.id], n = (r, name, score), n + 1
            seen_text.add(key)
        report.setdefault(name, n)

    # a value a "Fact changed" banner superseded is kept on disk but ranks below the banner;
    # a transcript line is what was said, not what was decided, so written memory outranks it
    superseded = {
        normalize(m.group(1)).lower() for r, _s, _sc in hits.values() for m in _WAS.finditer(r.text)
    }
    ordered = sorted(
        (
            (
                r,
                s,
                sc
                * (0.5 if normalize(r.text).lower() in superseded else 1.0)
                * (0.7 if r.kind == "transcript" else 1.0),
            )
            for r, s, sc in hits.values()
        ),
        key=lambda h: (h[2], h[0].date),
        reverse=True,
    )
    total = len(ordered)
    results = [_item(r, s, sc, fmt) for r, s, sc in ordered[offset : offset + limit]]
    out: dict[str, Any] = {
        "query": query,
        "scope": scope,
        "stores": report,
        "total": total,
        "results": results,
    }
    if total == 0 or (q_tok and best < _MISS_BELOW):
        out["miss"] = {
            "best": round(best, 2),
            "hits": total,
        }  # for the caller's log, not the reader
    while results and len(json.dumps(out)) // 4 > max_tokens:
        results.pop()
        out["note"] = (
            f"truncated to {len(results)} of {total} results at {max_tokens} tokens; "
            "narrow `scope`, lower `limit`, or use format='concise'"
        )
    shown = offset + len(results)
    if results and shown < total:
        out["next_offset"] = shown
        out["note"] = (
            out.get("note", f"{len(results)} of {total} results")
            + f"; call again with offset={shown} for the rest"
        )
    if not results:
        out["note"] = (
            f"offset {offset} is past the last result ({total})"
            if total
            else "no hits; try fewer or different words, or scope='all'"
        )
    return out


_full_text = full_text  # the name older callers import


def _item(r: Record, store: str, score: float, fmt: str) -> dict[str, Any]:
    r = Record(r.id, r.kind, full_text(r), r.date, r.domain, r.path, r.line, r.extra)
    text = (
        r.text
        if fmt == "detailed" or len(r.text) <= _CONCISE_CHARS
        else r.text[:_CONCISE_CHARS] + "…"
    )
    item: dict[str, Any] = {
        "name": "-".join(_WORD.findall(r.text.lower())[:6]) or r.kind,
        "kind": r.kind,
        "date": r.date.isoformat(),
        "source": f"{r.path}:{r.line}" if r.line else r.path or store,
        "text": text,
    }
    if fmt == "detailed":
        item.update(id=r.id, store=store, score=round(score, 3), domain=r.domain, extra=r.extra)
    return item
