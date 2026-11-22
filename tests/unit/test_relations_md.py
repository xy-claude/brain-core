"""M1a: relations live in vault/relations.md; the legacy table is a write-only mirror until M3."""

from __future__ import annotations

import stat
from datetime import date
from pathlib import Path

import pytest

from brain_core.recall import brain_recall
from brain_core.remember import brain_remember
from brain_core.status import rebuild_loss
from brain_core.storage import Database, migrate
from brain_core.stores import MemoryStore
from brain_core.stores.base import WriteResult, record_id
from brain_core.stores.graph import GraphStore, migrate_relations, relation_text
from brain_core.stores.index import RecordIndex
from brain_core.stores.vault import VaultStore

DAY = date(2026, 11, 22)


def rows(db: Database) -> set[tuple[str, ...]]:
    return {
        tuple(r)
        for r in db.fetchall("SELECT id, subject, predicate, object, created_at FROM relations")
    }


def vault_on(root: Path, db: Database) -> VaultStore:
    return VaultStore(root, owner="atlas", index=RecordIndex(db))


def legacy(db: Database, s: str, p: str, o: str, created_at: str) -> None:
    db.execute(
        "INSERT INTO relations (id, subject, predicate, object, created_at) VALUES (?, ?, ?, ?, ?)",
        (record_id(relation_text(s, p, o)), s, p, o, created_at),
    )


def test_a_relation_is_a_vault_line_with_its_recording_time(tmp_path: Path, db: Database) -> None:
    v = vault_on(tmp_path, db)
    r = v.write("relation", "", subject="ATLAS", predicate="uses", object="Hindsight", when=DAY)
    assert r.status == "written" and r.id == record_id("ATLAS —[uses]→ Hindsight")
    assert (
        "- [[ATLAS]] —[uses]→ [[Hindsight]] (recorded: 2026-11-22)"
        in (tmp_path / "relations.md").read_text().splitlines()
    )
    assert v.write("relation", "ATLAS —[uses]→ Hindsight", when=DAY).status == "exists"
    (got,) = v.read("relation")
    assert (got.id, got.text, got.extra["recorded"]) == (
        r.id,
        "ATLAS —[uses]→ Hindsight",
        "2026-11-22",
    )


def test_brain_remember_refuses_a_relation_the_line_cannot_hold(
    tmp_path: Path, db: Database
) -> None:
    hindsight = MemoryStore()
    hindsight.name = "hindsight"
    with pytest.raises(ValueError, match=r"relations\.md"):
        brain_remember(
            [vault_on(tmp_path, db), hindsight, GraphStore(db, tmp_path / "relations.md")],
            "",
            "relation",
            subject="A]]B",
            predicate="uses",
            object="C",
        )
    assert not hindsight.records and not rows(db)  # nothing reached any store


def test_a_failed_vault_line_leaves_no_mirror_row(db: Database) -> None:
    class DeadVault(MemoryStore):
        name = "vault"

        def write(self, kind, text, **kw):
            return WriteResult(self.name, "", "failed", "disk full")

    out = brain_remember(
        [DeadVault(), GraphStore(db, Path("/nowhere/relations.md"))],
        "",
        "relation",
        subject="A",
        predicate="b",
        object="C",
    )
    assert out["layers"]["graph"]["status"] == "refused" and not rows(db)
    assert out["status"] == "failed"


def test_the_mirror_is_refilled_from_the_file_with_exact_fields(tmp_path: Path) -> None:
    with Database.connect(tmp_path / "old.db") as old:
        migrate(old)
        legacy(old, "ATLAS", "uses", "Hindsight", "2026-04-10")
        legacy(old, "brain-core", "PART_OF", "Acme", "2026-11-02 09:15:00")
        before = rows(old)
        report = migrate_relations(
            old, vault_on(tmp_path / "vault", old), tmp_path / "data" / "backups"
        )
        assert report["appended"] == 2 and report["verified"]
    # brain.db deleted: a new one is filled from relations.md alone
    with Database.connect(tmp_path / "new.db") as new:
        migrate(new)
        vault_on(tmp_path / "vault", new).read("relation", "ATLAS")  # a search syncs first
        assert rows(new) == before


def test_migration_appends_only_what_is_missing_and_keeps_hand_lines(
    tmp_path: Path, db: Database
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    hand = "- [[Ada]] —[OWNS]→ [[atlas]] (recorded: 2026-01-01)"
    (root / "relations.md").write_text(f"# Relations\n\n## Relations\n{hand}\n")
    legacy(db, "ATLAS", "uses", "Hindsight", "2026-04-10")
    first = migrate_relations(db, vault_on(root, db), tmp_path / "backups")
    again = migrate_relations(db, vault_on(root, db), tmp_path / "backups")
    text = (root / "relations.md").read_text()
    assert (first["appended"], again["appended"]) == (1, 0) and hand in text.splitlines()
    assert text.count("[[Hindsight]]") == 1 and again["verified"]


def test_migration_refuses_rows_the_line_cannot_hold_and_names_them(
    tmp_path: Path, db: Database
) -> None:
    legacy(db, "A]]B", "uses", "C", "2026-04-10")
    legacy(db, "D", "has: role", "E", "2026-04-10")
    legacy(db, "F", "uses", "G", "2026-04-10")
    report = migrate_relations(db, vault_on(tmp_path / "vault", db), tmp_path / "backups")
    assert report["appended"] == 1 and len(report["refused"]) == 2 and report["verified"]
    assert any("A]]B" in r for r in report["refused"]) and not report["complete"]


def test_migration_takes_a_checked_private_backup_first(tmp_path: Path, db: Database) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "relations.md").write_text("# Relations\n")
    legacy(db, "A", "b", "C", "2026-04-10")
    before = rows(db)
    report = migrate_relations(db, vault_on(root, db), tmp_path / "backups")
    saved = [Path(p) for p in report["backup"]]
    assert len(saved) == 2 and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in saved)
    assert stat.S_IMODE((tmp_path / "backups").stat().st_mode) == 0o700
    # restored into a new folder, the backup is the database as it was
    restored = tmp_path / "restore" / "brain.db"
    restored.parent.mkdir()
    restored.write_bytes(next(p for p in saved if p.suffix == ".db").read_bytes())
    with Database.connect(restored) as back:
        assert back.fetchone("PRAGMA integrity_check")[0] == "ok"  # type: ignore[index]
        assert rows(back) == before
    assert next(p for p in saved if p.suffix == ".md").read_text() == "# Relations\n"


def test_a_crash_after_the_file_is_written_converges_on_the_rerun(
    tmp_path: Path, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy(db, "A", "b", "C", "2026-04-10")
    v = vault_on(tmp_path / "vault", db)
    real = VaultStore.append_relations

    def crash(self, items):
        real(self, items)
        raise KeyboardInterrupt  # killed after the file, before the check

    monkeypatch.setattr(VaultStore, "append_relations", crash)
    with pytest.raises(KeyboardInterrupt):
        migrate_relations(db, v, tmp_path / "backups")
    monkeypatch.setattr(VaultStore, "append_relations", real)
    report = migrate_relations(db, v, tmp_path / "backups")
    assert report["appended"] == 0 and report["verified"]
    assert (tmp_path / "vault" / "relations.md").read_text().count("[[C]]") == 1


def test_beside_a_vault_recall_reads_relations_from_the_file_only(
    tmp_path: Path, db: Database
) -> None:
    v = vault_on(tmp_path, db)
    g = GraphStore(db, tmp_path / "relations.md")
    brain_remember(
        [v, g], "", "relation", subject="ATLAS", predicate="uses", object="Hindsight", when=DAY
    )
    legacy(db, "ATLAS", "uses", "Kuzu", "2026-04-10")  # a mirror row with no line: removed by hand
    found = brain_recall([v, g], "ATLAS uses", scope="relation", today=DAY)
    assert [r["text"] for r in found["results"]] == ["ATLAS —[uses]→ Hindsight"]
    assert brain_recall([v, g], "ATLAS uses", scope="graph", today=DAY)["total"] == 1
    assert [r.text for r in g.read("relation", "ATLAS")] == ["ATLAS —[uses]→ Hindsight"]
    assert v.relations_drift() == (1, 0, 0)
    # ranked as 0.9.1 ranked them: by the graph store, not by the keyword index
    assert db.fetchone("SELECT count(*) FROM records_fts WHERE kind = 'relation'")[0] == 0  # type: ignore[index]


def test_an_older_version_still_reads_every_relation_from_the_mirror(
    tmp_path: Path, db: Database
) -> None:
    legacy(db, "A", "b", "C", "2026-04-10")
    v, g = vault_on(tmp_path, db), GraphStore(db, tmp_path / "relations.md")
    migrate_relations(db, v, tmp_path / "backups")
    for o in ("D", "E", "F", "G", "H"):
        brain_remember([v, g], "", "relation", subject="A", predicate="b", object=o, when=DAY)
    # 0.9.1 reads the table, as a GraphStore that is not a mirror does
    assert len(GraphStore(db).read("relation", limit=100)) == 6


def test_without_a_vault_the_graph_store_answers_as_before(db: Database) -> None:
    g = GraphStore(db)
    assert g.write("relation", "", subject="A", predicate="b", object="C").status == "written"
    assert [r.text for r in g.read("relation", "A")] == ["A —[b]→ C"]


def test_rebuild_loss_counts_what_brain_db_alone_holds(db: Database) -> None:
    db.execute("INSERT INTO metrics (metric_name, value) VALUES ('tool.x', 1)")
    assert rebuild_loss(db) == {"events": 0, "metrics": 1, "sole facts": 0, "v0.1 rows": 0}


def _agent(tmp_path: Path) -> Path:
    (tmp_path / "vault").mkdir()
    (tmp_path / "brain.yaml").write_text(f"name: T\nstores:\n  vault: {tmp_path / 'vault'}\n")
    return tmp_path


def test_brain_graph_migrate_copies_the_table_behind_a_backup(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from brain_core.agent import Agent
    from brain_core.cli.main import app

    root = _agent(tmp_path)
    with Agent.from_config(root / "brain.yaml") as a:
        legacy(a.db, "ATLAS", "uses", "Hindsight", "2026-04-10")
        backups = a.data_dir / "backups"
    out = CliRunner().invoke(app, ["graph", "migrate", str(root)])
    assert out.exit_code == 0, out.output
    assert "1 appended" in out.output and "verified" in out.output
    assert "[[Hindsight]]" in (root / "vault" / "relations.md").read_text()
    assert any(backups.glob("brain-*.db"))


def test_status_names_rows_the_file_lacks_and_what_a_rebuild_loses(tmp_path: Path) -> None:
    from brain_core.agent import Agent

    with Agent.from_config(_agent(tmp_path) / "brain.yaml") as a:
        legacy(a.db, "ATLAS", "uses", "Kuzu", "2026-04-10")
        st = a.brain_status()
    assert st["not_rebuilt"]["sole facts"] == 0
    assert any("relations.md" in line for line in st["attention"])


def test_an_upgraded_agent_recalls_its_table_until_relations_md_exists(
    tmp_path: Path, db: Database
) -> None:
    legacy(db, "ATLAS", "uses", "Hindsight", "2026-04-10")
    g = GraphStore(db, tmp_path / "relations.md")
    assert not g.mirror and [r.text for r in g.read("relation", "ATLAS")] == [
        "ATLAS —[uses]→ Hindsight"
    ]


def test_a_relation_write_waits_for_the_migration(tmp_path: Path, db: Database) -> None:
    legacy(db, "ATLAS", "uses", "Hindsight", "2026-04-10")
    v, g = vault_on(tmp_path, db), GraphStore(db, tmp_path / "relations.md")
    hindsight = MemoryStore()
    hindsight.name = "hindsight"
    with pytest.raises(ValueError, match="brain graph migrate"):
        brain_remember([v, hindsight, g], "", "relation", subject="A", predicate="b", object="C")
    assert not (tmp_path / "relations.md").exists() and not hindsight.records
    assert v.write("relation", "A —[b]→ C").status == "refused"  # the store itself refuses too
    migrate_relations(db, v, tmp_path / "backups")
    out = brain_remember([v, hindsight, g], "", "relation", subject="A", predicate="b", object="C")
    assert out["status"] == "written" and g.mirror and v.relations_drift() == (0, 0, 0)


def test_a_crash_between_the_vault_line_and_the_mirror_heals_on_the_next_sync(
    tmp_path: Path, db: Database
) -> None:
    v, g = vault_on(tmp_path, db), GraphStore(db, tmp_path / "relations.md")
    v.write("relation", "", subject="A", predicate="b", object="C", when=DAY)  # then killed
    assert not rows(db) and v.relations_drift() == (0, 1, 0)
    v.read("relation", "A")  # the next search syncs
    assert len(rows(db)) == 1 and [r.text for r in g.read("relation", "A")] == ["A —[b]→ C"]


def test_a_row_the_line_cannot_hold_stays_recallable_from_the_table(
    tmp_path: Path, db: Database
) -> None:
    legacy(db, "A]]B", "uses", "C", "2026-04-10")
    v, g = vault_on(tmp_path, db), GraphStore(db, tmp_path / "relations.md")
    assert not migrate_relations(db, v, tmp_path / "backups")["complete"]
    brain_remember([v, g], "", "relation", subject="D", predicate="owns", object="E", when=DAY)
    assert g.mirror and [r.text for r in g.read("relation", "uses")] == ["A]]B —[uses]→ C"]
    assert v.relations_drift() == (0, 0, 1)  # not "removed by hand": it never could be a line
