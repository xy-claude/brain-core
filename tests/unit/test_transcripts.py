"""The transcript index: what gets in, what is redacted, incremental reindex, recall scope."""

from __future__ import annotations

import json
import re
from pathlib import Path

from brain_core.recall import brain_recall
from brain_core.storage.db import Database
from brain_core.stores.transcripts import TranscriptStore, index, project_dir


def _line(role: str, content: object, uuid: str, **extra: object) -> str:
    return json.dumps(
        {
            "type": role,
            "uuid": uuid,
            "sessionId": "abcd1234-5678",
            "timestamp": "2026-11-02T03:05:57.771Z",
            "message": {"content": content},
            **extra,
        }
    )


def _write_session(folder: Path) -> Path:
    folder.mkdir(parents=True)
    path = folder / "abcd1234-5678.jsonl"
    lines = [
        _line("user", "Why does the smoke test print tools: [] on the release commit?", "u1"),
        _line("user", "<local-command-caveat>ignore me</local-command-caveat>", "u2", isMeta=True),
        _line(
            "assistant",
            [
                {"type": "thinking", "thinking": "private"},
                {"type": "text", "text": "Closing stdin races the shutdown against the reply."},
                {"type": "tool_use", "name": "Bash", "input": {"command": "uv run pytest -q"}},
            ],
            "a1",
        ),
        _line(
            "user",
            [{"type": "tool_result", "content": "ModuleNotFoundError: No module named mcp"}],
            "u3",
        ),
        _line("assistant", [{"type": "text", "text": "token sk-" + "a" * 24 + " leaked"}], "a2"),
        _line(
            "assistant",
            [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {
                        "command": "security add-generic-password -s pypi -a me -w 0123456789abcdef"
                    },
                }
            ],
            "a3",
        ),
        json.dumps({"type": "attachment", "uuid": "x"}),
        "not json at all",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_project_dir_encodes_the_cwd_like_claude_code(tmp_path: Path) -> None:
    root = tmp_path / "Agents" / "Atlas"
    assert project_dir(tmp_path / "projects", root).name == str(root.resolve()).translate(
        str.maketrans("/_.:\\", "-----")
    )


def test_index_keeps_text_commands_results_and_redacts(db: Database, tmp_path: Path) -> None:
    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    _write_session(project_dir(tmp_path / "projects", agent_root))
    out = index(db, tmp_path / "projects", agent_root)
    assert out == {"files": 1, "added": 6}
    texts = [r["text"] for r in db.fetchall("SELECT text FROM transcripts ORDER BY rowid")]
    assert texts[0].startswith("Why does the smoke test")
    assert "ignore me" not in " ".join(texts)  # meta line skipped
    assert "private" not in " ".join(texts)  # thinking skipped
    assert "$ uv run pytest -q" in texts
    assert "→ ModuleNotFoundError: No module named mcp" in texts
    assert texts[-2] == "token [redacted] leaked"
    assert texts[-1] == "$ security add-generic-password -s pypi -a me -w [redacted]"
    assert "0123456789abcdef" not in " ".join(texts)


def test_reindex_reads_only_appended_lines(db: Database, tmp_path: Path) -> None:
    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    path = _write_session(project_dir(tmp_path / "projects", agent_root))
    index(db, tmp_path / "projects", agent_root)
    assert index(db, tmp_path / "projects", agent_root) == {"files": 1, "added": 0}
    with path.open("a", encoding="utf-8") as f:
        f.write(_line("user", "A second question about launchd plists", "u9") + "\n")
        f.write('{"type": "user", "uuid": "u10", "message": {"content": "half written')  # no \n
    assert index(db, tmp_path / "projects", agent_root) == {"files": 1, "added": 1}
    assert index(db, tmp_path / "projects", agent_root) == {"files": 1, "added": 0}


def test_recall_scope_transcript_finds_the_error(db: Database, tmp_path: Path) -> None:
    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    _write_session(project_dir(tmp_path / "projects", agent_root))
    store = TranscriptStore(db, tmp_path / "projects", agent_root)
    out = brain_recall([store], "ModuleNotFoundError mcp", scope="transcript", fmt="detailed")
    assert out["stores"] == {"transcripts": 1}
    hit = out["results"][0]
    assert hit["kind"] == "transcript" and "ModuleNotFoundError" in hit["text"]
    assert hit["date"] == "2026-11-02" and hit["source"].startswith("transcript://abcd1234")
    assert store.write("fact", "x").status == "refused"
    assert store.health()[0]


def test_missing_project_folder_is_healthy_and_empty(db: Database, tmp_path: Path) -> None:
    store = TranscriptStore(db, tmp_path / "projects", tmp_path / "agent")
    assert store.read("fact", "anything") == []
    ok, detail = store.health()
    assert ok and detail.startswith("transcripts: no sessions yet")


def test_recall_skips_lines_of_the_last_ten_minutes(db: Database, tmp_path: Path) -> None:
    from datetime import UTC, datetime

    agent_root = tmp_path / "agent"
    folder = project_dir(tmp_path / "projects", agent_root)
    folder.mkdir(parents=True)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    (folder / "live.jsonl").write_text(
        _line("user", "old question about widgets", "u1")
        + "\n"
        + _line("user", "widgets again, asked just now", "u2", timestamp=now)
    )
    store = TranscriptStore(db, tmp_path / "projects", agent_root)
    texts = [r.text for r in store.read("transcript", "widgets")]
    assert texts == ["[user] old question about widgets"]


def test_project_dir_falls_back_to_the_legacy_underscore_folder(tmp_path: Path) -> None:
    from brain_core.stores.transcripts import project_dir

    agent = tmp_path / "Agents" / "WEB_AI"
    agent.mkdir(parents=True)
    root = tmp_path / "projects"
    dashed = root / re.sub(r"[^A-Za-z0-9]", "-", str(agent.resolve()))
    legacy = root / re.sub(r"[^A-Za-z0-9_]", "-", str(agent.resolve()))
    assert project_dir(root, agent) == dashed  # neither exists: the current naming
    legacy.mkdir(parents=True)
    assert project_dir(root, agent) == legacy  # only the old folder exists
    dashed.mkdir(parents=True)
    assert project_dir(root, agent) == dashed  # the new one wins once it exists
