"""The eval in CI: recall on a synthetic fixture vault and the write scenarios, no network.

The live evals (the author's real vault + Hindsight) run from the CLI runners; this is the
reproducible floor every commit must keep.
"""

from __future__ import annotations

import json
import shutil
import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest

from brain_core.stores.base import record_id
from tests.eval import run_gold, run_recall, run_write

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


def test_run_gold_can_pin_the_day_recall_treats_as_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    new = "Gateway port 9090 after the autumn move to the new rack"
    (vault / "facts.md").write_text(
        "# Facts\n\n## System\n- Gateway port 8080 on staging (2026-01-01)\n"
        f"- {new} (2026-11-01)\n- Lunch is at noon (2026-06-01)\n"
        "- The office closes at six (2026-06-01)\n- Backups run on Sunday (2026-06-01)\n"
    )
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(f"name: FIX\nstores:\n  vault: {vault}\n")
    questions = tmp_path / "questions.yaml"
    questions.write_text(
        f"k: 1\nquestions:\n  - {{q: gateway port, s: real, gold: ['{record_id(new)[:12]}']}}\n"
    )
    # the newer line leads while it is new; a year on, its age no longer lifts it past the
    # shorter old line. Same vault, same code: only the day differs
    near = run_gold.run(str(cfg), str(questions), today=date(2026, 11, 2))
    far = run_gold.run(str(cfg), str(questions), today=date(2028, 1, 1))
    assert [r["hit"] for r in near] == [True] and [r["hit"] for r in far] == [False]
    out = tmp_path / "result.json"
    argv = ["run_gold.py", "--config", str(cfg), "--questions", str(questions), "--out", str(out)]
    monkeypatch.setattr(sys, "argv", [*argv, "--today", "2028-01-01"])
    assert run_gold.main() == 0
    doc = json.loads(out.read_text())
    assert doc["run"]["today"] == "2028-01-01" and doc["summary"]["real"]["hits"] == 0
    monkeypatch.setattr(sys, "argv", [*argv, "--today", "2026-11-02"])
    assert run_gold.main() == 0
    assert json.loads(out.read_text())["summary"]["real"]["hits"] == 1
