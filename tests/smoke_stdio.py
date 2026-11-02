"""Start ``brain serve`` over stdio from an installed ``brain`` and list its tools.

    python tests/smoke_stdio.py /path/to/brain

Used by CI against the built wheel in a clean environment, where the lock file does not apply
and dependency resolution can drift (this is how an unpinned ``mcp`` 2.x slipped past pytest).
Exit 1 unless the server answers with exactly the five brain tools.

stdin stays open until the tools/list reply arrives. Closing it right after writing the
requests races the server's shutdown against its last reply and fails about one run in five.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EXPECTED = ["brain_recall", "brain_remember", "brain_session", "brain_distill", "brain_status"]
TIMEOUT = 120.0


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
        p = subprocess.Popen(
            [brain, "serve", str(agent)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert p.stdin is not None and p.stdout is not None and p.stderr is not None
        p.stdin.write("\n".join(json.dumps(m) for m in msgs) + "\n")
        p.stdin.flush()
        tools: list[str] | None = None
        deadline = time.monotonic() + TIMEOUT
        while tools is None and time.monotonic() < deadline:
            ln = p.stdout.readline()
            if not ln:
                break
            if ln.startswith("{") and json.loads(ln).get("id") == 2:
                tools = [t["name"] for t in json.loads(ln)["result"]["tools"]]
        p.stdin.close()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        err = p.stderr.read()
    print("tools:", tools)
    if tools != EXPECTED:
        print(err[-2000:], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "brain"))
