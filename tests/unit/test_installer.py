"""Hindsight installer: plists are exact, dry run never touches the system, install.sh parses."""

from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

from brain_core import installer

ROOT = Path(__file__).resolve().parents[2]


def test_dry_run_writes_the_service_plists_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("brain_core.installer.shutil.which", lambda name: None)
    monkeypatch.setattr("brain_core.installer.sys.platform", "darwin")  # CI runs on Linux
    calls: list[list[str]] = []
    monkeypatch.setattr("brain_core.installer.subprocess.run", lambda *a, **k: calls.append(a[0]))
    home = tmp_path / "home"
    out = installer.install_hindsight(
        home=home, launch_dir=tmp_path / "la", dashboard=True, run=False
    )
    assert out["hindsight-api"] == "not installed (dry run)" and out["service"].startswith(
        "not started"
    )
    assert calls == [], "dry run must not install or launchctl"
    api = plistlib.loads(Path(out["plist"]).read_bytes())
    assert api["Label"] == "io.vectorize.hindsight" and api["KeepAlive"] is True
    env = api["EnvironmentVariables"]
    assert env["HINDSIGHT_API_PORT"] == "8888" and env["HINDSIGHT_API_LLM_PROVIDER"] == "anthropic"
    assert (
        env["HINDSIGHT_API_EMBEDDINGS_PROVIDER"] == "local"
        and env["HINDSIGHT_API_DATABASE_URL"] == "pg0://hindsight"
    )
    assert env["HINDSIGHT_API_LLM_API_KEY"] == "${ANTHROPIC_API_KEY}", "default reads the env var"
    personal = installer.hindsight_plist(home, "/x/hindsight-api", provider="claude-code")
    assert "HINDSIGHT_API_LLM_API_KEY" not in personal["EnvironmentVariables"]
    assert api["ProgramArguments"] == [str(home / ".local" / "bin" / "hindsight-api")]
    cp = plistlib.loads(Path(out["dashboard_plist"]).read_bytes())
    assert cp["ProgramArguments"][1:] == ["--port", "9999", "--api-url", "http://127.0.0.1:8888"]
    assert (home / "Library" / "Logs" / "hindsight").is_dir()


def test_customer_provider_never_embeds_the_key(tmp_path: Path) -> None:
    p = installer.hindsight_plist(
        tmp_path, "/x/hindsight-api", provider="anthropic", api_key_env="ANTHROPIC_API_KEY"
    )
    env = p["EnvironmentVariables"]
    assert env["HINDSIGHT_API_LLM_PROVIDER"] == "anthropic"
    assert env["HINDSIGHT_API_LLM_API_KEY"] == "${ANTHROPIC_API_KEY}"


def test_install_sh_parses_and_refuses_without_agent() -> None:
    script = ROOT / "install.sh"
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert r.returncode == 2 and "usage:" in r.stderr
    if shutil.which("shellcheck"):
        assert subprocess.run(["shellcheck", "-S", "warning", str(script)]).returncode == 0


def test_systemd_unit_carries_the_environment(tmp_path: Path) -> None:
    plist = installer.hindsight_plist(tmp_path, "/x/hindsight-api")
    unit = installer.hindsight_unit("/x/hindsight-api", plist["EnvironmentVariables"])
    assert "ExecStart=/x/hindsight-api" in unit and "Restart=always" in unit
    assert 'Environment="HINDSIGHT_API_DATABASE_URL=pg0://hindsight"' in unit
    assert 'Environment="HINDSIGHT_API_LLM_API_KEY=${ANTHROPIC_API_KEY}"' in unit
    assert unit.endswith("WantedBy=default.target\n")


def test_linux_dry_run_writes_a_systemd_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("brain_core.installer.shutil.which", lambda name: None)
    monkeypatch.setattr("brain_core.installer.sys.platform", "linux")
    calls: list[list[str]] = []
    monkeypatch.setattr("brain_core.installer.subprocess.run", lambda *a, **k: calls.append(a[0]))
    home = tmp_path / "home"
    out = installer.install_hindsight(home=home, run=False)
    assert calls == [] and out["service"].startswith("not started")
    unit = Path(out["unit"])
    assert unit == home / ".config" / "systemd" / "user" / "hindsight.service"
    assert "ExecStart=" in unit.read_text() and "plist" not in out
