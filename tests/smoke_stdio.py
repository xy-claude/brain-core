"""Start ``brain serve`` over stdio from an installed ``brain`` and list its tools.

    python tests/smoke_stdio.py /path/to/brain

Used by CI against the built wheel in a clean environment, where the lock file does not apply
and dependency resolution can drift (this is how an unpinned ``mcp`` 2.x slipped past pytest).
Exit 1 unless the server answers with exactly the five brain tools.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED = ["brain_recall", "brain_remember", "brain_session", "brain_distill", "brain_status"]


def main(brain: str) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        agent = Path(tmp) / "agent"
        subprocess.run([brain, "init", "Smoke", "--path", str(agent), "--user", "ci"], check=True)
        msgs = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        p = subprocess.run(
            [brain, "serve", str(agent)],
            input="\n".join(json.dumps(m) for m in msgs) + "\n",
            capture_output=True,
            text=True,
            timeout=120,
        )
    tools: list[str] = []
    for ln in p.stdout.splitlines():
        if ln.startswith("{"):
            m = json.loads(ln)
            if m.get("id") == 2:
                tools = [t["name"] for t in m["result"]["tools"]]
    print("tools:", tools)
    if tools != EXPECTED:
        print(p.stderr[-2000:], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "brain"))
