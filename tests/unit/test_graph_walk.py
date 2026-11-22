"""M4: the bounded graph walk (audit H.3). Counts rows, queries and VM steps, never
milliseconds, so the bounds hold in CI on any machine."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from importlib import resources

from hypothesis import given, settings
from hypothesis import strategies as hs

from brain_core.knowledge.walk import EDGES_IN, EDGES_OUT, Limits, walk

T = date(2026, 11, 21)
SQL = (resources.files("brain_core.storage") / "migrations" / "009_claims.sql").read_text()


def graph() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(SQL)
    return db


def claim(
    db: sqlite3.Connection,
    cid: str,
    s: str,
    o: str,
    pred: str = "USES",
    start: str | None = "2026-01-01",
    end: str | None = None,
    life: str = "accepted",
) -> None:
    db.execute(
        "INSERT INTO claims VALUES (?, ?, ?, '', ?, NULL, NULL, ?, 'stated', NULL, NULL, ?)",
        (cid, s, pred, o, life, {"PART_OF": 1, "USES": 2}.get(pred, 9)),
    )
    db.execute(
        "INSERT INTO claim_periods VALUES (?, 0, ?, ?, NULL, 0, ?, 0, 0)",
        (cid, start, end, int(start is None)),
    )


def hub(db: sqlite3.Connection, size: int = 10_000, leaves: int = 5) -> None:
    """HUB USES n_i, n_i DEPENDS_ON m_i_j (known from February), and a cycle A -> B -> C -> A
    where A also touches the hub."""
    rows, periods = [], []
    for i in range(size):
        rows.append((f"c-h-{i:05d}", "HUB", "USES", f"n{i:05d}", 2))
        periods.append((f"c-h-{i:05d}", "2026-01-01"))
        for j in range(leaves):
            rows.append((f"c-n-{i:05d}-{j}", f"n{i:05d}", "DEPENDS_ON", f"m{i:05d}-{j}", 9))
            periods.append((f"c-n-{i:05d}-{j}", "2026-02-01"))
    db.executemany(
        "INSERT INTO claims VALUES (?, ?, ?, '', ?, NULL, NULL, 'accepted', 'stated', NULL, "
        "NULL, ?)",
        rows,
    )
    db.executemany("INSERT INTO claim_periods VALUES (?, 0, ?, NULL, NULL, 0, 0, 0, 0)", periods)
    for s, o in (("A", "B"), ("B", "C"), ("C", "A"), ("A", "HUB")):
        claim(db, f"c-{s}{o}", s, o, start="2026-03-01")


def test_a_walk_from_a_hub_is_bounded() -> None:
    db = graph()
    hub(db)
    lim = Limits()
    w = walk(db, ["HUB"], lim, T, T)
    assert len(w.edges) <= lim.max_edges
    assert w.rows_read <= 2 * lim.scan * (lim.max_seeds + lim.max_frontier)
    assert w.queries <= 5 * (lim.max_seeds + lim.max_frontier)
    assert sum(1 for e in w.edges if e.hop == 1) == lim.fan and w.truncated
    assert walk(db, ["HUB"], lim, T, T) == w  # the same vault, the same walk


def test_a_hub_reached_on_a_path_is_a_terminal_and_the_cycle_ends() -> None:
    db = graph()
    hub(db)
    w = walk(db, ["A"], Limits(), T, T)
    assert w.hubs == ["HUB"] and "hub" in w.reasons
    assert not any(e.src == "HUB" for e in w.edges)
    assert {e.src for e in w.edges} <= {"A", "B", "C"} and len(w.edges) == 4
    assert len({e.claim for e in w.edges}) == len(w.edges)  # each claim once


def test_every_cut_is_reported() -> None:
    db = graph()
    hub(db)
    assert "seeds" in walk(db, ["A", "B", "C", "HUB", "n00001", "n00002"], Limits(), T, T).reasons
    small = walk(db, ["HUB"], Limits(max_frontier=3), T, T)
    assert "frontier" in small.reasons and len({e.src for e in small.edges if e.hop == 2}) <= 3
    assert "scan" in walk(db, ["HUB"], Limits(), T, T).reasons
    assert "fan" in walk(db, ["HUB"], Limits(), T, T).reasons
    assert "edges" in walk(db, ["HUB"], Limits(max_edges=30), T, T).reasons
    ring = graph()
    for i in range(6):  # a ring longer than the depth
        claim(ring, f"r{i}", f"x{i}", f"x{(i + 1) % 6}")
    assert "depth" in walk(ring, ["x0"], Limits(max_hops=2), T, T).reasons


def test_as_of_leaves_out_what_was_not_true_then() -> None:
    db = graph()
    hub(db)
    w = walk(db, ["HUB"], Limits(), date(2026, 1, 15), T)  # hop-2 claims start in February
    assert w.edges and all(e.hop == 1 for e in w.edges)
    ended = graph()
    claim(ended, "old", "S", "O1", end="2026-06-01")
    claim(ended, "new", "S", "O2", start="2026-06-01")
    claim(ended, "gone", "S", "O3", life="rejected")
    assert [e.dst for e in walk(ended, ["S"], Limits(), T, T).edges] == ["O2"]
    assert [e.dst for e in walk(ended, ["S"], Limits(), date(2026, 3, 1), T).edges] == ["O1"]
    history = walk(ended, ["S"], Limits(), T, T, history=True)  # ended ones kept, rejected not
    assert sorted(e.dst for e in history.edges) == ["O1", "O2"]


def test_the_edge_queries_use_the_indexes() -> None:
    db = graph()
    hub(db, size=50, leaves=1)
    args = {"src": "HUB", "d": T.isoformat(), "today": T.isoformat(), "scan": 80, "history": 0}
    for sql, index in ((EDGES_OUT, "idx_claims_out"), (EDGES_IN, "idx_claims_in")):
        plan = " | ".join(r[-1] for r in db.execute("EXPLAIN QUERY PLAN " + sql, args))
        assert f"USING INDEX {index}" in plan and "TEMP B-TREE" not in plan.upper(), plan


def test_nothing_valid_reads_only_the_scan_window() -> None:
    db = graph()
    hub(db, leaves=1)
    steps = {"n": 0}

    def tick() -> int:
        steps["n"] += 1
        return 0

    db.set_progress_handler(tick, 100)
    args = {"src": "HUB", "d": "2025-01-01", "today": T.isoformat(), "scan": 80, "history": 0}
    assert db.execute(EDGES_OUT, args).fetchall() == []
    bounded = steps["n"]
    steps["n"] = 0
    first_draft = EDGES_OUT.replace("LIMIT :scan) AS c", ") AS c") + " LIMIT :scan"
    db.execute(first_draft, args).fetchall()
    db.set_progress_handler(None, 0)
    assert bounded * 20 < steps["n"], (bounded, steps["n"])


def _exhaustive(db: sqlite3.Connection, seeds: list[str], hops: int, d: date) -> set[str]:
    """The same rules with no limit: every claim TRUE at d within `hops` of a seed."""
    lim = Limits(
        max_hops=hops, fan=10**6, scan=10**6, hub_degree=10**6, max_frontier=10**6,
        max_edges=10**6, max_seeds=10**6,
    )  # fmt: skip
    return {e.claim for e in walk(db, seeds, lim, d, T).edges}


@settings(max_examples=120, deadline=None)
@given(
    hs.lists(
        hs.tuples(hs.integers(0, 9), hs.integers(0, 9), hs.integers(0, 60), hs.booleans()),
        min_size=1,
        max_size=40,
    ),
    hs.lists(hs.integers(0, 9), min_size=1, max_size=7),
    hs.integers(1, 3),
    hs.integers(1, 6),
    hs.integers(1, 8),
    hs.integers(0, 60),
)
def test_the_bounded_walk_never_hides_a_cut(
    rows: list[tuple[int, int, int, bool]],
    seeds: list[int],
    hops: int,
    fan: int,
    frontier: int,
    day: int,
) -> None:
    db = graph()
    base = date(2026, 1, 1)
    for i, (s, o, start, ends) in enumerate(rows):
        if s != o:
            first = base + timedelta(days=start)
            claim(db, f"c{i:02d}", f"e{s}", f"e{o}", start=first.isoformat(),
                  end=(first + timedelta(days=20)).isoformat() if ends else None)  # fmt: skip
    d = base + timedelta(days=day)
    names = [f"e{x}" for x in seeds]
    lim = Limits(max_hops=hops, fan=fan, scan=fan * 2, hub_degree=8, max_frontier=frontier,
                 max_edges=fan * 6, max_seeds=4)  # fmt: skip
    w = walk(db, names, lim, d, T)
    every = _exhaustive(db, names, hops, d)
    got = {e.claim for e in w.edges}
    assert got <= every  # never an edge the exhaustive walk does not have
    if got != every:
        assert w.truncated, (sorted(every - got), w.reasons)  # and a gap always says why
