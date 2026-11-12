"""``brain_remember``: one write, every store, in a fixed order, with per-layer status.

Order: vault → sqlite → hindsight → graph (graph only for ``relation``). Before writing, the
local stores are scanned for a near-duplicate (skipped) or a contradiction (written with the
``⚠ Fact changed`` banner, old line kept). A layer that fails is reported, never swallowed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from typing import Any

from brain_core.recall import tokens
from brain_core.stores.base import Kind, Record, Store, WriteResult, record_id
from brain_core.stores.graph import relation_text
from brain_core.stores.vault import _SECRET

ORDER = ("vault", "sqlite", "hindsight", "graph")
DUPLICATE = 0.8  # Jaccard at or above: same fact, skip
CONTRADICTION = 0.5  # Jaccard at or above with different numbers: new value for an old fact
_NUM = re.compile(r"\d[\d.,:/-]*")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_BANNER = re.compile(r"^\*\*⚠ Fact changed \d{4}-\d{2}-\d{2}:\*\* (.*?)(?: \(was: .*\))?$", re.S)


def brain_remember(
    stores: Sequence[Store],
    text: str,
    kind: Kind,
    *,
    domain: str = "",
    source: str = "",
    mission: str | None = None,
    when: date | None = None,
    force: bool = False,
    **extra: str,
) -> dict[str, Any]:
    text = text.strip()
    if (
        kind == "relation"
        and not text
        and all(extra.get(k) for k in ("subject", "predicate", "object"))
    ):
        text = relation_text(extra["subject"], extra["predicate"], extra["object"])
    if not text:
        raise ValueError("text must not be empty")
    if any(_SECRET.search(str(v)) for v in (text, source, *extra.values())):
        raise ValueError("text looks like it contains a secret; nothing was written to any store")
    when = when or date.today()
    ordered = sorted(stores, key=lambda s: ORDER.index(s.name) if s.name in ORDER else len(ORDER))
    if kind != "relation":
        ordered = [s for s in ordered if s.name != "graph"]
    # a store that is only read (transcripts, notes folders) is not a layer of a write
    ordered = [s for s in ordered if not getattr(s, "readonly", False)]

    match = _closest(ordered, kind, text) if kind in ("fact", "pattern") else None
    out: dict[str, Any] = {"kind": kind, "text": text, "layers": {}}
    # a changed number on a near-identical line is a new value, never a duplicate; so is a
    # near-identical line with a word the old one lacks ("always" → "never")
    changed = match is not None and (
        (match[1] >= CONTRADICTION and _numbers(core(match[0].text)) != _numbers(text))
        or (match[1] >= DUPLICATE and not tokens(text) <= tokens(core(match[0].text)))
    )
    if match and match[1] >= DUPLICATE and not changed and not force:
        out.update(id=match[0].id, status="duplicate", duplicate_of=_brief(match[0]))
        return out
    if match and changed:
        out["contradiction"] = _brief(match[0])
        text = f"**⚠ Fact changed {when.isoformat()}:** {text} (was: {match[0].text[:120]})"
        out["text"] = text
        extra.setdefault("supersedes", match[0].id)  # recall ranks the old value below this one

    if source:
        extra["source"] = source
    if mission:
        extra["mission"] = mission
    results: list[WriteResult] = []
    for store in ordered:
        try:
            r = store.write(kind, text, domain=domain, when=when, **extra)
        except Exception as e:  # a crashing layer is a failed layer, not a crashed call
            r = WriteResult(store.name, record_id(text), "failed", f"{type(e).__name__}: {e}"[:200])
        results.append(r)
        out["layers"][store.name] = {"status": r.status, "detail": r.detail}
    out["id"] = record_id(text)
    live = [r.status for r in results if r.status != "refused"]
    if not live or all(s == "failed" for s in live):
        out["status"] = "failed"
    elif "failed" in live or "pending" in live:
        out["status"] = "partial"
    elif all(s == "exists" for s in live):
        out["status"] = "exists"
    else:
        out["status"] = "written"
    return out


def _closest(stores: Sequence[Store], kind: Kind, text: str) -> tuple[Record, float] | None:
    """Best Jaccard match among local stores (Hindsight is skipped: slow, and it dedups itself)."""
    new = tokens(text)
    if not new:
        return None
    best: tuple[Record, float] | None = None
    for store in stores:
        if getattr(store, "whole", False):
            continue
        try:
            recs = store.read(kind, text if getattr(store, "ranked", False) else None, 2000)
        except Exception:
            continue
        for r in recs:
            old = tokens(core(r.text))
            j = len(new & old) / len(new | old) if old else 0.0
            if best is None or j > best[1]:
                best = (r, j)
    return best


def core(text: str) -> str:
    """A banner line is compared by its new value, not by the old value it quotes."""
    m = _BANNER.match(text)
    return m.group(1) if m else text


def _numbers(text: str) -> set[str]:
    """Numbers that carry a value; full dates are stamps, not values."""
    return {n.strip(".,:/-") for n in _NUM.findall(text) if not _DATE.fullmatch(n.strip(".,:/-"))}


def _brief(r: Record) -> dict[str, str]:
    return {"id": r.id, "date": r.date.isoformat(), "source": r.path, "text": r.text}
