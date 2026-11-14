"""``brain_recall``: one query across every store, deduplicated, ranked, capped.

Stores that rank by query themselves (the record index, Hindsight, SQLite FTS) are asked with
the query. A record from the index carries its bm25 score, and all of them share one scale, so
they are ranked by it. A store that only filters (the graph, a vault with no index) is read
whole and scored here by token overlap. A store that raises is reported in ``stores`` and never
aborts the call.

With ``vectors`` (``stores.vectors`` in brain.yaml) a second search runs beside the keywords: the
records nearest in meaning. The two lists are joined by rank, never by score, so neither net's
numbers can drown the other's; a record that holds an exact identifier from the question (a
port, a version, a file name) is put first; and each result says which net found it. If no
vector can be made the keyword result is returned as it is, with the reason in ``stores``.

Where a vault has a record index, the SQLite fact table answers only for the rows no vault
file held when they were saved (a save before the vault was configured, or while its write
failed): the index reads the files as they are now, and the table never learns of a line
edited or deleted by hand. A lite install, with no such index, answers from the whole table,
and so does a call whose vault could not be read.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any, get_args

from brain_core import judge as judging
from brain_core.embed import EmbedUnavailable
from brain_core.stores.base import Kind, Record, Store, full_text, holds, normalize
from brain_core.stores.index import RecordIndex, days_asked
from brain_core.stores.vault import redact
from brain_core.stores.vectors import VectorIndex

KINDS: tuple[Kind, ...] = get_args(Kind)
DEFAULT_TOKENS = 6_000
MAX_TOKENS = 25_000
_CONCISE_CHARS = 600
# a question is a sentence or two: a pasted log is cut here before it is embedded, sent to the
# judge or echoed back (a 24,000-character one used to crowd every result out of the reply)
_QUERY_CHARS = 1000
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
# Joining two ranked lists: a record is worth 1/(c + its place) in each list it is on. Measured
# 2026-11-14 on 255 dev questions with a gold record: 188 answered in the top ten at c=10, 181 at
# c=60, 157 for keywords alone. A small c lets the head of either list lead, which is what keeps
# an exact keyword hit on top.
_RRF_C = 10
_NETS = ("vault", "notes", "archive")  # the stores whose records carry vectors
# a word that names one thing exactly: has a digit, or an inner _ . / (0.4.26, invalid_grant,
# session_recovery.py). A date or a bare year is not one.
_IDENT = re.compile(r"[a-z0-9#][a-z0-9_./:#-]*[a-z0-9]")
_DATEISH = re.compile(r"(?:19|20)\d\d(?:-\d\d){0,2}|\d{1,2}(?:st|nd|rd|th)")
_PIN_MAX = 20  # an identifier more records than this hold names nothing in particular
# under a scope the vector net is asked for this many, then cut down to the scope: all of a
# vault up to this size, and below the 32,766 values SQLite takes in one statement
_SCOPED_NET = 20_000
# An undated line's date is only its file's, so its age is unknown: it is ranked as if six
# months old, neither as new as its file nor as the oldest line there is. Measured 2026-11-14,
# keywords only, 380 questions with a gold record: 269 in the top ten at this value, 260 at 0
# (the undated lines of that vault are its oldest curated facts), 273 at 1.
_UNDATED_FRESH = 1 / 3
_WAS = re.compile(r"\(was: (.+?)\)(?:\s*\(\d{4}-\d{2}-\d{2}\))?\s*$")
WAS_CHARS = 120  # how much of the old line a "Fact changed" banner quotes


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


def _when(r: Record) -> date:
    """The date two records of one score are ordered by. An undated one has only its file's,
    which every later write moves to today, so it never wins a tie as the newest."""
    return date.min if r.undated else r.date


def brain_recall(
    stores: Sequence[Store],
    query: str,
    scope: str = "all",
    fmt: str = "concise",
    limit: int = 10,
    max_tokens: int = DEFAULT_TOKENS,
    today: date | None = None,
    offset: int = 0,
    vectors: VectorIndex | None = None,
    candidates: int = 150,
    judge: judging.Runner | None = None,
    judge_candidates: int = 50,
    picked: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """``picked``: the ``judgement`` an earlier call of the same question returned. A later
    page (``offset`` > 0) passes it so the page continues the judged order; the judge itself
    is only ever asked for the first page."""
    today = today or date.today()
    names = [s.name for s in stores]
    asked = [s for s in stores if getattr(s, "recall", True)]  # a store can opt out of recall
    # the vault's index holds every fact and pattern as its file has it now; the SQLite copy
    # never learns of a hand edit. So beside such an index it answers only for the rows no
    # file ever held, unless it is asked by name or the vault cannot be read. It is asked
    # last: by then it is known whether the vault answered
    spare: list[Store] = []
    if any(
        s.name == "vault" and isinstance(getattr(s, "index", None), RecordIndex) for s in stores
    ):
        spare = [s for s in asked if s.name == "sqlite"]
        asked = [s for s in asked if s.name != "sqlite"] + spare
    if scope == "all":
        kinds, chosen = KINDS, asked
    elif scope in KINDS:
        kinds, chosen = (scope,), asked
    elif scope in names:
        kinds, chosen, spare = KINDS, [s for s in stores if s.name == scope], []
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
    query = query.strip()
    if not query:  # nothing was asked: no store is searched and no model is called
        return {
            "query": "",
            "scope": scope,
            "stores": {},
            "total": 0,
            "results": [],
            "note": "the question is empty: nothing was searched",
        }
    asked_chars = len(query)
    query = query[:_QUERY_CHARS]

    def in_scope(r: Record, store: str) -> bool:
        return r.kind in kinds and scope in ("all", *KINDS, store)

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
                if ranked and (vectors is not None or judge is not None or picked is not None):
                    # the keyword net puts forward as many as the vector net; and what a judge
                    # reads must not depend on the page, or its pages repeat and skip records
                    want = max(want, candidates)
                recs = store.read(kind, query if ranked else None, want)
                # the vault answered: of the SQLite rows, only those no file ever held
                sole = store in spare and "vault" not in report
                found[store.name] += [
                    (r, (1.0 - i / (len(recs) + 1)) * 0.6 if ranked else 0.0)
                    for i, r in enumerate(recs)
                    if (not whole or r.kind in kinds) and (not sole or r.extra.get("sole"))
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
            # an index record is judged below, by rarity-weighted cover, not by raw overlap
            if r.score <= 0 and (count_transcripts or r.kind != "transcript"):
                best = max(best, overlap)
            phrase = 0.5 if q_norm and q_norm in full.lower() else 0.0
            rel = r.score / top + phrase if r.score > 0 else max(overlap + phrase, place)
            if rel <= 0:
                continue
            fresh = _UNDATED_FRESH if r.undated else recency(r.date, today)
            score = 0.75 * min(rel, 1.5) / 1.5 + 0.25 * fresh
            key = normalize(r.text).lower()
            if r.id in hits or key in seen_text:
                if r.id in hits:
                    # one record in two stores: the better score, and the copy that names a file
                    # (a tie used to keep `sqlite://facts/N`, which no one can open or teach)
                    old, was, had = hits[r.id]
                    if r.path.startswith("sqlite://") and not old.path.startswith("sqlite://"):
                        r, name = old, was
                    hits[r.id] = (r, name, max(score, had))
                continue
            hits[r.id], n = (r, name, score), n + 1
            seen_text.add(key)
        report.setdefault(name, n)

    # a value a "Fact changed" banner superseded is kept on disk but ranks below the banner;
    # a transcript line is what was said, not what was decided, so written memory outranks it
    quotes = [(m.group(1), r.id) for r, _s, _sc in hits.values() for m in _WAS.finditer(r.text)]
    superseded = {normalize(q).lower() for q, _rid in quotes}
    # a quote of full length is the start of a longer old line, which is known by that start:
    # start -> the banners that quote it. A banner is never the line it quotes (a second
    # change on one day quotes a banner that starts like itself), and a start that two other
    # lines share names neither of them
    cut: dict[str, set[str]] = {}
    for q, rid in quotes:
        if len(q) == WAS_CHARS:
            cut.setdefault(normalize(q).lower(), set()).add(rid)
    starts = Counter(
        k
        for r, _s, _sc in hits.values()
        if (k := normalize(r.text[:WAS_CHARS]).lower()) in cut and r.id not in cut[k]
    )
    # a record another one names in `supersedes` (record_meta.md) is retired the same way
    replaced: dict[str, str] = {}
    for store in stores:  # the links live in the vault whatever the scope
        if hasattr(store, "replaced"):
            with contextlib.suppress(OSError):  # a folder that cannot be read has no links
                replaced |= store.replaced()
    retired = set(replaced)

    def quoted(r: Record) -> bool:
        k = normalize(r.text[:WAS_CHARS]).lower()
        return normalize(r.text).lower() in superseded or (
            k in cut and r.id not in cut[k] and starts[k] < 2
        )

    def stale(r: Record) -> bool:
        return quoted(r) or r.id[:16] in retired

    def halved(r: Record) -> float:
        # a line a "Fact changed" banner quotes has no link to its replacement, so its score is
        # cut. A linked record keeps its score: `_current` puts its replacement just above it,
        # and a question about the past can still find the old value
        return 0.5 if quoted(r) else 1.0

    ordered = sorted(
        (
            (
                r,
                s,
                sc * halved(r) * (0.7 if r.kind == "transcript" or s == "archive" else 1.0),
            )
            for r, s, sc in hits.values()
        ),
        key=lambda h: (h[2], _when(h[0])),
        reverse=True,
    )
    index = next(
        (i for s in chosen if isinstance(i := getattr(s, "index", None), RecordIndex)), None
    )
    # whether the question is answered is read off the keyword list alone: a vector search
    # returns its nearest records for any question, so it cannot say "not in memory"
    lead = [r.id for r, _s, _sc in ordered[:3] if r.score > 0]
    found_by: dict[str, list[str]] = {}
    # a transcript line or a graph relation has no vector, so those scopes skip the net
    if (
        vectors is not None
        and scope not in ("transcript", "relation")
        and (scope in ("all", *KINDS) or scope in _NETS)
    ):
        # a scope is cut out of the whole net, not out of the nearest few: a small kind (45
        # decisions among 5,400 records) got next to nothing from the nearest 150
        fetch = candidates if scope == "all" else max(candidates, _SCOPED_NET)
        try:
            # the archive's 0.7 stays on the keyword score only: cosines sit in a narrow band,
            # where it sent the best archive record from place 3 to place 81
            near = [
                (r, s, sim * halved(r))
                for r, s, sim in vectors.search(query, fetch)
                if in_scope(r, s)
            ]
        except EmbedUnavailable as e:
            report["vectors"] = f"unavailable: {str(e)[:120]}"
        else:
            near.sort(key=lambda h: h[2], reverse=True)
            near = near[:candidates]
            report["vectors"] = len(near)
            nets = {"keyword": ordered[:candidates], "vector": near}
            if index is not None and (days := days_asked(query, today)):
                # a day named in the question is a third net: it adds that day's records and
                # removes nothing. They stand in the order the other two nets gave them
                seen = {h[0].id: n for n, h in enumerate([*ordered[:candidates], *near])}
                on_day = [
                    (r, s, 0.0)
                    for day in days
                    for r, s in [h for h in index.dated(day, fetch) if in_scope(*h)][:candidates]
                ]
                on_day.sort(key=lambda h: seen.get(h[0].id, len(seen)))
                nets["date"] = on_day
                report["date"] = len(on_day)
            ordered = _join(nets, found_by)
            ordered = _pin(ordered, query, index, found_by, in_scope)
    ordered = _current(ordered, replaced, index, found_by)
    # what the judge said: its status, the ids it picked, how many it read of those gathered
    judgement = dict(picked) if picked is not None else None
    if judgement is None and judge is not None and ordered and offset == 0:
        read = ordered[:judge_candidates]
        try:
            picks, status = judging.judge(
                judge, query, [(r, stale(r)) for r, _s, _sc in read], today, len(ordered)
            )
        except judging.JudgeError as e:
            report["judge"] = f"unavailable: {str(e)[:120]}"
        else:
            judgement = {
                "status": status,
                "picks": [read[i][0].id for i in picks],
                "read": len(read),
                "gathered": len(ordered),
            }
    verdict = ""
    if judgement is not None:
        # by id and not by place, so a later page puts the same records first and continues
        # after them: cut from the unjudged order it showed a pick twice and skipped another
        report["judge"] = verdict = str(judgement["status"])
        at = {h[0].id: h for h in ordered}
        front = [at[i] for i in judgement["picks"] if i in at]
        for r, _s, _sc in front:
            found_by.setdefault(r.id, []).append("judge")
        ordered = front + [h for h in ordered if h[0].id not in judgement["picks"]]
        ordered = _current(ordered, replaced, index, found_by)  # holds for the judge too
    total = len(ordered)
    results = [
        _item(r, s, sc, fmt, stale(r), found_by.get(r.id))
        for r, s, sc in ordered[offset : offset + limit]
    ]
    if index and q_tok and lead:
        # written memory leads the list: it alone says whether the question is answered. Raw
        # overlap would let a record with only the question's common words count as an answer
        best = index.cover(query, lead)
    out: dict[str, Any] = {
        "query": query,
        "scope": scope,
        "stores": report,
        "total": total,
        "results": results,
    }
    if asked_chars > _QUERY_CHARS:
        out["query_cut"] = (
            f"the question was cut to its first {_QUERY_CHARS} of {asked_chars} characters"
        )
    if judgement is not None:
        out["judged"] = verdict  # answered | partial | not_in_memory, from the model judge
        # the verdict covers what the judge read, not everything the search gathered
        out["judge_read"] = {k: judgement[k] for k in ("read", "gathered")}
        out["judgement"] = judgement  # for the caller: pass it back as `picked` on later pages
    if verdict == "not_in_memory":
        # a model read the first candidates and none answers: stronger than a low keyword cover
        out["miss"] = {"best": round(best, 2), "hits": total, "judged": True}
    elif verdict:
        pass  # the judge found an answer; a low keyword cover no longer means a miss
    elif total == 0 or (q_tok and best < _MISS_BELOW):
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
    if not results and "note" not in out:  # results dropped for size keep the note that says so
        out["note"] = (
            f"offset {offset} is past the last result ({total})"
            if total
            else "no hits; try fewer or different words, or scope='all'"
        )
    return out


_full_text = full_text  # the name older callers import

Hit = tuple[Record, str, float]


def _join(nets: dict[str, list[Hit]], found_by: dict[str, list[str]]) -> list[Hit]:
    """One list from several, by place and not by score (reciprocal rank fusion)."""
    worth: dict[str, float] = {}
    keep: dict[str, Hit] = {}
    for net, hits in nets.items():
        for place, hit in enumerate(hits):
            rid = hit[0].id
            worth[rid] = worth.get(rid, 0.0) + 1.0 / (_RRF_C + place + 1)
            keep.setdefault(rid, hit)
            found_by.setdefault(rid, []).append(net)
    return sorted(
        ((r, s, worth[r.id]) for r, s, _sc in keep.values()),
        key=lambda h: (h[2], _when(h[0])),
        reverse=True,
    )


def _current(
    ordered: list[Hit],
    replaced: dict[str, str],
    index: RecordIndex | None,
    found_by: dict[str, list[str]],
) -> list[Hit]:
    """Current beats old, by rule and not by score: a record that another one replaced never
    stands above its replacement. The replacement is moved up to just before it, and brought
    in when the search did not find it."""
    if not replaced or not any(h[0].id[:16] in replaced for h in ordered):
        return ordered
    place = {h[0].id[:16]: h for h in ordered}
    out: list[Hit] = []
    done: set[str] = set()
    for hit in ordered:
        rid = hit[0].id[:16]
        if rid in done:
            continue
        new, hops = rid, 0
        while new in replaced and hops < 10:  # follow a chain of replacements to its newest
            new, hops = replaced[new], hops + 1
        if new != rid and new not in done:
            current = place.get(new)
            if current is None and index is not None and (got := index.get(new)):
                current = (got[0], got[1], hit[2])
            if current is not None:
                out.append(current)
                done.add(new)
                if "replaces" not in found_by.setdefault(current[0].id, []):
                    found_by[current[0].id].append("replaces")
        out.append(hit)
        done.add(rid)
    return out


def identifiers(query: str) -> list[str]:
    """The exact tokens of a question: a port, a version, a file name, an error string."""
    out = []
    for w in _IDENT.findall(query.lower()):
        w = w.strip(".:/-")
        coded = any(c.isdigit() for c in w) or any(c in w for c in "_./#")
        if coded and len(w) > 2 and not _DATEISH.fullmatch(w):
            out.append(w)
    return list(dict.fromkeys(out))


def _pin(
    ordered: list[Hit],
    query: str,
    index: RecordIndex | None,
    found_by: dict[str, list[str]],
    in_scope: Callable[[Record, str], bool] = lambda r, s: True,
) -> list[Hit]:
    """Records holding an exact identifier from the question go first, in the order they had.
    Every record is scanned for it, not only the candidates. How many hold it is counted over
    all of them; only those the scope asked for are pinned."""
    front: dict[str, Hit] = {}
    for token in identifiers(query):
        holders = {r.id: (r, s, sc) for r, s, sc in ordered if holds(token, full_text(r))}
        others = index.holding(token, _PIN_MAX + 1) if index is not None else []
        count = len({*holders, *(r.id for r, _s in others)})
        for r, s in others:
            if in_scope(r, s):
                holders.setdefault(r.id, (r, s, 0.0))
        if holders and count <= _PIN_MAX:
            for rid, hit in holders.items():
                front.setdefault(rid, hit)
                if "exact" not in found_by.setdefault(rid, []):
                    found_by[rid].append("exact")
    return [*front.values(), *(h for h in ordered if h[0].id not in front)]


def _item(
    r: Record,
    store: str,
    score: float,
    fmt: str,
    stale: bool = False,
    found_by: list[str] | None = None,
) -> dict[str, Any]:
    # masked again on the way out, behind the index's own masking: a credential-shaped run
    # never leaves in a reply, whatever the stored row holds
    full = redact(full_text(r))
    item: dict[str, Any] = {
        "name": "-".join(_WORD.findall(full.lower())[:6]) or r.kind,
        "kind": r.kind,
        # an undated line has only its file's date: empty, so no reader takes that for a fact
        "date": "" if r.undated else r.date.isoformat(),
        "source": f"{r.path}:{r.line}" if r.line else r.path or store,
        "text": (
            full
            if fmt == "detailed" or len(full) <= _CONCISE_CHARS
            else full[:_CONCISE_CHARS] + "…"
        ),
    }
    if stale:
        item["superseded"] = True  # a newer record replaced this value; kept for its history
    if found_by:
        item["found_by"] = found_by  # keyword, vector, exact, judge: what put it forward
    if fmt == "detailed":
        item.update(
            id=r.id,
            store=store,
            score=round(score, 3),
            domain=redact(r.domain),
            # a store may hand over a value that is not text (a timestamp): it passes as it is
            extra={k: redact(v) if isinstance(v, str) else v for k, v in r.extra.items()},
        )
        if r.undated:
            item["undated"] = True
    return item
