"""Compare two ``run_gold.py`` result files question by question.

    .venv/bin/python tests/eval/compare.py baseline.json candidate.json

A total alone hides what moved: 113 against 110 can be seven questions fixed and four broken.
This pairs the two runs by question and prints, per slice and overall, how many the candidate
fixed, how many it broke, and the exact two-sided McNemar p-value for that split. Small p means
the difference is unlikely to be chance; with few changed questions it cannot be small.
"""

from __future__ import annotations

import json
import sys
from math import comb
from pathlib import Path
from typing import Any


def mcnemar(fixed: int, broken: int) -> float:
    """Exact two-sided p: the chance of a split this uneven if fixes and breaks were a coin toss."""
    n = fixed + broken
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(fixed, broken) + 1)) / 2**n
    return float(min(1.0, 2 * tail))


def compare(base: list[dict[str, Any]], cand: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    b = {r["q"]: r for r in base}
    pairs = [(b[r["q"]], r) for r in cand if r["q"] in b]
    out: dict[str, dict[str, Any]] = {}
    for s in [*dict.fromkeys(y["s"] for _, y in pairs), "all"]:
        ps = [(x, y) for x, y in pairs if s in ("all", y["s"])]
        fixed = [y["q"] for x, y in ps if y["hit"] and not x["hit"]]
        broken = [y["q"] for x, y in ps if x["hit"] and not y["hit"]]
        out[s] = {
            "n": len(ps),
            "base": sum(x["hit"] for x, _ in ps),
            "cand": sum(y["hit"] for _, y in ps),
            "fixed": fixed,
            "broken": broken,
            "p": round(mcnemar(len(fixed), len(broken)), 4),
        }
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    base, cand = (json.loads(Path(p).read_text())["rows"] for p in sys.argv[1:])
    res = compare(base, cand)
    unpaired = len(cand) - res["all"]["n"]
    print(f"{'slice':<10} {'n':>4} {'base':>5} {'cand':>5} {'fixed':>6} {'broken':>7} {'p':>7}")
    for s, v in res.items():
        print(
            f"{s:<10} {v['n']:>4} {v['base']:>5} {v['cand']:>5} {len(v['fixed']):>6} "
            f"{len(v['broken']):>7} {v['p']:>7}"
        )
    for q in res["all"]["broken"]:
        print(f"BROKEN {q}")
    if unpaired:
        print(f"\n{unpaired} candidate questions are not in the baseline and were left out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
