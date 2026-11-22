"""M2: the entity registry. An entity is a note in vault/entities/ with a stable id; brain.db
holds a registry derived from those notes, and the mentions of each entity in every record."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from brain_core.entities import EntityIndex, normalize_alias, uuid7
from brain_core.journal import Journal, occurrence_id
from brain_core.remember import brain_remember
from brain_core.storage import Database
from brain_core.stores.base import record_id
from brain_core.stores.index import RecordIndex
from brain_core.stores.notes import NotesStore
from brain_core.stores.vault import VaultStore

NEO = "019a8b3e-7c2d-7f41-9a10-3b5e2d8c4f11"
BRAIN = "019a8b3e-7c2d-7f41-9a10-3b5e2d8c4f22"


def note(root: Path, name: str, eid: str, etype: str = "technology", **more: str) -> Path:
    (root / "entities").mkdir(parents=True, exist_ok=True)
    extra = "".join(f"{k}: {v}\n" for k, v in more.items())
    path = root / "entities" / f"{name}.md"
    path.write_text(
        f"---\ntype: entity\nid: {eid}\nentity_type: {etype}\nontology: 1\n{extra}---\n# {name}\n"
    )
    return path


def facts(root: Path, *lines: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "facts.md").write_text("# Facts\n\n## General\n" + "".join(f"- {x}\n" for x in lines))


def vault(tmp_path: Path, db: Database) -> VaultStore:
    v = VaultStore(tmp_path / "vault", index=RecordIndex(db))
    v.root.mkdir(parents=True, exist_ok=True)
    return v


def ents(v: VaultStore) -> EntityIndex:
    assert v.entities is not None
    return v.entities


def sync(v: VaultStore) -> None:
    v.read("fact", "sync")


def mentions(db: Database) -> set[tuple[str, str, str]]:
    return {
        (r["record_id"][:10], r["entity_id"][-2:], r["how"])
        for r in db.fetchall("SELECT record_id, entity_id, how FROM mentions")
    }


def test_an_entity_note_is_registered(tmp_path: Path, db: Database) -> None:
    v = vault(tmp_path, db)
    note(v.root, "Neo4j", NEO, aliases="[neo4j-community, Neo4j 5]")
    sync(v)
    row = db.fetchone("SELECT id, type, name, source_id FROM entities")
    assert tuple(row) == (NEO, "technology", "Neo4j", "vault:entities/Neo4j.md")  # type: ignore[arg-type]
    aliases = {r[0] for r in db.fetchall("SELECT alias FROM aliases WHERE entity_id = ?", (NEO,))}
    assert aliases == {"neo4j", "neo4j-community", "neo4j 5"}


def test_a_renamed_note_keeps_its_id(tmp_path: Path, db: Database) -> None:
    v = vault(tmp_path, db)
    path = note(v.root, "Neo4j", NEO)
    sync(v)
    path.rename(path.with_name("Neo4j graph.md"))
    sync(v)
    rows = db.fetchall("SELECT id, source_id FROM entities")
    assert [tuple(r) for r in rows] == [(NEO, "vault:entities/Neo4j graph.md")]


def test_wikilinks_aliases_and_tags_are_mentions(tmp_path: Path, db: Database) -> None:
    v = vault(tmp_path, db)
    note(v.root, "Neo4j", NEO, aliases="[neo4j-community]")
    note(v.root, "brain-core", BRAIN, etype="project")
    lines = (
        "We benchmarked [[Neo4j|the graph store]] last week",
        "The neo4j-community edition needs Java",
        "Decided against it #brain-core",
        "Nothing to see here",
    )
    facts(v.root, *lines)
    sync(v)
    want = {
        (record_id(lines[0])[:10], NEO[-2:], "wikilink"),
        (record_id(lines[1])[:10], NEO[-2:], "alias"),
        (record_id(lines[2])[:10], BRAIN[-2:], "tag"),
    }
    assert mentions(db) == want


def test_copies_get_their_own_mention_rows(tmp_path: Path, db: Database) -> None:
    v = vault(tmp_path, db)
    note(v.root, "Neo4j", NEO)
    facts(v.root, "Uses [[Neo4j]]", "Uses [[Neo4j]]")
    sync(v)
    occ = {r[0] for r in db.fetchall("SELECT occ_id FROM mentions")}
    rid = record_id("Uses [[Neo4j]]")
    assert occ == {occurrence_id("vault:facts.md", rid, 1), occurrence_id("vault:facts.md", rid, 2)}


def test_relation_lines_mention_their_entities_and_are_journaled(
    tmp_path: Path, db: Database
) -> None:
    j = Journal(tmp_path / "journal.db")
    v = VaultStore(tmp_path / "vault", index=RecordIndex(db, j))
    note(v.root, "Neo4j", NEO)
    note(v.root, "brain-core", BRAIN, etype="project")
    v.write("relation", "", subject="brain-core", predicate="rejects", object="Neo4j")
    assert {m[1] for m in mentions(db)} == {NEO[-2:], BRAIN[-2:]}
    sources = {r[0] for r in j.db.fetchall("SELECT source_id FROM ledger_occurrences")}
    assert "vault:relations.md" in sources  # recorded, though kept out of the keyword index
    assert db.fetchone("SELECT count(*) FROM records_fts WHERE kind = 'relation'")[0] == 0  # type: ignore[index]


def test_mentions_follow_a_new_alias(tmp_path: Path, db: Database) -> None:
    v = vault(tmp_path, db)
    path = note(v.root, "Neo4j", NEO)
    facts(v.root, "The graph store needs Java")
    sync(v)
    assert mentions(db) == set()
    path.write_text(
        path.read_text().replace("ontology: 1\n", "ontology: 1\naliases: [graph store]\n")
    )
    sync(v)
    assert mentions(db) == {(record_id("The graph store needs Java")[:10], NEO[-2:], "alias")}


def test_notes_records_are_mentioned_too(tmp_path: Path, db: Database) -> None:
    v = vault(tmp_path, db)
    note(v.root, "Neo4j", NEO)
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "graph.md").write_text("# Graphs\n\n## Choice\nWe tried [[Neo4j]]\n")
    sync(v)
    NotesStore([tmp_path / "shared"], v.index).read("knowledge", "sync")
    assert {(m[1], m[2]) for m in mentions(db)} == {(NEO[-2:], "wikilink")}


def test_a_merge_chain_resolves_and_a_dangling_merge_is_refused(
    tmp_path: Path, db: Database
) -> None:
    v = vault(tmp_path, db)
    third = "019a8b3e-7c2d-7f41-9a10-3b5e2d8c4f33"
    note(v.root, "neo4j-old", third, merged_into=NEO)
    note(v.root, "Neo4j", NEO, merged_into=BRAIN)  # a chain: third -> NEO -> BRAIN
    note(v.root, "brain-core", BRAIN, etype="project")
    note(v.root, "ghost", "019a8b3e-7c2d-7f41-9a10-3b5e2d8c4f44", merged_into="019a-none")
    sync(v)
    assert ents(v).resolve(third) == BRAIN
    problems = ents(v).problems()
    assert any("ghost" in p and "merged_into" in p for p in problems)
    ghost = db.fetchone("SELECT merged_into FROM entities WHERE name = 'ghost'")
    assert ghost[0] is None  # type: ignore[index]  # refused: not stored


def test_a_merge_cycle_is_refused(tmp_path: Path, db: Database) -> None:
    v = vault(tmp_path, db)
    note(v.root, "a", NEO, merged_into=BRAIN)
    note(v.root, "b", BRAIN, merged_into=NEO)
    sync(v)
    assert any("cycle" in p for p in ents(v).problems())
    assert ents(v).resolve(NEO) in (NEO, BRAIN)  # never loops


def test_an_alias_two_entities_share_seeds_both_and_is_reported(
    tmp_path: Path, db: Database
) -> None:
    v = vault(tmp_path, db)
    note(v.root, "Neo4j", NEO, aliases="[graph]")
    note(v.root, "brain-core", BRAIN, etype="project", aliases="[graph]")
    facts(v.root, "The graph is slow")
    sync(v)
    assert {m[1] for m in mentions(db)} == {NEO[-2:], BRAIN[-2:]}
    assert any("graph" in p and "2 entities" in p for p in ents(v).problems())


def test_an_unknown_entity_type_is_reported(tmp_path: Path, db: Database) -> None:
    v = vault(tmp_path, db)
    note(v.root, "Thing", NEO, etype="gadget")
    sync(v)
    assert any("gadget" in p for p in ents(v).problems())
    assert db.fetchone("SELECT count(*) FROM entities")[0] == 0  # type: ignore[index]


def test_brain_remember_makes_an_entity_note_once(tmp_path: Path, db: Database) -> None:
    v = vault(tmp_path, db)
    out = brain_remember(
        [v], "", "entity", name="Neo4j", entity_type="technology", aliases="neo4j-community"
    )
    path = v.root / "entities" / "Neo4j.md"
    assert out["status"] == "written" and path.exists()
    eid = db.fetchone("SELECT id FROM entities")[0]  # type: ignore[index]
    assert uuid.UUID(eid).version == 7
    again = brain_remember([v], "", "entity", name="neo4j", entity_type="technology")
    assert again["layers"]["vault"]["status"] == "exists"  # the same entity, by name or alias


def test_uuid7_is_time_ordered() -> None:
    a = uuid7()
    __import__("time").sleep(0.002)  # within one millisecond the order is random, by design
    b = uuid7()
    assert uuid.UUID(a).version == 7 and a <= b


def test_alias_normalisation() -> None:
    assert normalize_alias("  \uff2e\uff45\uff4f4\uff4a  Community ") == "neo4j community"


def test_propose_stages_names_without_a_note_and_writes_none(tmp_path: Path, db: Database) -> None:
    v = vault(tmp_path, db)
    note(v.root, "Neo4j", NEO)
    v.write("relation", "", subject="brain-core", predicate="rejects", object="Neo4j")
    added = ents(v).propose(v.root / "inbox_staged.md")
    inbox = (v.root / "inbox_staged.md").read_text()
    assert added == 1 and "[[brain-core]]" in inbox and "[[Neo4j]]" not in inbox
    assert not (v.root / "entities" / "brain-core.md").exists()  # a proposal, never a note
    assert ents(v).propose(v.root / "inbox_staged.md") == 0  # staged once


@pytest.mark.parametrize("bad", ["[[Neo4j]] — no frontmatter id", ""])
def test_a_note_without_an_id_is_reported_not_registered(
    tmp_path: Path, db: Database, bad: str
) -> None:
    v = vault(tmp_path, db)
    (v.root / "entities").mkdir(parents=True)
    (v.root / "entities" / "x.md").write_text(
        f"---\ntype: entity\nentity_type: technology\n---\n{bad}\n"
    )
    sync(v)
    assert db.fetchone("SELECT count(*) FROM entities")[0] == 0  # type: ignore[index]
    assert any("x.md" in p and "id" in p for p in ents(v).problems())


def test_brain_entities_check_and_propose(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from brain_core.cli.main import app

    v = tmp_path / "vault"
    note(v, "Neo4j", NEO)
    note(v, "Thing", BRAIN, etype="gadget")
    (v / "relations.md").write_text(
        "# Relations\n\n## Relations\n"
        "- [[brain-core]] —[rejects]→ [[Neo4j]] (recorded: 2026-11-23)\n"
    )
    (tmp_path / "brain.yaml").write_text(f"name: T\nstores:\n  vault: {v}\n")
    check = CliRunner().invoke(app, ["entities", "check", str(tmp_path)])
    assert check.exit_code == 1 and "gadget" in check.output
    listed = CliRunner().invoke(app, ["entities", "list", str(tmp_path)])
    assert "Neo4j" in listed.output and "technology" in listed.output
    prop = CliRunner().invoke(app, ["entities", "propose", str(tmp_path)])
    assert prop.exit_code == 0 and "1 proposed" in prop.output
    assert "[[brain-core]]" in (v / "inbox_staged.md").read_text()


def test_brain_status_names_entity_problems(tmp_path: Path) -> None:
    from brain_core.agent import Agent

    v = tmp_path / "vault"
    note(v, "Thing", NEO, etype="gadget")
    (tmp_path / "brain.yaml").write_text(f"name: T\nstores:\n  vault: {v}\n")
    with Agent.from_config(tmp_path / "brain.yaml") as a:
        a.brain_sync()
        st = a.brain_status()
    assert any("entity" in line and "gadget" in line for line in st["attention"])
