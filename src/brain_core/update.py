"""Tell the user when a newer brain-core is on PyPI. Nothing is ever installed from here.

``brain daily`` asks PyPI once a day and keeps the answer in ``data/update.json``. The brief,
``brain doctor`` and ``brain_status`` read that file, so they never touch the network.
``cron.update_check: false`` in ``brain.yaml`` stops the request.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

PYPI = "https://pypi.org/pypi/brain-core-mcp/json"
UPGRADE = "uv tool upgrade --no-cache brain-core-mcp"
FILE = "update.json"


def _key(version: str) -> tuple[int, ...]:
    """'0.4.23' → (0, 4, 23). Anything that is not dotted numbers sorts lowest, so it never
    raises a notice."""
    try:
        return tuple(int(part) for part in version.strip().split("."))
    except ValueError:
        return ()


def latest(timeout: float = 5.0) -> str | None:
    """The newest version on PyPI, or None when PyPI cannot be asked (offline, blocked, slow)."""
    try:
        with urllib.request.urlopen(PYPI, timeout=timeout) as r:
            return str(json.loads(r.read().decode())["info"]["version"])
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError):
        return None


def check(data_dir: Path, today: date) -> str | None:
    """Ask PyPI and remember the answer. A failed request leaves the last answer in place."""
    found = latest()
    if found:
        body = {"checked": today.isoformat(), "latest": found}
        (data_dir / FILE).write_text(json.dumps(body) + "\n", encoding="utf-8")
    return found


def notice(data_dir: Path) -> str:
    """One line when the remembered version is newer than the one running, else ''."""
    try:
        found = str(json.loads((data_dir / FILE).read_text(encoding="utf-8"))["latest"])
    except (OSError, ValueError, KeyError):
        return ""
    from brain_core import __version__  # here, not at the top: the package imports this module

    if _key(found) <= _key(__version__):
        return ""
    return (
        f"brain-core {found} is available (this is {__version__}). "
        f"Update: `{UPGRADE}`, then restart Claude."
    )
