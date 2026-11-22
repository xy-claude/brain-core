"""The graph net (M4, audit H.2-H.4): the claims around the entities a question names, as a
fourth list for recall's rank fusion, and as a structured block beside the results.

Seeds are found without a model: the longest names in the question that an entity note
holds as an alias, or that claims name while they wait for a note. The walk (``walk.py``)
keeps only claims TRUE on the day asked (``as_of``, else today); a question about the past
("originally", "used to", "why did we") keeps ended ones too, marked.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any

from brain_core.entities import normalize_alias
from brain_core.knowledge.walk import Limits, walk
from brain_core.recall import tokens
from brain_core.stores.base import Record
from brain_core.stores.graph import relation_text

if TYPE_CHECKING:
    from brain_core.knowledge.reconcile import ClaimIndex
    from brain_core.stores.index import RecordIndex

Hit = tuple[Record, str, float]
_BLOCK = 10  # claims shown in the reply's block; the rest are counted, never dropped silently
# a question about how things were, not how they are: ended claims stay, marked (H.2)
_HISTORY = re.compile(
    r"\b(originally|at first|first|before|used to|changed|since|until|why did we|history|"
    r"previously|no longer|anymore|any more|still|replaced|switched)\b",
    re.I,
)


class GraphNet:
    name = "graph"

    def __init__(
        self, claims: ClaimIndex, index: RecordIndex, limits: Limits | None = None
    ) -> None:
        self.claims = claims
        self.index = index
        self.limits = limits or Limits()

    def _names(self) -> dict[str, str]:
        """Normalised name -> entity id: every alias a note holds, and every name a claim
        still waits on (``name:<alias>``)."""
        out: dict[str, str] = {}
        ents = self.claims.vault.entities
        if ents is not None:
            out |= {a: next(iter(ids)) for a, ids in ents.alias_map().items() if len(ids) == 1}
        for (x,) in self.claims.db.fetchall(
            "SELECT subject FROM claims UNION SELECT object_entity FROM claims"
        ):
            if x and x.startswith("name:"):
                out.setdefault(x[5:], x)
        return {k: v for k, v in out.items() if len(k) >= 3}

    def seeds(self, query: str) -> list[tuple[str, str]]:
        """(name as found, entity id) in order of mention, the longest name first at a place."""
        names = self._names()
        if not names:
            return []
        alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        # a name inside a path, a file name or an address (local/x.yaml, x.name@mail) is not
        # the entity: the boundary keeps those out
        found = re.finditer(rf"(?<![\w\-./@])({alts})(?![\w\-/@]|\.\w)", normalize_alias(query))
        out: dict[str, str] = {}
        for m in found:
            out.setdefault(names[m.group(1)], m.group(1))
        return [(n, e) for e, n in out.items()]

    def search(
        self,
        query: str,
        as_of: date | None,
        today: date,
        in_scope: Callable[[Record, str], bool],
        candidates: int,
    ) -> tuple[list[Hit], dict[str, Any]]:
        self.claims.settle()  # the names come from the claims: bring them up to date first
        seeds = self.seeds(query)
        if not seeds:
            return [], {}
        history = bool(_HISTORY.search(query))
        day = as_of or today
        w = walk(self.claims.db, [e for _n, e in seeds], self.limits, day, today, history)
        held = self.claims.load([e.claim for e in w.edges])
        hits: list[Hit] = []
        paths: dict[str, str] = {}
        block: list[dict[str, Any]] = []
        seen: set[str] = set()
        # what the question asks beyond the names it was seeded by orders the claims of one
        # hop (H.3: by hop, then by the record's keyword score). A filter on it was tried:
        # it kept only questions that reuse a relation's own words, and paraphrases lost all
        asked = _words(query) - {w for n, _e in seeds for w in _words(n)}
        shown: list[tuple[int, int, str, Any]] = []
        for n, e in enumerate(w.edges):
            c = held.get(e.claim)
            if c is None:
                continue
            first = c.evidence[0]
            s = _shown(c.key.subject, first.subject_name, self.claims)
            o = c.key.object_literal or _shown(c.key.object_entity, first.object_name, self.claims)
            pred = f"{c.key.predicate}({c.key.role})" if c.key.role else c.key.predicate
            path = f"{s} —{pred}→ {o}"
            # the claims that share most words with the question first, then by hop: the
            # walk's own order (rank, id) says nothing about what was asked
            if history and all(p.undated and p.true_from is None for p in c.periods):
                continue  # a line with no date says nothing about what changed, or when
            score = _shared(asked, _words(path.replace("_", " ")))
            shown.append((-score, n, path, (e, c)))
        shown.sort(key=lambda x: (x[3][0].hop, x[0], x[1]))
        for _score, _n, path, (e, c) in shown:
            first = c.evidence[0]
            validity = c.at(day, today)
            item: dict[str, Any] = {
                "claim": path,
                "hop": e.hop,
                "validity": validity,
                "lifecycle": c.lifecycle.value,
                "evidence": len(c.evidence),
            }
            if all(p.undated and p.true_from is None for p in c.periods):
                # no row gives a date: true "now" by the votes, but nothing says it still holds
                item["undated"] = True
            if c.disputed_on(day, today):
                item["disputed"] = True
            if len(block) < _BLOCK:
                block.append(item)
            for ev in c.evidence:
                got = self._record(ev.occurrence.source_id, ev.occurrence.record_id, first)
                if got is None or got[0].id in seen or not in_scope(*got):
                    continue
                seen.add(got[0].id)
                paths[got[0].id] = path
                hits.append((got[0], got[1], 0.0))
        # The audit adds the records that merely mention a seed. Measured on a real agent
        # with five entity notes they repeat the keyword search at the graph net's weight and
        # broke 3 to 5 of 443 questions, so only the claims' own evidence is put forward
        info: dict[str, Any] = {"seeds": [n for n, _e in seeds], "claims": block}
        if len(shown) > len(block):
            info["claims_total"] = len(shown)
        if history:
            info["history"] = True
        if w.truncated:
            info["truncated"] = sorted(w.reasons)
            if w.hubs:
                info["hubs"] = w.hubs
        return hits[:candidates], {"paths": paths, **info}

    def _record(self, source: str, rid: str, first: Any) -> tuple[Record, str] | None:
        """The record an evidence row stands in: a relations.md line as the graph store
        shows it, anything else from the index."""
        if source == "vault:relations.md":
            row = self.claims.db.fetchone(
                "SELECT id, subject, predicate, object, created_at FROM relations WHERE id = ?",
                (rid,),
            )
            if row is None:
                return None
            return (
                Record(
                    row["id"],
                    "relation",
                    relation_text(row["subject"], row["predicate"], row["object"]),
                    date.fromisoformat(str(row["created_at"])[:10]),
                    row["predicate"],
                    "graph://relations",
                    0,
                    {
                        "subject": row["subject"],
                        "predicate": row["predicate"],
                        "object": row["object"],
                    },
                ),
                "graph",
            )
        return self.index.get(rid)


def _words(text: str) -> set[str]:
    return set(tokens(text))


def _shared(asked: set[str], said: set[str]) -> int:
    """How many of the question's words the claim says, a word meeting its own forms by a
    common start (trade, trades, trading; run, runs)."""

    def meets(a: str, b: str) -> bool:
        k = 0
        while k < min(len(a), len(b)) and a[k] == b[k]:
            k += 1
        return k >= 3 and k >= min(4, len(a), len(b))

    return sum(1 for a in asked if any(meets(a, b) for b in said))


def _shown(eid: str | None, written: str | None, claims: ClaimIndex) -> str:
    """An entity's note name, else the name as written."""
    if eid and not eid.startswith("name:"):
        row = claims.db.fetchone("SELECT name FROM entities WHERE id = ?", (eid,))
        if row:
            return str(row[0])
    return written or (eid or "").removeprefix("name:")
