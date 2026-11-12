"""Mental models: cited briefings in vault/models/, stale only when what they rest on moves."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from brain_core import Agent, models
from brain_core.cli.init import init_agent

TODAY = date(2026, 11, 12)


def make(tmp_path: Path, extra: str = "") -> Agent:
    init_agent("Atlas", tmp_path / "atlas", False, user="Ada", lite=True)
    cfg = tmp_path / "atlas" / "brain.yaml"
    cfg.write_text(
        cfg.read_text()
        + "\nmodels:\n  items:\n    - name: working-style\n"
        + "      question: How does the user like to work?\n      kinds: [pattern]\n"
        + extra
    )
    agent = Agent.from_config(cfg)
    agent.brain_remember("Wants proof before a claim of done", "pattern", title="Proof first")
    agent.brain_remember("Prefers short answers in tables", "pattern", title="Tables")
    return agent


def num(prompt: str, word: str) -> str:
    """The [n] the prompt gave the record that holds ``word``."""
    line = next(ln for ln in prompt.splitlines() if word in ln and ln.startswith("["))
    return line.split("]")[0] + "]"


def answer(text: str) -> models.Runner:
    """A runner that cites by word: ``{proof}`` becomes the number of the record holding it."""

    def run(system: str, prompt: str) -> str:
        out = text
        for word in ("proof", "tables"):
            if "{" + word + "}" in out:
                out = out.replace("{" + word + "}", num(prompt, word))
        return out

    return run


def test_a_model_is_written_with_sources_and_uncited_claims_are_dropped(tmp_path: Path) -> None:
    with make(tmp_path) as a:
        seen: list[str] = []

        def run(system: str, prompt: str) -> str:
            seen.append(prompt)
            return (
                "Here is the briefing.\n## Style\n"
                f"- Show proof before saying done {num(prompt, 'proof')}\n"
                f"- Likes tables {num(prompt, 'tables')}\n- Loves long essays\n"
                "- Cites nothing real [99]\n- Unknown: how they like to be greeted"
            )

        out = models.refresh(a, run=run, today=TODAY)
        assert out["working-style"].endswith("read, 2 cited, 2 uncited claim(s) dropped")
        assert "(pattern, " in seen[0] and "Question: How does the user like to work?" in seen[0]
        (tmp_path / "atlas" / "vault" / "patterns.md").open("a").write(
            "- **Token** — the deploy token is ghp_" + "a1B2" * 9 + " (2026-11-01)\n"
        )
        assert all("ghp_" not in r["text"] for r in models.gather(a, a.config.models.items[0], 50))  # type: ignore[union-attr]
        text = (tmp_path / "atlas" / "vault" / "models" / "working-style.md").read_text()
        assert "- Show proof before saying done [patterns.md:" in text
        assert "essays" not in text and "Cites nothing" not in text and "briefing." not in text
        assert "- Unknown: how they like to be greeted" in text
        assert models.status(a) == {"working-style": "fresh"}
        assert "sqlite://" not in seen[0], "only records a reader can open are cited"
        assert models.load(a)["working-style"].startswith("(fresh)\n## Style")
        assert a.brain_status()["models"] == {"working-style": "fresh"}
        # the briefing is not a memory: recall never returns it
        assert all("Show proof" not in r["text"] for r in a.brain_recall("proof done")["results"])
        day = tmp_path / "atlas" / "vault" / "sessions" / "2026-11-12.md"
        day.write_text(
            "# 2026-11-12\n\n## Said (hook)\n- please ship the report\n\n"
            "## Decisions Made\n- shipped\n"
        )
        a.config.models.items[0].kinds = ["note"]  # type: ignore[union-attr]
        texts = [r["text"] for r in models.gather(a, a.config.models.items[0], 50)]  # type: ignore[union-attr]
        assert "shipped" in texts and "please ship the report" not in texts, (
            "a request is not a record"
        )
        a.config.models.items[0].kinds = ["pattern"]  # type: ignore[union-attr]
        out = a.brain_remember("Likes a morning summary", "pattern", title="Morning")
        assert set(out["layers"]) <= {"vault", "sqlite"}, "read-only stores are not write layers"


def test_stale_only_when_what_it_rests_on_changes(tmp_path: Path) -> None:
    with make(tmp_path) as a:
        models.refresh(a, run=answer("- Proof first {proof}\n- Tables {tables}"), today=TODAY)
        a.brain_remember("The API listens on port 8888", "fact", domain="system")
        assert models.status(a)["working-style"] == "fresh", "an unrelated write changes nothing"
        again = models.refresh(a, run=answer("- never called [1]"), today=TODAY)
        assert again["working-style"] == "fresh, left as it is"

        patterns = tmp_path / "atlas" / "vault" / "patterns.md"
        patterns.write_text(patterns.read_text().replace("Wants proof", "Wanted proof"))
        assert "1 cited record(s) changed or were removed" in models.status(a)["working-style"]

        models.refresh(a, run=answer("- Tables {tables}"), force=True, today=TODAY)
        assert models.status(a)["working-style"] == "fresh"
        a.brain_remember("Works in focused blocks of ninety minutes", "pattern", title="Blocks")
        assert models.status(a)["working-style"] == "stale: 1 new pattern record(s)"


def test_a_failed_or_empty_run_keeps_the_file_it_had(tmp_path: Path) -> None:
    with make(tmp_path) as a:
        models.refresh(a, run=answer("- Proof first {proof}"), today=TODAY)
        path = tmp_path / "atlas" / "vault" / "models" / "working-style.md"
        before = path.read_text()

        def boom(system: str, prompt: str) -> str:
            raise models.RunnerError("no login")

        assert models.refresh(a, run=boom, force=True)["working-style"].startswith("failed")
        out = models.refresh(a, run=answer("- All invented\n- Also invented"), force=True)
        assert out["working-style"].startswith("rejected, old file kept: 2 uncited")
        assert path.read_text() == before and not path.with_suffix(".tmp").exists()

        models.refresh(a, run=answer("- Tables now {tables}"), force=True, today=TODAY)
        assert "Proof first" in path.with_suffix(".prev.md").read_text()


def test_models_are_off_without_the_block_and_the_question_change_is_seen(tmp_path: Path) -> None:
    init_agent("Bare", tmp_path / "bare", False, user="Ada", lite=True)
    with Agent.from_config(tmp_path / "bare" / "brain.yaml") as bare:
        assert bare.config.models is None and "models" not in bare.brain_status()
        assert models.refresh(bare) == {"note": "no `models:` in brain.yaml, or no vault"}
    with make(tmp_path) as a:
        models.refresh(a, run=answer("- Proof first {proof}"), today=TODAY)
        a.config.models.items[0].question = "What does the user dislike?"  # type: ignore[union-attr]
        assert models.status(a)["working-style"] == "stale: the question changed"


def test_the_api_key_is_the_default_runner_and_the_login_is_opt_in() -> None:
    from brain_core.config import ModelsConfig

    assert ModelsConfig().runner == "api"
    assert ModelsConfig(runner="claude").runner == "claude"


def test_the_api_runner_says_how_to_install_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> None:
        raise ImportError(name)

    monkeypatch.setattr("importlib.import_module", missing)
    with pytest.raises(models.RunnerError, match=r"brain-core-mcp\[api\]"):
        models.run_api("s", "p")
