"""Hardening of the write path, the reader and the secret pattern (review of 0.8.0)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pytest

from brain_core.capture import capture
from brain_core.recall import brain_recall
from brain_core.remember import brain_remember
from brain_core.storage.db import Database
from brain_core.stores import SqliteStore, VaultStore
from brain_core.stores.base import WriteResult, full_text
from brain_core.stores.index import RecordIndex
from brain_core.stores.notes import NotesStore
from brain_core.stores.vault import has_secret, redact

DAY = date(2026, 11, 14)

FACTS = """---
type: reference
owner: atlas
updated: 2026-10-01
---
# Operational Facts

## System
- ATLAS brain initialized: 2026-04-03
- Hindsight bank: atlas-brain self-hosted (2026-11-01)
"""

PATTERNS = """---
updated: 2026-10-01
---
# Patterns

## Work
- **Cadence** — ships on Fridays (2026-09-01)
"""

DECISIONS = """---
type: log
updated: 2026-10-01
---
# Decisions Log

### YYYY-MM-DD — Title
**Decision:** template

## 2026-04-06 — Universal Brain Inheritance Architecture
**Decision:** AGENTS/CLAUDE.md is the deployment target
**Reason:** one source
"""

CORRECTIONS = """# Corrections Log

## Corrections

### [2026-08-18] Claimed done by eyeballing
- **Error:** glanced at a thumbnail
- **Correction:** measure first
- **Implied rule:** witness the pixel before the claim
- **Theme:** execution
"""

SESSION = """# Session Archive — 2026-11-02

## What We Discussed
- the zebra codename is quokka
"""

WIKI = """---
updated: 2026-11-02
---
# LLM Wiki

## Core Concepts
- raw is immutable
"""

RAW = """---
type: raw
source: https://x/y
title: Paper
fetched: 2026-11-02
sha256: abc123
---
body
"""


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def legacy(root: Path) -> VaultStore:
    for name, text in {
        "facts.md": FACTS,
        "patterns.md": PATTERNS,
        "decisions_log.md": DECISIONS,
        "corrections.md": CORRECTIONS,
        "sessions/2026-11-02.md": SESSION,
        "knowledge/wiki.md": WIKI,
        "raw/2026-11-02-paper.md": RAW,
    }.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return VaultStore(root, owner="atlas")


# ── ids: record_meta.md is keyed by them, so no reader change may move one ──────────────


def test_ids_of_every_old_record_shape_are_pinned(tmp_path: Path) -> None:
    v = legacy(tmp_path)
    plain = tmp_path / "memory" / "push_rule.md"
    plain.parent.mkdir()
    plain.write_text("---\nname: push-rule\n---\n\nPush only when the user says push.\n")
    ids = {
        kind: [r.id for r in sorted(v.read(kind), key=lambda r: r.line)]  # type: ignore[arg-type]
        for kind in ("fact", "pattern", "decision", "correction", "note", "knowledge", "raw")
    }
    assert ids == {
        "fact": [
            sha("ATLAS brain initialized: 2026-04-03"),
            sha("Hindsight bank: atlas-brain self-hosted"),
        ],
        "pattern": [sha("**Cadence** — ships on Fridays")],
        "decision": [sha("Universal Brain Inheritance Architecture")],
        "correction": [sha("Claimed done by eyeballing")],
        "note": [sha("the zebra codename is quokka")],
        "knowledge": [sha("knowledge/wiki.md#Core Concepts")],
        "raw": ["abc123"],
    }
    assert [r.id for r in NotesStore([plain.parent]).read("knowledge")] == [sha(f"{plain}#")]


# ── WRITE-1, memarch-missed-1: with a vault, the files decide what is a duplicate ───────


@pytest.fixture(params=["indexed", "plain"])
def both(request: pytest.FixtureRequest, tmp_path: Path, db: Database) -> list[object]:
    """SQLite beside a vault, as an agent has them; the vault with and without its index."""
    index = RecordIndex(db) if request.param == "indexed" else None
    return [SqliteStore(db), VaultStore(tmp_path / "vault", index=index)]


def test_a_fact_deleted_by_hand_can_be_saved_again(both: list[object], tmp_path: Path) -> None:
    fact = "Invoices are sent on the first Monday of each month"
    assert brain_remember(both, fact, "fact", when=DAY)["status"] == "written"  # type: ignore[arg-type]
    facts = tmp_path / "vault" / "facts.md"
    kept = [ln for ln in facts.read_text().splitlines() if "Invoices" not in ln]
    facts.write_text("\n".join(kept) + "\n")  # the owner deletes the line by hand
    again = brain_remember(both, fact, "fact", when=DAY)  # type: ignore[arg-type]
    assert again["status"] == "written", again
    assert again["layers"]["vault"]["status"] == "written" and "Invoices" in facts.read_text()


def test_a_value_changed_by_hand_is_what_the_duplicate_check_sees(
    both: list[object], tmp_path: Path
) -> None:
    old = "The staging database listens on port 7001 behind the office VPN"
    brain_remember(both, old, "fact", when=DAY)  # type: ignore[arg-type]
    facts = tmp_path / "vault" / "facts.md"
    facts.write_text(facts.read_text().replace("7001", "7999"))  # corrected by hand
    back = brain_remember(both, old, "fact", when=DAY)  # type: ignore[arg-type]
    # SQLite still holds 7001 word for word; the vault says 7999, so this is a changed value
    assert back["status"] == "written" and back["contradiction"]["source"] == "facts.md"
    assert "7999" in back["contradiction"]["text"] and "port 7001" in facts.read_text()


def test_without_a_vault_sqlite_still_catches_the_duplicate(db: Database) -> None:
    lite = [SqliteStore(db)]
    fact = "Invoices are sent on the first Monday of each month"
    assert brain_remember(lite, fact, "fact", when=DAY)["status"] == "written"
    again = brain_remember(lite, fact, "fact", when=DAY)
    assert again["status"] == "duplicate" and again["duplicate_of"]["source"].startswith("sqlite:")


# ── RECALL-2, SESSION-1, WRITE-9, CONTENT-3: a line with no date of its own says so ─────


def test_a_fact_or_pattern_with_no_date_of_its_own_is_flagged_undated(tmp_path: Path) -> None:
    v = legacy(tmp_path)
    (tmp_path / "patterns.md").write_text(PATTERNS + "- prefers short commits\n")
    facts = {r.text: r for r in v.read("fact")}
    old, dated = (
        facts["ATLAS brain initialized: 2026-04-03"],
        facts["Hindsight bank: atlas-brain self-hosted"],
    )
    assert old.undated and old.date == date(2026, 10, 1), "the file's date stays, flagged"
    assert not dated.undated and dated.date == date(2026, 11, 1)
    patterns = {r.text: r.undated for r in v.read("pattern")}
    assert patterns == {"**Cadence** — ships on Fridays": False, "prefers short commits": True}
    # notes and knowledge keep their dating: the day is the file's by design
    assert not any(r.undated for r in v.read("note") + v.read("knowledge"))


# ── recall-missed-2: the text above the first section is a record ───────────────────────


def test_text_before_the_first_section_is_its_own_record(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    page = memory / "feedback_push.md"
    page.write_text(
        "---\nname: push-rule\n---\n# Push rule\n\nMarguerite approves every push.\n"
        "Never push on a Friday.\n\n## Why\nA Friday push broke the build.\n"
    )
    store = NotesStore([memory])
    recs = store.read("knowledge")
    assert [r.text for r in recs] == [
        "Push rule: Marguerite approves every push. Never push on a Friday.",
        "Push rule › Why: A Friday push broke the build.",
    ]
    assert [r.id for r in recs] == [sha(f"{page}#"), sha(f"{page}#Why")], "section id unchanged"
    assert len({r.line for r in recs}) == 2, "a source names one record"
    assert [r.line for r in store.read("knowledge", "Marguerite")] == [1]
    # a vault knowledge page is read by the same code
    v = legacy(tmp_path / "vault")
    (v.root / "knowledge" / "wiki.md").write_text(
        WIKI.replace("\n## Core", "\nKarpathy's idea.\n\n## Core")
    )
    assert [r.text for r in v.read("knowledge")] == [
        "LLM Wiki: Karpathy's idea.",
        "LLM Wiki › Core Concepts: - raw is immutable",
    ]


# ── WRITE-3: shapes the reader used to drop or glue to the wrong record ─────────────────


def test_a_level_three_decision_is_a_record_and_keeps_its_own_fields(tmp_path: Path) -> None:
    v = legacy(tmp_path)
    (tmp_path / "decisions_log.md").write_text(
        DECISIONS + "\n### 2026-04-07 — Vault stays in iCloud\n**Decision:** no move to git\n"
        "**Reason:** phone access\n\n## Open questions\n**Decision:** not a decision at all\n"
    )
    got = {r.text: r for r in v.read("decision")}
    assert set(got) == {"Universal Brain Inheritance Architecture", "Vault stays in iCloud"}
    nested = got["Vault stays in iCloud"]
    assert nested.id == sha("Vault stays in iCloud") and nested.date == date(2026, 4, 7)
    assert nested.extra["decision"] == "no move to git" and nested.extra["reason"] == "phone access"
    first = got["Universal Brain Inheritance Architecture"]
    assert first.extra["decision"] == "AGENTS/CLAUDE.md is the deployment target"
    assert first.extra["reason"] == "one source", "the entry below did not overwrite it"
    # the writer still files a new decision above the first level-2 entry
    v.write("decision", "ship weekly", title="Cadence", when=DAY)
    text = (tmp_path / "decisions_log.md").read_text()
    assert text.index("## 2026-11-14 — Cadence") < text.index("## 2026-04-06 — Universal")
    assert text.index("## 2026-04-06 — Universal") < text.index("### 2026-04-07 — Vault stays")


def test_every_field_of_a_correction_is_searchable_text(tmp_path: Path) -> None:
    v = legacy(tmp_path)
    c = v.read("correction")[0]
    assert c.extra["implied rule"] == "witness the pixel before the claim"
    assert "witness the pixel" in full_text(c) and "measure first" in full_text(c)


def test_blocks_in_a_session_file_that_are_not_bullets_are_records(tmp_path: Path) -> None:
    v = legacy(tmp_path)
    (tmp_path / "sessions" / "2026-11-03.md").write_text(
        "---\ntype: session\nupdated: 2026-11-03\n---\n# Session Archive — 2026-11-03\n\n"
        "## What We Discussed\n"
        "- top level bullet about walrus\n"
        "  - nested detail about narwhal\n"
        "  - second nested detail\n"
        "\n"
        "A paragraph about the ocelot\nthat runs over two lines.\n"
        "\n"
        "1. numbered step about the pangolin\n2. second step\n"
        "\n"
        "> a quote about the axolotl\n"
        "\n"
        "| animal | port |\n|---|---|\n| capybara | 8888 |\n"
        "\n"
        "## Next\n"
        "closing paragraph about the tapir"
    )
    notes = {r.text: r for r in v.read("note") if r.path.endswith("03.md")}
    assert set(notes) == {
        "top level bullet about walrus",
        "- nested detail about narwhal - second nested detail",
        "A paragraph about the ocelot that runs over two lines.",
        "1. numbered step about the pangolin 2. second step",
        "> a quote about the axolotl",
        "| animal | port | | capybara | 8888 |",
        "closing paragraph about the tapir",
    }, "one record per block; frontmatter and the table rule are not text"
    para = notes["A paragraph about the ocelot that runs over two lines."]
    assert (para.domain, para.line, para.date) == ("What We Discussed", 12, date(2026, 11, 3))
    assert notes["closing paragraph about the tapir"].domain == "Next"
    assert notes["top level bullet about walrus"].id == sha("top level bullet about walrus")
    for word in ("narwhal", "ocelot", "pangolin", "axolotl", "capybara", "tapir"):
        assert len(v.read("note", word)) == 1, word
    # facts and patterns files are still read bullet by bullet
    (tmp_path / "facts.md").write_text(FACTS + "\nA stray paragraph.\n")
    assert len(v.read("fact")) == 2


# ── WRITE-4: a title that comes back with something new to say is stored ────────────────


def test_a_second_decision_with_the_same_title_is_stored_under_its_own_id(tmp_path: Path) -> None:
    v = VaultStore(tmp_path)
    march = v.write("decision", "Postgres for everything", title="Database choice", reason="one db")
    sept = v.write("decision", "Move the queue to SQLite", title="Database choice", reason="cost")
    assert (march.status, sept.status) == ("written", "written")
    assert march.id == sha("Database choice") and sept.id == sha("Database choice (2)")
    text = (tmp_path / "decisions_log.md").read_text()
    assert "Postgres for everything" in text and "Move the queue to SQLite" in text
    # the reader derives the same ids from the file
    assert {r.id: r.extra["decision"] for r in v.read("decision")} == {
        march.id: "Postgres for everything",
        sept.id: "Move the queue to SQLite",
    }
    again = v.write("decision", "Move the queue to SQLite", title="Database choice", reason="cost")
    assert again.status == "exists" and again.id == sept.id, "the same entry is still idempotent"
    third = v.write("decision", "Back to Postgres", title="Database choice")
    assert third.status == "written" and third.id == sha("Database choice (3)")
    assert len(v.read("decision")) == 3


def test_untitled_decisions_that_share_their_first_words_are_both_stored(tmp_path: Path) -> None:
    v = VaultStore(tmp_path)
    head = "For the reporting pipeline we will keep the nightly batch and "
    a = v.write("decision", head + "add a morning run")
    b = v.write("decision", head + "drop the weekend run")
    assert a.status == b.status == "written" and a.id != b.id
    text = (tmp_path / "decisions_log.md").read_text()
    assert "add a morning run" in text and "drop the weekend run" in text


def test_a_correction_keeps_its_text_and_a_repeated_title(tmp_path: Path) -> None:
    v = VaultStore(tmp_path)
    one = v.write(
        "correction",
        "Reported the deploy as done from the exit code alone",
        title="Claimed done without proof",
        error="trusted exit code 0",
        correction="open the page",
        rule="witness the effect",
    )
    c = v.read("correction")[0]
    assert c.extra["summary"] == "Reported the deploy as done from the exit code alone"
    assert c.extra["error"] == "trusted exit code 0" and "from the exit code alone" in full_text(c)
    two = v.write(
        "correction",
        "Said the migration ran; it had not",
        title="Claimed done without proof",
        error="read the plan, not the table",
    )
    assert two.status == "written" and two.id != one.id == sha("Claimed done without proof")
    assert len(v.read("correction")) == 2
    # with no error passed the text is the error, as before: no second copy of it
    v.write("correction", "Pushed without asking", title="Push")
    assert (tmp_path / "corrections.md").read_text().count("Pushed without asking") == 1


def test_pasted_text_under_a_reused_label_is_stored(tmp_path: Path) -> None:
    v = VaultStore(tmp_path)
    a = v.write("raw", "monday: agreed the budget", title="meeting notes", source="meeting notes")
    b = v.write("raw", "tuesday: cut the budget", title="meeting notes", source="meeting notes")
    assert a.status == b.status == "written" and a.id != b.id and a.detail != b.detail
    assert (tmp_path / b.detail).read_text().endswith("tuesday: cut the budget")
    same = v.write("raw", "tuesday: cut the budget", title="other name", source="meeting notes")
    assert same.status == "exists" and same.id == b.id, "the same body is still one source"


# ── WRITE-8, write-missed-1: one bad file, one failed write ─────────────────────────────


def test_a_stray_byte_costs_one_character_not_the_store(tmp_path: Path) -> None:
    v = legacy(tmp_path)
    day = tmp_path / "sessions" / "2026-11-02.md"
    day.write_bytes(day.read_bytes() + b"- caf\xe9 on the corner\n")
    assert [r.text for r in v.read("note", "zebra")] == ["the zebra codename is quokka"]
    assert len(v.read("note", "corner")) == 1
    r = v.write("note", "a new note for that day", when=date(2026, 11, 2))
    assert r.status == "written"
    raw = day.read_bytes()
    assert b"caf\xe9 on the corner" in raw, "the byte is written back as it was"
    assert b"a new note for that day" in raw
    ok, detail = v.health()
    assert ok and "sessions/2026-11-02.md (not UTF-8)" in detail


def test_an_unreadable_file_is_skipped_and_named_in_health(tmp_path: Path, db: Database) -> None:
    legacy(tmp_path)
    (tmp_path / "sessions" / "2026-11-05.md").mkdir()  # exists, cannot be read as a file
    for v in (VaultStore(tmp_path), VaultStore(tmp_path, index=RecordIndex(db))):
        assert [r.text for r in v.read("note", "zebra")] == ["the zebra codename is quokka"]
        ok, detail = v.health()
        assert ok and "not read cleanly: sessions/2026-11-05.md" in detail
    # a process that has searched nothing yet names the file too
    fresh = VaultStore(tmp_path, index=RecordIndex(db))
    assert "not read cleanly: sessions/2026-11-05.md" in fresh.health()[1]
    clean = legacy(tmp_path / "clean")
    clean.read("note")
    assert "not read cleanly" not in clean.health()[1]


def transcript(path: Path, messages: list[str]) -> Path:
    path.write_text(
        "".join(
            json.dumps(
                {
                    "type": "user",
                    "uuid": f"u{i}",
                    "sessionId": "s1",
                    "timestamp": "2026-11-14T03:00:00Z",
                    "message": {"role": "user", "content": m},
                }
            )
            + "\n"
            for i, m in enumerate(messages)
        )
    )
    return path


def test_capture_stops_at_a_failed_write_and_takes_it_up_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from brain_core import Agent

    (tmp_path / "vault").mkdir()
    (tmp_path / "brain.yaml").write_text(f"name: T\nstores:\n  vault: {tmp_path / 'vault'}\n")
    t = transcript(
        tmp_path / "s1.jsonl", [f"instruction number {i} for the week" for i in range(3)]
    )
    real = VaultStore.write

    def flaky(self: VaultStore, kind: str, text: str, **kw: object) -> WriteResult:
        if "number 1" in text:
            raise OSError(35, "Resource deadlock avoided")  # what iCloud does to a busy file
        return real(self, kind, text, **kw)  # type: ignore[arg-type]

    with Agent.from_config(tmp_path / "brain.yaml") as agent:
        monkeypatch.setattr(VaultStore, "write", flaky)
        first = capture(agent, t, "s1")
        assert (first["written"], first["duplicate"], first["failed"]) == (1, 0, 2), first
        assert first["scanned"] == 1, "the cursor rests before the line that was not filed"
        monkeypatch.setattr(VaultStore, "write", real)
        second = capture(agent, t, "s1")
        assert (second["written"], second["duplicate"], second["failed"]) == (2, 0, 0), second
        day = next((tmp_path / "vault" / "sessions").glob("*.md")).read_text()
        assert all(f"instruction number {i}" in day for i in range(3))
        assert capture(agent, t, "s1")["scanned"] == 0


def test_capture_without_a_vault_still_moves_on(tmp_path: Path) -> None:
    from brain_core import Agent

    (tmp_path / "brain.yaml").write_text("name: T\n")
    t = transcript(tmp_path / "s1.jsonl", ["a message nothing can file on this install"])
    with Agent.from_config(tmp_path / "brain.yaml") as agent:
        out = capture(agent, t, "s1")
        assert out["scanned"] == 1 and out["failed"] == 0
        assert capture(agent, t, "s1")["scanned"] == 0


# ── OPS-8, write-missed-2, content-missed-1: a label and a long mixed value ─────────────

A = "aB3dE5fG7hJ9kL1mN2pQ4rS6tU8vW0xY"  # filler; nothing below is a real credential
H = "0123456789abcdef" * 2
P = "Tr0ub4dor3horseBattery9"
L = "AB12C-DE34F-GH56I-JK78L"

LABELLED = [  # (the text, the value that must not survive)
    ("API_KEY=" + A, A),
    ("export SUPABASE_SERVICE_ROLE_KEY=" + A, A),
    ("api_key: " + A, A),
    ('apikey = "' + A + '"', A),
    ('{"apiKey": "' + A + '", "region": "eu"}', A),
    ("aws_secret_access_key = " + A + "ABCD/+xy", A + "ABCD/+xy"),
    ("STRIPE_SECRET_KEY=" + "sk_live_" + A[:24], A[:24]),
    ("GOOGLE_API_KEY=" + "AIza" + A, A),
    ("the hf token is " + "hf_" + A, A),
    ("npm token: " + "npm_" + A, A),
    ("export GITLAB_TOKEN=" + "glpat-" + A[:20], A[:20]),
    ("curl --token " + H + " https://api.example.com", H),
    ("auth token " + H, H),
    ("client_secret: " + A, A),
    ("the JWT signing secret " + H + H + " is for staging", H),
    ("password=" + P, P),
    ("the admin password is " + P, P),
    ("DB_PASSWORD='" + "p4ssW0rdForProd2026x" + "'", "p4ssW0rdForProd2026x"),
    ("passwd: " + A[:20], A[:20]),
    ("PWD=" + A[:18], A[:18]),
    ("licence key: " + L, L),
    ("License: " + L, L),
    ("**Signing key:** `" + H + "`", H),
    ("auth=" + A, A),
    ("credential: " + A, A),
    ("credentials = " + A, A),
    ("https://api.example.com/v1/items?token=" + A, A),
]

HARMLESS = [
    "the key insight is that recall needs dates",
    "primary key user_id on the accounts table",
    "key=value pairs in brain.yaml",
    "password authentication is disabled on the server",
    "token count 18169 for the always-loaded rules",
    "max_tokens=4096 and temperature 0",
    "the ssh key file is ~/.ssh/brain_windows_fix_ed25519",
    "ssh key: /Users/ada/.ssh/id_ed25519_2026",
    "auth docs: https://platform.example.com/docs/api-keys/rotate2024guide",
    "token https://example.com/v2/items/12345abcde67890fghij",
    "commit 16fe2a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f fixed the key rotation",
    "git hash e102e0b7c9d14f3a8b6e5d2c1f0a9b8c7d6e5f4a adds redact",
    "the token refresh shipped on 2026-11-14",
    "secret santa list is due 2026-12-24T18:00:00Z",
    "token expiry: 2026-11-14T05:00:00Z",
    "license: Apache-2.0",
    "licence MIT, version 0.8.0",
    "key version 0.8.0-rc1 replaces 0.7.12",
    "password: stored in the Keychain as koopi.admin",
    "the password is in 1Password under Koopi",
    "key: risk-adjusted-return-on-capital-2026",
    "token: session-recovery-2026-11-03",
    "secret: feedback_push_rule_2026",
    "Keychain item pypi.recovery-codes holds the codes",
    "the author rewrote tokenizer_v2_fast_path_2026 last week",
    "use the risk-adjusted-return-on-capital figure and task-level-retry",
    "OAuth 2.0 client for the 1234567890-app",
    "a monkey patch in session_recovery.py:42",
    "key points: 1) dates 2) ids 3) nothing is deleted",
    "sha256 of the text is the record id",
    "Use bearer authentication-header for the API",
]


@pytest.mark.parametrize(("text", "value"), LABELLED)
def test_a_labelled_value_is_a_secret_and_is_masked(text: str, value: str) -> None:
    assert has_secret(text), text
    masked = redact(text)
    assert value not in masked and "[redacted]" in masked, masked


@pytest.mark.parametrize("text", HARMLESS)
def test_plain_words_paths_urls_hashes_dates_and_versions_are_not_secrets(text: str) -> None:
    assert not has_secret(text), text
    assert redact(text) == text


def test_the_lists_are_long_enough_to_mean_something() -> None:
    assert len(LABELLED) >= 20 and len(HARMLESS) >= 20


def test_masking_keeps_the_label_and_guards_every_write(tmp_path: Path) -> None:
    assert redact("deploy with API_KEY=" + A + " today") == "deploy with API_KEY=[redacted] today"
    assert redact("the admin password is " + P) == "the admin password is [redacted]"
    v = VaultStore(tmp_path)
    assert v.write("fact", "staging signing key: " + H).status == "refused"
    with pytest.raises(ValueError, match="secret"):
        brain_remember([v], "wrong env file", "correction", correction="use DB_PASSWORD=" + P)
    assert not (tmp_path / "facts.md").exists() and not (tmp_path / "corrections.md").exists()
    from brain_core.stores.transcripts import _rows

    # a password said in prose passed the transcript's own pattern; the flag form keeps the
    # space that pattern has always put before the mask
    for said, kept in (
        ("the admin password is " + P + " for now", "the admin password is [redacted] for now"),
        ("note the API_KEY=" + A + " ok", "note the API_KEY= [redacted] ok"),
    ):
        row = {"type": "user", "uuid": "u1", "message": {"content": said}}
        assert [r[4] for r in _rows(json.dumps(row).encode(), "s1")] == [kept]


# ── CRITIC-4: the npm package brain_distill runs is one exact version ───────────────────


def test_defuddle_is_called_at_a_pinned_version(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from brain_core import distill

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr("brain_core.distill.shutil.which", lambda name: "/x/npx")
    monkeypatch.setattr("brain_core.distill.subprocess.run", fake_run)
    distill._defuddle("https://x.example/")
    assert len(calls) == 2
    for cmd in calls:
        assert cmd[:2] == ["npx", "-y"] and re.fullmatch(r"defuddle@\d+\.\d+\.\d+", cmd[2]), cmd


# ── recall-missed-5, memarch-missed-3: a long old line is known by the start a banner quotes


def test_a_banner_marks_a_long_old_line_as_replaced(db: Database) -> None:
    lite = [SqliteStore(db)]  # no vault, so no supersedes link: the banner alone must do it
    old = (
        "The API server that every agent on the office network talks to for memory and for "
        "the daily brief and for the nightly jobs listens on port 8887"
    )
    assert len(old) > 120
    brain_remember(lite, old, "fact", when=date(2026, 5, 1))
    out = brain_remember(lite, old.replace("8887", "8888"), "fact", when=DAY)
    # the quote is cut as 0.8.0 cut it, so the banners already in a vault mark their line too
    assert "contradiction" in out and out["text"].endswith(f"(was: {old[:120]})")
    found = brain_recall(lite, "which port does the API server listen on", today=DAY)["results"]
    marks = {
        ("new" if "Fact changed" in r["text"] else "old"): r.get("superseded", False) for r in found
    }
    assert marks == {"new": False, "old": True}


def test_a_fact_that_keeps_changing_does_not_grow_by_its_history(db: Database) -> None:
    lite = [SqliteStore(db)]
    line = "The reporting service of the finance team answers on port {} every night at two"
    sizes = [
        len(brain_remember(lite, line.format(7000 + i), "fact", when=date(2026, 11, 1 + i))["text"])
        for i in range(6)
    ]
    assert len(set(sizes[2:])) == 1, sizes  # the value, one quote of 120, the banner's words


# ── OPS-8: the generic rule reads every record, so no input may cost it seconds ─────────


@pytest.mark.parametrize(
    "text",
    ["token" + "=" * 20_000, "key=" * 5_000, "auth: " + "ab=" * 7_000],
    ids=["a rule of equals signs", "a label over and over", "a long value with no digit"],
)
def test_a_long_run_after_a_label_costs_no_time(text: str) -> None:
    import time

    start = time.perf_counter()
    assert not has_secret(text) and redact(text) == text
    assert time.perf_counter() - start < 0.5  # 2 s and more before the value's start was fixed


# ── WRITE-4: a title of spaces is no title ──────────────────────────────────────────────


def test_a_title_of_spaces_falls_back_to_the_text(tmp_path: Path) -> None:
    v = VaultStore(tmp_path)
    r = v.write("decision", "ship weekly", title="   ")
    assert r.status == "written" and r.id == sha("ship weekly")
    assert [d.text for d in v.read("decision")] == ["ship weekly"]


# ── RECALL-2: a duplicate's reply shows no date the line does not carry ─────────────────


def test_a_duplicate_of_an_undated_line_is_not_given_its_files_date(tmp_path: Path) -> None:
    v = legacy(tmp_path)
    out = brain_remember([v], "ATLAS brain initialized: 2026-04-03", "fact", when=DAY)
    assert out["status"] == "duplicate" and out["duplicate_of"]["date"] == ""
    dated = brain_remember([v], "Hindsight bank: atlas-brain self-hosted", "fact", when=DAY)
    assert dated["duplicate_of"]["date"] == "2026-11-01"
