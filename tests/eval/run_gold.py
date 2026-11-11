"""Recall eval against hand-labelled record ids. No judge model, and nothing is logged.

    .venv/bin/python tests/eval/run_gold.py --config brain.yaml --questions questions.yaml \
        [--split dev|heldout] [--out result.json] [--misses]

``run_recall.py`` judges by substring, which a query written in the note's own words always
passes. Here every question names the records that answer it (``gold``: id prefixes), so a
question asked in other words can fail. Slices (``s``):

* reworded, real, same: a gold record is in the top k
* multi: every gold record is in the top k
* update: a gold record comes before any ``stale`` one
* temporal: a session note dated ``date`` is in the top k
* absent: nothing in the store answers it, so recall must flag a miss

``answer`` (case-insensitive substrings) is scored apart as "answer in top k": a store that
rewrites text (a vector store) returns the answer under another id.

It calls ``recall.brain_recall`` on the stores, never ``Agent.brain_recall``, so no
``recall_miss`` event is written to the database under test.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from brain_core import Agent
from brain_core.recall import brain_recall


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
    if s == "temporal":
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


def run(config: str, questions: str, split: str = "all") -> list[dict[str, Any]]:
    spec = yaml.safe_load(Path(questions).read_text())
    k = int(spec.get("k", 10))
    # every third question is held out: tune on dev, quote the held-out number
    qs = [
        q
        for i, q in enumerate(spec["questions"])
        if split == "all" or (i % 3 == 2) == (split == "heldout")
    ]
    rows = []
    with Agent.from_config(config) as agent:
        for q in qs:
            t0 = time.perf_counter()
            out = brain_recall(agent.stores, q["q"], fmt="detailed", limit=k)
            ms = (time.perf_counter() - t0) * 1000
            hit, ans, rank = judge(q, out)
            rows.append(
                {
                    "s": q["s"],
                    "q": q["q"],
                    "hit": hit,
                    "answer": ans,
                    "rank": rank,
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
            "top1": sum(r["rank"] == 1 for r in rs),
            "top5": sum(bool(r["rank"]) and r["rank"] <= 5 for r in rs),
            "answer_hits": sum(r["answer"] for r in keyed),
            "answer_n": len(keyed),
            "mrr": round(sum(1 / x for x in ranks) / len(rs), 3),
            "flagged_miss": sum(r["flagged_miss"] for r in rs),
            "median_ms": sorted(r["ms"] for r in rs)[len(rs) // 2],
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--split", choices=("all", "dev", "heldout"), default="all")
    ap.add_argument("--out")
    ap.add_argument("--misses", action="store_true", help="print every question that failed")
    a = ap.parse_args()
    rows = run(a.config, a.questions, a.split)
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
    errors = sorted({e for r in rows for e in r["errors"]})
    if errors:
        print(f"\nstores that errored: {errors}")
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summary(rows), "rows": rows}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
