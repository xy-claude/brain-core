"""The twelve traits score from files; every defensible signal has a case that moves it."""

from __future__ import annotations

import json
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


def test_a_server_restart_inside_an_open_session_is_not_an_unopened_session(
    tmp_path: Path,
) -> None:
    agent, _ = make(tmp_path)
    with agent:
        agent.brain_session("start", "s1")
        agent.brain_remember("first note", "note")
        agent.start_session("mcp-aaaaaaaaaaaa")  # what `brain serve` does at every launch
        agent.brain_remember("after a restart, s1 still open", "note")
        agent.brain_session("end")
        agent.start_session("mcp-bbbbbbbbbbbb")
        agent.brain_remember("after the close, no new start", "note")
        agent.brain_session("start", "s2")
        agent.brain_remember("in the next session", "note")
        tr = traits.compute(agent, agent.brain_status(), TODAY)
    opened = tr["working_memory"]["signals"]["sessions_opened"]
    # the restart is part of s1, not a session of its own; the write after the close is a miss
    assert (opened["value"], opened["n"]) == (2, 3)


def test_a_new_conversation_after_a_crash_is_not_folded_into_the_crashed_session(
    tmp_path: Path,
) -> None:
    agent, _ = make(tmp_path)
    with agent:
        agent.brain_session("start", "s1")
        agent.brain_remember("s1 note", "note")
        # s1 crashed 13 hours ago: no end. A new conversation launches a server, never starts
        agent.db.execute(
            "UPDATE events SET occurred_at = datetime(occurred_at, '-13 hours') "
            "WHERE session_id = 's1'"
        )
        agent.start_session("mcp-cccccccccccc")
        late = agent.brain_remember("new conversation, no start", "note")
        tr = traits.compute(agent, agent.brain_status(), TODAY)
    opened = tr["working_memory"]["signals"]["sessions_opened"]
    assert (opened["value"], opened["n"]) == (1, 2), "the second conversation never started"
    assert "brain_session('start')" in late["hint"]


def test_confidence_spread_compares_the_level_not_the_whole_string(tmp_path: Path) -> None:
    agent, _ = make(tmp_path)
    with agent:  # the scaffold's own first decision says "high"
        agent.brain_remember("Ship on Friday", "decision", title="A", confidence="high")
        agent.brain_remember(
            "Keep the port", "decision", title="B", confidence="High: measured twice, same result"
        )
        agent.brain_remember("Wait a week", "decision", title="C", confidence="medium")
        tr = traits.compute(agent, agent.brain_status(), TODAY)
    spread = tr["metacognition"]["signals"]["confidence_spread"]
    assert (spread["value"], spread["n"]) == (1, 4), "three say high, one says medium"


def test_over_escalation_reads_the_whole_label() -> None:
    rows = [
        ["rename a file", "taste", "reversible × low-risk"],
        ["swap a colour", "taste", "Reversible x  Low-Risk"],
        ["buy the domain", "money", "irreversible × low-risk"],  # holds the word "reversible"
        ["delete the prod db", "money", "irreversible × high-risk"],
    ]
    sig = traits._authority(rows)["over_escalation"]
    assert (sig["value"], sig["n"]) == (2, 4)


def test_recurrence_counts_from_the_promotion_date_the_entry_states(tmp_path: Path) -> None:
    (tmp_path / "corrections.md").write_text(
        "# Corrections\n\n## Corrections\n\n"
        "### [2026-04-10] Called it close enough\n- **Theme:** execution\n"
        "- **Promoted:** Yes (2026-04-12)\n\n"
        "### [2026-04-11] Close enough again, before the rule existed\n- **Theme:** execution\n"
        "- **Promoted:** No\n\n"
        "### [2026-05-10] And once after it\n- **Theme:** execution\n- **Promoted:** No\n"
    )
    sig = traits._learning(tmp_path, TODAY)["correction_recurrence"]
    assert (sig["value"], sig["n"]) == (1, 1), "the correction of 04-11 came before the rule"


def test_repeat_cascades_counts_only_sessions_that_hold_a_write(tmp_path: Path) -> None:
    agent, _ = make(tmp_path)
    with agent:
        agent.brain_session("start", "s1")
        agent.brain_remember("one note", "note")
        agent.log_event("lessons_injected", {"titles": []}, session_id="a-hook-session")
        tr = traits.compute(agent, agent.brain_status(), TODAY)
    sig = tr["reasoning_planning"]["signals"]["repeat_cascades"]
    assert (sig["value"], sig["n"]) == (0, 1), "the hook's id holds no write"


def test_write_failures_names_the_partial_writes(tmp_path: Path) -> None:
    from datetime import datetime

    from brain_core.memory.episodic import Event

    events = [
        Event(i, "brain_remember", {"status": status}, None, datetime(2026, 11, 2))
        for i, status in enumerate(("written", "partial", "partial", "failed"))
    ]
    sig = traits._execution(events, tmp_path, "daily_brief.md", TODAY)["write_failures"]
    assert (sig["value"], sig["n"], sig["better"]) == (1, 4, "lower")
    assert "2 more were partial" in sig["note"]


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


def test_calibration_scores_resolved_decisions_only() -> None:
    from brain_core.stores.base import Record

    def dec(text: str, conf: str, d: date) -> Record:
        return Record("id-" + text, "decision", text, d, "", "", 0, {"confidence": conf})

    decisions = [
        dec("Deploy the fare engine on Friday", "high", date(2026, 9, 1)),  # old, no correction
        dec("Skip the staging rehearsal", "high", date(2026, 10, 1)),  # named by a correction
        dec("Rename the module", "medium", date(2026, 10, 30)),  # too young: censored
    ]
    corrections = [
        (
            date(2026, 10, 5),
            "Skipped the staging rehearsal and broke prod",
            {"error": "staging rehearsal skipped"},
        )
    ]
    out = traits.calibration(decisions, corrections, TODAY)
    assert out is not None and out["n"] == 2 and out["better"] == "lower"
    # (0.9-1)^2 = 0.01 for the good one, (0.9-0)^2 = 0.81 for the bad one -> 0.41
    assert out["value"] == 0.41
    assert traits.calibration(decisions[2:], corrections, TODAY) is None


def test_calibration_does_not_fail_a_decision_on_short_or_common_shared_words() -> None:
    from brain_core.stores.base import Record

    def dec(text: str, d: date) -> Record:
        return Record("id-" + text, "decision", text, d, "", "", 0, {"confidence": "high"})

    decisions = [
        dec("Run brain core from the tool install", date(2026, 9, 1)),
        dec("Archive sessions after brain weekly", date(2026, 9, 2)),
        dec("Hindsight replaced with the archive store", date(2026, 9, 3)),
        dec("Replace the brain index in one pass", date(2026, 9, 4)),
    ]
    # none is about a decision above: each shares one telling word at most
    corrections: list[tuple[date, str, dict[str, str]]] = [
        (date(2026, 10, 5), "Called the brain core release done too early", {}),
        (date(2026, 10, 6), "Asked again after the brain answered", {}),
        (date(2026, 10, 7), "Replaced a figure with a guess", {}),
        (date(2026, 10, 8), "Replaced the wrong brain file", {}),  # "brain" is in most titles
    ]
    out = traits.calibration(decisions, corrections, TODAY)
    assert out is not None and (out["value"], out["n"]) == (0.01, 4), "all four held"


def test_missions_and_pending_ages_helpers(tmp_path: Path) -> None:
    q = tmp_path / "mission_queue.md"
    q.write_text(
        "| ID | Mission | Priority | Status | Next step | Last reviewed |\n"
        "|---|---|---|---|---|---|\n"
        "| M-1 | a | P1 | done | - | 2026-01-01 |\n| M-2 | b | P2 | active | x | 2026-10-01 |\n"
    )
    assert [m["id"] for m in traits.missions(q)] == ["M-1", "M-2"]
    assert [(m["id"], d) for m, d in traits.stalled(q, TODAY)] == [("M-2", 32)]
    (tmp_path / "pending_seen.json").write_text(json.dumps({"x": "2026-10-20"}))
    assert traits.pending_ages(tmp_path, [["x"], ["y"]], TODAY) == {"x": 13}


def test_a_pending_decision_keeps_its_age_when_its_row_number_changes(tmp_path: Path) -> None:
    from brain_core import cron

    def rows(*decisions: str) -> list[list[str]]:
        table = "".join(
            f"| {n} | {d} | reversible × low-risk |\n" for n, d in enumerate(decisions, 1)
        )
        return traits._pending_rows(
            "## Pending Decisions\n| # | Decision | Classification |\n|---|---|---|\n" + table
        )

    first = rows("buy the domain", "rename a file")
    assert cron._track_pending(tmp_path, first, date(2026, 10, 20)) == {
        "buy the domain": 0,
        "rename a file": 0,
    }
    # the first one is settled: the second moves up to row 1 and a new one takes row 2
    later = rows("rename a file", "pick a colour")
    cron._track_pending(tmp_path, later, date(2026, 10, 30))
    assert traits.pending_ages(tmp_path, later, TODAY) == {"rename a file": 13, "pick a colour": 3}


def test_mission_files_with_frontmatter_win_over_the_table(tmp_path: Path) -> None:
    goals = tmp_path / "goals"
    (goals / "missions").mkdir(parents=True)
    (goals / "mission_queue.md").write_text(
        "| ID | Mission |\n|---|---|\n| M-9 | from the table |\n"
    )
    (goals / "missions" / "M-001.md").write_text(
        '---\nmission_id: "M-001"\ntitle: "Ship it"\nstatus: active\npriority: 1\n'
        "last_reviewed: 2026-09-01\nnext_step: tag v1\n---\n# Ship it\n"
    )
    (goals / "missions" / "README.md").write_text("no frontmatter, not a mission\n")
    got = traits.missions(goals / "mission_queue.md")
    assert got == [
        {
            "id": "M-001",
            "mission": "Ship it",
            "priority": "1",
            "status": "active",
            "next": "tag v1",
            "reviewed": "2026-09-01",
        }
    ]
    assert [m["id"] for m, _d in traits.stalled(goals / "mission_queue.md", TODAY)] == ["M-001"]
