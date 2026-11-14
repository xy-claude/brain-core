"""What the last review of 0.9.0 found, one test per finding. Each fails on the code as that
review read it. Every credential here is made up at run time."""

from __future__ import annotations

import os
import random
import string
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from brain_core import Agent
from brain_core.stores.vault import has_secret, knowledge_records, redact

GOOD = (
    "## Primary Objective\nShip payroll\n\n## Top Missions\n- M-1\n\n## Pending Decisions\n- None\n"
)
_RND = random.Random(20261114)
BAR = "-" * 5  # a key header is built in parts so a secret scanner does not read one here


def made_up(n: int = 28) -> str:
    """A random value with letters and digits mixed all through."""
    return "".join(
        _RND.choice(string.ascii_letters) + _RND.choice(string.digits) for _ in range(n // 2)
    )


def _agent(tmp_path: Path, extra: str = "") -> Agent:
    (tmp_path / "vault").mkdir(exist_ok=True)
    (tmp_path / "brain.yaml").write_text(f"name: T\nstores:\n  vault: ./vault\n{extra}")
    return Agent.from_config(tmp_path / "brain.yaml")


def _rows(agent: Agent) -> int:
    return len(agent._db.fetchall("SELECT rid FROM records_fts"))


def _texts(out: dict[str, Any]) -> str:
    return " ".join(r["text"] for r in out["results"])


def _fail(vault: Any) -> Any:
    real = vault.write

    def down(*a: object, **kw: object) -> object:
        raise OSError("the sync folder is not writable")

    vault.write = down
    return real


# ── the vault is away ────────────────────────────────────────────────────────


def test_a_save_while_the_vault_is_away_does_not_make_an_empty_vault(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        agent.brain_remember("The quarterly invoice run happens on the third Tuesday", "fact")
        assert "Tuesday" in _texts(agent.brain_recall("quarterly invoice run"))
        os.rename(tmp_path / "vault", tmp_path / "away")  # a drive that is not mounted
        saved = agent.brain_remember("The audit folder is called ledger-2026", "fact")
        assert saved["layers"]["vault"]["status"] == "failed"
        agent.brain_remember("We talked about the audit", "note")
        assert not (tmp_path / "vault").exists(), "a write must not build the folder again"
        os.rename(tmp_path / "away", tmp_path / "vault")  # the drive is back
        assert "Tuesday" in _texts(agent.brain_recall("quarterly invoice run"))
        assert "ledger-2026" in _texts(agent.brain_recall("audit folder called"))


def test_an_empty_folder_where_the_vault_stood_is_not_an_empty_vault(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        agent.brain_remember("The quarterly invoice run happens on the third Tuesday", "fact")
        agent.brain_recall("quarterly invoice run")
        rows = _rows(agent)
        os.rename(tmp_path / "vault", tmp_path / "away")
        (tmp_path / "vault").mkdir()  # a mount point without its drive
        out = agent.brain_recall("quarterly invoice run")
        assert out["stores"]["vault"].startswith("error: FileNotFoundError")
        assert "Tuesday" in _texts(out), "the SQLite copy answers meanwhile"
        assert _rows(agent) == rows


def test_a_notes_folder_that_is_away_keeps_its_rows(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "printer.md").write_text("# Printer\n\n## Queue\nThe office printer queue is quokka\n")
    with _agent(tmp_path, "  notes:\n    - ./notes\n") as agent:
        assert "quokka" in _texts(agent.brain_recall("office printer queue"))
        rows = _rows(agent)
        os.rename(notes, tmp_path / "gone")
        out = agent.brain_recall("office printer queue")
        assert out["stores"]["notes"].startswith("error: FileNotFoundError")
        assert _rows(agent) == rows
        os.rename(tmp_path / "gone", notes)
        assert "quokka" in _texts(agent.brain_recall("office printer queue"))


# ── a fact only SQLite holds ─────────────────────────────────────────────────


def test_a_fact_saved_again_while_its_line_is_gone_and_the_vault_fails_is_found(
    tmp_path: Path,
) -> None:
    with _agent(tmp_path) as agent:
        vault = agent.stores[1]
        agent.brain_remember("The payroll export goes out every 25th", "fact")
        facts = tmp_path / "vault" / "facts.md"
        facts.write_text(facts.read_text().replace("- The payroll export", "- The rent"))
        assert "payroll" not in _texts(agent.brain_recall("payroll export goes out when"))
        _fail(vault)  # the row exists from the first save; this time no file takes the line
        again = agent.brain_remember("The payroll export goes out every 25th", "fact")
        assert again["status"] == "partial"
        assert "payroll" in _texts(agent.brain_recall("payroll export goes out when"))


def test_a_meta_file_that_cannot_be_written_does_not_report_the_line_lost(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        (tmp_path / "vault" / "record_meta.md").mkdir()  # exists, cannot be written as a file
        saved = agent.brain_remember(
            "The standby server is called heron", "fact", source="ops handbook"
        )
        layer = saved["layers"]["vault"]
        assert layer["status"] == "written" and "record_meta.md not written" in layer["detail"]
        # the file holds the line, so the row is a copy: a hand delete is not undone by it
        facts = tmp_path / "vault" / "facts.md"
        facts.write_text(facts.read_text().replace("- The standby server", "- The spare desk"))
        assert "standby" not in _texts(agent.brain_recall("standby server called"))


def test_a_fact_only_sqlite_holds_is_found_behind_many_copies(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        for n in range(30):  # copies of vault lines that outrank the row in SQLite's own order
            agent.brain_remember(
                f"Printer queue name list {n}: printer queue name, printer queue name", "fact"
            )
        _fail(agent.stores[1])
        agent.brain_remember("The quokka is what the office calls its printer queue", "fact")
        assert "quokka" in _texts(agent.brain_recall("printer queue name"))


def test_a_changed_value_of_a_fact_only_sqlite_holds_gets_its_banner(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        vault = agent.stores[1]
        real = _fail(vault)
        agent.brain_remember("The payroll export goes out on day 25 of each month", "fact")
        vault.write = real  # type: ignore[method-assign]
        changed = agent.brain_remember(
            "The payroll export goes out on day 28 of each month", "fact"
        )
        assert "contradiction" in changed and "Fact changed" in changed["text"]
        # the same line again, vault up: it is filed there, not called a duplicate of the row
        with _agent(tmp_path) as second:
            _fail(second.stores[1])
            second.brain_remember("The gate code rotates each Monday at noon", "fact")
        again = agent.brain_remember("The gate code rotates each Monday at noon", "fact")
        assert again["layers"]["vault"]["status"] == "written"


# ── status, start and end ────────────────────────────────────────────────────


def test_status_and_start_survive_files_that_cannot_be_read(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    for name in ("executive_state.md", "daily_brief.md", "session_critique.md", "record_meta.md"):
        (vault / name).mkdir(parents=True)  # each exists and is not a file
    (vault / "knowledge").mkdir()
    (vault / "knowledge" / "_index.md").mkdir()
    (vault / "knowledge" / "page.md").mkdir()
    (vault / "facts.md").write_text(
        "# Facts\n\n## Ops\n- The standby server is heron (2026-11-01)\n"
    )
    with _agent(tmp_path) as agent:
        st = agent.brain_status()
        assert st["stores"]["vault"]["ok"] is True
        assert "heron" in _texts(agent.brain_recall("standby server")), "the vault still answers"
        start = agent.brain_session("start", "s-1")
        assert "brief" in start and "executive_state" in start


def test_attention_ends_when_the_unreadable_file_is_gone(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        bad = tmp_path / "vault" / "sessions" / "2026-11-05.md"
        bad.mkdir(parents=True)
        assert "sessions/2026-11-05.md" in agent.brain_status()["attention"][0]
        bad.rmdir()
        assert "attention" not in agent.brain_status()


def test_a_hand_written_state_replaced_on_a_retry_is_still_in_a_file(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        vault = tmp_path / "vault"
        agent.brain_session("start", "s-1")
        agent.brain_session("end", "s-1", executive_state=GOOD)
        agent.brain_session("start", "s-2")
        agent.brain_session("end", "s-2", executive_state=GOOD.replace("payroll", "invoices"))
        # the owner rewrites the state by hand in a shape of their own
        (vault / "executive_state.md").write_text("Focus this week: the quokka migration\n")
        agent.brain_session("start", "s-3")
        agent.brain_session("end", "s-3", executive_state=GOOD.replace("payroll", "audits"))
        assert "Ship payroll" in (vault / "executive_state.prev.md").read_text()
        assert "quokka migration" in (vault / "executive_state.replaced.md").read_text()


# ── recall ───────────────────────────────────────────────────────────────────


def test_pages_with_the_judge_on_show_no_record_twice(tmp_path: Path) -> None:
    rnd = random.Random(7)
    words = ["rent", "travel", "cloud", "payroll", "tools", "legal", "ads", "audit", "office"]
    lines = "".join(
        f"- Budget line {n} covers cost centre {n} "
        f"{' '.join(rnd.choice(words) for _ in range(rnd.randint(0, 12)))} "
        f"({date(2026, 11, 14) - timedelta(days=rnd.randint(0, 600))})\n"
        for n in range(400)
    )
    (tmp_path / "vault").mkdir()
    (tmp_path / "vault" / "facts.md").write_text("# Facts\n\n## Budget\n" + lines)
    with _agent(tmp_path) as agent:
        from brain_core.recall import brain_recall

        def judge(system: str, prompt: str) -> str:
            return '{"picks": [7, 3], "status": "answered"}'

        seen: list[str] = []
        picked = None
        for offset in range(0, 400, 10):  # the depth of a page must not grow with the page
            out = brain_recall(
                agent.stores, "which budget line covers the cost centre", limit=10,
                offset=offset, judge=judge, picked=picked, fmt="detailed", today=date(2026, 11, 14),
            )  # fmt: skip
            picked = out.pop("judgement", picked)
            seen += [r["id"] for r in out["results"]]
        assert len(seen) == len(set(seen)), "a record came back on two pages"
        assert len(seen) >= 150


def test_a_value_changed_back_is_a_change_not_a_duplicate(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        agent.brain_remember("The gateway listens on port 7001 for the staging cluster", "fact")
        agent.brain_remember("The gateway listens on port 7002 for the staging cluster", "fact")
        back = agent.brain_remember(
            "The gateway listens on port 7001 for the staging cluster", "fact"
        )
        assert back["status"] != "duplicate" and "contradiction" in back
        first = agent.brain_recall("which port does the gateway listen on", fmt="detailed")[
            "results"
        ][0]
        assert "7001" in first["text"].split("(was:")[0] and "superseded" not in first


def test_a_replacement_from_another_kind_stays_out_of_a_scope(tmp_path: Path) -> None:
    with _agent(tmp_path) as agent:
        old = agent.brain_remember("The cache layer is redis for every service", "fact")
        agent.brain_remember(
            "Move the cache layer to valkey",
            "decision",
            title="Cache layer moves to valkey",
            reason="licence",
            supersedes=old["id"],
        )
        out = agent.brain_recall("cache layer", scope="fact", fmt="detailed")
        assert {r["kind"] for r in out["results"]} == {"fact"}


# ── credentials ──────────────────────────────────────────────────────────────


def test_a_credential_in_a_decision_field_is_masked(tmp_path: Path) -> None:
    value = made_up()
    (tmp_path / "vault").mkdir()
    (tmp_path / "vault" / "decisions_log.md").write_text(
        "# Decisions\n\n## 2026-11-01 — Rotate the lemur account\n"
        f"**Decision:** rotate it monthly\n**Password:** {value}\n**Reason:** audit\n"
    )
    with _agent(tmp_path) as agent:
        out = agent.brain_recall("rotate the lemur account", fmt="detailed")
        assert out["results"] and value not in str(out)
        rows = agent._db.fetchall("SELECT body, record FROM records_fts")
        assert not any(value in r["body"] or value in r["record"] for r in rows)
        assert agent.brain_status()["secrets_masked"] == 1


def test_a_key_block_is_masked_in_json_and_in_a_quote_and_a_named_header_takes_no_prose() -> None:
    body = [made_up(64), made_up(64), made_up(20)]
    block = "\n".join([f"{BAR}BEGIN RSA PRIVATE KEY{BAR}", *body, f"{BAR}END RSA PRIVATE KEY{BAR}"])
    shapes = {
        "json": '"private_key": "' + block.replace("\n", "\\n") + '\\n", "client_email": "x@y"',
        "quote": "> " + block.replace("\n", "\n> ") + "\nnext line",
        "pgp": block.replace("RSA PRIVATE KEY", "PGP PRIVATE KEY BLOCK"),
    }
    for name, text in shapes.items():
        assert not any(line[:12] in redact(text) for line in body), name
    assert "client_email" in redact(shapes["json"]) and "next line" in redact(shapes["quote"])
    prose = f"Look for {BAR}BEGIN OPENSSH PRIVATE KEY{BAR} at the top of the file and delete it"
    assert redact(prose).endswith("at the top of the file and delete it")


def test_env_names_and_basic_auth_are_seen_and_tickets_are_not() -> None:
    value = made_up(24)
    for line in (
        "SECRET_" + f"KEY_BASE={value}",
        "DEPLOY_" + f"TOKEN_V2={value}",
        "DB_" + f"PASS={value}",
        "pass" + f"phrase: {value}",
        "Authorization: Basic " + made_up(24) + "==",
        "VAULT_TOKEN=hvs." + made_up(28),
    ):
        assert has_secret(line), line.split("=")[0]
    for line in (
        "Ticket CASE-2026-1114-0001 is closed",
        "PO PO12-3456-7890-1234 was paid",
        "asset tag LAPT-0042-2026-MBP1",
        "Advisory GHSA-JFH8-C2JP-5V3Q is patched",
        "the docs placeholder is ABCD-1234-EFGH-5678",
        "http://localhost:8080,admin@example.com",
        "cache_key_prefix: user_v2_profile_v3",
    ):
        assert not has_secret(line), line
    # a value said again without its label or prefix is masked with it
    token = made_up(24)
    said = redact(f"Authorization: Bearer {token} and later the same {token} in a log")
    assert token not in said


def test_the_start_block_the_brief_and_the_miss_log_hold_no_credential(tmp_path: Path) -> None:
    value = made_up()
    vault = tmp_path / "vault"
    (vault / "sessions").mkdir(parents=True)
    (vault / "models").mkdir()
    (vault / "executive_state.md").write_text(
        GOOD.replace("- M-1", f"- M-1 rotate the lemur api key {value} before Friday")
    )
    (vault / "models" / "active-priorities.md").write_text(
        f"---\ntype: model\nquestion: what matters\n---\n- the lemur token: {value} [facts.md:3]\n"
    )
    long = "x" * 180
    (vault / "sessions" / "2026-11-13.md").write_text(
        f"# Session\n\n## What We Discussed\n- {long} password: {value}\n"
    )
    with _agent(tmp_path) as agent:
        from brain_core import cron

        start = agent.brain_session("start", "s-1")
        assert value not in str(start) and value[:14] not in str(start)
        warm = cron._warmup(vault / "sessions")
        assert "What We Discussed" not in warm and value[:10] not in warm and "xxxx" in warm
        agent.brain_recall(f"is the lemur api key {value} still the live one")
        events = agent.recent_events(event_type="recall_miss", limit=5)
        assert events and value not in str([e.payload for e in events])
        assert value not in str(agent.brain_status())


def test_distill_keeps_a_page_with_its_example_masked_and_refuses_a_password_in_the_url(
    tmp_path: Path,
) -> None:
    value = made_up()
    with _agent(tmp_path) as agent:
        page = f"# Auth guide\n\nSend the header like this:\n\n    API_KEY={value}\n\nThen retry."
        kept = agent.brain_distill("auth guide", text=page)
        assert kept["status"] == "written"
        raw = next((tmp_path / "vault" / "raw").glob("*.md")).read_text()
        assert value not in raw and "Then retry." in raw
        refused = agent.brain_distill(
            f"https://reader:{value}@docs.example.com/guide", text="# Guide\n\nplain text"
        )
        assert refused["status"] == "refused" and value not in str(refused)
        with pytest.raises(ValueError, match="secret"):
            agent.brain_remember("The lemur rota", "fact", mission=f"token {value}")


# ── a private key in other clothes ───────────────────────────────────────────

BODY = ["MIIEow" + "Ab1" * 19 + "x", "Zx9" * 21 + "y", "Qw3" * 21 + "z", "Qm9keUVuZA=="]


def _block(label: str, nl: str = "\n", pre: str = "", head: str = "") -> str:
    lines = [f"{pre}{BAR}BEGIN {label}{BAR}", *([head] if head else []), *[pre + b for b in BODY]]
    return nl.join([*lines, f"{pre}{BAR}END {label}{BAR}"])


LEGACY = "Proc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,0A1B2C3D4E5F60718293A4B5C6D7E8F9\n"


@pytest.mark.parametrize(
    "text",
    [
        '{"private_key": "' + _block("PRIVATE KEY", nl="\\n") + '\\n", "client_email": "x@y"}',
        'APP_KEY="' + _block("RSA PRIVATE KEY", nl="\\n") + '"',
        '{"stdout": "' + _block("PRIVATE KEY", nl="\\\\n") + '"}',
        _block("OPENSSH PRIVATE KEY", pre="> "),
        _block("RSA PRIVATE KEY", head=LEGACY),
        " ".join(_block("RSA PRIVATE KEY", head=LEGACY).split()),
        _block("PGP PRIVATE KEY BLOCK", head="Comment: exported for the build box\n"),
        ('→ {"private_key": "' + _block("PRIVATE KEY", nl="\\n"))[:150],  # cut: no END line
    ],
    ids=["json", "env", "json-in-json", "quoted", "legacy", "legacy-one-line", "pgp", "cut"],
)
def test_a_private_key_in_other_clothes_is_masked_with_its_body(text: str) -> None:
    assert has_secret(text)
    out = redact(text)
    assert not [b for b in BODY if b[:16] in out and b[:16] in text]


def test_a_sentence_that_names_the_header_keeps_its_words() -> None:
    said = f"Look for {BAR}BEGIN OPENSSH PRIVATE KEY{BAR} at the top of the file and delete it"
    assert redact(said) == "Look for [redacted] at the top of the file and delete it"


def test_a_key_block_under_a_section_keeps_its_first_line_for_the_mask() -> None:
    page = (
        f"# Page\n\n## Deploy\nIn plain lines:\n\n{_block('RSA PRIVATE KEY')}\n\n---\n\nrotate it\n"
    )
    (record,) = knowledge_records(page, "knowledge/page.md", date(2026, 1, 1), None)
    assert redact(record.text) == "Page › Deploy: In plain lines: [redacted] rotate it"
