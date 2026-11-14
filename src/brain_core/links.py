"""``brain links``: find the records a newer record replaced, and write the link to the vault.

``brain_remember`` links a changed fact to its old line when the two are nearly the same words.
A value that changed in other words, or across kinds (a session note, then a decision), is left
unlinked, and recall can then show the old value first. This looks for those pairs: each record's
nearest older neighbours by meaning are put to a model, pair by pair, with one question: does the
newer record replace what the older one says? A yes becomes a ``supersedes`` line in
``record_meta.md``. The files stay the truth: delete the line and the link is gone.

It needs ``stores.vectors`` (to find neighbours) and a runner (``recall.runner``). Pairs already
asked about are remembered in the data directory, so a later run asks only about new records.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from brain_core.stores.base import Record, full_text
from brain_core.stores.vault import _SECRET, VaultStore

if TYPE_CHECKING:
    from brain_core.agent import Agent

Runner = Callable[[str, str], str]
NEAR = 0.7  # cosine at or above: close enough to be the same subject
NEIGHBOURS = 5  # older neighbours looked at per record
BATCH = 15  # pairs per model call
CHARS = 600

SYSTEM = """You compare pairs of memory records from one person's work log. In each pair, OLD was \
written before NEW. Decide whether NEW replaces OLD: both are about the same specific thing, and \
NEW gives a different, later value, status or decision for it, so that OLD is no longer true.

It is NOT a replacement when NEW only adds detail, repeats OLD, is about a different thing, \
records a later step of the same work, or when OLD is still true beside NEW. When unsure, say no.

Reply with one JSON object and nothing else: {"replaced": [numbers of the pairs where NEW \
replaces OLD]}"""

_JSON = re.compile(r"\{.*\}", re.S)


def _hook(r: Record) -> bool:
    """A raw message the capture hook filed: a request, not a statement of how things are."""
    return r.kind == "note" and r.domain.endswith("(hook)")


def candidates(agent: Agent) -> list[tuple[Record, Record]]:
    """(old, new) pairs worth asking about: a record and its nearest older neighbours."""
    import numpy as np

    v = agent.vectors
    assert v is not None
    v._load()
    if v._matrix is None:
        return []
    recs: dict[str, tuple[Record, str]] = {}
    for rid in v._ids:
        got = v.index_record(rid)
        if got:
            recs[rid] = got
    vault = next(s for s in agent.stores if isinstance(s, VaultStore))
    linked = vault.replaced()
    out: list[tuple[Record, Record]] = []
    seen: set[tuple[str, str]] = set()
    for i, rid in enumerate(v._ids):
        if rid not in recs or recs[rid][1] == "archive" or _hook(recs[rid][0]):
            continue  # an archive copy or a raw message never replaces anything
        new = recs[rid][0]
        sims = v._matrix @ v._matrix[i]
        for j in np.argsort(-sims)[1 : NEIGHBOURS * 3]:
            other = v._ids[int(j)]
            if float(sims[int(j)]) < NEAR or len([p for p in out if p[1].id == rid]) >= NEIGHBOURS:
                break
            old = recs.get(other, (None, ""))[0]
            # shortcut: two records of the same day are not ordered; add times to compare them
            if old is None or _hook(old) or old.date >= new.date:
                continue
            if linked.get(old.id[:16]) or (old.id, rid) in seen:
                continue
            if _SECRET.search(full_text(old)) or _SECRET.search(full_text(new)):
                continue
            seen.add((old.id, rid))
            out.append((old, new))
    return out


def _prompt(pairs: list[tuple[Record, Record]]) -> str:
    def show(r: Record) -> str:
        return f"({r.kind}, {r.date.isoformat()}) {' '.join(full_text(r).split())[:CHARS]}"

    return "\n\n".join(
        f"Pair {n}\nOLD {show(old)}\nNEW {show(new)}" for n, (old, new) in enumerate(pairs, 1)
    )


def find(agent: Agent, run: Runner, limit: int | None = None, write: bool = True) -> dict[str, Any]:
    """Ask about every pair not asked before; write the links found. Returns counts and the
    links as (old source, new source) for a human to read."""
    vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
    if vault is None or agent.vectors is None:
        return {"note": "needs a vault and `stores.vectors` in brain.yaml"}
    agent.brain_sync()
    side = agent.data_dir / "links_asked.json"
    asked: set[str] = set(json.loads(side.read_text())) if side.exists() else set()
    pairs = [p for p in candidates(agent) if f"{p[0].id[:16]}>{p[1].id[:16]}" not in asked]
    pairs = pairs[:limit] if limit else pairs
    links: list[tuple[str, str]] = []
    failed = 0
    for i in range(0, len(pairs), BATCH):
        part = pairs[i : i + BATCH]
        try:
            m = _JSON.search(run(SYSTEM, _prompt(part)))
            doc = json.loads(m.group(0)) if m else {}
            picked = doc["replaced"] if isinstance(doc.get("replaced"), list) else None
        except Exception:  # a failed batch is asked again next run
            picked = None
        if picked is None:
            failed += len(part)
            continue
        for n in picked:
            if isinstance(n, int) and 1 <= n <= len(part):
                old, new = part[n - 1]
                links.append((f"{old.path}:{old.line}", f"{new.path}:{new.line}"))
                if write:
                    vault.supersede(new.id, old.id)
        if write:
            asked |= {f"{o.id[:16]}>{n.id[:16]}" for o, n in part}
            side.write_text(json.dumps(sorted(asked)))
    return {"pairs": len(pairs), "links": len(links), "failed": failed, "found": links}
