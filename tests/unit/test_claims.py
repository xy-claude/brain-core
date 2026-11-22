"""M3 through the real stores: vault and notes files, the journal with its own clock, the
claim index in brain.db. T1-T11 and T15 of the audit (M3), the two mandatory ones included."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as hs

from brain_core import entities
from brain_core.journal import Journal
from brain_core.knowledge import reconcile
from brain_core.knowledge.model import Claim, Lifecycle, Origin, Verification
from brain_core.knowledge.reconcile import ClaimIndex
from brain_core.remember import brain_remember
from brain_core.storage import Database, migrate
from brain_core.stores.base import record_id
from brain_core.stores.graph import relation_text
from brain_core.stores.index import RecordIndex
from brain_core.stores.notes import NotesStore
from brain_core.stores.vault import VaultStore

T0 = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
TODAY = date(2026, 12, 12)
D = date.fromisoformat
BRAIN = "019a8b3e-7c2d-7f41-9a10-3b5e2d8c4f22"
NEO = "019a8b3e-7c2d-7f41-9a10-3b5e2d8c4f11"
KUZU = "019a8b3e-7c2d-7f41-9a10-3b5e2d8c4f33"
USES_NEO = "[[Brain-Core]] —[USES: graph-database]→ [[Neo4j]]"
USES_KUZU = "[[Brain-Core]] —[USES: graph-database]→ [[Kuzu]]"


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def tick(self, days: float = 0, hours: float = 1) -> None:
        self.now += timedelta(days=days, hours=hours)


class Agent:
    """A vault, a notes folder, brain.db and the journal, as Agent wires them."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.clock = Clock()
        self.journal = Journal(tmp / "data" / "journal.db", clock=self.clock)
        self.open()
        self.v.root.mkdir(parents=True, exist_ok=True)
        (tmp / "shared").mkdir(exist_ok=True)

    def open(self) -> None:
        self.db = Database.connect(self.tmp / "data" / "brain.db")
        migrate(self.db)
        self.v = VaultStore(self.tmp / "vault", index=RecordIndex(self.db, self.journal))
        self.notes = NotesStore([self.tmp / "shared"], self.v.index)

    def rebuild(self) -> None:
        """Delete brain.db and read everything again; the journal stays."""
        self.db.close()
        for p in (self.tmp / "data").glob("brain.db*"):
            p.unlink()
        self.open()
        self.sync()

    def sync(self) -> None:
        self.notes.read("knowledge", "sync")
        self.v.read("fact", "sync")

    @property
    def claims(self) -> ClaimIndex:
        assert self.v.claims is not None
        return self.v.claims

    def now(self) -> dict[str, Claim]:
        self.sync()
        return self.claims.current()

    def write(self, name: str, text: str) -> Path:
        p = self.v.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def note(self, name: str, eid: str, etype: str = "technology", **more: str) -> None:
        extra = "".join(f"{k}: {v}\n" for k, v in more.items())
        self.write(
            f"entities/{name}.md",
            f"---\ntype: entity\nid: {eid}\nentity_type: {etype}\nontology: 1\n{extra}---\n"
            f"# {name}\n",
        )

    def relations(self, *lines: str) -> None:
        self.write("relations.md", "# Relations\n\n" + "".join(f"- {x}\n" for x in lines))

    def meta(self, *lines: str) -> None:
        self.write("record_meta.md", "# Record meta\n\n" + "".join(f"- {x}\n" for x in lines))

    def reviews(self, *lines: str) -> None:
        self.write("claim_reviews.md", "# Claim reviews\n\n" + "".join(f"- {x}\n" for x in lines))

    def shared(self, name: str, text: str) -> Path:
        p = self.tmp / "shared" / name
        p.write_text(text)
        return p

    def tables(self) -> dict[str, list[tuple[Any, ...]]]:
        return self.claims.tables()


def rel_id(line: str) -> str:
    """The record id of a relations.md line, 16 characters, as record_meta.md writes it."""
    s, rest = line[2:].lstrip("[").split("]] —[", 1)
    p, o = rest.split("]→ ", 1)
    o = o.split(" (")[0]
    return record_id(relation_text(s, p, o.strip("[]")))[:16]


def one(claims: dict[str, Claim], obj: str, pred: str = "USES") -> Claim:
    got = [c for c in claims.values() if c.key.predicate == pred and c.key.object_entity == obj]
    assert len(got) == 1, [c.key for c in claims.values()]
    return got[0]


@pytest.fixture
def a(tmp_path: Path) -> Agent:
    ag = Agent(tmp_path)
    ag.note("Brain-Core", BRAIN, "project")
    ag.note("Neo4j", NEO)
    ag.note("Kuzu", KUZU)
    return ag


DECISIONS = """# Decisions

## 2026-11-21 — Graph database for Brain-Core
**Decision:** Use [[Neo4j]] as the Brain-Core graph database.
**Reason:** Cypher, mature GraphRAG library.

## 2026-12-10 — Graph database for Brain-Core (2)
**Decision:** Move the Brain-Core graph database to [[Kuzu]].
**Reason:** Neo4j needs a JVM service.
"""


def decision_ids(a: Agent) -> list[str]:
    rows = a.db.fetchall("SELECT rid, record FROM records_fts WHERE kind = 'decision'")
    return [r["rid"][:16] for r in sorted(rows, key=lambda r: json.loads(r["record"])["date"])]


# ── T1: the worked example end to end ────────────────────────────────────────────────


def test_t1_the_worked_example(a: Agent) -> None:
    a.write("decisions_log.md", DECISIONS)
    a.relations(f"{USES_NEO} (2026-11-22)", f"{USES_KUZU} (2026-12-10)")
    a.sync()
    dec_a, dec_b = decision_ids(a)
    before = a.now()
    neo, kuzu = one(before, NEO), one(before, KUZU)
    assert [(c.scope, c.overlap_from) for c in neo.conflicts] == [("interval", D("2026-12-10"))]
    a.clock.tick()
    a.meta(
        f"{dec_b} | supersedes: {dec_a}",
        f"{rel_id('- ' + USES_KUZU)} | supersedes: {rel_id('- ' + USES_NEO)}",
    )
    got = a.now()
    neo, kuzu = one(got, NEO), one(got, KUZU)
    assert neo.lifecycle is Lifecycle.ACCEPTED and neo.verification is Verification.STATED
    assert [(p.true_from, p.true_to) for p in neo.periods] == [(D("2026-11-22"), D("2026-12-10"))]
    assert [(p.true_from, p.true_to) for p in kuzu.periods] == [(D("2026-12-10"), None)]
    assert not neo.conflicts and not kuzu.conflicts  # the periods meet, they do not overlap
    sel_a, sel_b = one(got, NEO, "SELECTS"), one(got, KUZU, "SELECTS")
    assert sel_a.key.subject == f"record:{dec_a}" and sel_a.origins == {Origin.MARKUP}
    assert sel_a.verification is Verification.DERIVED and sel_a.lifecycle is Lifecycle.ACCEPTED
    assert [(p.true_from, p.true_to) for p in sel_a.periods] == [(D("2026-11-21"), D("2026-12-10"))]
    assert sel_b.periods[0].true_from == D("2026-12-10")
    # what was originally selected, and when it changed
    group = [c for c in got.values() if (c.key.subject, c.key.role) == (BRAIN, "graph-database")]
    first = min(group, key=lambda c: c.periods[0].true_from or date.max)
    assert first.key.object_entity == NEO and first.periods[0].true_to == D("2026-12-10")
    assert neo.at(D("2026-12-01"), TODAY) == "true" and neo.at(TODAY, TODAY) == "false"
    assert a.claims.check() == []


def test_a_decision_naming_two_entities_gives_no_claim(a: Agent) -> None:
    a.write("decisions_log.md", DECISIONS.replace("to [[Kuzu]]", "from [[Neo4j]] to [[Kuzu]]"))
    got = a.now()
    assert {c.key.object_entity for c in got.values()} == {NEO}


# ── T2-T4 ───────────────────────────────────────────────────────────────────────────


def test_t2_deleting_one_of_two_sources_keeps_the_claim(a: Agent) -> None:
    brain_remember([a.v], USES_NEO.replace("[[", "").replace("]]", ""), "relation")
    a.shared("x.md", f"# X\n\n## Graph\n{USES_NEO}\n")
    c = one(a.now(), NEO)
    assert c.origins == {Origin.AGENT, Origin.EXTERNAL} and len(c.evidence) == 2
    assert c.verification is Verification.STATED  # its strongest row: relations.md's
    (a.tmp / "shared" / "x.md").unlink()
    a.clock.tick()
    c = one(a.now(), NEO)
    assert c.origins == {Origin.AGENT} and len(c.evidence) == 1


def test_t3_an_unknown_start_is_never_true(a: Agent) -> None:
    a.relations(f"{USES_NEO} (recorded: 2026-11-20T10:00:00)")  # provenance, not valid time
    c = one(a.now(), NEO)
    assert c.evidence[0].stated_date is None and c.periods[0].undated
    for d in ("2026-01-01", "2026-11-20", "2026-12-11"):
        assert c.at(D(d), TODAY) == "unknown"
    assert c.at(TODAY, TODAY) == "true"


def test_t4_a_reassertion_after_an_end_opens_a_second_period(a: Agent) -> None:
    a.relations(f"{USES_NEO} (2026-11-01)", f"{USES_KUZU} (2026-12-01)")
    a.meta(f"{rel_id('- ' + USES_KUZU)} | supersedes: {rel_id('- ' + USES_NEO)}")
    a.shared("x.md", f"# X\n\n## Again\n{USES_NEO} (2027-01-01)\n")
    c = one(a.now(), NEO)
    assert [(p.true_from, p.true_to) for p in c.periods] == [
        (D("2026-11-01"), D("2026-12-01")),
        (D("2027-01-01"), None),
    ]
    # superseded, then silent until the line restating it: unknown, never true (E7)
    assert c.at(D("2026-12-15"), TODAY) == "unknown" and c.at(D("2027-02-01"), TODAY) == "true"


# ── T5-T7: reviews, conflicts, re-keying ─────────────────────────────────────────────


def test_t5_reviews_survive_a_rebuild(a: Agent) -> None:
    a.relations(f"{USES_NEO} (2026-11-01)", f"{USES_KUZU} (2026-11-05)")
    a.sync()
    a.clock.tick()
    a.reviews(f"reject: {USES_KUZU} | never chosen", f"retract: {USES_NEO} | found wrong")
    got = a.now()
    neo, kuzu = one(got, NEO), one(got, KUZU)
    assert kuzu.lifecycle is Lifecycle.REJECTED and kuzu.retracted_at is None
    assert neo.lifecycle is Lifecycle.REJECTED and neo.retracted_at == a.clock.now
    assert neo.origins == {Origin.USER} and neo.verification is Verification.STATED
    before = a.tables()
    a.clock.tick()
    a.rebuild()
    assert a.tables() == before


def test_t6_a_functional_overlap_is_one_conflict_until_ack_or_until(a: Agent) -> None:
    a.relations(f"{USES_NEO} (2026-11-01)", f"{USES_KUZU} (2026-11-20)")
    got = a.now()
    assert {c.lifecycle for c in got.values()} == {Lifecycle.ACCEPTED}
    rows = a.db.fetchall("SELECT * FROM claim_conflicts")
    assert [(r["scope"], r["overlap_from"], r["acknowledged"]) for r in rows] == [
        ("interval", "2026-11-20", 0)
    ]
    a.clock.tick()
    a.reviews(f"ack: {USES_NEO} & {USES_KUZU} | a migration: both ran")
    a.sync()
    a.claims.settle()
    assert [r["acknowledged"] for r in a.db.fetchall("SELECT * FROM claim_conflicts")] == [1]
    assert a.claims.summary()["open_conflicts"] == 0
    a.meta(f"{rel_id('- ' + USES_NEO)} | until: 2026-11-20")
    a.sync()
    a.claims.settle()
    assert a.db.fetchall("SELECT * FROM claim_conflicts") == []
    assert any(r.startswith("orphaned_ack") for r in a.claims.summary()["report"])


def test_t7_a_merge_rekeys_claims_and_their_reviews_follow(a: Agent) -> None:
    dup = "019a8b3e-7c2d-7f41-9a10-3b5e2d8c4f44"
    a.relations(
        f"{USES_NEO} (2026-11-01)",
        "[[Brain-Core]] —[USES: graph-database]→ [[neo4j-ce]] (2026-11-02)",
    )
    a.reviews("reject: [[Brain-Core]] —[USES: graph-database]→ [[neo4j-ce]] | a duplicate")
    got = a.now()
    assert len(got) == 2  # neo4j-ce has no note: it waits as a name, rejected
    old = next(c.id for c in got.values() if c.lifecycle is Lifecycle.REJECTED)
    a.clock.tick()
    a.note("neo4j-ce", dup, merged_into=NEO)
    got = a.now()
    neo = one(got, NEO)
    assert len(got) == 1 and len(neo.evidence) == 2 and old in neo.aliases
    assert neo.lifecycle is Lifecycle.REJECTED  # the review followed its claim (F.5)
    redirects = {
        (r["kind"], r["old_id"]): r["new_id"]
        for r in a.db.fetchall("SELECT * FROM identity_redirects")
    }
    assert redirects[("claim", old)] == neo.id and redirects[("entity", dup)] == NEO
    (a.v.root / "entities" / "neo4j-ce.md").unlink()  # undo: the merge goes, the claims return
    a.clock.tick()
    assert len(a.now()) == 2


def test_a_renamed_predicate_rekeys(a: Agent, monkeypatch: pytest.MonkeyPatch) -> None:
    a.relations("[[Brain-Core]] —[runs on]→ [[Neo4j]] (2026-11-01)")
    old = one(a.now(), NEO, "RUNS_ON").id
    real = entities.ontology

    def renamed() -> dict[str, Any]:
        return {**real(), "renames": {"RUNS_ON": "USES"}}

    monkeypatch.setattr(reconcile, "ontology", renamed)
    a.claims.mark_dirty()
    c = one(a.claims.current(), NEO, "USES")
    assert old in c.aliases


# ── T8, T9, T15: incremental equals rebuild ─────────────────────────────────────────


def test_t9_two_rebuilds_give_identical_tables(a: Agent) -> None:
    a.write("decisions_log.md", DECISIONS)
    a.relations(f"{USES_NEO} (2026-11-22)", f"{USES_KUZU}")
    a.reviews(f"ack: {USES_NEO} & {USES_KUZU}")
    a.sync()
    first = a.tables()
    versions = a.journal.db.fetchone("SELECT count(*) FROM derivation_journal")[0]  # type: ignore[index]
    a.rebuild()
    assert a.tables() == first
    a.rebuild()
    assert a.tables() == first
    # a rebuild adds no version to the derivation journal
    assert a.journal.db.fetchone("SELECT count(*) FROM derivation_journal")[0] == versions  # type: ignore[index]
    assert a.claims.check() == []


LINES = [USES_NEO, USES_KUZU, "[[Kuzu]] —[ALTERNATIVE_TO]→ [[Neo4j]]", "[[Neo4j]] —[VERSION]→ 5.18"]
OPS = hs.lists(
    hs.tuples(
        hs.sampled_from(
            ["relations", "notes", "move", "meta", "review", "delete", "rebuild", "crash"]
        ),
        hs.integers(0, 3),
        hs.sampled_from(["", " (2026-11-01)", " (2026-12-01)"]),
    ),
    min_size=1,
    max_size=7,
)


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(ops=OPS)
def test_t8_t15_incremental_equals_rebuild(
    tmp_path_factory: pytest.TempPathFactory, ops: list[tuple[str, int, str]]
) -> None:
    a = Agent(tmp_path_factory.mktemp("t15"))
    a.note("Brain-Core", BRAIN, "project")
    a.note("Neo4j", NEO)
    a.note("Kuzu", KUZU)
    held: list[str] = []
    for op, i, day in ops:
        a.clock.tick()
        line = LINES[i] + day
        if op == "relations":
            held.append(line)
            a.relations(*held)
        elif op == "notes":
            a.shared("x.md", f"# X\n\n## S{i}\n{LINES[i]}{day}\n")
        elif op == "move" and held:  # one line leaves relations.md and arrives in a note
            gone = held.pop()
            a.relations(*held)
            a.shared("moved.md", f"# M\n\n## Moved\n{gone}\n")
        elif op == "meta" and held:
            a.meta(f"{rel_id('- ' + held[-1])} | valid: 2026-10-01")
        elif op == "review":
            a.reviews(f"reject: {LINES[i % 2]}")
        elif op == "delete" and held:
            held.pop(0)
            a.relations(*held)
        elif op == "rebuild":
            a.rebuild()
        elif op == "crash":  # brain.db fails after the journal committed: the next sync repairs
            real = ClaimIndex.store

            def boom(self: ClaimIndex, source: str, rows: Any) -> None:
                raise OSError("disk full")

            held.append(line)
            a.relations(*held)
            ClaimIndex.store = boom  # type: ignore[method-assign]
            try:
                with pytest.raises(OSError):
                    a.sync()
            finally:
                ClaimIndex.store = real  # type: ignore[method-assign]
        a.sync()
        assert a.claims.check() == [], (op, i, day)
    incremental = a.tables()
    if held:  # not vacuous: the relations still held are claims
        assert len(incremental["claims"]) >= len({ln.split(" (")[0] for ln in held})
    a.rebuild()
    assert a.tables() == incremental


# ── T10 (mandatory): three occurrences, three rows ──────────────────────────────────


def test_t10_one_text_in_three_places_is_three_evidence_rows(a: Agent) -> None:
    a.relations(USES_NEO)
    a.sync()
    a.clock.tick()
    section = f"## Graph\n{USES_NEO}\n"
    a.shared("x.md", f"# X\n\n{section}")
    a.sync()
    a.clock.tick()
    a.shared("x.md", f"# X\n\n{section}\n{section}")  # a second copy, an hour later
    a.sync()
    a.claims.settle()
    notes_rid = a.db.fetchone(  # type: ignore[index]
        "SELECT record_id FROM claim_evidence WHERE source_id LIKE 'notes:%'"
    )[0]
    a.clock.tick()
    a.meta(f"{notes_rid[:16]}@notes:shared/x.md#2 | valid: 2026-10-01")  # copy 2 only
    c = one(a.now(), NEO)
    rows = sorted(
        (e.occurrence.source_id, e.occurrence.ordinal, e.recorded_at, e.valid_from)
        for e in c.evidence
    )
    assert rows == [
        ("notes:shared/x.md", 1, T0 + timedelta(hours=1), None),
        ("notes:shared/x.md", 2, T0 + timedelta(hours=2), D("2026-10-01")),
        ("vault:relations.md", 1, T0, None),
    ]
    assert c.at(D("2026-10-15"), TODAY) == "true"
    stored = a.db.fetchone("SELECT count(*), count(DISTINCT recorded_at) FROM claim_evidence")
    assert tuple(stored) == (3, 3)  # type: ignore[arg-type]
    # deleting a source leaves the other rows, through reconcile
    (a.v.root / "relations.md").unlink()
    a.clock.tick()
    c = one(a.now(), NEO)
    assert sorted(e.occurrence.ordinal for e in c.evidence) == [1, 2]
    a.shared("x.md", f"# X\n\n{section}")
    a.clock.tick()
    c = one(a.now(), NEO)
    assert len(c.evidence) == 1 and c.at(D("2026-10-15"), TODAY) == "unknown"
    assert a.claims.check() == []


def test_t10_a_copy_inserted_later_makes_per_copy_meta_ambiguous(a: Agent) -> None:
    section = f"## Graph\n{USES_NEO}\n"
    a.shared("x.md", f"# X\n\n{section}\n{section}")
    a.sync()
    a.claims.settle()
    rid = a.db.fetchone("SELECT record_id FROM claim_evidence")[0]  # type: ignore[index]
    a.clock.tick()
    a.meta(f"{rid[:16]}@notes:shared/x.md#2 | valid: 2026-10-01")
    c = one(a.now(), NEO)
    assert sorted(str(e.valid_from) for e in c.evidence) == ["2026-10-01", "None"]
    a.clock.tick()
    a.shared("x.md", f"# X\n\n{section}\n{section}\n{section}")  # which copy is #2 now?
    c = one(a.now(), NEO)
    assert all(e.valid_from is None for e in c.evidence)
    assert any(r.startswith("occurrence_meta_ambiguous") for r in a.claims.summary()["report"])


# ── T11 (mandatory): transaction time from the journal, never from the text ─────────


def test_t11_known_at_comes_from_the_journal(a: Agent) -> None:
    a.relations(f"{USES_KUZU} (2026-11-20)")
    a.sync()  # 11-21 09:00
    assert a.claims.known_at(T0 - timedelta(hours=1)) is None  # before the journal began
    a.clock.tick(days=4)  # 11-25: a hand-written line that says "(2026-01-01)"
    a.relations(f"{USES_KUZU} (2026-11-20)", f"{USES_NEO} (2026-01-01)")
    neo = one(a.now(), NEO)
    assert neo.at(D("2026-06-01"), TODAY) == "true"  # valid time: what the text asserts
    assert neo.evidence[0].recorded_at == a.clock.now  # not 2026-01-01
    held_on_24 = a.claims.known_at(datetime(2026, 11, 24, tzinfo=UTC))
    assert held_on_24 is not None and {c.key.object_entity for c in held_on_24.values()} == {KUZU}


def test_t11_a_deleted_row_is_still_seen_before_its_deletion(a: Agent) -> None:
    a.relations(f"{USES_NEO} (2026-11-22)")
    a.meta(f"{rel_id('- ' + USES_NEO)} | valid: 2026-11-21")  # the decision's stated start
    a.shared("x.md", f"# X\n\n## G\n{USES_NEO} (2026-11-22)\n")
    c = one(a.now(), NEO)
    assert c.at(D("2026-11-21"), TODAY) == "true"
    a.clock.now = datetime(2026, 12, 1, 9, tzinfo=UTC)
    (a.v.root / "relations.md").unlink()  # the row with the stated start is deleted on 12-01
    c = one(a.now(), NEO)
    assert c.at(D("2026-11-21"), TODAY) == "unknown"
    then = a.claims.known_at(datetime(2026, 11, 23, tzinfo=UTC))
    assert then is not None and one(then, NEO).at(D("2026-11-21"), TODAY) == "true"
    later = a.claims.known_at(datetime(2026, 12, 5, tzinfo=UTC))
    assert later is not None and one(later, NEO).at(D("2026-11-21"), TODAY) == "unknown"


def test_known_at_in_a_ledger_gap_is_unknown(a: Agent, tmp_path: Path) -> None:
    a.relations(USES_NEO)
    a.sync()
    a.clock.tick()  # the backup is taken an hour after the line was first seen
    backup = a.journal.backup(tmp_path / "bk", today=date(2026, 11, 21))
    a.journal.close()
    for p in (a.tmp / "data").glob("journal.db*"):
        p.unlink()
    a.clock.tick(days=2)
    a.journal = Journal(a.tmp / "data" / "journal.db", clock=a.clock)
    a.journal.restore(backup)
    a.db.close()
    a.open()
    a.sync()
    assert a.claims.known_at(T0 + timedelta(days=1)) is None  # after the backup, before now
    held = a.claims.known_at(T0 + timedelta(minutes=30))  # inside what the backup covers
    assert held is not None and len(held) == 1


# ── the rules ───────────────────────────────────────────────────────────────────────


def test_hook_captured_session_lines_never_become_claims(a: Agent) -> None:
    a.write("sessions/2026-11-21.md", f"# 2026-11-21\n\n## Said (hook)\n- {USES_NEO}\n")
    assert a.now() == {}


def test_a_literal_object_and_a_role(a: Agent) -> None:
    a.relations("[[Neo4j]] —[LISTENS_ON]→ 7687", "[[Neo4j]] —[listens on]→ 7474 (2026-12-01)")
    got = a.now()
    assert {(c.key.object_literal, c.key.datatype) for c in got.values()} == {
        ("7687", "port"),
        ("7474", "port"),
    }
    assert a.db.fetchone("SELECT count(*) FROM claim_conflicts WHERE scope = 'current'")[0] == 1  # type: ignore[index]


def test_brain_remember_writes_a_role(a: Agent) -> None:
    out = brain_remember([a.v], "Brain-Core —[USES: graph-database]→ Neo4j", "relation")
    assert out["status"] == "written", out
    assert "—[USES: graph-database]→ [[Neo4j]]" in (a.v.root / "relations.md").read_text()
    c = one(a.now(), NEO)
    assert c.key.role == "graph-database" and c.evidence[0].recorded_by == "write"


def test_unresolved_names_wait_and_resolve_when_a_note_names_them(tmp_path: Path) -> None:
    ag = Agent(tmp_path)
    ag.relations(f"{USES_NEO} (2026-11-22)")
    c = next(iter(ag.now().values()))
    assert (c.key.subject, c.key.object_entity) == ("name:brain-core", "name:neo4j")
    assert ag.claims.summary()["waiting_names"] == 1
    ag.clock.tick()
    ag.note("Brain-Core", BRAIN, "project")
    ag.note("Neo4j", NEO)
    c2 = next(iter(ag.now().values()))
    assert (c2.key.subject, c2.key.object_entity) == (BRAIN, NEO) and c.id in c2.aliases
    assert ag.claims.summary()["waiting_names"] == 0


def test_check_finds_a_tampered_table(a: Agent) -> None:
    a.relations(f"{USES_NEO} (2026-11-22)")
    a.sync()
    a.claims.settle()
    a.db.execute("UPDATE claims SET lifecycle = 'candidate'")
    assert any(x.startswith("claims:") for x in a.claims.check())


def test_a_no_change_sync_does_not_recompute(a: Agent, monkeypatch: pytest.MonkeyPatch) -> None:
    a.relations(USES_NEO)
    a.now()
    calls: list[int] = []
    monkeypatch.setattr(ClaimIndex, "recompute", lambda self: calls.append(1))
    a.sync()
    a.claims.settle()
    assert calls == []


def test_the_cli_lists_checks_and_reports(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from brain_core.cli.main import app

    vault = tmp_path / "vault"
    (vault / "entities").mkdir(parents=True)
    (vault / "relations.md").write_text(
        f"# Relations\n\n- {USES_NEO} (2026-11-22)\n- {USES_KUZU}\n"
    )
    (tmp_path / "brain.yaml").write_text(f"name: T\nstores:\n  vault: {vault}\n")
    run = CliRunner().invoke
    out = run(app, ["claims", "list", str(tmp_path), "--as-of", "2026-11-25"])
    assert out.exit_code == 0, out.output
    assert "Brain-Core —[USES: graph-database]→ Neo4j: true on 2026-11-25" in out.output
    assert "2 claims" in out.output
    assert run(
        app, ["claims", "list", str(tmp_path), "--known-at", "2000-01-01"]
    ).output.startswith("unknown")
    check = run(app, ["index", str(tmp_path), "--check"])
    assert check.exit_code == 0 and "in step with a rebuild" in check.output, check.output
    doctor = run(app, ["doctor", str(tmp_path)])
    assert "claims     2 (2 accepted), 1 open conflict(s), 2 waiting" in doctor.output, (
        doctor.output
    )
    assert run(app, ["claims", "check", str(tmp_path)]).exit_code == 0


def test_an_impossible_date_is_reported_not_fatal(a: Agent) -> None:
    a.relations(f"{USES_NEO} (2026-02-30)", f"{USES_KUZU} (2026-11-20)")
    a.shared("x.md", f"# X\n\n## G\n{USES_NEO} (2026-13-01)\n")
    a.meta(f"{rel_id('- ' + USES_KUZU)} | until: 2026-11-31")
    got = a.now()
    assert len(got) == 2 and one(got, NEO).periods[0].undated
    assert one(got, KUZU).evidence[0].valid_to is None  # an impossible `until:` is no end
    report = a.claims.summary()["report"]
    assert sum(r.startswith("invalid_date") for r in report) == 2


def test_who_wrote_a_line_is_its_origin(a: Agent) -> None:
    a.relations(f"{USES_NEO} (recorded: 2026-11-20T10:00:00)", f"{USES_KUZU} (2026-11-20)")
    a.shared("x.md", "# X\n\n## G\n[[Kuzu]] —[ALTERNATIVE_TO]→ [[Neo4j]]\n")
    got = a.now()
    assert one(got, NEO).origins == {Origin.AGENT}  # `recorded:`: brain-core wrote it
    assert one(got, KUZU).origins == {Origin.USER}  # by hand, read in by a sync
    alt = one(got, NEO, "ALTERNATIVE_TO")
    assert alt.origins == {Origin.EXTERNAL} and alt.verification is Verification.DERIVED
    assert alt.lifecycle is Lifecycle.ACCEPTED  # a rule-derived claim, shown as derived (R 6)


def test_two_servers_recompute_one_after_the_other(a: Agent) -> None:
    import threading

    a.relations(f"{USES_NEO} (2026-11-22)", f"{USES_KUZU}")
    a.sync()
    errors: list[BaseException] = []

    def server() -> None:
        try:
            db = Database.connect(a.tmp / "data" / "brain.db")
            j = Journal(a.tmp / "data" / "journal.db", clock=a.clock)
            v = VaultStore(a.v.root, index=RecordIndex(db, j))
            assert v.claims is not None
            for _ in range(5):
                v.claims.mark_dirty()
                v.claims.settle()
            db.close()
            j.close()
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=server) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == []
    assert a.claims.check() == [] and len(a.claims.current()) == 2


def test_index_check_rebuilds_from_the_files(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from brain_core.cli.main import app

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "relations.md").write_text(f"# Relations\n\n- {USES_NEO} (2026-11-22)\n")
    (tmp_path / "brain.yaml").write_text(f"name: T\nstores:\n  vault: {vault}\n")
    run = CliRunner().invoke
    assert run(app, ["index", str(tmp_path), "--check"]).exit_code == 0
    db = Database.connect(tmp_path / "data" / "brain.db")  # raw rows drift from the file
    row = db.fetchone("SELECT row_key, row_json FROM claim_raw")
    db.execute(
        "UPDATE claim_raw SET row_json = ? WHERE row_key = ?",
        (row["row_json"].replace("2026-11-22", "2026-11-01"), row["row_key"]),  # type: ignore[index]
    )
    db.execute("UPDATE claims_state SET dirty = 1")
    db.close()
    out = run(app, ["index", str(tmp_path), "--check"])
    assert out.exit_code == 1 and "differ from a rebuild from the files" in out.output, out.output
