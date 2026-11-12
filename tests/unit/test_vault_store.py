"""VaultStore against a legacy-shaped vault copy (docs/VAULT_SCHEMA.md)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from brain_core.stores import MemoryStore, VaultStore
from brain_core.stores.base import Kind, record_id
from brain_core.stores.vault import FILES

LEGACY_FACTS = """---
type: reference
owner: atlas
updated: 2026-10-01
---
# Operational Facts

## System
- ATLAS brain initialized: 2026-04-03
- Hindsight bank: atlas-brain self-hosted (2026-11-01)

## Hardware
- Mac mini M4 (2026-04-19)
"""

LEGACY_DECISIONS = """---
type: log
owner: atlas
updated: 2026-10-01
---
# Decisions Log

### YYYY-MM-DD — Title
**Decision:** template

## 2026-04-06 — Universal Brain Inheritance Architecture
**Decision:** AGENTS/CLAUDE.md is the deployment target
**Reason:** one source
**Classification:** reversible × low-risk
**Confidence:** high
"""

LEGACY_CORRECTIONS = """---
type: log
owner: atlas
updated: 2026-08-18
---
# Corrections Log

## Corrections

### [2026-08-18] Claimed done by eyeballing
- **Error:** glanced at a thumbnail
- **Correction:** measure first
- **Theme:** execution
"""


@pytest.fixture
def vault(tmp_path: Path) -> VaultStore:
    (tmp_path / "facts.md").write_text(LEGACY_FACTS)
    (tmp_path / "decisions_log.md").write_text(LEGACY_DECISIONS)
    (tmp_path / "corrections.md").write_text(LEGACY_CORRECTIONS)
    return VaultStore(tmp_path, owner="atlas")


def test_reads_legacy_facts_with_and_without_dates(vault: VaultStore) -> None:
    facts = vault.read("fact")
    assert [f.text for f in facts][:1] == ["Hindsight bank: atlas-brain self-hosted"]
    undated = next(f for f in facts if f.text.startswith("ATLAS brain initialized"))
    assert undated.date == date(2026, 10, 1) and undated.extra == {"legacy": "undated"}
    assert undated.domain == "System" and undated.line == 9


def test_reads_decisions_and_corrections_with_fields(vault: VaultStore) -> None:
    d = vault.read("decision")
    assert len(d) == 1 and d[0].date == date(2026, 4, 6)
    assert d[0].extra["classification"] == "reversible × low-risk"
    c = vault.read("correction")
    assert c[0].extra["correction"] == "measure first" and c[0].text == "Claimed done by eyeballing"


def test_fact_write_is_dated_sectioned_and_idempotent(vault: VaultStore) -> None:
    r1 = vault.write("fact", "defuddle extracts web pages", domain="Tools", when=date(2026, 11, 2))
    r2 = vault.write("fact", "defuddle  extracts web pages (2026-11-02)", domain="Tools")
    assert (
        r1.status == "written"
        and r2.status == "exists"
        and r1.id == r2.id == record_id("defuddle extracts web pages")
    )
    text = (vault.root / "facts.md").read_text()
    assert "## Tools\n- defuddle extracts web pages (2026-11-02)" in text
    assert "updated: 2026-11-02" in text
    assert text.count("defuddle") == 1


def test_fact_write_appends_inside_existing_section(vault: VaultStore) -> None:
    vault.write("fact", "pg0 runs Postgres 18", domain="System", when=date(2026, 11, 2))
    lines = (vault.root / "facts.md").read_text().splitlines()
    sys_i = lines.index("## System")
    hw_i = lines.index("## Hardware")
    assert any("pg0 runs Postgres 18 (2026-11-02)" in ln for ln in lines[sys_i:hw_i])


def test_decision_inserted_newest_first_after_template(vault: VaultStore) -> None:
    r = vault.write(
        "decision",
        "Self-host Hindsight",
        title="Hindsight self-hosted",
        reason="no bill",
        classification="reversible × low-risk",
        confidence="high",
        when=date(2026, 11, 1),
    )
    assert r.status == "written"
    text = (vault.root / "decisions_log.md").read_text()
    assert text.index("## 2026-11-01 — Hindsight self-hosted") < text.index(
        "## 2026-04-06 — Universal"
    )
    assert text.index("### YYYY-MM-DD — Title") < text.index("## 2026-11-01")
    assert vault.read("decision")[0].extra["reason"] == "no bill"


def test_correction_goes_under_corrections_heading(vault: VaultStore) -> None:
    vault.write(
        "correction",
        "Added co-author trailer",
        title="Co-author trailer",
        correction="Ada is the sole author",
        rule="no trailers",
        when=date(2026, 11, 1),
    )
    text = (vault.root / "corrections.md").read_text()
    assert (
        text.index("## Corrections")
        < text.index("### [2026-11-01] Co-author trailer")
        < text.index("### [2026-08-18]")
    )


def test_note_creates_daily_file_with_section(vault: VaultStore) -> None:
    r = vault.write("note", "Ada said ship it", when=date(2026, 11, 2), section="Decisions Made")
    p = vault.root / "sessions" / "2026-11-02.md"
    assert r.status == "written" and p.exists()
    assert (
        "# Session Archive — 2026-11-02" in p.read_text()
        and "## Decisions Made\n- Ada said ship it" in p.read_text()
    )
    assert vault.read("note", "ship it")[0].domain == "Decisions Made"


def test_raw_write_is_immutable_and_deduped_by_source(vault: VaultStore) -> None:
    r1 = vault.write(
        "raw",
        "body text",
        when=date(2026, 11, 2),
        title="LLM Wiki",
        source="https://x/y",
        author="K",
    )
    r2 = vault.write(
        "raw",
        "different body",
        when=date(2026, 11, 3),
        title="LLM Wiki again",
        source="https://x/y",
    )
    assert r1.status == "written" and r2.status == "exists" and r2.detail == r1.detail
    fm = vault.read("raw")[0].extra
    assert fm["sha256"] == r1.id and fm["compiled_into"] == "[]"


def test_secret_refused(vault: VaultStore) -> None:
    r = vault.write("fact", "token is hsk_abcdefghijklmnop", when=date(2026, 11, 2))
    assert r.status == "refused" and "hsk_" not in (vault.root / "facts.md").read_text()


def test_health_reports_root(vault: VaultStore, tmp_path: Path) -> None:
    ok, detail = vault.health()
    assert ok and "3 notes" in detail
    assert VaultStore(tmp_path / "missing").health()[0] is False


def test_memory_store_same_contract() -> None:
    m = MemoryStore()
    assert m.write("fact", "a").status == "written" and m.write("fact", "a").status == "exists"
    assert MemoryStore(healthy=False).write("fact", "a").status == "failed"
    assert m.read("fact", "A")[0].text == "a"


def test_knowledge_pages_are_read_per_section_and_never_written(tmp_path: Path) -> None:
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "_index.md").write_text("| [[wiki]] | | | |\n")
    (tmp_path / "knowledge" / "wiki.md").write_text(
        "---\nupdated: 2026-11-02\n---\n# LLM Wiki\n\n## Core Concepts\n- raw is immutable\n"
        "- the agent owns the wiki\n\n## Rules\n- cite or omit\n"
    )
    v = VaultStore(tmp_path, "t")
    recs = v.read("knowledge")
    assert [r.text for r in recs] == [
        "LLM Wiki › Core Concepts: - raw is immutable - the agent owns the wiki",
        "LLM Wiki › Rules: - cite or omit",
    ]
    assert (
        recs[0].path == "knowledge/wiki.md"
        and recs[0].line == 6
        and recs[0].date == date(2026, 11, 2)
    )
    assert v.write("knowledge", "nope").status == "refused"


@pytest.mark.parametrize(
    ("kind", "extra"),
    [
        ("decision", {"title": "Hindsight self-hosted"}),
        ("correction", {"title": "Pushed without approval"}),
        ("pattern", {"title": "Cadence"}),
    ],
)
def test_titled_write_twice_is_exists_not_a_duplicate(
    vault: VaultStore, kind: Kind, extra: dict[str, str]
) -> None:
    first = vault.write(kind, "Self-host Hindsight before paying for cloud", title=extra["title"])
    second = vault.write(kind, "Self-host Hindsight before paying for cloud", title=extra["title"])
    assert first.status == "written" and second.status == "exists" and first.id == second.id
    body = (vault.root / FILES[kind]).read_text()
    assert body.count(extra["title"]) == 1


def test_multiline_text_is_one_bullet_with_one_id(vault: VaultStore) -> None:
    first = vault.write("fact", "step one\n  step two", domain="System")
    second = vault.write("fact", "step one step two", domain="System")
    assert first.status == "written" and second.status == "exists"
    assert "- step one step two (" in (vault.root / "facts.md").read_text()


def test_typo_date_heading_does_not_break_reads(vault: VaultStore) -> None:
    path = vault.root / "decisions_log.md"
    path.write_text(path.read_text() + "\n## 2026-13-01 — Typed by hand\n**Decision:** x\n")
    titles = [r.text for r in vault.read("decision")]
    assert "Typed by hand" in titles and "Universal Brain Inheritance Architecture" in titles


def test_raw_same_title_different_source_keeps_both(vault: VaultStore) -> None:
    a = vault.write("raw", "body of a", title="Home", source="https://a.example/")
    b = vault.write("raw", "body of b", title="Home", source="https://b.example/")
    assert a.status == b.status == "written" and a.detail != b.detail
    assert (vault.root / a.detail).read_text().endswith("body of a")
    assert (vault.root / b.detail).read_text().endswith("body of b")
    c = vault.write("raw", "body of c", title="日本語", source="https://c.example/")
    assert c.detail.endswith("-untitled.md")


def test_bearer_guard_needs_a_digit(vault: VaultStore) -> None:
    ok = vault.write("fact", "Use bearer authentication-header for the API", domain="System")
    assert ok.status == "written"
    bad = vault.write("fact", "token: bearer abcdef1234567890xyz", domain="System")
    assert bad.status == "refused"


def test_the_lock_lives_outside_the_vault(vault: VaultStore) -> None:
    """A sync service can evict a file kept in the vault; an unreadable old lock must not matter."""
    import os
    import sys

    from brain_core.stores import vault as vault_module

    stale = vault.root / ".brain.lock"  # what versions before 0.4.14 left behind
    stale.write_text("")
    if sys.platform != "win32":
        os.chmod(stale, 0)
    r = vault.write("fact", "the lock is local", domain="system", when=date(2026, 11, 9))
    assert r.status == "written"
    assert [p.name for p in vault.root.glob(".*lock*")] == [".brain.lock"], (
        "nothing new in the vault"
    )
    assert list(vault_module._lock_dir().glob("*.lock")), "the lock file is on the local disk"


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-" + "aB3_" * 20 + "-xyzAA",
        "sk-proj-" + "aB3d" * 12,
        "sk-" + "a1" * 12,
        ".".join(["eyJ" + "hbGciOiJI" * 2, "eyJ" + "yb2xlIjoi" * 2, "abcDEF123456"]),  # JWT shape
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "ghp_" + "a1B2" * 9,
    ],
)
def test_common_key_formats_are_refused(vault: VaultStore, secret: str) -> None:
    assert vault.write("fact", f"the key is {secret}").status == "refused"


def test_a_hyphenated_word_is_not_a_key(vault: VaultStore) -> None:
    r = vault.write("fact", "use the risk-adjusted-return-on-capital figure and task-level-retry")
    assert r.status == "written"


def test_archived_and_old_notes_are_still_read(vault: VaultStore) -> None:
    sessions = vault.root / "sessions"
    (sessions / "archive" / "2025-06").mkdir(parents=True)
    (sessions / "archive" / "2025-06" / "2025-06-01.md").write_text(
        "# s\n\n## What We Discussed\n- the zebra codename is quokka\n", encoding="utf-8"
    )
    (sessions / "archive" / "2025-06.md").write_text("# 2025-06 — 1 session files\n")
    (sessions / "2026-11-01.md").write_text(
        "# s\n\n## What We Discussed\n" + "".join(f"- filler line {i}\n" for i in range(1100)),
        encoding="utf-8",
    )
    from brain_core.recall import brain_recall

    out = brain_recall([vault], "zebra codename", scope="note")
    assert out["total"] == 1 and out["results"][0]["date"] == "2025-06-01"
