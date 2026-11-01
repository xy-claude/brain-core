"""Kuzu entity-graph adapter via the AI-ORG ``entity_graph.py`` CLI.

Only ``relation`` records live here: ``subject —[predicate]→ object``. The CLI owns the DB
path and the Kuzu dependency; this adapter just shells out and parses its lines.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path

from brain_core.stores.base import Kind, Record, WriteResult, record_id

_LINE = re.compile(r"^\s*(.+?) —\[(.+?)\]→ (.+?)\s+\((\d{4}-\d{2}-\d{2})\)\s*$")
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class GraphStore:
    name = "graph"

    def __init__(
        self, script: Path | str, python: Path | str = "python3", runner: Runner | None = None
    ) -> None:
        self.script, self.python = Path(script).expanduser(), str(python)
        self._run: Runner = runner or self._subprocess

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        if kind != "relation":
            return []
        cp = self._run(["search", query] if query else ["all"])
        out: list[Record] = []
        for ln in cp.stdout.splitlines():
            if m := _LINE.match(ln):
                s, p, o, d = m.groups()
                text = f"{s} —[{p}]→ {o}"
                out.append(
                    Record(
                        record_id(text),
                        "relation",
                        text,
                        date.fromisoformat(d),
                        p,
                        "graph://",
                        0,
                        {"subject": s, "predicate": p, "object": o},
                    )
                )
        return out[:limit]

    def write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        if kind != "relation":
            return WriteResult(self.name, "", "refused", "graph stores relations only")
        s, p, o = extra.get("subject"), extra.get("predicate"), extra.get("object")
        if not (s and p and o):
            m = re.match(r"^(.+?)\s+—\[(.+?)\]→\s+(.+)$", text)
            if not m:
                return WriteResult(
                    self.name, "", "refused", "give subject/predicate/object or 'S —[p]→ O'"
                )
            s, p, o = m.groups()
        rid = record_id(f"{s} —[{p}]→ {o}")
        cp = self._run(["add", s, p, o])
        if cp.returncode != 0:
            return WriteResult(self.name, rid, "failed", (cp.stderr or cp.stdout)[-200:])
        if cp.stdout.lower().startswith("exists"):
            return WriteResult(self.name, rid, "exists", cp.stdout.strip()[:120])
        return WriteResult(self.name, rid, "written", cp.stdout.strip()[:120])

    def health(self) -> tuple[bool, str]:
        cp = self._run(["stats"])
        if cp.returncode != 0:
            return (False, (cp.stderr or cp.stdout)[-200:])
        return (True, " ".join(cp.stdout.split()))

    def _subprocess(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.python, str(self.script), *args], capture_output=True, text=True, timeout=60
        )
