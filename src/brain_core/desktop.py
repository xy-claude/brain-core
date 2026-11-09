"""Connect an agent to the Claude desktop app: one ``brain`` entry in the app's MCP config.

The desktop chat gets the five tools on the same vault and database Claude Code uses. It has no
hooks, so the brief and the capture do not run there; ``brain_session`` is called by hand.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

CONFIG_NAME = "claude_desktop_config.json"
SERVER = "brain"


def config_paths(home: Path | None = None) -> list[Path]:
    """Where the desktop app reads its MCP config on this platform; empty when it has no build.

    A Microsoft Store install keeps its files under a package folder instead of %APPDATA%, so
    on Windows every such folder that exists is returned as well.
    """
    home = home or Path.home()
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / "Claude" / CONFIG_NAME]
    if sys.platform == "win32":
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        store = sorted((local / "Packages").glob("Claude_*/LocalCache/Roaming/Claude"))
        return [roaming / "Claude" / CONFIG_NAME, *(p / CONFIG_NAME for p in store)]
    return []


def connect(agent_dir: Path, config: Path, brain_bin: str | None = None) -> str:
    """Add or update the ``brain`` server in one config file. Returns what happened.

    Every other key in the file is kept. A file that is not valid JSON is left alone, and the
    first change to an existing file leaves a ``.bak`` copy beside it.
    """
    brain_bin = brain_bin or shutil.which("brain") or str(Path(sys.executable).with_name("brain"))
    entry = {"command": brain_bin, "args": ["serve", str(agent_dir.resolve())]}
    data: dict[str, object] = {}
    if config.exists():
        try:
            loaded = json.loads(config.read_text(encoding="utf-8-sig") or "{}")
        except ValueError as e:
            return f"left alone: {config} is not valid JSON ({e})"
        if not isinstance(loaded, dict):
            return f"left alone: {config} does not hold a JSON object"
        data = loaded
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return f"left alone: mcpServers in {config} is not an object"
    if servers.get(SERVER) == entry:
        return f"already connected: {config}"
    verb = "updated" if SERVER in servers else "added"
    servers[SERVER] = entry
    config.parent.mkdir(parents=True, exist_ok=True)
    backup = config.with_name(config.name + ".bak")
    if config.exists() and not backup.exists():
        shutil.copy2(config, backup)
    config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"{verb}: {config}"
