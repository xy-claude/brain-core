"""VaultStore against a legacy-shaped vault copy (docs/VAULT_SCHEMA.md)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from brain_core.stores import MemoryStore, VaultStore
from brain_core.stores.base import record_id

LEGACY_FACTS = """---
type: reference
owner: xyclaude
updated: 2026-10-01
---
# Operational Facts

## System
- XYCLAUDE brain initialized: 2026-04-03
- Hindsight bank: xyclaude-brain self-hosted (2026-11-01)

## Hardware
- Mac mini M4 (2026-04-19)
"""

LEGACY_DECISIONS = """---
type: log
owner: xyclaude
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
owner: xyclaude
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
    return VaultStore(tmp_path, owner="xyclaude")


def test_reads_legacy_facts_with_and_without_dates(vault: VaultStore) -> None:
    facts = vault.read("fact")
    assert [f.text for f in facts][:1] == ["Hindsight bank: xyclaude-brain self-hosted"]
    undated = next(f for f in facts if f.text.startswith("XYCLAUDE brain initialized"))
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
        correction="Sir sole author",
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
    r = vault.write("note", "Sir said go M9", when=date(2026, 11, 2), section="Decisions Made")
    p = vault.root / "sessions" / "2026-11-02.md"
    assert r.status == "written" and p.exists()
    assert (
        "# Session Archive — 2026-11-02" in p.read_text()
        and "## Decisions Made\n- Sir said go M9" in p.read_text()
    )
    assert vault.read("note", "go M9")[0].domain == "Decisions Made"


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
