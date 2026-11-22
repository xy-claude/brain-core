"""Translate eval labels to M1b's store-relative ids: every gold or stale prefix that names a
notes or archive record by its path id is replaced by the record's new id. Other ids pass.

    .venv/bin/python -I tests/eval/translate_labels.py CONFIG QUESTIONS OUT
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from brain_core.agent import Agent
from brain_core.stores.notes import NotesStore


def main(config: str, questions: str, out: str) -> int:
    with Agent.from_config(config) as agent:
        old_to_new: dict[str, str] = {}
        for s in agent.stores:
            if isinstance(s, NotesStore):
                old_to_new |= s.id_map()
    by_prefix = {old[:10]: new[:10] for old, new in old_to_new.items()}
    doc = yaml.safe_load(Path(questions).read_text())
    moved = 0
    for q in doc["questions"]:
        for key in ("gold", "stale"):
            if q.get(key):
                new = [by_prefix.get(p, p) for p in q[key]]
                moved += sum(a != b for a, b in zip(q[key], new, strict=True))
                q[key] = new
    Path(out).write_text(
        "# Labels translated to M1b's store-relative ids by tests/eval/translate_labels.py\n"
        + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    )
    print(f"{moved} label ids translated, {len(by_prefix)} notes and archive ids known")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
