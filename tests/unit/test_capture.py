"""brain capture: user messages and URLs from a transcript into the session file, incrementally."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brain_core.agent import Agent
from brain_core.capture import capture
from brain_core.cli.main import app

runner = CliRunner()


def line(role: str, content: object, uuid: str) -> str:
    return json.dumps(
        {
            "type": role,
            "uuid": uuid,
            "sessionId": "s1",
            "timestamp": "2026-11-03T05:00:00Z",
            "message": {"role": role, "content": content},
        }
    )


def test_capture_is_incremental_and_skips_tool_rows(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "bot", "--path", str(tmp_path)])
    t = tmp_path / "s1.jsonl"
    t.write_text(
        "\n".join(
            [
                line(
                    "user",
                    "please remember the deadline is 2026-12-01, spec at https://example.com/spec",
                    "u1",
                ),
                line(
                    "assistant",
                    [
                        {"type": "text", "text": "Reading https://docs.test/x now"},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la /tmp"}},
                    ],
                    "a1",
                ),
                line(
                    "user",
                    [{"type": "tool_result", "content": "total 0 files in the directory"}],
                    "u2",
                ),
                line("user", "my token is hsk_abcdefghijklmnop1234 keep it out", "u3"),
                line(
                    "assistant",
                    [
                        {
                            "type": "text",
                            "text": "badge https://x.test/b.svg; api http://127.0.0.1:8888/v1 ok",
                        },
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "curl https://cmd.test/x"},
                        },
                    ],
                    "a2",
                ),
            ]
        )
        + "\n"
    )
    with Agent.from_config(tmp_path / "brain.yaml") as agent:
        out = capture(agent, t, "s1")
        assert out["written"] == 4 and out["duplicate"] == 0 and out["queued"] == 4, out
        queue = (tmp_path / "data" / "hindsight_queue.jsonl").read_text().splitlines()
        assert len(queue) == 4  # Hindsight is never called from the hook
        day = next((tmp_path / "vault" / "sessions").glob("*.md")).read_text()
        assert "deadline is 2026-12-01" in day and "URL https://docs.test/x" in day
        assert "ls -la" not in day and "total 0 files" not in day  # tool rows are not speech
        assert "[redacted]" in day and "hsk_abcdefghijklmnop1234" not in day
        assert "b.svg" not in day and "127.0.0.1" not in day and "cmd.test" not in day
        again = capture(agent, t, "s1")
        assert again["written"] == 0 and again["scanned"] == 0  # cursor: nothing re-read
        with t.open("a") as f:
            f.write(line("user", "also: ship on Friday, not Thursday", "u4") + "\n")
        more = capture(agent, t, "s1")
        assert more["written"] == 1 and more["scanned"] == 1

    payload = {"session_id": "s1", "transcript_path": str(t), "hook_event_name": "Stop"}
    r = runner.invoke(app, ["capture", "--path", str(tmp_path)], input=json.dumps(payload))
    assert r.exit_code == 0 and r.stdout == ""  # hook mode is silent
    r = runner.invoke(app, ["capture", "--path", str(tmp_path), "--transcript", str(t)])
    assert r.exit_code == 0 and r.stdout.startswith("captured 0 new")


# ── checkpoint: what a compaction summary loses, read back from the transcript ──


def boundary() -> str:
    return json.dumps({"type": "system", "subtype": "compact_boundary", "sessionId": "s1"})


def summary() -> str:
    obj = json.loads(
        line("user", "This session is being continued from a previous conversation.", "sum")
    )
    return json.dumps({**obj, "isCompactSummary": True})


def compacted(tmp_path: Path, landed: bool = False) -> Path:
    """A session compacted once before, at the moment SessionStart fires for the second
    compaction. Claude Code writes that second boundary after the hook; `landed` adds it,
    with the summary and the /compact echo that follow it, in case that order ever changes."""
    after = [
        boundary(),
        summary(),
        line("user", "<command-name>/compact</command-name>", "c1"),
        line("user", "<local-command-stdout>Compacted</local-command-stdout>", "c2"),
    ]
    t = tmp_path / "s1.jsonl"
    t.write_text(
        "\n".join(
            [
                line("user", "first task: rename the config loader to load_settings", "u0"),
                boundary(),
                summary(),
                line("user", "now add retry with backoff to the uploader, three attempts", "u1"),
                line(
                    "assistant",
                    [
                        {"type": "text", "text": "Reading the uploader before changing it."},
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "/r/up.py"}},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}},
                    ],
                    "a1",
                ),
                line("user", [{"type": "tool_result", "content": "3 passed in 0.2s today"}], "r1"),
                line("user", "the log says compact_boundary twice, is that expected?", "u2"),
                line("user", "my token is hsk_abcdefghijklmnop1234 keep it out", "u3"),
                line("user", "use exponential backoff, base two seconds, " + "jitter " * 40, "u4"),
                line(
                    "assistant",
                    [
                        {"type": "tool_use", "name": "Write", "input": {"file_path": "/r/t_up.py"}},
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "/r/up.py"}},
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "/r/other.py"}},
                        {"type": "text", "text": "Retry is in; the backoff test still fails."},
                    ],
                    "a2",
                ),
            ]
            + (after if landed else [])
        )
        + "\n"
    )
    return t


@pytest.mark.parametrize("landed", [False, True])
def test_checkpoint_reads_only_the_stretch_just_compacted(tmp_path: Path, landed: bool) -> None:
    from brain_core.capture import REQUEST_CHARS, checkpoint

    cp = checkpoint(compacted(tmp_path, landed))
    asked = [ln[2:] for ln in cp.splitlines() if ln.startswith("- ")]
    # the newest three requests, oldest first; the fourth-newest is dropped
    assert len(asked) == 3 and asked[0].startswith("the log says compact_boundary"), cp
    assert "retry with backoff" not in cp
    assert asked[2].endswith("…") and len(asked[2]) == REQUEST_CHARS
    assert "[redacted]" in asked[1] and "hsk_abcdefghijklmnop1234" not in cp
    # nothing from before the previous compaction, its summary, or the /compact echo
    assert "rename the config loader" not in cp and "being continued" not in cp
    assert "command-name" not in cp and "Compacted" not in cp
    # edited files once each, most recently touched last; a file only read is not listed
    assert "Files edited: /r/t_up.py, /r/up.py" in cp and "other.py" not in cp
    assert "pytest -q" not in cp and "3 passed" not in cp  # tool rows are not speech
    assert "Last reply before the compaction: Retry is in; the backoff test still fails." in cp


def test_checkpoint_reads_the_whole_file_at_a_first_compaction(tmp_path: Path) -> None:
    from brain_core.capture import checkpoint

    # the first compaction of a session: no boundary is on disk yet when the hook runs
    t = tmp_path / "s2.jsonl"
    said = ["please fix the flaky upload test", "the log says compact_boundary twice, expected?"]
    t.write_text("\n".join(line("user", s, f"u{i}") for i, s in enumerate(said)) + "\n")
    asked = [ln[2:] for ln in checkpoint(t).splitlines() if ln.startswith("- ")]
    assert asked == said  # and a quoted word is not a boundary
    assert checkpoint(tmp_path / "missing.jsonl") == ""
    (tmp_path / "s3.jsonl").write_text(boundary() + "\n" + summary() + "\n")
    assert checkpoint(tmp_path / "s3.jsonl") == ""  # no speech anywhere


def test_brief_hook_adds_the_checkpoint_only_after_a_compaction(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "bot", "--path", str(tmp_path), "--lite"])
    t = compacted(tmp_path)

    def hook(source: str) -> str:
        payload = {"session_id": "s1", "transcript_path": str(t), "source": source}
        r = runner.invoke(
            app, ["brief", "--hook", "--path", str(tmp_path)], input=json.dumps(payload)
        )
        assert r.exit_code == 0, r.stdout
        return r.stdout

    brief = tmp_path / "vault" / "daily_brief.md"
    brief.unlink(missing_ok=True)
    assert hook("startup") == ""  # no brief, no compaction: the hook stays silent
    alone = json.loads(hook("compact"))["hookSpecificOutput"]["additionalContext"]
    assert alone.startswith("Task checkpoint") and "Daily brief" not in alone

    brief.write_text("# Daily Brief — 2026-11-03\n\n- x\n")
    both = json.loads(hook("compact"))["hookSpecificOutput"]["additionalContext"]
    assert both.startswith("Task checkpoint") and "Daily Brief — 2026-11-03" in both
    fresh = json.loads(hook("startup"))["hookSpecificOutput"]["additionalContext"]
    assert "Task checkpoint" not in fresh and "Daily Brief — 2026-11-03" in fresh
    with Agent.from_config(tmp_path / "brain.yaml") as agent:
        assert len(agent.recent_events(event_type="checkpoint_injected")) == 2
