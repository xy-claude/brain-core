"""M4 follow-up: answers asked about a past day, end to end through the stores an agent wires
(vault, graph mirror, graph net). Fixture tests in the shape of the audit's as-of-unknown,
conflict and decision-history slices; the measured slices on real data are a separate eval."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from brain_core.journal import Journal
from brain_core.knowledge.net import GraphNet
from brain_core.recall import brain_recall
from brain_core.storage import Database, migrate
from brain_core.stores.graph import GraphStore
from brain_core.stores.index import RecordIndex
from brain_core.stores.vault import VaultStore

TODAY = date(2026, 12, 12)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 12, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def agent(tmp: Path, relations: list[str], facts: list[str] = ()) -> tuple[list[Any], GraphNet]:  # type: ignore[assignment]
    j = Journal(tmp / "data" / "journal.db", clock=Clock())
    db = Database.connect(tmp / "data" / "brain.db")
    migrate(db)
    v = VaultStore(tmp / "vault", index=RecordIndex(db, j))
    v.root.mkdir(parents=True)
    (v.root / "relations.md").write_text("# Relations\n\n" + "".join(f"- {x}\n" for x in relations))
    (v.root / "facts.md").write_text("# Facts\n\n## General\n" + "".join(f"- {x}\n" for x in facts))
    v.read("fact", "sync")
    assert v.claims is not None and v.index is not None
    return [v, GraphStore(db, v.root / "relations.md")], GraphNet(v.claims, v.index)


def test_as_of_unknown_is_never_asserted(tmp_path: Path) -> None:
    # recorded on 11-20: when it became true is not known, so on 06-01 it is unknown
    stores, net = agent(
        tmp_path, ["[[Ride App]] —[USES: maps]→ [[MapBox]] (recorded: 2026-11-20T10:00:00)"]
    )
    out = brain_recall(
        stores, "which maps does the ride app use?", fmt="detailed", today=TODAY, graph=net,
        as_of=date(2026, 6, 1),
    )  # fmt: skip
    assert out["claims"] == []  # nothing is walked as true that day
    rel = [r for r in out["results"] if r["kind"] == "relation"]
    assert rel and all(r["as_of_validity"] == "unknown" for r in rel)  # and the line says so


def test_a_record_dated_after_the_day_asked_says_so(tmp_path: Path) -> None:
    stores, net = agent(
        tmp_path, [],
        ["The fare cap is 30 euros (2026-05-01)", "The fare cap went up to 40 euros (2026-09-01)"],
    )  # fmt: skip
    out = brain_recall(
        stores, "what is the fare cap?", today=TODAY, graph=net, as_of=date(2026, 6, 1)
    )
    marked = {r["text"]: r.get("after_as_of", False) for r in out["results"]}
    assert marked == {"The fare cap is 30 euros": False, "The fare cap went up to 40 euros": True}
    plain = brain_recall(stores, "what is the fare cap?", today=TODAY, graph=net)
    assert not any("after_as_of" in r for r in plain["results"])  # only when a day is asked


def test_a_conflict_on_the_day_asked_is_disputed(tmp_path: Path) -> None:
    stores, net = agent(
        tmp_path,
        ["[[Brain-Core]] —[USES: graph-database]→ [[Neo4j]] (2026-11-01)",
         "[[Brain-Core]] —[USES: graph-database]→ [[Kuzu]] (2026-11-20)"],
    )  # fmt: skip
    q = "which graph database does Brain-Core use?"
    before = brain_recall(stores, q, today=TODAY, graph=net, as_of=date(2026, 11, 10))
    assert [(c["claim"], c.get("disputed")) for c in before["claims"]] == [
        ("Brain-Core —USES(graph-database)→ Neo4j", None)
    ]
    after = brain_recall(stores, q, today=TODAY, graph=net, as_of=date(2026, 11, 25))
    assert all(c.get("disputed") for c in after["claims"]) and len(after["claims"]) == 2


def test_decision_history_keeps_what_ended(tmp_path: Path) -> None:
    stores, net = agent(
        tmp_path,
        ["[[Brain-Core]] —[USES: graph-database]→ [[Neo4j]] (2026-11-01)",
         "[[Brain-Core]] —[USES: graph-database]→ [[Kuzu]] (2026-12-01)"],
    )  # fmt: skip
    v = stores[0]
    ids = {r.extra["object"]: r.id[:16] for r in v.read("relation", None, 10)}
    (v.root / "record_meta.md").write_text(
        f"# Meta\n\n- {ids['Kuzu']} | supersedes: {ids['Neo4j']}\n"
    )
    v.read("fact", "sync")
    now = brain_recall(stores, "which graph database does Brain-Core use?", today=TODAY, graph=net)
    assert [c["claim"] for c in now["claims"]] == ["Brain-Core —USES(graph-database)→ Kuzu"]
    then = brain_recall(
        stores, "which graph database did Brain-Core use originally?", today=TODAY, graph=net
    )
    got = {c["claim"]: c["validity"] for c in then["claims"]}
    assert got == {
        "Brain-Core —USES(graph-database)→ Neo4j": "false",  # ended 12-01, kept and marked
        "Brain-Core —USES(graph-database)→ Kuzu": "true",
    }
