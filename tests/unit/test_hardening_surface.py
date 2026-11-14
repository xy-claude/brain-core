"""Hardening of the tool surface: what the tool text tells the agent, the failed-command hook
and session start as plain searches, session files that are kept and checked, the crash flag
with two sessions open, and what status and doctor say about degraded recall and credentials."""

from __future__ import annotations

import asyncio
import json
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_type_hints

import pytest
import typer
from typer.testing import CliRunner

from brain_core import Agent, models, traits
from brain_core.cli.init import PACK, init_agent
from brain_core.cli.main import app, recall_cmd
from brain_core.embed import WorkerEmbedder
from brain_core.judge import JUDGE_MODEL
from brain_core.mcp.server import build_server
from brain_core.stores.transcripts import project_dir

runner = CliRunner()
SECTIONS = ("## Primary Objective", "## Top Missions", "## Pending Decisions")
GOOD = (
    "# Executive State\n\n## Primary Objective\nShip v1\n\n## Top Missions\n"
    "- M-1 the payroll move to the lunar office\n\n## Pending Decisions (Ada)\n- none\n"
)
PLAIN = "Objective: ship v1.\nPending:\n1. Rotate the keys\n2. Pick a name\n"


def bare(tmp_path: Path, executive: str | None = GOOD, extra: str = "") -> tuple[Path, Path]:
    """A vault and a brain.yaml with nothing else configured. Returns (brain.yaml, vault)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    if executive is not None:
        (vault / "executive_state.md").write_text(executive)
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(f"name: T\nstores:\n  vault: {vault}\n{extra}")
    return cfg, vault


def with_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    """A lite agent with the vector search and the model judge switched on, records waiting
    for a vector, and every way to reach a model recorded in the list returned."""
    out = tmp_path / "agent"
    init_agent("Atlas", out, False, user="Ada", lite=True)
    yaml = out / "brain.yaml"
    yaml.write_text(
        yaml.read_text()
        .replace("transcripts: ~/.claude/projects", f"transcripts: {tmp_path}/p")
        .replace("stores:\n", "stores:\n  vectors: {model: fake}\n", 1)
        + "\nrecall:\n  judge: model\n  runner: claude\n"
    )
    facts = out / "vault" / "facts.md"
    facts.write_text(
        facts.read_text() + "- The first mission is the payroll move, not started (2026-11-01)\n"
    )
    calls: list[str] = []

    def embed(self: WorkerEmbedder, texts: list[str], role: str = "document") -> list[bytes]:
        calls.append("embed")
        return [b"\0" * 8 for _ in texts]

    def model(*args: Any, **kwargs: Any) -> str:
        calls.append("model")
        return '{"picks": [], "status": "not_in_memory"}'

    monkeypatch.setenv("BRAIN_EMBED_HOME", str(tmp_path / "embed"))
    monkeypatch.setattr(WorkerEmbedder, "embed", embed)
    monkeypatch.setattr(WorkerEmbedder, "running", lambda self: False)
    for where in ("brain_core.agent", "brain_core.models"):  # wherever the judge finds them
        monkeypatch.setattr(f"{where}.run_claude", model, raising=False)
        monkeypatch.setattr(f"{where}.run_api", model, raising=False)
    with Agent.from_config(yaml) as agent:
        agent.brain_sync()  # the records are indexed and none has a vector yet
        assert agent.vectors is not None and agent.vectors.pending()
    return out, calls


def transcript(tmp_path: Path, out: Path, lines: list[str]) -> None:
    folder = project_dir(tmp_path / "p", out)
    folder.mkdir(parents=True)
    rows = [
        {
            "type": "user",
            "uuid": f"u{i}",
            "sessionId": "old-session",
            "timestamp": "2026-10-03T10:00:00Z",
            "message": {"content": text},
        }
        for i, text in enumerate(lines)
    ]
    (folder / "old-session.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def hook(out: Path, error: str) -> str:
    payload = {"session_id": "new-session", "error": error}
    r = runner.invoke(app, ["recall", "--hook", "--path", str(out)], input=json.dumps(payload))
    assert r.exit_code == 0, r.stdout
    return r.stdout


# ── CRITIC-1, SESSION-4: what the tool text tells the agent ───────────────────


def test_recall_asks_for_a_plain_question_and_describes_its_reply(tmp_path: Path) -> None:
    cfg, _ = bare(tmp_path)
    with Agent.from_config(cfg) as agent:
        tools = {t.name: t for t in asyncio.run(build_server(agent).list_tools())}
    recall = tools["brain_recall"]
    query = recall.inputSchema["properties"]["query"]["description"]
    assert "full question" in query and "exact name" in query
    assert "keywords beat" not in query
    for field in (
        "judged",
        "not_in_memory",
        "thin_recall",
        "weak_match",
        "degraded",
        "found_by",
        "undated",
    ):
        assert f"`{field}`" in (recall.description or ""), field
    assert "archive" in recall.inputSchema["properties"]["scope"]["description"]
    for name, tool in tools.items():  # a store that may not be there is not named as a layer
        assert "Hindsight" not in (tool.description or ""), name
    for name in ("brain_recall", "brain_remember", "brain_status"):
        assert "every configured store" in " ".join((tools[name].description or "").split()), name
    arg = get_type_hints(recall_cmd, include_extras=True)["query"].__metadata__[0]
    assert "full question" in arg.help and "keywords beat" not in arg.help
    # the command's own help too: this Click drops the help of a positional argument
    cli = typer.main.get_command(app).commands["recall"]  # type: ignore[attr-defined]
    assert "full question in plain words" in " ".join((cli.help or "").split())


def test_recall_is_marked_open_world_only_when_a_model_judges(tmp_path: Path) -> None:
    def open_world(extra: str, where: Path) -> bool | None:
        where.mkdir()
        cfg, _ = bare(where, extra=extra)
        with Agent.from_config(cfg) as agent:
            tools = {t.name: t for t in asyncio.run(build_server(agent).list_tools())}
        notes = tools["brain_recall"].annotations
        assert notes is not None
        return notes.openWorldHint

    assert open_world("", tmp_path / "a") is False
    # record text leaves for the model that judges: the annotation has to say so
    assert open_world("recall:\n  judge: model\n", tmp_path / "b") is True


def test_template_rules_name_no_store_that_may_be_absent() -> None:
    rules = PACK / ".claude" / "rules"
    memory = (rules / "04-memory.md").read_text()
    assert "Hindsight is the vector memory" not in memory and "→ Hindsight" not in memory
    assert "every other configured store" in memory
    for name in ("03-authority.md", "05-system.md"):
        assert "Hindsight" not in (rules / name).read_text(), name


# ── RECALL-7, OPS-5, LIVE-2 and the missed items: the hook and session start ──


def test_the_failure_hook_searches_for_the_error_not_the_first_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _calls = with_models(tmp_path, monkeypatch)
    transcript(
        tmp_path,
        out,
        [
            "Collecting requests from the mirror took a while yesterday",
            "ModuleNotFoundError: No module named mcp, fixed by uv sync",
        ],
    )
    ctx = json.loads(
        hook(
            out,
            "Exit code 1\nCollecting requests\nTraceback (most recent call last):\n"
            "  File \"x.py\", line 1, in <module>\nModuleNotFoundError: No module named 'mcp'",
        )
    )["hookSpecificOutput"]["additionalContext"]
    assert "fixed by uv sync" in ctx and "Collecting" not in ctx
    assert "possibly related" in ctx and "hit this error" not in ctx


def test_the_failure_hook_starts_no_model_logs_no_miss_and_is_silent_without_a_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, calls = with_models(tmp_path, monkeypatch)
    # one past line shares a word with the error: the search returns it, a match it is not
    transcript(tmp_path, out, ["fatal error while reading the gateway revision list"])
    printed = hook(
        out,
        "Exit code 2\nfatal: Needed a single revision\n"
        "error: could not parse the frobnicate manifest",
    )
    assert printed == ""
    assert calls == [], "a failed command must not start the embed worker or a model call"
    with Agent.from_config(out / "brain.yaml") as agent:
        assert agent.recent_events(event_type="recall_miss") == []
        assert agent.vectors is not None and agent.vectors.pending(), "nothing was embedded"


def test_session_start_recalls_missions_without_a_model_or_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, calls = with_models(tmp_path, monkeypatch)
    with Agent.from_config(out / "brain.yaml") as agent:
        s = agent.brain_session("start", "s1")
        (line, found), *_ = s["missions"].items()
        assert "first mission" in line and "payroll move" in found[0]["text"]
        assert calls == [], "session start must not start the embed worker or a model call"
        assert agent.recent_events(event_type="recall_miss") == []


# ── SESSION-2: session files are kept, checked, and never blanked ─────────────


def test_end_keeps_what_it_replaces_and_leaves_an_unpassed_critique_alone(
    tmp_path: Path,
) -> None:
    cfg, vault = bare(tmp_path)
    critique = vault / "session_critique.md"
    critique.write_text("# Critique\n\n## Apply Next Session\n- ask before deleting\n")
    was = critique.read_text()
    with Agent.from_config(cfg) as agent:
        agent.brain_session("start", "s1")
        e = agent.brain_session("end")  # nothing passed: nothing replaced, no stub
        assert e["critique"].startswith("unchanged") and critique.read_text() == was
        agent.brain_session("start", "s2")
        e = agent.brain_session("end", critique="   ")  # an empty body would blank the file
        assert e["critique"].startswith("unchanged") and critique.read_text() == was

        agent.brain_session("start", "s3")
        e = agent.brain_session(
            "end",
            executive_state=GOOD.replace("Ship v1", "Ship v2"),
            critique="# Critique\n\n## Apply Next Session\n- cite the source\n",
        )
    assert e["executive_state"] == "rewritten" and e["critique"] == "rewritten"
    assert "warning" not in e
    assert (vault / "executive_state.prev.md").read_text() == GOOD
    assert (vault / "session_critique.prev.md").read_text() == was
    assert "Ship v2" in (vault / "executive_state.md").read_text()
    assert "cite the source" in critique.read_text()
    assert not (vault / "last_standalone_session.prev.md").exists(), "the sync file is a stub"


def test_end_warns_when_the_executive_state_has_none_of_the_sections(tmp_path: Path) -> None:
    cfg, vault = bare(tmp_path)
    with Agent.from_config(cfg) as agent:
        agent.brain_session("start", "s1")
        e = agent.brain_session("end", executive_state=PLAIN)
        for heading in SECTIONS:
            assert heading in e["warning"], heading
        assert (vault / "executive_state.prev.md").read_text() == GOOD, "the last good one stays"

        s = agent.brain_session("start", "s2")
        for heading in SECTIONS:  # a visible note, not an empty string
            assert heading in s["executive_state"], heading
        assert s["missions"] == {}
        st = agent.brain_status()
        assert "pending_decisions" not in st, "0 would say nothing waits; two do"
        assert "## Pending Decisions" in st["executive_state"]
    doctor = runner.invoke(app, ["doctor", str(tmp_path)]).stdout
    assert "pending    executive_state.md has none of the sections" in doctor
    assert "0 decision(s)" not in doctor


def test_a_missing_executive_state_is_said_and_numbered_decisions_are_counted(
    tmp_path: Path,
) -> None:
    cfg, vault = bare(tmp_path, executive=None)
    with Agent.from_config(cfg) as agent:
        assert agent.brain_session("start", "s1")["executive_state"] == (
            "missing: executive_state.md"
        )
        assert agent.brain_status()["executive_state"] == "missing: executive_state.md"
        numbered = "## Pending Decisions\n1. Rotate the keys\n2) Pick a name\n- Clean four files\n"
        (vault / "executive_state.md").write_text(numbered)
        assert agent.brain_status()["pending_decisions"] == 3
        assert [r[0] for r in traits._pending_rows(numbered)] == [
            "Rotate the keys",
            "Pick a name",
            "Clean four files",
        ]


# ── SESSION-5: two sessions open at once, both closed cleanly ─────────────────


def test_two_overlapping_sessions_that_both_close_raise_no_crash_flag(tmp_path: Path) -> None:
    cfg, _ = bare(tmp_path)
    with Agent.from_config(cfg) as a, Agent.from_config(cfg) as b:
        a.brain_session("start", "A")
        b.brain_session("start", "B")
        b.brain_session("end")
        a.brain_session("end")  # the marker now holds A; the last session started was B
        assert a.brain_status()["session"]["unclosed"] is False
        assert a.brain_session("start", "C")["recovery"] is None
        # a session that never closed is still flagged
        assert b.brain_session("start", "D")["recovery"]["unclosed"] == "C"


# ── OPS-3 and the secrets display: what status and doctor say ─────────────────


def age(agent: Agent, days: int) -> None:
    agent.db.execute(
        "UPDATE events SET occurred_at = datetime('now', ?) WHERE event_type = 'recall_degraded'",
        (f"-{days} days",),
    )


def test_status_counts_recall_fallbacks_and_asks_for_attention_within_a_day(
    tmp_path: Path,
) -> None:
    cfg, _ = bare(tmp_path)
    with Agent.from_config(cfg) as agent:
        st = agent.brain_status()
        assert st["ok"] is True and "recall_degraded" not in st and "attention" not in st

        agent.log_event("recall_degraded", {"part": "vectors", "reason": "no numpy"})
        agent.log_event("recall_degraded", {"part": "judge", "reason": "login expired"})
        st = agent.brain_status()
        fell = st["recall_degraded"]
        assert (fell["window_days"], fell["count"], fell["last_day"]) == (7, 2, 2)
        assert fell["latest"].startswith("judge: login expired (") and "UTC" in fell["latest"]
        assert st["ok"] is False and "2 time(s) in the last day" in st["attention"][0]

        age(agent, 3)  # still counted for the week; no longer a reason to stop
        st = agent.brain_status()
        assert st["recall_degraded"]["count"] == 2 and st["recall_degraded"]["last_day"] == 0
        assert st["ok"] is True and "attention" not in st

        age(agent, 9)
        assert "recall_degraded" not in agent.brain_status()


def test_doctor_shows_vectors_and_judge_and_ends_with_attention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _calls = with_models(tmp_path, monkeypatch)
    doctor = runner.invoke(app, ["doctor", str(out)]).stdout
    assert "  vectors    fake · 0 rows · " in doctor and " waiting · worker down" in doctor
    # no recall.model in the config: the small model the judge really runs on, not "default"
    assert f"  judge      model · runner claude · model {JUDGE_MODEL}\n" in doctor
    # no record has a vector yet, so recall cannot search by meaning: said before any recall
    assert "fallback" not in doctor and "no record has a vector from fake" in doctor
    assert doctor.rstrip().endswith("Brain: ATTENTION")

    with Agent.from_config(out / "brain.yaml") as agent:
        agent.log_event("recall_degraded", {"part": "vectors", "reason": "the model did not load"})
        age(agent, 3)
        st = agent.brain_status()
        assert st["ok"] is False and "wait for a vector" in st["attention"][0]
    doctor = runner.invoke(app, ["doctor", str(out)]).stdout
    assert "fallback   recall fell back to keywords 1 time(s) in 7 days" in doctor
    assert "the model did not load" in doctor and "  attention  " in doctor
    assert doctor.rstrip().endswith("Brain: ATTENTION")


def test_status_and_doctor_say_how_many_indexed_records_hold_a_credential(
    tmp_path: Path,
) -> None:
    cfg, vault = bare(tmp_path)
    (vault / "facts.md").write_text("# Facts\n\n## System\n- The CI runs on a Mac mini\n")
    with Agent.from_config(cfg) as agent:
        agent.brain_sync()
        assert "secrets_masked" not in agent.brain_status()
        (vault / "facts.md").write_text(
            "# Facts\n\n## System\n- The CI runs on a Mac mini\n"
            "- deploy token ghp_abcdefghijklmnopqrstuvwxyz0123 for the CI\n"
        )
        agent.brain_sync()
        assert agent.brain_status()["secrets_masked"] == 1
    doctor = runner.invoke(app, ["doctor", str(tmp_path)]).stdout
    assert "secrets    1 indexed record(s) hold what looks like a credential" in doctor
    assert "ghp_" not in doctor


# ── the runners' time limit, and a cut mental model ───────────────────────────


def test_run_claude_honours_its_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": "fine"}), "")

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr("subprocess.run", run)
    assert models.run_claude("s", "p") == "fine" and seen["timeout"] == 600.0
    assert models.run_claude("s", "p", None, timeout=7) == "fine" and seen["timeout"] == 7

    def hang(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr("subprocess.run", hang)
    with pytest.raises(models.RunnerError, match="within 7 seconds"):
        models.run_claude("s", "p", timeout=7)


def test_run_api_honours_its_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []

    class APIConnectionError(Exception):
        pass

    class APITimeoutError(APIConnectionError):
        pass

    class Client:
        def with_options(self, *, timeout: float) -> Client:
            seen.append(timeout)
            return self

        @property
        def beta(self) -> Client:
            return self

        @property
        def messages(self) -> Client:
            return self

        def create(self, **kwargs: Any) -> SimpleNamespace:
            if seen[-1] < 1:
                raise APITimeoutError
            text = SimpleNamespace(type="text", text="fine")
            return SimpleNamespace(stop_reason="end_turn", content=[text])

    sdk = SimpleNamespace(
        Anthropic=Client,
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        RateLimitError=type("RateLimitError", (Exception,), {}),
        APIStatusError=type("APIStatusError", (Exception,), {}),
        APITimeoutError=APITimeoutError,
        APIConnectionError=APIConnectionError,
    )
    monkeypatch.setattr("importlib.import_module", lambda name: sdk)
    assert models.run_api("s", "p") == "fine"
    assert models.run_api("s", "p", "claude-haiku-5-5", timeout=20) == "fine"
    assert seen == [600.0, 20]
    with pytest.raises(models.RunnerError, match=r"did not answer within 0\.5 seconds"):
        models.run_api("s", "p", timeout=0.5)


def test_a_mental_model_cut_at_load_says_so(tmp_path: Path) -> None:
    init_agent("Atlas", tmp_path / "atlas", False, user="Ada", lite=True)
    cfg = tmp_path / "atlas" / "brain.yaml"
    cfg.write_text(
        cfg.read_text()
        + textwrap.dedent("""
        models:
          items:
            - {name: long-one, question: "What is long?"}
            - {name: short-one, question: "What is short?"}
        """)
    )
    folder = tmp_path / "atlas" / "vault" / "models"
    folder.mkdir()
    head = "---\ntype: model\n---\n# Title\n\n_A briefing, not a source._\n\n"
    bullets = "".join(f"- claim number {i} about the system [facts.md:{i}]\n" for i in range(80))
    assert len(bullets) > models.BODY_CHARS
    (folder / "long-one.md").write_text(head + bullets)
    (folder / "short-one.md").write_text(head + "- one claim [facts.md:3]\n")
    with Agent.from_config(cfg) as agent:
        loaded = models.load(agent)
    assert f"cut at {models.BODY_CHARS} of {len(bullets.strip())} characters" in loaded["long-one"]
    assert "models/long-one.md" in loaded["long-one"]
    assert "cut at" not in loaded["short-one"] and "one claim" in loaded["short-one"]


# ── SESSION-1: the model writer is told when a line has no date of its own ────


def test_the_model_writer_sees_undated_and_never_the_files_date(tmp_path: Path) -> None:
    init_agent("Atlas", tmp_path / "atlas", False, user="Ada", lite=True)
    cfg = tmp_path / "atlas" / "brain.yaml"
    cfg.write_text(
        cfg.read_text()
        + textwrap.dedent("""
        models:
          items:
            - {name: by-search, question: "What does Ada want for the quokka channel?"}
            - {name: by-kind, question: "zebra", kinds: [fact]}
        """)
    )
    facts = tmp_path / "atlas" / "vault" / "facts.md"
    facts.write_text(
        facts.read_text()
        + "- Ada wants the quokka channel back\n- The quokka channel was removed (2026-11-02)\n"
    )
    with Agent.from_config(cfg) as agent:
        assert agent.config.models is not None
        for item in agent.config.models.items:  # found by the search, then read by kind
            got = {r["text"]: r["date"] for r in models.gather(agent, item, 50)}
            assert got["Ada wants the quokka channel back"] == "undated", item.name
            assert got["The quokka channel was removed"] == "2026-11-02", item.name
    shown = runner.invoke(app, ["recall", "who wants the quokka channel back", "--path", str(cfg)])
    assert "[fact] undated facts.md:" in shown.stdout, "the shell prints no empty date either"


def test_the_copy_end_keeps_holds_a_stray_byte_as_it_was(tmp_path: Path) -> None:
    cfg, vault = bare(tmp_path)
    was = GOOD.encode() + b"- caf\xe9 budget is open\n"  # Latin-1, not UTF-8
    (vault / "executive_state.md").write_bytes(was)
    with Agent.from_config(cfg) as agent:
        agent.brain_session("start", "s-1")
        agent.brain_session("end", "s-1", executive_state=GOOD)
    # the stray byte is what must survive; text mode on Windows writes \r\n line ends
    assert (vault / "executive_state.prev.md").read_bytes().replace(b"\r\n", b"\n") == was
