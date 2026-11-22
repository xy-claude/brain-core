"""`brain index --migrate-ids` (M1b): notes and archive records move from ids that hash a
folder's absolute path to ids that hash ``<store>:<root name>/<file>#heading``, and what was
filed under the old ids comes along. Search keys and `supersedes` links follow through
`was:` lines in record_meta.md; vectors are remapped in brain.db.

A dry run by default, which writes nothing. With ``apply``:
1. a checked backup of brain.db and record_meta.md
2. a manifest (the id map and every source file's hash)
3. the `was:` lines, under a dated comment
4. the vectors
5. every notes and archive file indexed again, then checked

A crash resumes from the manifest, unless the files changed since; then it refuses, and the
dry run is the next step.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from brain_core.backup import backup_db, private_file, stamp
from brain_core.storage.db import Database
from brain_core.stores.notes import NotesStore
from brain_core.stores.vault import META, VaultStore


def _sources(stores: Sequence[NotesStore]) -> dict[str, str]:
    """sha256 of every file the migration reads, by path."""
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for s in stores
        for d in s.roots
        if d.is_dir()
        for p in sorted(d.glob("*.md"))
    }


def _write(path: Path, data: dict[str, Any]) -> None:
    """The manifest, replaced whole, readable by the owner only."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    private_file(tmp, json.dumps(data, indent=1).encode())
    os.replace(tmp, path)


def migrate_ids(
    db: Database,
    vault: VaultStore,
    stores: Sequence[NotesStore],
    data_dir: Path,
    apply: bool = False,
    old_paths: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """Plan, and with ``apply`` carry out, the move to store-relative ids. ``old_paths``: a
    folder's former location by root name, when keys were written before it moved."""
    mapping: dict[str, str] = {}
    for s in stores:
        mapping |= s.id_map(old_paths)
    sources = _sources(stores)
    manifest: Path | None = None
    backup: list[str] = []
    if apply:
        data_dir.mkdir(parents=True, exist_ok=True)
        for m in sorted(data_dir.glob("migrate-ids-*.json")):
            open_ = json.loads(m.read_text())
            if open_.get("status") == "applying":
                if open_["sources"] != sources:
                    raise RuntimeError(
                        f"the notes or archive files changed since the interrupted migration "
                        f"({m.name}): run `brain index --migrate-ids` without --apply, then apply"
                    )
                manifest, backup, mapping = m, open_["backup"], open_["map"]
    meta = vault.meta()
    named = set(meta) | {
        old[:16] for d in meta.values() for old in d.get("supersedes", "").replace(";", " ").split()
    }
    to_was = {o: n for o, n in mapping.items() if o[:16] in named}
    vectors = {r[0] for r in db.fetchall("SELECT record_id FROM record_vectors")}
    to_move = {o: n for o, n in mapping.items() if o in vectors}
    report: dict[str, Any] = {
        "changed": len(mapping),
        "meta_ids": len(to_was),
        "vectors": len(to_move),
    }
    if not apply:
        return report
    if manifest is None:
        at = stamp()
        saved = [backup_db(db, data_dir / "backups", at)]
        if (vault.root / META).exists():
            data = (vault.root / META).read_bytes()
            saved.append(private_file(data_dir / "backups" / f"record_meta-{at}.md", data))
        backup = [str(p) for p in saved]
        manifest = data_dir / f"migrate-ids-{at}.json"
        _write(
            manifest, {"status": "applying", "backup": backup, "sources": sources, "map": mapping}
        )
    added = vault.append_meta(
        [f"- {n[:16]} | was: {o[:16]}" for o, n in sorted(to_was.items())],
        f"<!-- brain index --migrate-ids {date.today().isoformat()} -->",
    )
    for old, new in to_move.items():
        if db.fetchone("SELECT 1 FROM record_vectors WHERE record_id = ?", (new,)):
            db.execute("DELETE FROM record_vectors WHERE record_id = ?", (old,))
        else:
            db.execute("UPDATE record_vectors SET record_id = ? WHERE record_id = ?", (new, old))
    for s in stores:  # every notes and archive file is read again, under its new ids
        db.execute("DELETE FROM index_files WHERE store = ?", (s.name,))
        s.read("knowledge", "sync", 1)
    vault.read("fact", "sync", 1)  # the keys again, `was:` lines included
    rids = {r[0] for r in db.fetchall("SELECT rid FROM records_fts")}
    verified = all(n in rids for n in mapping.values())
    _write(
        manifest,
        {
            "status": "applied" if verified else "applying",
            "backup": backup,
            "sources": sources,
            "map": mapping,
        },
    )
    return {
        **report,
        "was_lines": added,
        "vectors_remapped": len(to_move),
        "backup": backup,
        "manifest": str(manifest),
        "verified": verified,
    }
