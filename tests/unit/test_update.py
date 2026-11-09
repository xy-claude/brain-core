"""The update notice: brain daily asks PyPI once, everything else reads what it wrote."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brain_core import __version__, cron, update
from brain_core.agent import Agent
from brain_core.cli.init import init_agent
from brain_core.cli.main import app

TODAY = date(2026, 11, 9)
NEWER = "99.0.0"


def agent_at(tmp_path: Path) -> Agent:
    init_agent("Atlas", tmp_path / "atlas", False, user="Ada", lite=True)
    return Agent.from_config(tmp_path / "atlas" / "brain.yaml")


def test_notice_only_for_a_newer_version(tmp_path: Path) -> None:
    assert update.notice(tmp_path) == "", "no file yet"
    for found, expected in ((NEWER, True), (__version__, False), ("0.0.1", False), ("soon", False)):
        (tmp_path / update.FILE).write_text(json.dumps({"latest": found}))
        said = update.notice(tmp_path)
        assert bool(said) is expected, found
    (tmp_path / update.FILE).write_text(json.dumps({"latest": NEWER}))
    said = update.notice(tmp_path)
    assert NEWER in said and __version__ in said and update.UPGRADE in said
    (tmp_path / update.FILE).write_text("{broken")
    assert update.notice(tmp_path) == "", "a damaged file is no notice, not an error"


def test_daily_asks_once_and_the_brief_status_and_doctor_say_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cron, "_admin", lambda: None)
    asked: list[float] = []

    def pypi(timeout: float = 5.0) -> str:
        asked.append(timeout)
        return NEWER

    monkeypatch.setattr(update, "latest", pypi)
    with agent_at(tmp_path) as agent:
        out = cron.daily(agent, TODAY)
        assert len(asked) == 1 and NEWER in out["update"]
        brief = Path(out["brief"]).read_text(encoding="utf-8")
        assert "## Update available" in brief and update.UPGRADE in brief
        assert NEWER in agent.brain_status()["update"]
        saved = json.loads((agent.data_dir / update.FILE).read_text())
        assert saved == {"checked": "2026-11-09", "latest": NEWER}
    r = CliRunner().invoke(app, ["doctor", str(tmp_path / "atlas")])
    assert f"update     brain-core {NEWER} is available" in r.output
    assert len(asked) == 1, "status and doctor read the file; they never ask PyPI"


def test_no_notice_when_current_offline_or_switched_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cron, "_admin", lambda: None)
    with agent_at(tmp_path) as agent:
        monkeypatch.setattr(update, "latest", lambda timeout=5.0: __version__)
        out = cron.daily(agent, TODAY)
        assert out["update"] == "up to date"
        assert "Update available" not in Path(out["brief"]).read_text(encoding="utf-8")
        assert "update" not in agent.brain_status()

        (agent.data_dir / update.FILE).unlink()
        monkeypatch.setattr(update, "latest", lambda timeout=5.0: None)  # offline
        assert cron.daily(agent, TODAY)["update"] == "up to date"
        assert not (agent.data_dir / update.FILE).exists(), "nothing learned, nothing written"

        agent.config.cron.update_check = False
        monkeypatch.setattr(update, "latest", lambda timeout=5.0: pytest.fail("asked PyPI"))
        assert cron.daily(agent, TODAY)["update"].startswith("check disabled")


def test_latest_survives_an_unreachable_pypi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # the real function, not the conftest stand-in
    monkeypatch.setattr(update, "PYPI", "http://127.0.0.1:1/nothing")
    assert update.latest(timeout=1) is None
