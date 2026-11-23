"""0.18.2: a workspace's brain.yaml found from a repo inside it, a quiet no-memory mode for
hooks and `brain serve`, `transcripts_cwd` as a list, and peers labelled by their own name."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brain_core.agent import Agent
from brain_core.cli.main import _find, app
from brain_core.storage.db import Database
from brain_core.stores.transcripts import TranscriptStore, project_dir

runner = CliRunner()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return h


def _workspace(home: Path) -> Path:
    ws = home / "Projects" / "acme"
    (ws / "acme-api" / "src").mkdir(parents=True)
    (ws / "brain.yaml").write_text("name: ACME\nstores:\n  vault: ./.brain/notes\n")
    return ws


def test_find_walks_up_from_the_project_dir(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _workspace(home)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(ws / "acme-api" / "src"))
    assert _find(Path()) == (ws / "brain.yaml").resolve()


def test_find_uses_the_working_directory_without_the_env(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(home)
    monkeypatch.chdir(ws / "acme-api")
    assert _find(Path()) == (ws / "brain.yaml").resolve()


def test_find_stops_below_the_home_folder(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (home / "brain.yaml").write_text("name: EVERYTHING\n")  # would capture every project
    (home / "Projects" / "plain").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(home / "Projects" / "plain"))
    assert _find(Path()) is None


def test_find_outside_home_checks_only_the_start_folder(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "brain.yaml").write_text("name: ABOVE\n")
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "elsewhere"))
    assert _find(Path()) is None


def test_an_explicit_path_does_not_walk_up(home: Path) -> None:
    ws = _workspace(home)
    assert _find(ws / "acme-api") is None
    assert _find(ws) == ws / "brain.yaml"
    assert _find(ws / "brain.yaml") == ws / "brain.yaml"


def test_hooks_are_quiet_where_there_is_no_memory(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = home / "Projects" / "plain"
    plain.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(plain))
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("")
    calls = [
        (["brief", "--hook"], {"session_id": "s"}),
        (["capture"], {"transcript_path": str(transcript), "session_id": "s"}),
        (["recall", "--hook"], {"error": "Exit code 1 boom", "session_id": "s"}),
        (["lessons", "--hook"], {"prompt": "fix the build", "session_id": "s"}),
    ]
    for args, payload in calls:
        r = runner.invoke(app, args, input=json.dumps(payload))
        assert r.exit_code == 0, (args, r.output)
        assert r.stdout == "", (args, r.stdout)
    r = runner.invoke(app, ["doctor"])  # not a hook: say so
    assert r.exit_code == 1 and "no brain.yaml" in r.output


def test_a_hook_in_a_nested_repo_writes_to_the_workspace(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = home / "Projects" / "acme"
    runner.invoke(app, ["init", "ACME", "--path", str(ws), "--lite"])
    (ws / "acme-api").mkdir()
    (ws / "vault" / "daily_brief.md").write_text("# Daily Brief, acme\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(ws / "acme-api"))
    r = runner.invoke(app, ["brief", "--hook"], input=json.dumps({"session_id": "c1"}))
    assert r.exit_code == 0, r.output
    assert "Daily Brief, acme" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_serve_without_memory_runs_a_server_with_no_tools(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import brain_core.mcp.server as server

    ran: list[str] = []
    monkeypatch.setattr(server, "run_empty", lambda: ran.append("empty"))
    monkeypatch.setattr(server, "run_server", lambda cfg: ran.append(str(cfg)))
    plain = home / "Projects" / "plain"
    plain.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(plain))
    assert runner.invoke(app, ["serve"]).exit_code == 0
    assert ran == ["empty"]
    bad = runner.invoke(app, ["serve", str(plain)])  # an explicit path stays an error
    assert bad.exit_code == 1 and ran == ["empty"]


def _session(folder: Path, sid: str, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    line = {
        "type": "user",
        "uuid": sid,
        "sessionId": sid,
        "timestamp": "2026-11-02T03:05:57.771Z",
        "message": {"content": text},
    }
    (folder / f"{sid}.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")


def test_transcripts_cwd_takes_a_list(db: Database, tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    ws, repo = tmp_path / "ws", tmp_path / "ws" / "repo"
    repo.mkdir(parents=True)
    _session(project_dir(projects, ws), "aaaa1111", "the workspace root session about pelicans")
    _session(project_dir(projects, repo), "bbbb2222", "the nested repo session about pelicans")
    store = TranscriptStore(db, projects, [ws, repo])
    assert store.index() == {"files": 2, "added": 2}
    texts = {r.text for r in store.read("transcript", "pelicans")}
    assert any("workspace root" in t for t in texts) and any("nested repo" in t for t in texts)
    assert store.health()[0] is True


def test_brain_yaml_accepts_a_list_of_transcript_folders(tmp_path: Path) -> None:
    (tmp_path / "vault").mkdir()
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(
        textwrap.dedent(f"""\
        name: T
        stores:
          vault: ./vault
          transcripts: {tmp_path / "projects"}
          transcripts_cwd: [{tmp_path / "a"}, {tmp_path / "b"}]
        """)
    )
    with Agent.from_config(cfg) as agent:
        store = next(s for s in agent.stores if isinstance(s, TranscriptStore))
        assert store.agent_roots == [tmp_path / "a", tmp_path / "b"]


def test_a_workspace_peer_is_labelled_by_its_name(tmp_path: Path) -> None:
    notes = tmp_path / "acme" / ".brain" / "notes"
    notes.mkdir(parents=True)
    (tmp_path / "acme" / "brain.yaml").write_text("name: ACME\nstores:\n  vault: ./.brain/notes\n")
    (notes / "last_standalone_session.md").write_text("## shipped the api\n")
    (tmp_path / "me").mkdir()
    cfg = tmp_path / "me" / "brain.yaml"
    cfg.write_text(
        textwrap.dedent(f"""\
        name: ME
        stores:
          vault: ./vault
        session:
          peers: ['{tmp_path}/*/.brain/notes/last_standalone_session.md']
        """)
    )
    (tmp_path / "me" / "vault").mkdir()
    with Agent.from_config(cfg) as agent:
        peers = agent.brain_session("start", "s1")["peers"]
    assert peers.startswith("### ACME (") and "shipped the api" in peers
