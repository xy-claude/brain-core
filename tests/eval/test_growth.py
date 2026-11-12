"""The growth eval: the stratified recall slices hold their floors, and a brain with thirty days
of sessions scores higher on every defensible trait signal than the same brain on day one.
"""

from __future__ import annotations

import json
import shutil
import textwrap
from datetime import date
from pathlib import Path

from brain_core import Agent, traits
from brain_core.cli.init import init_agent
from tests.eval import run_recall

HERE = Path(__file__).parent
TODAY = date(2026, 11, 2)
FLOORS = {"single-hop": 0.9, "multi-hop": 1.0, "update": 1.0, "abstention": 1.0, "temporal": 1.0}


def fixture_agent(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    shutil.copytree(HERE / "fixture" / "vault", vault)
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(textwrap.dedent(f"name: FIX\nstores:\n  vault: {vault}\n"))
    return cfg, vault


def test_every_recall_slice_holds_its_floor_at_pass_3(tmp_path: Path) -> None:
    cfg, _ = fixture_agent(tmp_path)
    _, rows = run_recall.run(cfg, HERE / "fixture" / "recall.yaml", runs=3)
    slices = run_recall.by_type(rows)
    assert set(slices) == set(FLOORS), "every LongMemEval-style slice has items"
    for kind, floor in FLOORS.items():
        rate = slices[kind]["hits"] / slices[kind]["n"]
        misses = [r["q"] for r in rows if r["type"] == kind and not r["hit"]]
        assert rate >= floor, f"{kind}: {rate:.0%} < {floor:.0%}; misses: {misses}"


def test_eval_result_feeds_the_memory_traits(tmp_path: Path) -> None:
    cfg, _ = fixture_agent(tmp_path)
    _, rows = run_recall.run(cfg, HERE / "fixture" / "recall.yaml", runs=1)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "eval.json").write_text(
        json.dumps({"date": "2026-11-02", "runs": 1, "by_type": run_recall.by_type(rows)})
    )
    with Agent.from_config(cfg) as agent:
        tr = traits.compute(agent, agent.brain_status(), TODAY)
    sem = tr["semantic_memory"]["signals"]["stratified_recall"]
    epi = tr["episodic_memory"]["signals"]["temporal_recall"]
    assert sem["verdict"] == "defensible" and sem["n"] == 25 and sem["pct"] >= 90
    assert epi["verdict"] == "defensible" and (epi["value"], epi["n"]) == (3, 3)
    assert tr["episodic_memory"]["grown"] and tr["semantic_memory"]["grown"]


def test_gold_eval_result_feeds_the_memory_traits(tmp_path: Path) -> None:
    cfg, _ = fixture_agent(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    slices = {"reworded": (50, 75), "same": (20, 20), "temporal": (4, 8), "absent": (11, 12)}
    summary = {s: {"n": n, "hits": h} for s, (h, n) in slices.items()}
    (tmp_path / "data" / "eval.json").write_text(
        json.dumps({"date": "2026-11-12", "summary": summary, "rows": []})
    )
    with Agent.from_config(cfg) as agent:
        tr = traits.compute(agent, agent.brain_status(), TODAY)
    sem = tr["semantic_memory"]["signals"]["stratified_recall"]
    epi = tr["episodic_memory"]["signals"]["temporal_recall"]
    assert (sem["value"], sem["n"]) == (81, 107) and "reworded 50/75" in sem["note"]
    assert (epi["value"], epi["n"]) == (4, 8)


def test_thirty_days_of_sessions_grow_the_brain(tmp_path: Path) -> None:
    init_agent("Day1", tmp_path / "day1", False, user="Ada")
    with Agent.from_config(tmp_path / "day1" / "brain.yaml") as fresh:
        fresh.stores[:] = [s for s in fresh.stores if s.name != "hindsight"]
        day1 = traits.compute(fresh, fresh.brain_status(), TODAY)
    cfg, _ = fixture_agent(tmp_path / "day30")
    with Agent.from_config(cfg) as grown:
        day30 = traits.compute(grown, grown.brain_status(), TODAY)

    assert sum(t["grown"] for t in day30.values()) > sum(t["grown"] for t in day1.values())
    for tid, t in day30.items():
        for sid, s in t["signals"].items():
            if s["verdict"] != "defensible" or not s.get("n"):
                continue
            share = s["value"] / s["n"]
            if s["better"] == "higher":
                assert share > 0, f"{tid}.{sid} grew nothing: {s}"
            else:
                assert share < 1, f"{tid}.{sid} is all bad: {s}"
            d1 = day1[tid]["signals"][sid]
            if d1.get("n"):
                d1_share = d1["value"] / d1["n"]
                assert (share >= d1_share) if s["better"] == "higher" else (share <= d1_share), (
                    f"{tid}.{sid} moved the wrong way: day1 {d1}, day30 {s}"
                )
