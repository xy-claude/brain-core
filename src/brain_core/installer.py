"""Machine setup pieces behind ``install.sh``: the Hindsight server as a launchd service.

Hindsight (MIT, Vectorize) is a required store. ``brain hindsight install`` puts ``hindsight-api``
in place with ``uv tool``, writes the LaunchAgent (local embeddings on CPU, ``pg0`` embedded
Postgres, LLM provider ``anthropic`` by default reading ``ANTHROPIC_API_KEY``),
bootstraps it and waits for ``/health``. ``--provider claude-code`` uses a Claude Code login
instead of a key; Anthropic allows that for personal use only.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

LABEL = "io.vectorize.hindsight"
CP_LABEL = "io.vectorize.hindsight-cp"
HEALTH = "http://127.0.0.1:{port}/health"


def hindsight_plist(
    home: Path,
    api_bin: str,
    *,
    port: int = 8888,
    provider: str = "anthropic",
    model: str = "claude-sonnet-5-5",
) -> dict[str, Any]:
    env = {
        "PATH": f"/opt/homebrew/bin:{home}/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "HINDSIGHT_API_HOST": "127.0.0.1",
        "HINDSIGHT_API_PORT": str(port),
        "HINDSIGHT_API_LLM_PROVIDER": provider,
        "HINDSIGHT_API_LLM_MODEL": model,
        "HINDSIGHT_API_LLM_TIMEOUT": "300",
        "HINDSIGHT_API_REFLECT_LLM_TIMEOUT": "180",
        "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "local",
        "HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU": "true",
        "HINDSIGHT_API_DATABASE_URL": "pg0://hindsight",
    }
    # The key never lands in the plist: launchd does not expand ${VAR}, so the service sources
    # the 0600 env file written by write_env_file() and execs the real binary.
    log = home / "Library" / "Logs" / "hindsight" / "api.log"
    return {
        "Label": LABEL,
        "ProgramArguments": [
            "/bin/sh",
            "-c",
            f'set -a; . "{env_file(home)}"; set +a; exec "{api_bin}"',
        ],
        "EnvironmentVariables": env,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }


def control_plane_plist(
    cp_bin: str, home: Path, *, port: int = 9999, api_port: int = 8888
) -> dict[str, Any]:
    log = home / "Library" / "Logs" / "hindsight" / "cp.log"
    return {
        "Label": CP_LABEL,
        "ProgramArguments": [
            cp_bin,
            "--port",
            str(port),
            "--api-url",
            f"http://127.0.0.1:{api_port}",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }


def hindsight_unit(api_bin: str, env: dict[str, str]) -> str:
    """systemd user unit text (Linux) with the same environment as the LaunchAgent."""
    lines = "\n".join(f'Environment="{k}={v}"' for k, v in env.items())
    return (
        "[Unit]\nDescription=Hindsight memory server (brain-core)\nAfter=network.target\n\n"
        f"[Service]\nExecStart={api_bin}\nRestart=always\nRestartSec=3\n{lines}\n"
        "EnvironmentFile=-%h/.config/hindsight/env\n\n"
        "[Install]\nWantedBy=default.target\n"
    )


def env_file(home: Path) -> Path:
    return home / ".config" / "hindsight" / "env"


def write_env_file(home: Path, api_key_env: str | None) -> str:
    """Write the 0600 env file the service sources. Returns a one-line status for the report."""
    path = env_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.environ.get(api_key_env, "") if api_key_env else ""
    if key:
        body, status = f"HINDSIGHT_API_LLM_API_KEY={key}\n", f"{api_key_env} written"
    elif api_key_env:
        body = f"# export {api_key_env}=... then re-run: brain hindsight install\n"
        status = f"{api_key_env} is not set in this shell; Hindsight cannot reason until it is"
    else:
        body, status = "# no key needed for this provider\n", "not needed"
    if not (path.exists() and path.read_text(encoding="utf-8") == body):
        path.write_text(body, encoding="utf-8")
    path.chmod(0o600)
    return status


def install_hindsight(
    *,
    home: Path | None = None,
    launch_dir: Path | None = None,
    port: int = 8888,
    provider: str = "anthropic",
    model: str = "claude-sonnet-5-5",
    api_key_env: str | None = None,
    dashboard: bool = False,
    run: bool = True,
    wait: float = 120.0,
) -> dict[str, str]:
    """Install (idempotent) and start Hindsight. ``run=False`` only writes the plists."""
    if sys.platform == "win32":
        return {
            "hindsight": "not supported on Windows: no service manager path and no pg0 build "
            "verified. Stay lite (vault + SQLite), or run Hindsight on a Linux host and point "
            "brain.yaml at its URL."
        }
    home = home or Path.home()
    launch_dir = launch_dir or home / "Library" / "LaunchAgents"
    launch_dir.mkdir(parents=True, exist_ok=True)
    (home / "Library" / "Logs" / "hindsight").mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    if api_key_env is None and provider != "claude-code":
        api_key_env = (
            "ANTHROPIC_API_KEY" if provider == "anthropic" else f"{provider.upper()}_API_KEY"
        )
    out["api_key"] = write_env_file(home, api_key_env)

    api_bin = shutil.which("hindsight-api") or str(home / ".local" / "bin" / "hindsight-api")
    if run and not Path(api_bin).exists():
        if not shutil.which("uv"):
            raise RuntimeError("uv is required: curl -LsSf https://astral.sh/uv/install.sh | sh")
        subprocess.run(
            [
                "uv",
                "tool",
                "install",
                "hindsight-api",
                "--with",
                "hindsight-all",
                "--python",
                "3.12",
            ],
            check=True,
        )
        out["hindsight-api"] = "installed"
    else:
        out["hindsight-api"] = "present" if Path(api_bin).exists() else "not installed (dry run)"

    if sys.platform != "darwin":
        unit_dir = home / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        body = hindsight_plist(home, api_bin, port=port, provider=provider, model=model)
        unit = unit_dir / "hindsight.service"
        unit.write_text(hindsight_unit(api_bin, body["EnvironmentVariables"]), encoding="utf-8")
        out["unit"] = str(unit)
        if not run:
            out["service"] = "not started (dry run)"
            return out
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "hindsight.service"], capture_output=True
        )
        out["service"] = (
            "healthy"
            if wait_healthy(port, wait)
            else f"not healthy after {wait:.0f}s; journalctl --user -u hindsight"
        )
        return out

    plist = launch_dir / f"{LABEL}.plist"
    plist.write_bytes(
        plistlib.dumps(hindsight_plist(home, api_bin, port=port, provider=provider, model=model))
    )
    out["plist"] = str(plist)
    if dashboard:
        cp_bin = (
            shutil.which("hindsight-control-plane") or "/opt/homebrew/bin/hindsight-control-plane"
        )
        if run and not Path(cp_bin).exists() and shutil.which("npm"):
            subprocess.run(
                ["npm", "install", "-g", "@vectorize-io/hindsight-control-plane"], check=True
            )
        cp = launch_dir / f"{CP_LABEL}.plist"
        cp.write_bytes(plistlib.dumps(control_plane_plist(cp_bin, home, api_port=port)))
        out["dashboard_plist"] = str(cp)
    if not run:
        out["service"] = "not started (dry run)"
        return out

    for p in [plist] + ([launch_dir / f"{CP_LABEL}.plist"] if dashboard else []):
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(p)], capture_output=True)
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(p)], capture_output=True
        )
    out["service"] = (
        "healthy"
        if wait_healthy(port, wait)
        else f"not healthy after {wait:.0f}s; see ~/Library/Logs/hindsight/api.log"
    )
    return out


def wait_healthy(port: int = 8888, timeout: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health(port):
            return True
        time.sleep(2)
    return False


def health(port: int = 8888) -> bool:
    try:
        with urllib.request.urlopen(HEALTH.format(port=port), timeout=3) as r:
            return bool(json.loads(r.read().decode()).get("status") == "healthy")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False
