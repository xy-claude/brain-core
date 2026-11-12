"""Demo driver for the README recording and docs/img/session.svg.

Run against an agent made by ``brain init``. One save with search keys, one changed value,
then three recalls: the same words, other words, and something that was never saved.
``DEMO_PAUSE`` (seconds, default 0) waits between steps so a recording can be followed.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time

from brain_core import Agent

PAUSE = float(os.environ.get("DEMO_PAUSE", "0"))


def show(label: str, out: dict[str, object]) -> None:
    time.sleep(PAUSE)
    print(f"\n> {label}")
    for k, v in out.items():
        line = f"  {k}: {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}"
        print(
            "\n".join(
                textwrap.wrap(line, 84, subsequent_indent="    ", max_lines=2, placeholder="…")
            )
        )


def top(q: dict[str, object]) -> dict[str, object]:
    hit = q["results"][0]  # type: ignore[index]
    out = {"text": hit["text"], "source": hit["source"]}
    return out | ({"superseded": True} if hit.get("superseded") else {})


with Agent.from_config(sys.argv[1] if len(sys.argv) > 1 else "brain.yaml") as a:
    s = a.brain_session("start")
    show("brain_session('start')", {k: s[k] for k in ("session_id", "inbox", "recovery")})
    r = a.brain_remember(
        "Deploys go through staging first",
        "pattern",
        title="Staging first",
        keys="how we ship a release; rollout order",
    )
    show(
        "brain_remember('Deploys go through staging first', 'pattern', keys='how we ship…')",
        # a read-only store answers "refused"; only the stores that take writes are shown
        {
            "status": r["status"],
            "layers": {k: v["status"] for k, v in r["layers"].items() if v["status"] != "refused"},
        },
    )
    a.brain_remember("The API listens on port 8887", "fact", domain="system")
    r = a.brain_remember("The API listens on port 8888", "fact", domain="system")
    show(
        "brain_remember('The API listens on port 8888', 'fact')   # it said 8887 before",
        {"status": r["status"], "was": r["contradiction"]["text"], "text": r["text"]},
    )
    q = a.brain_recall("which port does the API use")
    show("brain_recall('which port does the API use')", top(q))
    show(
        "brain_recall('how do we roll out a release')   # none of the memory's own words",
        top(a.brain_recall("how do we roll out a release")),
    )
    q = a.brain_recall("who is our accountant")
    show("brain_recall('who is our accountant')   # never saved", {"weak_match": q["weak_match"]})
    a.brain_session("end", critique="# Session Critique\n\n## What Went Well\n- demo")
