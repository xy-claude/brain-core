"""Run the stratified brain_recall eval against a brain.yaml. Exit 1 below the threshold.

    .venv/bin/python tests/eval/run_recall.py --config path/to/brain.yaml \
        [--tasks tests/eval/fixture/recall.yaml] [--min 0.9] [--runs 3] [--out data/eval.json]

Task types (LoCoMo / LongMemEval slices): single-hop (default), multi-hop (every ``expect``
must appear somewhere in the top-k), update (the first result that mentions the fact must carry
the new value, never a ``reject`` value), abstention (no result at all), temporal (a session note
dated ``date`` is in the top-k). ``--runs N`` repeats every task and counts a hit only when all
N runs hit (tau-bench pass^k), which exposes flaky retrieval a single run hides.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from brain_core import Agent

HERE = Path(__file__).parent
TYPES = ("single-hop", "multi-hop", "update", "abstention", "temporal")


def judge(task: dict[str, Any], results: list[dict[str, Any]]) -> int | None:
    """Rank of the hit (1-based) or None."""
    kind = task.get("type", "single-hop")
    texts = [r["text"].lower() for r in results]
    expect = [e.lower() for e in task.get("expect", [])]
    if kind == "abstention":
        return 1 if not results else None
    if kind == "temporal":
        return next(
            (
                i + 1
                for i, r in enumerate(results)
                if r["kind"] == "note" and r["date"] == task["date"]
            ),
            None,
        )
    if kind == "multi-hop":
        return len(results) if all(any(e in t for t in texts) for e in expect) else None
    if kind == "update":
        reject = [x.lower() for x in task.get("reject", [])]
        for i, t in enumerate(texts):
            live = re.sub(r"\(was: .*?\)", "", t)  # a banner quotes the old value on purpose
            if any(e in live for e in expect):
                return i + 1
            if any(x in live for x in reject):
                return None  # the stale value outranks the new one
        return None
    return next((i + 1 for i, t in enumerate(texts) if any(e in t for e in expect)), None)


def run(
    config: str | Path, tasks_file: str | Path, scope: str = "all", runs: int = 1
) -> tuple[float, list[dict[str, Any]]]:
    spec = yaml.safe_load(Path(tasks_file).read_text())
    limit, tasks = int(spec.get("limit", 10)), spec["tasks"]
    rows: list[dict[str, Any]] = []
    with Agent.from_config(config) as agent:
        for t in tasks:
            ranks: list[int | None] = []
            t0 = time.perf_counter()
            for _ in range(runs):
                out = agent.brain_recall(t["q"], scope=scope, fmt="detailed", limit=limit)
                ranks.append(judge(t, out["results"]))
            ms = (time.perf_counter() - t0) * 1000 / runs
            rows.append(
                {
                    "q": t["q"],
                    "type": t.get("type", "single-hop"),
                    "hit": all(r is not None for r in ranks),
                    "rank": ranks[0],
                    "runs": runs,
                    "ms": round(ms),
                    "tokens": len(str(out)) // 4,
                    "errors": [k for k, v in out["stores"].items() if isinstance(v, str)],
                }
            )
    rate = sum(r["hit"] for r in rows) / len(rows)
    return rate, rows


def by_type(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        d = out.setdefault(r["type"], {"hits": 0, "n": 0})
        d["n"] += 1
        d["hits"] += int(r["hit"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--tasks", default=str(HERE / "fixture" / "recall.yaml"))
    ap.add_argument("--min", type=float, default=0.9)
    ap.add_argument("--scope", default="all")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out", help="write {date, runs, by_type} JSON here; traits read it")
    a = ap.parse_args()
    rate, rows = run(a.config, a.tasks, a.scope, a.runs)
    for r in rows:
        tail = f"  {r['errors']}" if r["errors"] else ""
        status = "HIT " if r["hit"] else "MISS"
        rank = r["rank"] or "-"
        print(
            f"{status} {r['type']:<11} rank={rank:<3} {r['ms']:>6}ms "
            f"{r['tokens']:>5}tok  {r['q']}{tail}"
        )
    slices = by_type(rows)
    print()
    for k, v in slices.items():
        print(f"  {k:<11} {v['hits']}/{v['n']}")
    print(
        f"\n{sum(r['hit'] for r in rows)}/{len(rows)} = {rate:.0%} pass^{a.runs} (min {a.min:.0%})"
    )
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(
            json.dumps(
                {"date": date.today().isoformat(), "runs": a.runs, "by_type": slices}, indent=1
            )
        )
    return 0 if rate >= a.min else 1


if __name__ == "__main__":
    sys.exit(main())
