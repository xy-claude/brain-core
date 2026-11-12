"""Turn the miss repairs an agent logged into eval questions for ``run_gold.py``.

    .venv/bin/python tests/eval/from_repairs.py --config brain.yaml >> questions.yaml

Every ``brain_remember(kind='key')`` says "this question, which missed, is answered by this
record". That is a labelled case nobody had to write: the question must keep finding the record.
"""

from __future__ import annotations

import argparse
import json

from brain_core import Agent


def questions(config: str) -> list[dict[str, object]]:
    with Agent.from_config(config) as agent:
        seen = {
            (str(e.payload["query"]), str(e.payload["id"])[:16])
            for e in agent.recent_events(event_type="recall_repair", limit=5000)
        }
    return [{"s": "learned", "q": q, "gold": [rid]} for q, rid in sorted(seen)]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    for q in questions(ap.parse_args().config):
        print(f"  - {json.dumps(q)}")
