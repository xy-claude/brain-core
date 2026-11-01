"""Demo driver for the README recording: one remember, one changed value, one recall.

Run inside an agent folder created by ``brain init``. Prints compact JSON the way the MCP does.
"""

from __future__ import annotations

import json
import sys

from brain_core import Agent


def show(label: str, out: dict[str, object]) -> None:
    print(f"\n> {label}")
    print(json.dumps(out, indent=1, ensure_ascii=False)[:900])


with Agent.from_config(sys.argv[1] if len(sys.argv) > 1 else "brain.yaml") as a:
    s = a.brain_session("start")
    show("brain_session('start')", {k: s[k] for k in ("session_id", "inbox", "recovery")})
    r = a.brain_remember(
        "Deploys go through staging first", "pattern", extra={"title": "Staging first"}
    )
    show(
        "brain_remember('Deploys go through staging first', kind='pattern')",
        {k: r[k] for k in ("status", "layers")},
    )
    a.brain_remember("Hindsight API listens on port 8887", "fact", domain="system")
    r = a.brain_remember("Hindsight API listens on port 8888", "fact", domain="system")
    show(
        "brain_remember('Hindsight API listens on port 8888', kind='fact')  # was 8887",
        {k: r[k] for k in ("status", "contradiction", "text") if k in r},
    )
    q = a.brain_recall("which port does hindsight use", limit=2)
    show(
        "brain_recall('which port does hindsight use')",
        {"results": q["results"], "stores": q["stores"]},
    )
    a.brain_session("end", critique="# Session Critique\n\n## What Went Well\n- demo")
