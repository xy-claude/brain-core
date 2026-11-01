"""Run the brain_recall eval against a real brain.yaml. Exit 1 below the threshold.

.venv/bin/python tests/eval/run_recall.py --config local/xyclaude.brain.yaml [--min 0.9]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml

from brain_core import Agent

HERE = Path(__file__).parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--tasks", default=str(HERE / "recall_tasks.yaml"))
    ap.add_argument("--min", type=float, default=0.9)
    ap.add_argument("--scope", default="all")
    a = ap.parse_args()
    spec = yaml.safe_load(Path(a.tasks).read_text())
    limit, tasks = int(spec.get("limit", 10)), spec["tasks"]
    hits, rows = 0, []
    with Agent.from_config(a.config) as agent:
        for t in tasks:
            t0 = time.perf_counter()
            out = agent.brain_recall(t["q"], scope=a.scope, limit=limit)
            ms = (time.perf_counter() - t0) * 1000
            blob = " ".join(r["text"] for r in out["results"]).lower()
            hit = any(e.lower() in blob for e in t["expect"])
            rank = next(
                (
                    i + 1
                    for i, r in enumerate(out["results"])
                    if any(e.lower() in r["text"].lower() for e in t["expect"])
                ),
                None,
            )
            hits += hit
            tokens = len(str(out)) // 4
            errs = [k for k, v in out["stores"].items() if isinstance(v, str)]
            rows.append((("HIT" if hit else "MISS"), rank, f"{ms:.0f}ms", tokens, t["q"], errs))
    for status, rank, ms, tokens, q, errs in rows:
        tail = f"  {errs}" if errs else ""
        print(f"{status:4} rank={rank or '-':<3} {ms:>7} {tokens:>5}tok  {q}{tail}")
    rate = hits / len(tasks)
    print(f"\n{hits}/{len(tasks)} = {rate:.0%} (min {a.min:.0%})")
    return 0 if rate >= a.min else 1


if __name__ == "__main__":
    sys.exit(main())
