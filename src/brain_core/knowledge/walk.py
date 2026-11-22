"""The graph net's walk (audit H.3): breadth-first over accepted claims, from the entities a
question names, bounded in work as well as in output.

Per expanded entity: a bounded degree check, then per direction one indexed query that reads
at most ``scan`` index rows before the validity filter, and a count that says whether that
window came back full. So the work is independent of a hub's degree. Every limit that can
leave something out adds its name to ``reasons``: recall says the expansion was cut, never
nothing.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

# TRUE at :d (as_of, else today), J.1; history mode takes every accepted claim
_VALID = """(:history = 1 OR EXISTS (SELECT 1 FROM claim_periods p WHERE p.claim_id = c.id
   AND (p.true_to IS NULL OR :d < p.true_to)
   AND ((p.stated = 1 AND p.true_from <= :d)
     OR (p.stated = 0 AND (p.timeless = 1
                           OR (p.true_from IS NOT NULL AND p.true_from <= :d)
                           OR (p.undated = 1 AND :d = :today))))))"""
# one direction: the first :scan rows in index order, THEN the filter, so a day that rejects
# most rows still reads at most :scan index entries (the miss is reported as `scan`)
EDGES_OUT = f"""SELECT * FROM (
  SELECT c.object_entity AS dst, c.id AS id, c.predicate AS predicate, 1 AS forward, c.rank
    FROM claims c
   WHERE c.subject = :src AND c.lifecycle = 'accepted' AND c.object_entity IS NOT NULL
   ORDER BY c.rank, c.id LIMIT :scan) AS c
 WHERE {_VALID} ORDER BY c.rank, c.id"""
EDGES_IN = f"""SELECT * FROM (
  SELECT c.subject AS dst, c.id AS id, c.predicate AS predicate, 0 AS forward, c.rank
    FROM claims c
   WHERE c.object_entity = :src AND c.lifecycle = 'accepted'
   ORDER BY c.rank, c.id LIMIT :scan) AS c
 WHERE {_VALID} ORDER BY c.rank, c.id"""
_FULL = {
    EDGES_OUT: "SELECT count(*) FROM (SELECT 1 FROM claims c WHERE c.subject = :src AND "
    "c.lifecycle = 'accepted' AND c.object_entity IS NOT NULL LIMIT :scan)",
    EDGES_IN: "SELECT count(*) FROM (SELECT 1 FROM claims c WHERE c.object_entity = :src AND "
    "c.lifecycle = 'accepted' LIMIT :scan)",
}
# how many claims name an entity, counted no further than a hub's threshold
_DEGREE = """SELECT (SELECT count(*) FROM (SELECT 1 FROM claims WHERE subject = :n AND
  lifecycle = 'accepted' LIMIT :cap)) + (SELECT count(*) FROM (SELECT 1 FROM claims WHERE
  object_entity = :n AND lifecycle = 'accepted' LIMIT :cap))"""


class _Conn(Protocol):
    def execute(self, sql: str, args: Any = ..., /) -> Any: ...


@dataclass(frozen=True)
class Limits:
    max_hops: int = 2  # hard cap 3
    fan: int = 20  # edges kept per expanded entity, across both directions
    scan: int = 80  # index rows read per entity and direction
    hub_degree: int = 200  # above this an entity is expanded only as a seed
    max_frontier: int = 50  # entities expanded per hop
    max_edges: int = 200  # edges returned in total
    max_seeds: int = 5


@dataclass(frozen=True)
class Edge:
    hop: int
    src: str  # the entity it was reached from
    claim: str
    predicate: str
    forward: bool  # src is the claim's subject
    dst: str


@dataclass
class Walk:
    edges: list[Edge] = field(default_factory=list)
    reasons: set[str] = field(default_factory=set)  # seeds frontier hub scan fan edges depth
    hubs: list[str] = field(default_factory=list)
    queries: int = 0
    rows_read: int = 0

    @property
    def truncated(self) -> bool:
        return bool(self.reasons)


def walk(
    db: _Conn,
    seeds: Sequence[str],
    lim: Limits,
    d: date,
    today: date,
    history: bool = False,
) -> Walk:
    assert 1 <= lim.max_hops <= 3
    asked = list(dict.fromkeys(seeds))
    w = Walk(reasons={"seeds"} if len(asked) > lim.max_seeds else set())
    depth = {s: 0 for s in asked[: lim.max_seeds]}
    frontier, seen = list(depth), set()
    args: dict[str, Any] = {"d": d.isoformat(), "today": today.isoformat(), "scan": lim.scan}
    args["history"] = int(history)

    def degree(node: str) -> int:
        w.queries += 1
        row = db.execute(_DEGREE, {"n": node, "cap": lim.hub_degree + 1}).fetchone()
        return int(row[0]) if row else 0

    nxt: list[str] = []
    for hop in range(1, lim.max_hops + 1):
        nxt = []
        if len(frontier) > lim.max_frontier:
            w.reasons.add("frontier")
        for node in frontier[: lim.max_frontier]:
            if depth[node] > 0 and degree(node) > lim.hub_degree:
                w.hubs.append(node)  # reached through a path: listed, never expanded
                w.reasons.add("hub")
                continue
            rows: list[sqlite3.Row] = []
            for sql in (EDGES_OUT, EDGES_IN):
                part = db.execute(sql, {**args, "src": node}).fetchall()
                w.queries += 2  # the edges, and the count of what the window read
                w.rows_read += len(part)
                if db.execute(_FULL[sql], {**args, "src": node}).fetchone()[0] == lim.scan:
                    w.reasons.add("scan")  # the window came back full: rows past it unread
                rows += part
            rows.sort(key=lambda r: (r[4], r[1], r[3]))  # one order across both directions
            kept = 0
            for dst, cid, pred, fwd, _rank in rows:
                if cid in seen:  # a claim reached from its other end is listed once
                    continue
                if kept == lim.fan:
                    w.reasons.add("fan")
                    break
                kept += 1
                seen.add(cid)
                w.edges.append(Edge(hop, node, cid, pred, bool(fwd), dst))
                if dst not in depth:  # visited: each entity expanded once, at its least depth
                    depth[dst] = hop
                    nxt.append(dst)
                if len(w.edges) >= lim.max_edges:
                    w.reasons.add("edges")
                    return w
        frontier = nxt
        if not frontier:
            break
    else:
        # the last hop's new entities were not expanded: say so when one leads further
        if any(degree(n) > 1 for n in nxt):
            w.reasons.add("depth")
    return w
