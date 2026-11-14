"""Recall eval against labelled record ids. No judge model, and nothing is logged.

    .venv/bin/python tests/eval/run_gold.py --config brain.yaml --questions questions.yaml \
        [--split dev|heldout] [--depth 500] [--out result.json] [--misses]

``run_recall.py`` judges by substring, which a query written in the note's own words always
passes. Here every question names the records that answer it (``gold``: id prefixes), so a
question asked in other words can fail. Slices (``s``):

* reworded, real, same, identifier: a gold record is in the top k
* multi: every gold record is in the top k
* update: a gold record comes before any ``stale`` one
* temporal: a gold record is in the top k; with no ``gold``, a session note dated ``date``
* absent: nothing in the store answers it, so recall must flag a miss

``answer`` (case-insensitive substrings) is scored apart as "answer in top k": a store that
rewrites text (a vector store) returns the answer under another id.

A question may carry ``split: dev|heldout``; one without it is held out when it is every third.
``--depth N`` asks a second time for the top N and reports how many questions have their gold
record anywhere in the top 50, 100, 200 and N: the ceiling a reader of that list could reach.
The last line counts three errors: a false answer (an absent question not flagged), a false
refusal (an answerable question flagged as a miss), and a miss with no warning (an answerable
question whose record did not come back, with nothing in the reply to say so).

It calls ``recall.brain_recall`` on the stores, never ``Agent.brain_recall``, so no
``recall_miss`` event is written to the database under test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from brain_core import Agent, recall
from brain_core.recall import brain_recall

CEILINGS = (50, 100, 200)


def _is(r: dict[str, Any], ids: list[str]) -> bool:
    return any(r["id"].startswith(i) for i in ids)


def judge(q: dict[str, Any], out: dict[str, Any]) -> tuple[bool, bool, int | None]:
    """(hit, answer_hit, rank of the first gold record)."""
    res, s = out["results"], q["s"]
    gold, answers = q.get("gold", []), [a.lower() for a in q.get("answer", [])]
    rank = next((i + 1 for i, r in enumerate(res) if _is(r, gold)), None)
    ans = any(a in r["text"].lower() for r in res for a in answers)
    if s == "absent":
        return "miss" in out, False, None
    if s == "temporal" and not gold:
        hit = any(r["kind"] == "note" and r["date"] == q["date"] for r in res)
        return hit, False, None
    if s == "multi":
        return all(any(r["id"].startswith(g) for r in res) for g in gold), ans, rank
    if s == "update":
        for i, r in enumerate(res):
            if _is(r, gold) or any(a in r["text"].lower() for a in answers):
                return True, True, i + 1
            if _is(r, q.get("stale", [])):
                return False, ans, rank  # the stale value outranks the current one
        return False, ans, rank
    return rank is not None, ans, rank


def deep_rank(q: dict[str, Any], res: list[dict[str, Any]]) -> int | None:
    """Where the gold sits in a long list: the first gold record, or for ``multi`` the last one
    needed. None when it is not there, or the slice has no gold."""
    gold = q.get("gold", [])
    if not gold:
        return None
    places = [next((i + 1 for i, r in enumerate(res) if r["id"].startswith(g)), None) for g in gold]
    if q["s"] == "multi":
        return None if None in places else max(p for p in places if p)
    return min((p for p in places if p), default=None)


def run(
    config: str,
    questions: str,
    split: str = "all",
    depth: int = 0,
    runner: Any = None,  # a judge runner (system, prompt) -> reply; None: the agent's own
) -> list[dict[str, Any]]:
    spec = yaml.safe_load(Path(questions).read_text())
    k = int(spec.get("k", 10))
    # tune on dev, quote the held-out number. A question says its split; without one, every
    # third question is held out
    qs = [
        q
        for i, q in enumerate(spec["questions"])
        if split == "all" or q.get("split", "heldout" if i % 3 == 2 else "dev") == split
    ]
    if depth:
        recall.MAX_TOKENS = 10**9  # the long list is for counting, never for a reader
    rows = []
    with Agent.from_config(config) as agent:
        for q in qs:
            t0 = time.perf_counter()
            nets: dict[str, Any] = {
                "vectors": agent.vectors,
                "candidates": agent.config.recall.candidates,
                "judge": runner or agent.judge,
                "judge_candidates": agent.config.recall.judge_candidates,
            }
            out = brain_recall(agent.stores, q["q"], fmt="detailed", limit=k, **nets)
            ms = (time.perf_counter() - t0) * 1000
            hit, ans, rank = judge(q, out)
            deep = None
            if depth and q.get("gold"):
                long = brain_recall(
                    agent.stores, q["q"], fmt="detailed", limit=depth, max_tokens=10**9, **nets
                )
                deep = deep_rank(q, long["results"])
            rows.append(
                {
                    "s": q["s"],
                    "q": q["q"],
                    "hit": hit,
                    "answer": ans,
                    "rank": rank,
                    "deep_rank": deep,
                    "has_gold": bool(q.get("gold")),
                    "flagged_miss": "miss" in out,
                    "has_answer_key": bool(q.get("answer")),
                    "ms": round(ms),
                    "errors": [n for n, v in out["stores"].items() if isinstance(v, str)],
                }
            )
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for s in dict.fromkeys(r["s"] for r in rows):
        rs = [r for r in rows if r["s"] == s]
        keyed = [r for r in rs if r["has_answer_key"]]
        ranks = [r["rank"] for r in rs if r["rank"]]
        out[s] = {
            "n": len(rs),
            "hits": sum(r["hit"] for r in rs),
            "any_gold": sum(r["rank"] is not None for r in rs),  # multi: at least one of them
            "top1": sum(r["rank"] == 1 for r in rs),
            "top5": sum(bool(r["rank"]) and r["rank"] <= 5 for r in rs),
            "answer_hits": sum(r["answer"] for r in keyed),
            "answer_n": len(keyed),
            "mrr": round(sum(1 / x for x in ranks) / len(rs), 3),
            "flagged_miss": sum(r["flagged_miss"] for r in rs),
            "median_ms": sorted(r["ms"] for r in rs)[len(rs) // 2],
        }
    return out


def ceilings(rows: list[dict[str, Any]], depth: int) -> dict[str, dict[str, int]]:
    """Per slice: questions with a gold record, and how many have it in the top N."""
    out: dict[str, dict[str, int]] = {}
    for s in dict.fromkeys(r["s"] for r in rows):
        rs = [r for r in rows if r["s"] == s and r["has_gold"]]
        if rs:
            out[s] = {"n": len(rs)} | {
                str(c): sum(bool(r["deep_rank"]) and r["deep_rank"] <= c for r in rs)
                for c in (*[c for c in CEILINGS if c < depth], depth)
            }
    return out


def refusals(rows: list[dict[str, Any]]) -> dict[str, int]:
    absent = [r for r in rows if r["s"] == "absent"]
    rest = [r for r in rows if r["s"] != "absent"]
    return {
        "absent_n": len(absent),
        "false_answers": sum(not r["flagged_miss"] for r in absent),
        "answerable_n": len(rest),
        "false_refusals": sum(r["flagged_miss"] for r in rest),
        "refused_though_found": sum(r["flagged_miss"] and r["hit"] for r in rest),
        # the error with no warning: an answerable question, the right record not returned,
        # and nothing in the reply says so. An upper bound: a label can miss a second record
        # that also answers
        "missed_no_warning": sum(not r["hit"] and not r["flagged_miss"] for r in rest),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--split", choices=("all", "dev", "heldout"), default="all")
    ap.add_argument("--depth", type=int, default=0, help="also report the ceiling in the top N")
    ap.add_argument("--out")
    ap.add_argument("--misses", action="store_true", help="print every question that failed")
    a = ap.parse_args()
    rows = run(a.config, a.questions, a.split, a.depth)
    if a.misses:
        for r in rows:
            if not r["hit"]:
                print(f"MISS {r['s']:<9} {r['q']}")
        print()
    print(
        f"{'slice':<9} {'hit@k':>9} {'top5':>5} {'top1':>5} {'answer@k':>9} {'mrr':>6} "
        f"{'flagged':>8} {'ms':>6}"
    )
    for s, v in summary(rows).items():
        print(
            f"{s:<9} {v['hits']:>4}/{v['n']:<4} {v['top5']:>5} {v['top1']:>5} "
            f"{v['answer_hits']:>4}/{v['answer_n']:<4} {v['mrr']:>6} {v['flagged_miss']:>8} "
            f"{v['median_ms']:>6}"
        )
    if multi := summary(rows).get("multi"):
        print(
            f"\nmulti: every needed record {multi['hits']}/{multi['n']}, "
            f"at least one {multi['any_gold']}/{multi['n']}"
        )
    if a.depth:
        print(f"\nceiling: gold record anywhere in the top N (of {a.depth} asked)")
        for s, v in ceilings(rows, a.depth).items():
            print(
                f"{s:<10} n={v['n']:<4} "
                + "  ".join(f"top{c} {n}" for c, n in v.items() if c != "n")
            )
    f = refusals(rows)
    print(
        f"\nfalse answers {f['false_answers']}/{f['absent_n']} absent questions; "
        f"false refusals {f['false_refusals']}/{f['answerable_n']} answerable "
        f"({f['refused_though_found']} of them had the record in the top k); "
        f"missed with no warning {f['missed_no_warning']}/{f['answerable_n']}"
    )
    errors = sorted({e for r in rows for e in r["errors"]})
    if errors:
        print(f"\nstores that errored: {errors}")
    if a.out:
        # `date` and `summary` are what brain_status reads when this is <data_dir>/eval.json
        doc = {
            "date": date.today().isoformat(),
            "summary": summary(rows),
            "refusals": f,
            "ceilings": ceilings(rows, a.depth) if a.depth else {},
            # what was run, so two result files can be told apart later
            "run": {
                "config": a.config,
                "questions": a.questions,
                "questions_sha256": hashlib.sha256(Path(a.questions).read_bytes()).hexdigest(),
                "split": a.split,
                "depth": a.depth,
            },
            "rows": rows,
        }
        Path(a.out).write_text(json.dumps(doc, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
