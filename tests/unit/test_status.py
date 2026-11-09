"""brain_status: store health, knowledge lint, context tokens, session close state, pending."""

from __future__ import annotations

import textwrap
from pathlib import Path

from brain_core import Agent
from brain_core.stores import MemoryStore


def test_status_reports_everything(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "raw").mkdir()
    (vault / "knowledge" / "_index.md").write_text(
        "| [[good-page]] | sys | 2026-11-02 | ok |\n| [[ghost]] | | | |\n"
    )
    (vault / "knowledge" / "good-page.md").write_text("---\nsources: [raw/x.md]\n---\n# Good\n")
    (vault / "knowledge" / "orphan.md").write_text("# Orphan with no frontmatter\n")
    (vault / "raw" / "2026-11-02-x.md").write_text("---\ntype: raw\ncompiled_into: []\n---\nbody\n")
    (vault / "executive_state.md").write_text(
        "# E\n\n## Pending Decisions (Ada)\n| Decision | Why |\n|---|---|\n"
        "| Go public | cost |\n| Pick a name | taste |\n\n## Open Loops\n- x\n"
    )
    (tmp_path / "CLAUDE.md").write_text("x" * 400)
    (tmp_path / ".claude" / "rules").mkdir(parents=True)
    (tmp_path / ".claude" / "rules" / "01.md").write_text("y" * 800)
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(textwrap.dedent(f"name: T\nstores:\n  vault: {vault}\n"))
    with Agent.from_config(cfg) as a:
        a.stores.append(MemoryStore(healthy=False))
        a.brain_session("start", "s1")
        st = a.brain_status()
    assert st["ok"] is False
    assert (
        st["stores"]["sqlite"]["ok"]
        and st["stores"]["vault"]["ok"]
        and not st["stores"]["memory"]["ok"]
    )
    k = st["knowledge"]
    assert k["pages"] == 2 and k["raw"] == 1 and k["issue_count"] == 4
    assert {i.split(" ")[0] for i in k["issues"]} == {
        "orphan.md",
        "_index.md",
        "raw/2026-11-02-x.md",
    }
    assert st["pending_decisions"] == 2
    assert st["context"] == {"tokens": 300, "files": {".claude/rules/01.md": 200, "CLAUDE.md": 100}}
    assert st["session"] == {
        "last_start": "s1",
        "last_close": "",
        "current": "s1",
        "unclosed": False,
    }


def test_status_lists_what_recall_could_not_answer(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "facts.md").write_text(
        "# Facts\n\n## System\n- The staging cluster runs a helm chart\n"
    )
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(textwrap.dedent(f"name: T\nstores:\n  vault: {vault}\n"))
    with Agent.from_config(cfg) as a:
        assert "recall_misses" not in a.brain_status()
        a.brain_recall("helm chart staging")
        for _ in range(2):
            out = a.brain_recall("dentist appointment friday")
            assert "miss" not in out, "the flag is for the log, not for the reader"
        a.brain_recall("dentist appointment friday", offset=5)  # a later page is not a new miss
        a.brain_recall("wedding anniversary gift")
        misses = a.brain_status()["recall_misses"]
    assert misses["count"] == 3 and misses["window_days"] == 30
    assert misses["top"][0] == {"query": "dentist appointment friday", "count": 2, "best": 0.0}
