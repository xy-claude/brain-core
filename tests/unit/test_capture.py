"""brain capture: user messages and URLs from a transcript into the session file, incrementally."""

from __future__ import annotations

import json
from pathlib import Path

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
