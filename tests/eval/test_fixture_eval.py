"""The eval in CI: recall on a synthetic fixture vault and the write scenarios, no network.

The live evals (the author's real vault + Hindsight) run from the CLI runners; this is the
reproducible floor every commit must keep.
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

from tests.eval import run_recall, run_write

HERE = Path(__file__).parent


def test_fixture_recall_at_least_90_percent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(HERE / "fixture" / "vault", vault)
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(textwrap.dedent(f"name: FIX\nstores:\n  vault: {vault}\n"))
    rate, rows = run_recall.run(cfg, HERE / "fixture" / "recall.yaml")
    misses = [r["q"] for r in rows if not r["hit"]]
    assert rate >= 0.9, f"{rate:.0%}; misses: {misses}"
    assert all(not r["errors"] for r in rows)
    assert max(r["tokens"] for r in rows) < 6_000


def test_write_scenarios_all_pass() -> None:
    rate, rows = run_write.run(HERE / "write_tasks.yaml")
    assert rate == 1.0, [r for r in rows if not r["ok"]]
