"""Hindsight installer: plists are exact, dry run never touches the system, install.sh parses."""

from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from brain_core import installer
from tests.conftest import BASH

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    sys.platform == "win32", reason="compares a /bin/sh launchd plist against a POSIX home path"
)
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
    assert "HINDSIGHT_API_LLM_API_KEY" not in env, "the key never lands in the plist"
    api_bin = str(home / ".local" / "bin" / "hindsight-api")
    assert api["ProgramArguments"] == [
        "/bin/sh",
        "-c",
        f'set -a; . "{home}/.config/hindsight/env"; set +a; exec "{api_bin}"',
    ]
    assert out["api_key"].startswith("ANTHROPIC_API_KEY is not set")
    assert (home / ".config" / "hindsight" / "env").read_text().startswith("# export")
    cp = plistlib.loads(Path(out["dashboard_plist"]).read_bytes())
    assert cp["ProgramArguments"][1:] == ["--port", "9999", "--api-url", "http://127.0.0.1:8888"]
    assert (home / "Library" / "Logs" / "hindsight").is_dir()


def test_key_goes_to_a_private_env_file_not_the_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    assert installer.write_env_file(tmp_path, "ANTHROPIC_API_KEY") == "ANTHROPIC_API_KEY written"
    env_file = tmp_path / ".config" / "hindsight" / "env"
    assert env_file.read_text() == "HINDSIGHT_API_LLM_API_KEY=sk-ant-test-123\n"
    assert sys.platform == "win32" or oct(env_file.stat().st_mode & 0o777) == "0o600"
    plist = installer.hindsight_plist(tmp_path, "/x/hindsight-api", provider="anthropic")
    assert (
        "sk-ant" not in str(plist)
        and plist["EnvironmentVariables"]["HINDSIGHT_API_LLM_PROVIDER"] == "anthropic"
    )
    assert installer.write_env_file(tmp_path, None) == "not needed"
    assert env_file.read_text().startswith("# no key")


def test_install_sh_parses_and_refuses_without_agent() -> None:
    script = ROOT / "install.sh"
    assert subprocess.run([BASH, "-n", str(script)]).returncode == 0
    r = subprocess.run([BASH, str(script)], capture_output=True, text=True)
    assert r.returncode == 2 and "usage:" in r.stderr
    if shutil.which("shellcheck"):
        assert subprocess.run(["shellcheck", "-S", "warning", str(script)]).returncode == 0


@pytest.mark.skipif(sys.platform == "win32", reason="install.sh is the macOS and Linux installer")
def test_install_sh_picks_a_provider_that_starts_and_keeps_a_lite_agent_lite(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / ".local" / "bin"  # first on PATH: every tool the script runs is a recorder
    bin_dir.mkdir(parents=True)
    for name in ("uv", "node", "claude", "brain"):
        (bin_dir / name).write_text('#!/bin/sh\necho "$(basename "$0") $*" >> "$HOME/calls"\n')
    (bin_dir / "uname").write_text("#!/bin/sh\necho Linux\n")  # the Linux path needs no Homebrew
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    calls = tmp_path / "calls"

    def run(*args: str, **env: str) -> tuple[subprocess.CompletedProcess[str], str]:
        calls.unlink(missing_ok=True)
        r = subprocess.run(
            [BASH, str(ROOT / "install.sh"), "--agent", "Atlas", *args],
            env={"HOME": str(tmp_path), "PATH": f"{bin_dir}:/usr/bin:/bin", **env},
            capture_output=True,
            text=True,
        )
        return r, calls.read_text() if calls.exists() else ""

    r, said = run("--desktop")  # the README line, no key in the shell
    assert r.returncode == 0, r.stderr
    assert "brain hindsight install --provider claude-code" in said and "--lite" not in said
    assert "no Linux build" in r.stdout and "brain desktop" not in said
    _, said = run(ANTHROPIC_API_KEY="k")
    assert "brain hindsight install --provider anthropic" in said
    r, said = run("--provider", "openai")  # Hindsight would never start: refuse before any step
    assert r.returncode == 2 and "OPENAI_API_KEY" in r.stderr and said == ""
    _, said = run("--lite")
    assert "--lite" in said and "hindsight install" not in said
    agent = tmp_path / "Agents" / "Atlas"
    agent.mkdir(parents=True)
    (agent / "brain.yaml").write_text("stores:\n  # hindsight:  # lite\n")
    r, said = run()
    assert "stays lite" in r.stdout and "hindsight install" not in said and "cron install" in said


def test_windows_dry_run_writes_only_the_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")  # before which() is stubbed
    real_run = subprocess.run
    monkeypatch.setattr("brain_core.installer.sys.platform", "win32")
    monkeypatch.setattr("brain_core.installer.shutil.which", lambda _: None)
    monkeypatch.setattr("brain_core.installer.subprocess.run", lambda *a, **k: pytest.fail(str(a)))
    out = installer.install_hindsight(home=tmp_path, provider="claude-code", run=False)
    script = Path(out["launcher"])
    text = script.read_text(encoding="utf-8")
    assert out["service"] == "not started (dry run)" and script.name == "hindsight.ps1"
    assert "$env:HINDSIGHT_API_DATABASE_URL = 'pg0://hindsight'" in text
    assert "$env:HINDSIGHT_API_LLM_PROVIDER = 'claude-code'" in text
    assert "$env:PATH" not in text and "LLM_API_KEY" not in text, "the key stays in the env file"
    assert "$env:PYTHONUTF8 = '1'" in text, "the banner crashes a cp1252 log without it"
    assert "hindsight-api.exe" in text and not (tmp_path / "Library").exists()
    if pwsh:
        parse = (
            "$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
            f"'{script}', [ref]$null, [ref]$e); exit $e.Count"
        )
        assert real_run([pwsh, "-NoProfile", "-Command", parse]).returncode == 0


def test_windows_install_registers_a_logon_entry_and_starts_the_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("brain_core.installer.sys.platform", "win32")
    api = tmp_path / ".local" / "bin" / "hindsight-api.exe"
    api.parent.mkdir(parents=True)
    api.write_text("")
    monkeypatch.setattr("brain_core.installer.shutil.which", lambda _: None)
    ran: list[list[str]] = []
    started: list[list[str]] = []
    monkeypatch.setattr("brain_core.installer.subprocess.run", lambda cmd, **k: ran.append(cmd))
    monkeypatch.setattr(
        "brain_core.installer.subprocess.Popen", lambda cmd, **k: started.append(cmd)
    )
    monkeypatch.setattr("brain_core.installer.wait_healthy", lambda port, wait: True)
    out = installer.install_hindsight(home=tmp_path, provider="claude-code")
    assert out["hindsight-api"] == "present" and out["service"] == "healthy"
    reg = ran[0]
    assert reg[:3] == ["reg", "add", installer.RUN_KEY] and installer.RUN_VALUE in reg
    assert "hindsight.ps1" in reg[-1] and "-WindowStyle Hidden" in reg[-1]
    assert ran[1][0] == "powershell" and "Stop-Process" in ran[1][-1], "an old launcher is stopped"
    assert started == [[*ran[1][:2], "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                        "-File", out["launcher"]]]  # fmt: skip


def test_install_ps1_parses_and_refuses_a_bad_agent_name() -> None:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if pwsh is None:
        pytest.skip("no PowerShell on this host")
    script = ROOT / "install.ps1"
    r = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(script), "-Agent", "bad name"],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 and "-Agent must be" in r.stderr + r.stdout
    code = [ln for ln in script.read_text().splitlines() if not ln.lstrip().startswith("#")]
    exits = [ln for ln in code if re.search(r"\bexit\s+[$\d]", ln)]
    assert not exits, "exit would close the user's PowerShell window"


def test_systemd_unit_carries_the_environment(tmp_path: Path) -> None:
    plist = installer.hindsight_plist(tmp_path, "/x/hindsight-api")
    unit = installer.hindsight_unit("/x/hindsight-api", plist["EnvironmentVariables"])
    assert "ExecStart=/x/hindsight-api" in unit and "Restart=always" in unit
    assert 'Environment="HINDSIGHT_API_DATABASE_URL=pg0://hindsight"' in unit
    assert "HINDSIGHT_API_LLM_API_KEY" not in unit
    assert "EnvironmentFile=-%h/.config/hindsight/env" in unit
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
