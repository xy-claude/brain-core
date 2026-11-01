"""Run the brain_remember eval on a fresh temp vault (never the live one). Exit 1 on any failure.

.venv/bin/python tests/eval/run_write.py [--hindsight-bank brain-test] [--tasks ...]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import yaml

from brain_core import Agent

HERE = Path(__file__).parent


def run(
    tasks_file: str | Path, hindsight_bank: str | None = None
) -> tuple[float, list[dict[str, Any]]]:
    tasks = yaml.safe_load(Path(tasks_file).read_text())["tasks"]
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        vault.mkdir()
        cfg = Path(tmp) / "brain.yaml"
        hs = (
            f"  hindsight: {{url: http://127.0.0.1:8888, bank: {hindsight_bank}}}\n"
            if hindsight_bank
            else ""
        )
        cfg.write_text(textwrap.dedent(f"name: EVAL\nstores:\n  vault: {vault}\n") + hs)
        with Agent.from_config(cfg) as agent:
            for t in tasks:
                if t.get("requires") == "hindsight" and not hindsight_bank:
                    rows.append(
                        {"name": t["name"], "ok": True, "skipped": True, "why": "no hindsight"}
                    )
                    continue
                call = dict(t["call"])
                extra = call.pop("extra", {})
                try:
                    out = agent.brain_remember(call.pop("text"), call.pop("kind"), **call, **extra)
                    problems = _check(out, t["expect"])
                except ValueError as e:
                    want = t["expect"].get("error")
                    problems = [] if want and want in str(e).lower() else [f"unexpected error: {e}"]
                rows.append({"name": t["name"], "ok": not problems, "problems": problems})
    rate = sum(r["ok"] for r in rows) / len(rows)
    return rate, rows


def _check(out: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    problems = []
    if "error" in expect:
        problems.append(f"expected a {expect['error']} error, got status {out.get('status')}")
    if "status" in expect and out.get("status") != expect["status"]:
        problems.append(f"status {out.get('status')} != {expect['status']}")
    if expect.get("contradiction") and "contradiction" not in out:
        problems.append("no contradiction reported")
    if "text_prefix" in expect and not out.get("text", "").startswith(expect["text_prefix"]):
        problems.append(f"text does not start with {expect['text_prefix']!r}")
    for store, status in expect.get("layers", {}).items():
        got = out.get("layers", {}).get(store, {}).get("status")
        if got != status:
            problems.append(f"layer {store}: {got} != {status}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(HERE / "write_tasks.yaml"))
    ap.add_argument("--hindsight-bank", default=None)
    a = ap.parse_args()
    rate, rows = run(a.tasks, a.hindsight_bank)
    for r in rows:
        flag = "SKIP" if r.get("skipped") else ("PASS" if r["ok"] else "FAIL")
        print(f"{flag}  {r['name']}" + (f"  → {r['problems']}" if r.get("problems") else ""))
    print(f"\n{sum(r['ok'] for r in rows)}/{len(rows)} = {rate:.0%}")
    return 0 if rate == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
