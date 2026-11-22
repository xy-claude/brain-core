"""M1b: notes and archive ids come from `<store>:<root name>/<file>#heading`, not a folder's
absolute path, so moving a folder keeps every id and the search keys and vectors with it."""

from __future__ import annotations

import json
import shutil
import stat
import sys
from pathlib import Path

import pytest

from brain_core.migrate_ids import migrate_ids
from brain_core.storage import Database
from brain_core.stores.base import record_id
from brain_core.stores.index import RecordIndex
from brain_core.stores.notes import ArchiveStore, NotesStore
from brain_core.stores.vault import VaultStore


def page(root: Path, name: str = "tips.md", body: str = "## Deploy\nrsync the build\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(f"# Tips\n\n{body}")
    return root / name


def ids(store: NotesStore) -> set[str]:
    return {r.id for r in store.read("knowledge", limit=100)}


def legacy(file: Path, heading: str = "Deploy") -> str:
    """The id 0.10.0 gave a notes record: its file's absolute path and heading."""
    return record_id(f"{file}#{heading}")


def keyed(vault: VaultStore, rid: str, words: str) -> None:
    vault._note_meta(rid, __import__("datetime").date(2026, 11, 22), {"keys": words})


def found(store: NotesStore, query: str) -> list[str]:
    return [r.text for r in store.read("knowledge", query, 10)]


def test_moving_a_folder_keeps_every_id(tmp_path: Path) -> None:
    page(tmp_path / "a" / "shared")
    before = ids(NotesStore([tmp_path / "a" / "shared"]))
    (tmp_path / "b").mkdir()
    shutil.move(tmp_path / "a" / "shared", tmp_path / "b" / "shared")
    assert ids(NotesStore([tmp_path / "b" / "shared"])) == before


def test_a_renamed_folder_keeps_its_ids_when_named(tmp_path: Path) -> None:
    page(tmp_path / "shared")
    before = ids(NotesStore([(tmp_path / "shared", "team")]))
    (tmp_path / "shared").rename(tmp_path / "renamed")
    assert ids(NotesStore([(tmp_path / "renamed", "team")])) == before


def test_the_id_is_the_store_root_and_file_and_the_shown_path_is_the_real_one(
    tmp_path: Path,
) -> None:
    f = page(tmp_path / "shared")
    (r,) = ArchiveStore([tmp_path / "shared"]).read("knowledge")
    assert r.id == record_id("archive:shared/tips.md#Deploy") and r.path == str(f)


def test_vault_knowledge_ids_are_unchanged(tmp_path: Path) -> None:
    page(tmp_path / "knowledge", "x.md")
    (r,) = VaultStore(tmp_path).read("knowledge")
    assert r.id == record_id("knowledge/x.md#Deploy")


def test_two_roots_with_one_name_keep_their_path_ids(tmp_path: Path) -> None:
    a, b = page(tmp_path / "p1" / "memory"), page(tmp_path / "p2" / "memory", "other.md")
    s = NotesStore([tmp_path / "p1" / "memory", tmp_path / "p2" / "memory"])
    assert ids(s) == {legacy(a), legacy(b)}
    assert "name:" in s.health()[1]


def test_an_upgrade_without_the_migration_keeps_search_keys(tmp_path: Path, db: Database) -> None:
    f = page(tmp_path / "shared")
    vault = VaultStore(tmp_path / "vault", index=RecordIndex(db))
    keyed(vault, legacy(f), "zanzibar")  # written by 0.10.0, under the path id
    notes = NotesStore([tmp_path / "shared"], vault.index)
    vault.read("fact", "sync")  # the vault loads the keys
    assert found(notes, "zanzibar") == ["Tips › Deploy: rsync the build"]
    assert vault.detached_keys() == 0


def test_a_rename_without_a_name_detaches_keys_and_doctor_names_them(
    tmp_path: Path, db: Database
) -> None:
    page(tmp_path / "shared")
    vault = VaultStore(tmp_path / "vault", index=RecordIndex(db))
    keyed(vault, record_id("notes:shared/tips.md#Deploy"), "zanzibar")
    (tmp_path / "shared").rename(tmp_path / "renamed")
    NotesStore([tmp_path / "renamed"], vault.index).read("knowledge", "sync")
    vault.read("fact", "sync")
    assert vault.detached_keys() == 1


def _setup(tmp_path: Path, db: Database) -> tuple[VaultStore, NotesStore, Path]:
    f = page(tmp_path / "old" / "shared")
    vault = VaultStore(tmp_path / "vault", index=RecordIndex(db))
    keyed(vault, legacy(f), "zanzibar")
    vault.supersede("f" * 64, legacy(f))  # a later record replaced this one
    notes = NotesStore([tmp_path / "old" / "shared"], vault.index)
    notes.read("knowledge", "sync")
    db.execute(
        "INSERT INTO record_vectors (record_id, model, dim, text_hash, vec) "
        "VALUES (?, 'm', 1, 'h', x'00')",
        (legacy(f),),
    )
    return vault, notes, f


def test_the_dry_run_writes_nothing(tmp_path: Path, db: Database) -> None:
    vault, notes, _f = _setup(tmp_path, db)
    meta = (vault.root / "record_meta.md").read_text()
    report = migrate_ids(db, vault, [notes], tmp_path / "data")
    assert (report["changed"], report["meta_ids"], report["vectors"]) == (1, 1, 1)
    assert (vault.root / "record_meta.md").read_text() == meta and not (tmp_path / "data").exists()


def test_after_the_migration_keys_links_and_vectors_survive_a_move(
    tmp_path: Path, db: Database
) -> None:
    vault, notes, _f = _setup(tmp_path, db)
    report = migrate_ids(db, vault, [notes], tmp_path / "data", apply=True)
    assert report["verified"] and report["was_lines"] == 1 and report["vectors_remapped"] == 1
    new = record_id("notes:shared/tips.md#Deploy")
    assert db.fetchone("SELECT record_id FROM record_vectors")[0] == new  # type: ignore[index]
    # the keys once, as before: twice would weigh the record's words double in ranking
    assert db.fetchone("SELECT keys FROM records_fts WHERE rid = ?", (new,))[0] == "zanzibar"  # type: ignore[index]
    # the folder moves: the path id is gone, and the `was:` line still carries the keys
    (tmp_path / "new").mkdir()
    shutil.move(tmp_path / "old" / "shared", tmp_path / "new" / "shared")
    moved = NotesStore([tmp_path / "new" / "shared"], vault.index)
    vault.read("fact", "sync")
    assert found(moved, "zanzibar") == ["Tips › Deploy: rsync the build"]
    assert new[:16] in vault.retired()  # the supersedes link follows the record
    again = migrate_ids(db, vault, [moved], tmp_path / "data", apply=True)
    assert again["was_lines"] == 0  # nothing left to map


def test_the_backup_is_checked_and_private(tmp_path: Path, db: Database) -> None:
    vault, notes, _f = _setup(tmp_path, db)
    report = migrate_ids(db, vault, [notes], tmp_path / "data", apply=True)
    saved = [Path(p) for p in report["backup"]]
    assert {p.suffix for p in saved} == {".db", ".md"}
    assert sys.platform == "win32" or all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in saved)


def test_a_resume_refuses_sources_that_changed(
    tmp_path: Path, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, notes, f = _setup(tmp_path, db)

    def crash(*a: object, **k: object) -> None:
        raise KeyboardInterrupt  # killed after the manifest, before the `was:` lines

    monkeypatch.setattr(VaultStore, "append_meta", crash)
    with pytest.raises(KeyboardInterrupt):
        migrate_ids(db, vault, [notes], tmp_path / "data", apply=True)
    monkeypatch.undo()
    f.write_text(f.read_text() + "## Later\nadded after the crash\n")
    with pytest.raises(RuntimeError, match="changed"):
        migrate_ids(db, vault, [notes], tmp_path / "data", apply=True)
    manifest = next((tmp_path / "data").glob("migrate-ids-*.json"))
    assert json.loads(manifest.read_text())["status"] == "applying"


def test_a_resume_with_unchanged_sources_completes(
    tmp_path: Path, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, notes, _f = _setup(tmp_path, db)

    def crash(*a: object, **k: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(VaultStore, "append_meta", crash)
    with pytest.raises(KeyboardInterrupt):
        migrate_ids(db, vault, [notes], tmp_path / "data", apply=True)
    monkeypatch.undo()
    report = migrate_ids(db, vault, [notes], tmp_path / "data", apply=True)
    assert report["verified"] and report["was_lines"] == 1


def test_an_old_location_maps_keys_written_there(tmp_path: Path, db: Database) -> None:
    """A folder already moved before the migration: --old-path names where it was."""
    f = page(tmp_path / "now" / "shared")
    vault = VaultStore(tmp_path / "vault", index=RecordIndex(db))
    was_at = tmp_path / "then" / "shared"
    keyed(vault, legacy(was_at / "tips.md"), "zanzibar")
    notes = NotesStore([tmp_path / "now" / "shared"], vault.index)
    report = migrate_ids(
        db, vault, [notes], tmp_path / "data", apply=True, old_paths={"shared": was_at}
    )
    vault.read("fact", "sync")
    assert report["was_lines"] == 1 and found(notes, "zanzibar") and f.exists()


def test_a_reply_does_not_carry_the_old_id(tmp_path: Path, db: Database) -> None:
    """`was` is bookkeeping: in a reply it would cost the token budget a result (M1b)."""
    from brain_core.recall import brain_recall

    page(tmp_path / "shared")
    vault = VaultStore(tmp_path / "vault", index=RecordIndex(db))
    notes = NotesStore([tmp_path / "shared"], vault.index)
    (hit,) = brain_recall([vault, notes], "rsync the build", fmt="detailed")["results"]
    assert hit["store"] == "notes" and "was" not in hit["extra"]
