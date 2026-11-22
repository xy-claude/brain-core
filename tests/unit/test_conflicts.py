"""M7: a contradiction is said when a relation is saved, not found later; claims from an
outside or automated path stay provisional; a reflection must name the claims it rests on."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from brain_core.journal import Journal
from brain_core.knowledge.model import Lifecycle, Verification
from brain_core.knowledge.net import GraphNet
from brain_core.recall import brain_recall
from brain_core.remember import brain_remember
from brain_core.storage import Database, migrate
from brain_core.stores.base import record_id
from brain_core.stores.graph import relation_text
from brain_core.stores.index import RecordIndex
from brain_core.stores.notes import NotesStore
from brain_core.stores.vault import VaultStore

TODAY = date(2026, 12, 12)
NEO = "[[Brain-Core]] —[USES: graph-database]→ [[Neo4j]]"
KUZU = "[[Brain-Core]] —[USES: graph-database]→ [[Kuzu]]"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 12, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def vault(tmp: Path, *lines: str) -> VaultStore:
    j = Journal(tmp / "data" / "journal.db", clock=Clock())
    db = Database.connect(tmp / "data" / "brain.db")
    migrate(db)
    v = VaultStore(tmp / "vault", index=RecordIndex(db, j))
    v.root.mkdir(parents=True)
    (v.root / "relations.md").write_text("# Relations\n\n" + "".join(f"- {x}\n" for x in lines))
    v.read("fact", "sync")
    return v


def by_object(v: VaultStore) -> dict[str, object]:
    assert v.claims is not None
    return {str(c.evidence[0].object_name): c for c in v.claims.current().values()}


def test_saving_a_relation_that_cannot_hold_beside_another_says_so(tmp_path: Path) -> None:
    v = vault(tmp_path, f"{NEO} (2026-11-01)")
    out = brain_remember([v], "Brain-Core —[USES: graph-database]→ Kuzu", "relation")
    assert out["status"] == "written"
    c = out["contradiction"]
    assert c["with"] == ["Brain-Core —USES(graph-database)→ Neo4j"]
    assert "until:" in c["note"] and "ack:" in c["note"]


def test_a_relation_that_can_hold_beside_others_is_no_contradiction(tmp_path: Path) -> None:
    v = vault(tmp_path, "[[Brain-Core]] —[DEPENDS_ON]→ [[SQLite]] (2026-11-01)")
    out = brain_remember([v], "Brain-Core —[DEPENDS_ON]→ Python", "relation")
    assert out["status"] == "written" and "contradiction" not in out
    ended = vault(tmp_path / "b", f"{NEO} (2026-11-01)")
    rid = record_id(relation_text("Brain-Core", "USES: graph-database", "Neo4j"))[:16]
    (ended.root / "record_meta.md").write_text(f"# Meta\n\n- {rid} | until: 2026-11-15\n")
    ended.read("fact", "sync")  # the old one ended before: the two never hold on one day
    out = brain_remember([ended], "Brain-Core —[USES: graph-database]→ Kuzu", "relation")
    assert out["status"] == "written" and "contradiction" not in out


def test_the_conflict_slice_carries_disputed_with(tmp_path: Path) -> None:
    v = vault(tmp_path, f"{NEO} (2026-11-01)", f"{KUZU} (2026-11-20)")
    assert v.claims is not None and v.index is not None
    out = brain_recall(
        [v],
        "which graph database does Brain-Core use?",
        today=TODAY,
        graph=GraphNet(v.claims, v.index),
    )
    disputed = {c["claim"]: c.get("disputed_with") for c in out["claims"]}
    assert disputed["Brain-Core —USES(graph-database)→ Neo4j"] == [
        "Brain-Core —USES(graph-database)→ Kuzu"
    ]
    assert disputed["Brain-Core —USES(graph-database)→ Kuzu"] == [
        "Brain-Core —USES(graph-database)→ Neo4j"
    ]
    (v.root / "claim_reviews.md").write_text(
        f"# Claim reviews\n\n- ack: {NEO} & {KUZU} | both ran\n"
    )
    v.read("fact", "sync")
    acked = brain_recall(
        [v],
        "which graph database does Brain-Core use?",
        today=TODAY,
        graph=GraphNet(v.claims, v.index),
    )
    assert not any(c.get("disputed_with") for c in acked["claims"])


def test_a_line_from_an_outside_folder_stays_provisional(tmp_path: Path) -> None:
    v = vault(tmp_path)
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "x.md").write_text(f"# X\n\n## G\n{NEO}\n")
    NotesStore([tmp_path / "shared"], v.index).read("knowledge", "sync")
    c = by_object(v)["Neo4j"]
    assert c.lifecycle is Lifecycle.CANDIDATE and c.verification is Verification.UNVERIFIED  # type: ignore[attr-defined]
    (v.root / "relations.md").write_text(f"# Relations\n\n- {NEO}\n")  # a person states it
    v.read("fact", "sync")
    assert by_object(v)["Neo4j"].lifecycle is Lifecycle.ACCEPTED  # type: ignore[attr-defined]


def test_a_reflection_names_its_parents_or_stays_a_candidate(tmp_path: Path) -> None:
    v = vault(tmp_path, f"{NEO} (2026-11-01)")
    assert v.claims is not None
    parent = next(iter(v.claims.current()))[:12]
    (v.root / "knowledge").mkdir()
    (v.root / "knowledge" / "_reflections.md").write_text(
        "# Reflections\n\n## 2026-12-01\n\n"
        "- [[Neo4j]] —[ALTERNATIVE_TO]→ [[Kuzu]]\n"
        f"- [[Kuzu]] —[ALTERNATIVE_TO]→ [[SQLite]] (parents: {parent})\n"
        "- [[Brain-Core]] —[OWNS]→ [[Kuzu]] (parents: 0123456789ab)\n"
    )
    v.read("fact", "sync")
    got = {
        (c.evidence[0].subject_name, c.evidence[0].object_name): c
        for c in v.claims.current().values()
    }
    assert got[("Neo4j", "Kuzu")].lifecycle is Lifecycle.CANDIDATE  # no parents
    assert got[("Kuzu", "SQLite")].lifecycle is Lifecycle.ACCEPTED  # rests on a claim held
    assert got[("Kuzu", "SQLite")].verification is Verification.DERIVED
    assert got[("Brain-Core", "Kuzu")].lifecycle is Lifecycle.CANDIDATE  # a parent no one holds
    report = v.claims.summary()["report"]
    assert sum(r.startswith("reflection_unparented") for r in report) == 2
