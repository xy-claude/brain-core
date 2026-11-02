"""The twelve traits score from files; every defensible signal has a case that moves it."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from brain_core import Agent, traits
from brain_core.cli.init import init_agent

TODAY = date(2026, 11, 2)


def make(tmp_path: Path) -> tuple[Agent, Path]:
    init_agent("Atlas", tmp_path / "atlas", False, user="Ada")
    vault = tmp_path / "atlas" / "vault"
    (vault / "corrections.md").write_text(
        "---\ntype: log\n---\n# Corrections\n\n## Corrections\n\n"
        "### [2026-10-01] Claimed done without output\n- **Error:** e\n- **Correction:** c\n"
        "- **Implied rule:** r\n- **Theme:** verification\n- **Promoted:** Yes\n\n"
        "### [2026-10-20] Claimed done again\n- **Error:** e\n- **Correction:** c\n"
        "- **Implied rule:** r\n- **Theme:** verification\n- **Promoted:** No\n\n"
        "### [2026-10-25] Too long an answer\n- **Error:** e\n- **Correction:** c\n"
        "- **Implied rule:** r\n- **Theme:** tone\n- **Promoted:** No\n"
    )
    (vault / "facts.md").write_text(
        "---\ntype: reference\nupdated: 2026-11-01\n---\n# Facts\n\n## System\n"
        "- API on port 8887 (2026-10-01)\n"
        "- **⚠ Fact changed 2026-10-15:** API on port 8888 (was: API on port 8887) (2026-10-15)\n"
        "- undated legacy fact\n"
    )
    (vault / "sessions" / "2026-10-20.md").write_text(
        "---\ntype: session\n---\n# Session Archive — 2026-10-20\n\n## What We Discussed\n"
        "- still calling API on port 8887 here\n"
    )
    (vault / "goals" / "mission_queue.md").write_text(
        "---\ntype: log\n---\n# Mission Queue\n\n"
        "| ID | Mission | Priority | Status | Next step | Last reviewed |\n"
        "|---|---|---|---|---|---|\n"
        "| M-001 | fresh | P1 | active | x | 2026-11-01 |\n"
        "| M-002 | stalled | P2 | blocked | y | 2026-09-01 |\n"
        "| M-003 | finished | P3 | done | - | 2026-08-01 |\n"
    )
    (vault / "executive_state.md").write_text(
        "---\ntype: log\n---\n# Executive State\n\n## Primary Objective\nx\n\n"
        "## Pending Decisions (Ada)\n| Decision | Why | Classification |\n|---|---|---|\n"
        "| rename a file | taste | reversible × low-risk |\n"
        "| delete the prod db | money | irreversible × high-risk |\n"
    )
    (vault / "procedures" / "deploy.md").write_text(
        "---\nstatus: active\nlast_validated: 2026-10-30\n---\n# Deploy\n"
    )
    (vault / "procedures" / "old.md").write_text(
        "---\nstatus: active\nlast_validated: 2026-08-01\n---\n# Old\n"
    )
    agent = Agent.from_config(tmp_path / "atlas" / "brain.yaml")
    agent.stores[:] = [s for s in agent.stores if s.name != "hindsight"]
    return agent, vault


def test_every_trait_is_reported_with_its_signals(tmp_path: Path) -> None:
    agent, _ = make(tmp_path)
    with agent:
        st = agent.brain_status()
    tr = st["traits"]
    assert list(tr) == [t["id"] for t in traits.load(None)] and len(tr) == 12
    for t in tr.values():
        assert t["signals"] and all(
            s["verdict"] in ("defensible", "cost", "pending") for s in t["signals"].values()
        )


def test_signals_move_with_the_evidence(tmp_path: Path) -> None:
    agent, _ = make(tmp_path)
    with agent:
        agent.brain_session("start", "s1")
        agent.brain_remember("Self-host first", "decision", title="A", confidence="high")
        agent.brain_remember("Pay later", "decision", title="B", confidence="low")
        for _ in range(3):
            agent.brain_remember("same note", "note")
        st = agent.brain_status()
        tr = traits.compute(agent, st, TODAY)
    s = {k: v["signals"] for k, v in tr.items()}
    assert s["learning"]["correction_recurrence"]["value"] == 1, (
        "verification recurred after promotion"
    )
    leaks = s["learning"]["fact_update_leaks"]
    assert (leaks["value"], leaks["n"], leaks["verdict"]) == (1, 1, "defensible")
    assert (
        s["semantic_memory"]["facts_dated"]["value"] == 2
        and s["semantic_memory"]["facts_dated"]["n"] == 3
    )
    assert s["procedural_memory"]["procedures_validated"] == {
        "value": 1,
        "n": 2,
        "verdict": "defensible",
        "better": "higher",
        "note": "procedures validated within 30 days",
    }
    assert (
        s["goal_management"]["missions_stalled"]["value"] == 1
        and s["goal_management"]["missions_stalled"]["n"] == 2
    )
    assert (
        s["authority"]["over_escalation"]["value"] == 1
        and s["authority"]["over_escalation"]["n"] == 2
    )
    assert s["user_model"]["style_corrections"]["value"] == 1
    assert s["working_memory"]["sessions_opened"] == {
        "value": 1,
        "n": 1,
        "verdict": "defensible",
        "better": "higher",
        "note": "sessions with writes that called brain_session('start') first",
    }
    assert s["reasoning_planning"]["repeat_cascades"]["value"] == 1, (
        "three identical writes in a row, even when deduped, is one cascade"
    )
    assert s["metacognition"]["confidence_spread"]["value"] >= 1
    assert s["decision"]["classified"]["n"] >= 3
    assert tr["learning"]["grown"] and not tr["episodic_memory"]["grown"]


def test_ratios_become_percentages_only_past_min_n() -> None:
    assert "pct" not in traits._ratio(3, 10, "x")
    assert traits._ratio(15, 20, "x")["pct"] == 75


def test_one_line_and_brief_section(tmp_path: Path) -> None:
    agent, _ = make(tmp_path)
    from brain_core import cron

    with agent:
        st = agent.brain_status()
        line = traits.one_line(st["traits"])
        section = cron._traits(st["traits"])
    assert "learning=1/1" in line and "authority=1/2" in line
    assert section.startswith("## Traits") and section.count("\n- ") == 12
