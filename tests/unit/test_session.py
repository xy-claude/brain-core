"""brain_session start/end against a tmp vault, a fake Hindsight, and the real SQLite journal."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

from brain_core import Agent
from brain_core.stores.hindsight import HindsightStore


class FakeHindsight(HindsightStore):
    def __init__(self) -> None:
        super().__init__("http://127.0.0.1:1", "t", "T")
        self.retained: list[dict[str, Any]] = []

    def call(self, tool: str, **args: Any) -> Any:
        if tool == "get_mental_model":
            return {"content": f"model {args['mental_model_id']} body"}
        if tool == "retain":
            self.retained.append(args)
            return {"status": "accepted"}
        if tool == "recall":
            return {"results": []}
        raise AssertionError(tool)


def make(tmp_path: Path, *, queue: bool = True) -> tuple[Agent, Path, FakeHindsight]:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "daily_brief.md").write_text("# Daily Brief — 2026-10-30\n\n## Hot Corrections\n- x\n")
    (vault / "executive_state.md").write_text(
        "---\ntype: log\n---\n# Executive State\n\n## Primary Objective\nShip v1\n\n"
        "## Top Missions\n- **M-1** v1 MVP iOS first\n- M-2 brain-core v0.2\n\n"
        "## Pending Decisions (Ada)\n- none\n\n## Open Loops\n- lots\n"
    )
    (vault / "inbox_staged.md").write_text("# Inbox\n- item one\n- item two\n")
    (vault / "last_standalone_session.md").write_text("## T — own sync, must be skipped\n")
    (tmp_path / "OTHER").mkdir()
    (tmp_path / "OTHER" / "last_standalone_session.md").write_text("## OTHER — shipped v2\n")
    q = tmp_path / "queue.jsonl"
    q.write_text(
        json.dumps({"agent": "T", "content": "mine", "context": "hsam-conversation", "tags": []})
        + "\n"
        + json.dumps({"agent": "OTHER", "content": "theirs"})
        + "\n"
    )
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(
        textwrap.dedent(f"""\
        name: T
        stores:
          vault: {vault}
        session:
          mental_models: [active-priorities, user-working-style]
          peers: ['{tmp_path}/*/last_standalone_session.md']
          queue: {q if queue else "null"}
        """)
    )
    agent = Agent.from_config(cfg)
    fake = FakeHindsight()
    agent.stores.append(fake)
    return agent, vault, fake


def test_start_block_and_recovery_flag(tmp_path: Path) -> None:
    agent, _vault, _ = make(tmp_path)
    with agent:
        s = agent.brain_session("start", "s1")
        assert s["session_id"] == "s1" and s["recovery"] is None
        assert s["brief"].startswith("# Daily Brief") and s["brief_stale"] is True
        assert (
            "## Primary Objective" in s["executive_state"]
            and "Open Loops" not in s["executive_state"]
        )
        assert s["inbox"] == 2
        assert s["peers"].startswith("### OTHER (") and "shipped v2" in s["peers"]
        assert "own sync" not in s["peers"]
        assert s["mental_models"] == {
            "active-priorities": "model active-priorities body",
            "user-working-style": "model user-working-style body",
        }
        assert list(s["missions"]) == ["M-1 v1 MVP iOS first", "M-2 brain-core v0.2"]
        # a second start without an end → previous session flagged
        s2 = agent.brain_session("start", "s2")
        assert s2["recovery"] == {"unclosed": "s1", "started": s2["recovery"]["started"]}


def test_end_drains_queue_writes_stubs_and_marker(tmp_path: Path) -> None:
    agent, vault, fake = make(tmp_path)
    try:
        agent.brain_session("start", "s1")
        agent.brain_remember("Hindsight runs on 8887", "fact", domain="system")
        agent.brain_remember("Hindsight runs on 8888", "fact", domain="system")
        agent.brain_remember("Self-host before paying", "decision", title="Self-host")
        e = agent.brain_session("end", sync="## T — Session Sync\n**Status:** fine")
        assert agent.brain_session("start", "s3")["recovery"] is None, "clean close, no recovery"
    finally:
        agent.close()
    assert e["writes"] == 3 and e["queue_drained"] == 1
    assert [r["content"] for r in fake.retained].count("mine") == 1, "queue entry retained once"
    docs = [r["document_id"] for r in fake.retained]
    assert len(set(docs)) == len(docs), "a shared document id makes Hindsight drop earlier writes"
    assert json.loads((tmp_path / "queue.jsonl").read_text())["agent"] == "OTHER"
    assert e["hsam"] == "written" and e["executive_state"].startswith("unchanged")
    assert e["critique"] == "stub" and e["sync"] == "rewritten"
    crit = (vault / "session_critique.md").read_text()
    assert crit.startswith("---\ntype: log\nowner: t\n") and "Fact changed" in crit
    assert "**Status:** fine" in (vault / "last_standalone_session.md").read_text()
    assert Path(e["marker"]).read_text().strip() == "s1"
    day = next((vault / "sessions").glob("*.md")).read_text()
    assert "closed" in day and "decision×1, fact×2" in day


def test_end_without_session_is_an_error(tmp_path: Path) -> None:
    agent, _, _ = make(tmp_path, queue=False)
    with agent:
        try:
            agent.brain_session("end")
        except ValueError as e:
            assert "no active session" in str(e)
        else:
            raise AssertionError("expected ValueError")


def test_end_refuses_secrets_in_files_and_drops_them_from_the_queue(tmp_path: Path) -> None:
    agent, vault, fake = make(tmp_path)
    q = tmp_path / "queue.jsonl"
    q.write_text(
        q.read_text()
        + json.dumps({"agent": "T", "content": "token ghp_abcdefghijklmnopqrstuvwxyz0123"})
        + "\n"
    )
    try:
        agent.brain_session("start", "s9")
        e = agent.brain_session(
            "end", critique="# Critique\n\nused ghp_abcdefghijklmnopqrstuvwxyz0123 today"
        )
    finally:
        agent.close()
    assert e["critique"].startswith("refused") and e["queue_drained"] == 1
    assert not (vault / "session_critique.md").exists(), "a refused body writes nothing"
    assert "ghp_" not in q.read_text() and "ghp_" not in json.dumps(fake.retained)


def test_end_reports_which_trait_signals_moved(tmp_path: Path) -> None:
    agent, vault, _ = make(tmp_path)
    (vault / "decisions_log.md").write_text("---\ntype: log\n---\n# Decisions Log\n")
    try:
        agent.brain_session("start", "s7")
        snap = json.loads((agent.data_dir / "traits_start.json").read_text())
        assert snap["session_id"] == "s7"
        agent.brain_remember("Ship it", "decision", title="Ship", confidence="high")
        agent.brain_remember("Wait", "decision", title="Wait", confidence="low")
        e = agent.brain_session("end")
    finally:
        agent.close()
    moved = e["traits_moved"]
    assert any(m.startswith("decision.classified:") for m in moved), moved
    assert any(m.startswith("metacognition.confidence_spread:") for m in moved), moved
    day = next((vault / "sessions").glob("*.md")).read_text()
    assert "trait signal(s) moved" in day


def test_start_omits_the_brief_when_the_sessionstart_hook_injected_it(tmp_path: Path) -> None:
    agent, _vault, _ = make(tmp_path)
    with agent:
        agent.log_event("brief_injected", {"session_id": "claude-1"})
        s = agent.brain_session("start", "s1")
        assert s["brief"].startswith("injected at SessionStart") and "Daily Brief" not in s["brief"]
        assert s["brief_stale"] is True  # staleness is still judged from the file


def test_sections_match_headings_regardless_of_case() -> None:
    from brain_core.session import _sections

    text = "## Apply next session\n- a\n\n## WHAT TO IMPROVE\n- b\n\n## Other\n- c\n"
    out = _sections(text, ("Apply Next Session", "What To Improve"))
    assert "- a" in out and "- b" in out and "- c" not in out
