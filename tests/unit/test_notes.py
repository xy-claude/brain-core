"""NotesStore: read-only folders recall also searches (shared vault folder, Claude Code memory)."""

from pathlib import Path

from brain_core.recall import brain_recall
from brain_core.stores.notes import NotesStore


def test_notes_reads_sections_and_plain_memory_files(tmp_path: Path) -> None:
    shared, memory = tmp_path / "shared", tmp_path / "memory"
    shared.mkdir(), memory.mkdir()
    (shared / "infrastructure.md").write_text(
        "---\nupdated: 2026-10-01\n---\n# Infrastructure\n\n## Hindsight\nruns on port 8888\n"
    )
    # a Claude Code memory file: frontmatter, no H1, no sections
    (memory / "push_rule.md").write_text(
        "---\nname: push-rule\ndescription: when to push\n---\n\n"
        "Push only when the user says push.\n"
    )
    store = NotesStore([shared, memory])
    texts = {r.text for r in store.read("knowledge")}
    assert "Infrastructure › Hindsight: runs on port 8888" in texts
    assert "push-rule: Push only when the user says push." in texts
    assert store.read("fact") == []
    assert store.read("knowledge", "8888")[0].path == str(shared / "infrastructure.md")

    hit = brain_recall([store], "when do we push")["results"][0]
    assert hit["kind"] == "knowledge" and "push" in hit["text"]


def test_notes_never_writes_and_reports_a_missing_folder(tmp_path: Path) -> None:
    store = NotesStore([tmp_path / "gone"])
    assert store.write("fact", "x").status == "refused"
    ok, msg = store.health()
    assert not ok and "gone" in msg
    (tmp_path / "gone").mkdir()
    assert store.health() == (True, "notes files=0 folders=1")
