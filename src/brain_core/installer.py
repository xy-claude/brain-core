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
    api_key_env: str | None = None,
) -> dict[str, Any]:
    if api_key_env is None and provider != "claude-code":
        api_key_env = (
            "ANTHROPIC_API_KEY" if provider == "anthropic" else f"{provider.upper()}_API_KEY"
        )
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
    if api_key_env:
        # the key itself never lands in the plist: the service reads it from the keychain shim
        env["HINDSIGHT_API_LLM_API_KEY"] = f"${{{api_key_env}}}"
    log = home / "Library" / "Logs" / "hindsight" / "api.log"
    return {
        "Label": LABEL,
        "ProgramArguments": [api_bin],
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
    home = home or Path.home()
    launch_dir = launch_dir or home / "Library" / "LaunchAgents"
    launch_dir.mkdir(parents=True, exist_ok=True)
    (home / "Library" / "Logs" / "hindsight").mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}

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

    plist = launch_dir / f"{LABEL}.plist"
    plist.write_bytes(
        plistlib.dumps(
            hindsight_plist(
                home, api_bin, port=port, provider=provider, model=model, api_key_env=api_key_env
            )
        )
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
