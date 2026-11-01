"""Run a brain_recall eval against a brain.yaml. Exit 1 below the threshold.

    .venv/bin/python tests/eval/run_recall.py --config path/to/brain.yaml \
        [--tasks tests/eval/fixture/recall.yaml] [--min 0.9]

Per task: hit, rank of the first hit, tool calls, latency, tokens returned, store errors.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from brain_core import Agent

HERE = Path(__file__).parent


def run(
    config: str | Path, tasks_file: str | Path, scope: str = "all"
) -> tuple[float, list[dict[str, Any]]]:
    spec = yaml.safe_load(Path(tasks_file).read_text())
    limit, tasks = int(spec.get("limit", 10)), spec["tasks"]
    rows: list[dict[str, Any]] = []
    with Agent.from_config(config) as agent:
        for t in tasks:
            t0 = time.perf_counter()
            out = agent.brain_recall(t["q"], scope=scope, limit=limit)
            ms = (time.perf_counter() - t0) * 1000
            expect = [e.lower() for e in t["expect"]]
            rank = next(
                (
                    i + 1
                    for i, r in enumerate(out["results"])
                    if any(e in r["text"].lower() for e in expect)
                ),
                None,
            )
            rows.append(
                {
                    "q": t["q"],
                    "hit": rank is not None,
                    "rank": rank,
                    "calls": 1,
                    "ms": round(ms),
                    "tokens": len(str(out)) // 4,
                    "errors": [k for k, v in out["stores"].items() if isinstance(v, str)],
                }
            )
    rate = sum(r["hit"] for r in rows) / len(rows)
    return rate, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--tasks", default=str(HERE / "fixture" / "recall.yaml"))
    ap.add_argument("--min", type=float, default=0.9)
    ap.add_argument("--scope", default="all")
    a = ap.parse_args()
    rate, rows = run(a.config, a.tasks, a.scope)
    for r in rows:
        tail = f"  {r['errors']}" if r["errors"] else ""
        status = "HIT " if r["hit"] else "MISS"
        rank = r["rank"] or "-"
        print(f"{status} rank={rank:<3} {r['ms']:>6}ms {r['tokens']:>5}tok  {r['q']}{tail}")
    print(f"\n{sum(r['hit'] for r in rows)}/{len(rows)} = {rate:.0%} (min {a.min:.0%})")
    return 0 if rate >= a.min else 1


if __name__ == "__main__":
    sys.exit(main())
