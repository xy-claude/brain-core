"""M3: the claim model and derive(), ported from the audit's validated checker (rev 2.3).

T12 (the twelve temporal cases and E1-E13), T13 (merge and rename traceability, undo), T14
(the F.3 models against the shipped schema) and the properties behind T8 and T15.
"""

from __future__ import annotations

import re
import sqlite3
import typing
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from importlib import resources

import pytest
from hypothesis import given, settings
from hypothesis import strategies as hs

from brain_core.journal import SCHEMA as JOURNAL_SCHEMA
from brain_core.knowledge import model as m
from brain_core.knowledge.derive import TRUE_ON_SQL, canonical, derive

TODAY = date(2026, 12, 12)
D = date.fromisoformat
K = m.ClaimKey(subject="bc", predicate="USES", role="graph-database", object_entity="neo")
KUZU = m.ClaimKey(subject="bc", predicate="USES", role="graph-database", object_entity="kuzu")
FNS = dict(links=[], reviews=[], merged={}, renames={}, functional={"USES"})


def at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def ev(
    rid: str,
    src: str,
    *,
    ordinal: int = 1,
    stated: str | None = None,
    vf: str | None = None,
    vt: str | None = None,
    seen: str = "2026-11-21T09:00:00",
    origin: str = "agent",
    ver: str = "stated",
    timeless: bool = False,
    rule: str = "relations.md/1",
) -> m.Evidence:
    return m.Evidence(
        occurrence=m.Occurrence(source_id=src, record_id=rid * 16, ordinal=ordinal),
        rule=rule,
        line=1,
        content_hash=rid * 8,
        subject_name="Brain-Core",
        object_name="Neo4j",
        stated_date=D(stated) if stated else None,
        event_date=None,
        valid_from=D(vf) if vf else None,
        valid_to=D(vt) if vt else None,
        timeless=timeless,
        recorded_at=at(seen),
        recorded_by="ingest",
        origin=origin,  # type: ignore[arg-type]
        verification=ver,  # type: ignore[arg-type]
        quote="Brain-Core uses Neo4j",
    )


def claim(
    *evs: m.Evidence, links: Sequence[m.Link] = (), reviews: Sequence[m.Review] = ()
) -> m.Claim:
    got = derive([(K, e) for e in evs], list(links), list(reviews), {}, {}, {"USES"})[0]
    return got[K.id()]


def claims_of(
    pairs: list[tuple[m.ClaimKey, m.Evidence]], reviews: Sequence[m.Review] = ()
) -> dict[str, m.Claim]:
    return derive(pairs, [], list(reviews), {}, {}, {"USES"})[0]


# ── T14: the models against the shipped schema ───────────────────────────────────────


def _schema() -> tuple[sqlite3.Connection, str]:
    mig = resources.files("brain_core.storage") / "migrations"
    sql = JOURNAL_SCHEMA + "".join(
        (mig / f).read_text() for f in ("008_entities.sql", "009_claims.sql")
    )
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(sql)
    return db, sql


def _cols(db: sqlite3.Connection) -> dict[str, list[str]]:
    return {
        t: [r[1] for r in db.execute(f"PRAGMA table_info({t})")]
        for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _fields(model: type, flatten: dict[str, list[str]] | None = None) -> set[str]:
    out: set[str] = set()
    for name in model.model_fields:  # type: ignore[attr-defined]
        out |= set((flatten or {}).get(name, [name]))
    return out


OCC = ["occ_id", "source_id", "record_id", "ordinal"]


def test_t14_every_model_field_has_its_column() -> None:
    db, _sql = _schema()
    cols = _cols(db)
    maps = {
        "claim_evidence": (_fields(m.Evidence, {"occurrence": OCC}) | {"claim_id"}, set()),
        "claims": (
            _fields(m.ClaimKey) | {"id", "lifecycle", "verification", "confidence", "retracted_at"},
            {"rank"},
        ),
        "claim_periods": (
            {"claim_id", "seq", "true_from", "true_to", "link_end", "timeless", "undated"}
            | {"stated", "disputed"},
            set(),
        ),
        "claim_conflicts": ({"claim_a", "claim_b", "seq"} | _fields(m.Conflict) - {"other"}, set()),
        "claim_reviews": (
            {"occ_id", "action", "key_json", "other_json", "claim_id", "other_claim_id"}
            | {"recorded_at", "reason"},
            set(),
        ),
        "record_ledger": (_fields(m.LedgerRow), set()),
        "entities": (_fields(m.Entity) - {"aliases"}, {"degree"}),
        "mentions": (_fields(m.Mention, {"occurrence": OCC}), set()),
        "identity_redirects": (_fields(m.Redirect), set()),
    }
    for table, (want, sql_only) in maps.items():
        have = set(cols[table])
        assert have - sql_only == want, (table, sorted(have - sql_only - want), sorted(want - have))
    not_stored = {"origins", "evidence", "periods", "conflicts", "aliases"}
    assert set(m.Claim.model_fields) - maps["claims"][0] - {"key"} == not_stored


def _allowed(tp: object) -> set[str] | None:
    if isinstance(tp, type) and issubclass(tp, Enum):
        return {e.value for e in tp}
    args = typing.get_args(tp)
    for a in args:
        got = _allowed(a)
        if got is not None:
            return got
    if typing.get_origin(tp) is typing.Literal:
        return {str(a) for a in args}
    return None


def test_t14_every_enum_matches_its_check_list() -> None:
    _db, sql = _schema()
    checks: dict[tuple[str, str], set[str]] = {}
    for t, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\)", sql, re.S):
        for col, vals in re.findall(r"\b(\w+)\b[^\n]*?CHECK \(\1 IN \(([^)]*)\)\)", body):
            checks[(t, col)] = set(re.findall(r"'([^']*)'", vals))
    pairs = [
        (m.Evidence, "claim_evidence"),
        (m.ClaimKey, "claims"),
        (m.Claim, "claims"),
        (m.LedgerRow, "record_ledger"),
        (m.Conflict, "claim_conflicts"),
        (m.Mention, "mentions"),
        (m.Redirect, "identity_redirects"),
    ]
    n = 0
    for model, table in pairs:
        for name, f in model.model_fields.items():  # type: ignore[attr-defined]
            vals = _allowed(f.annotation)
            if vals is not None and (table, name) in checks:
                assert vals == checks[(table, name)], (table, name)
                n += 1
    assert n >= 9
    assert checks[("claim_reviews", "action")] == {"reject", "retract", "restore", "ack"}


def _row(e: m.Evidence, claim_id: str) -> dict[str, object]:
    d = e.model_dump(mode="json")
    o = d.pop("occurrence")
    return {
        "claim_id": claim_id,
        "occ_id": e.occurrence.id(),
        **o,
        **d,
        "timeless": int(d["timeless"]),
    }


def _insert(db: sqlite3.Connection, table: str, r: dict[str, object]) -> None:
    db.execute(
        f"INSERT INTO {table} ({','.join(r)}) VALUES ({','.join('?' * len(r))})",
        tuple(r.values()),
    )


def test_t14_rows_round_trip_and_bad_rows_are_refused() -> None:
    db, _sql = _schema()
    cols = _cols(db)
    e0 = ev("a", "vault:relations.md", stated="2026-11-22")
    _insert(db, "claim_evidence", _row(e0, "c" * 32))
    got = db.execute("SELECT * FROM claim_evidence").fetchone()
    back = dict(zip(cols["claim_evidence"], got, strict=True))
    rebuilt = m.Evidence(
        occurrence=m.Occurrence(
            source_id=back["source_id"], record_id=back["record_id"], ordinal=back["ordinal"]
        ),
        **{k: v for k, v in back.items() if k in m.Evidence.model_fields and k != "occurrence"},
    )
    assert rebuilt == e0
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db, "claim_evidence", _row(e0, "c" * 32))  # one occurrence once per rule
    lr = m.LedgerRow(
        occ_id="o" * 32, content_hash="h" * 64, seen_from=at("2026-11-21T09:00:00"), via="ingest"
    )
    _insert(db, "record_ledger", lr.model_dump(mode="json"))
    for bad in ({"via": "move"}, {"seen_to": "2026-01-01T00:00:00Z"}):
        with pytest.raises(sqlite3.IntegrityError):
            _insert(
                db,
                "record_ledger",
                {**lr.model_dump(mode="json"), "seen_from": "2026-11-22T00:00:00Z", **bad},
            )


def _claim_row(cid: str, **kw: object) -> dict[str, object]:
    return {
        "id": cid, "subject": "bc", "predicate": "USES", "role": "", "object_entity": "x",
        "object_literal": None, "datatype": None, "lifecycle": "accepted",
        "verification": "stated", "confidence": None, "retracted_at": None, "rank": 0, **kw,
    }  # fmt: skip


def test_t14_foreign_keys_and_claim_checks() -> None:
    db, _sql = _schema()
    period = {"seq": 0, "true_from": None, "true_to": None, "link_end": None, "timeless": 0}
    period |= {"undated": 0, "stated": 0, "disputed": 0}
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db, "claim_periods", {"claim_id": "nope", **period})
    _insert(db, "claims", _claim_row("k" * 32))
    _insert(db, "claim_periods", {"claim_id": "k" * 32, **period})
    db.execute("DELETE FROM claims WHERE id = ?", ("k" * 32,))
    assert db.execute("SELECT count(*) FROM claim_periods").fetchone()[0] == 0
    for bad in (
        {"lifecycle": "accepted", "verification": "unverified"},
        {"lifecycle": "accepted", "retracted_at": "2026-12-12T00:00:00Z"},
    ):
        with pytest.raises(sqlite3.IntegrityError):
            _insert(db, "claims", _claim_row("j" * 32, **bad))


# ── T10, T11 in the pure model (the stores' versions are in test_claims.py) ───────────


def test_t10_model_three_copies_keep_three_rows() -> None:
    copies = [
        ev("f", "vault:facts.md", stated="2026-11-01", seen="2026-11-01T08:00:00"),
        ev("f", "vault:facts.md", ordinal=2, stated="2026-11-03", vf="2026-10-01",
           seen="2026-11-03T08:00:00"),
        ev("f", "notes:shared/x.md", stated="2026-11-05", seen="2026-11-20T08:00:00"),
    ]  # fmt: skip
    c3 = derive([(K, e) for e in copies], **FNS)[0][K.id()]  # type: ignore[arg-type]
    c1 = derive([(K, copies[0])], **FNS)[0][K.id()]  # type: ignore[arg-type]
    assert len(c3.evidence) == 3 and len(c1.evidence) == 1 and c1.id == c3.id
    assert c3.at(D("2026-10-15"), TODAY) == "true"
    assert c1.at(D("2026-10-15"), TODAY) == "unknown"
    assert c3.at(D("2026-11-02"), TODAY) == "true"


# ── T12: E1-E13 and the twelve cases ──────────────────────────────────────────────────

RET = m.Review(action="retract", key=K, recorded_at=at("2026-12-12T10:00:00"), reason="wrong")
C5 = None


def _e5() -> m.Claim:
    return claim(
        ev("a", "vault:d.md", stated="2026-11-21", vf="2026-11-21"),
        ev("b", "vault:d.md", ordinal=2, stated="2027-03-01", vf="2027-03-01"),
        links=[("a" * 16, "x" * 16, D("2026-12-10"))],
    )


def _both() -> list[m.Evidence]:
    return [
        ev("a", "vault:decisions_log.md", stated="2026-11-21", vf="2026-11-21", origin="markup",
           ver="derived", rule="decision-field/1"),
        ev("b", "vault:relations.md", stated="2026-11-22"),
    ]  # fmt: skip


def _examples() -> list[tuple[str, m.Claim, list[tuple[str, str]]]]:
    both = _both()
    return [
        ("E1", claim(ev("a", "vault:f.md", stated="2026-11-01"),
                     ev("b", "vault:g.md", stated="2026-11-20")),
         [("2026-10-31", "unknown"), ("2026-11-01", "true"), ("2026-11-25", "true")]),
        ("E2", claim(ev("a", "vault:f.md", stated="2026-11-12", vf="2026-11-10"),
                     ev("b", "vault:g.md", stated="2026-11-05")),
         [("2026-11-04", "false"), ("2026-11-07", "unknown"), ("2026-11-10", "true")]),
        ("E2b", claim(ev("a", "vault:f.md", stated="2026-11-01", vt="2026-12-01"),
                      ev("b", "vault:g.md", stated="2026-11-01", vt="2026-12-08")),
         [("2026-11-30", "true"), ("2026-12-03", "unknown"), ("2026-12-08", "false")]),
        ("E3", claim(ev("a", "vault:d.md", stated="2026-12-10", vf="2027-01-01")),
         [("2026-12-12", "false"), ("2027-01-01", "true")]),
        ("E5", _e5(), [("2026-12-01", "true"), ("2027-01-15", "false"), ("2027-04-01", "true")]),
        ("E6 before", claim(*both), [("2026-11-21", "true"), ("2026-11-20", "false")]),
        ("E6 after", claim(both[1]), [("2026-11-21", "unknown"), ("2026-11-22", "true")]),
        ("E7", claim(ev("a", "vault:f.md", stated="2026-11-22")),
         [("2026-06-01", "unknown"), ("2026-11-22", "true")]),
        ("E8", claim(ev("a", "vault:f.md")), [("2026-06-01", "unknown"), ("2026-12-12", "true")]),
        ("E9", claim(ev("a", "vault:f.md", timeless=True)), [("1999-01-01", "true")]),
    ]  # fmt: skip


def test_t12_temporal_examples() -> None:
    examples = _examples()
    for name, c, expect in examples:
        for d, want in expect:
            assert c.at(D(d), TODAY) == want, (name, d)
    assert len(_e5().periods) == 2
    assert sum(p.disputed for p in examples[1][1].periods) == 1


def test_t12_e4_retraction_keeps_evidence_and_origins() -> None:
    c4 = claim(ev("a", "vault:f.md", stated="2026-11-01"), reviews=[RET])
    assert c4.lifecycle is m.Lifecycle.REJECTED and c4.retracted_at == at("2026-12-12T10:00:00")
    assert c4.origins == {m.Origin.AGENT} and c4.verification is m.Verification.STATED


def test_t12_the_twelve_cases() -> None:
    neo = K
    got: list[tuple[str, str]] = []
    c = claims_of([(neo, ev("a", "vault:f.md", stated="2026-11-22"))])[neo.id()]
    got.append((c.at(D("2026-06-01"), TODAY), "unknown"))  # 1
    c = claims_of([(neo, ev("a", "vault:f.md", stated="2026-11-22", vf="2026-03-01"))])[neo.id()]
    got.append((c.at(D("2026-02-28"), TODAY) + "/" + c.at(D("2026-03-01"), TODAY), "false/true"))
    c = claims_of([(neo, ev("a", "vault:f.md", stated="2026-03-01", vt="2026-06-01"))])[neo.id()]
    got.append((c.at(D("2026-05-31"), TODAY) + "/" + c.at(D("2026-06-01"), TODAY), "true/false"))
    rec_today = ev(
        "a", "vault:f.md", stated="2026-12-12", vf="2025-12-01", seen="2026-12-12T08:00:00"
    )
    c = claims_of([(neo, rec_today)])[neo.id()]
    got.append((c.at(D("2026-01-15"), TODAY), "true"))  # 4
    hidden = rec_today.recorded_at > at("2026-12-11T23:59:00")
    got.append(("not known" if hidden else "known", "not known"))
    both2 = claims_of([
        (neo, ev("a", "vault:f.md", stated="2026-11-01", vf="2026-11-01")),
        (KUZU, ev("b", "vault:g.md", stated="2026-11-20", vf="2026-11-20")),
    ])  # fmt: skip
    ov = both2[neo.id()].conflicts
    got.append(
        (f"conflict from {ov[0].overlap_from}" if ov else "none", "conflict from 2026-11-20")
    )
    und = claims_of([(neo, ev("a", "vault:f.md")), (KUZU, ev("b", "vault:g.md"))])  # 6
    ov6 = und[neo.id()].conflicts
    tomorrow = TODAY + timedelta(days=1)
    got.append((
        f"past {und[neo.id()].at(D('2026-06-01'), TODAY)}; {ov6[0].scope} conflict, today "
        f"{ov6[0].active_on(TODAY, TODAY)}, tomorrow {ov6[0].active_on(tomorrow, TODAY)}",
        "past unknown; current conflict, today True, tomorrow False",
    ))  # fmt: skip
    c = claims_of([(neo, ev("a", "vault:d.md", stated="2026-12-10", vf="2027-01-01"))])[neo.id()]
    got.append((c.at(TODAY, TODAY), "false"))  # 7
    c = claims_of([(neo, ev("a", "vault:f.md", stated="2026-11-01"))], [RET])[neo.id()]
    got.append(
        (f"{c.lifecycle.value}, evidence kept: {len(c.evidence)}", "rejected, evidence kept: 1")
    )
    c5 = _e5()
    got.append((c5.at(D("2027-01-15"), TODAY) + "/" + c5.at(D("2027-04-01"), TODAY), "false/true"))
    c1 = derive([(K, ev("f", "vault:facts.md", stated="2026-11-01"))], **FNS)[0][K.id()]  # type: ignore[arg-type]
    got.append((c1.at(D("2026-11-02"), TODAY), "true"))  # 10
    c = claims_of([(neo, ev("a", "vault:f.md", stated="2026-11-01")),
                   (neo, ev("b", "vault:g.md", stated="2026-11-20"))])[neo.id()]  # fmt: skip
    got.append((c.at(D("2026-11-10"), TODAY), "true"))  # 11
    late = ev("a", "vault:f.md", stated="2026-11-21", vf="2026-01-01", vt="2026-06-01",
              seen="2026-11-21T08:00:00")  # fmt: skip
    c = claims_of([(neo, late)])[neo.id()]
    known = "not known" if late.recorded_at > at("2026-05-01T00:00:00") else "known"
    got.append((
        f"{c.at(D('2026-03-01'), TODAY)}/{c.at(D('2026-08-01'), TODAY)}; known_at 05-01: {known}",
        "true/false; known_at 05-01: not known",
    ))  # fmt: skip
    assert len(got) == 13
    for i, (have, want) in enumerate(got):
        assert have == want, (i, have, want)


def test_t12_issue_a_always_superseded() -> None:
    ca = claim(ev("a", "vault:f.md", timeless=True), links=[("a" * 16, "x" * 16, D("2026-12-10"))])
    assert ca.at(D("2026-12-11"), TODAY) == "false" and ca.at(D("2026-12-09"), TODAY) == "true"
    assert ca.at(D("1999-01-01"), TODAY) == "true" and ca.periods[0].true_to == D("2026-12-10")
    cv = claim(
        ev("a", "vault:f.md", timeless=True),
        ev("b", "vault:g.md", stated="2026-11-12", vf="2026-11-10"),
    )
    assert cv.at(D("2026-11-01"), TODAY) == "unknown" and cv.at(D("2026-11-10"), TODAY) == "true"
    assert cv.periods[0].disputed


def test_t12_issue_b_current_conflict_does_not_move() -> None:
    ub = claims_of([(K, ev("a", "vault:f.md")), (KUZU, ev("b", "vault:g.md"))])
    cb = ub[K.id()].conflicts
    assert [(c.scope, c.overlap_from, c.overlap_to) for c in cb] == [("current", None, None)]
    tomorrow = TODAY + timedelta(days=1)
    for d, today, want in (
        (TODAY, TODAY, True), (tomorrow, TODAY, False), (D("2026-06-01"), TODAY, False),
        (tomorrow, tomorrow, True),
    ):  # fmt: skip
        both = ub[K.id()].at(d, today) == "true" and ub[KUZU.id()].at(d, today) == "true"
        assert cb[0].active_on(d, today) == both == want
    assert (
        claims_of([(K, ev("a", "vault:f.md")), (KUZU, ev("b", "vault:g.md"))])[K.id()].conflicts
        == cb
    )


# ── T13: merges and renames, and their undo ───────────────────────────────────────────

DUP = m.ClaimKey(subject="bc", predicate="uses", role="graph-database", object_entity="neo-dup")
ROWS = [
    (K, ev("a", "vault:f.md", stated="2026-11-01")),
    (DUP, ev("b", "vault:g.md", stated="2026-11-02")),
    (KUZU, ev("k", "vault:h.md", stated="2026-11-03")),
]
REVIEWS = [
    m.Review(action="reject", key=DUP, recorded_at=at("2026-11-10T00:00:00")),
    m.Review(action="restore", key=K, recorded_at=at("2026-11-11T00:00:00")),
    m.Review(action="ack", key=DUP, other=KUZU, recorded_at=at("2026-11-12T00:00:00")),
]


def test_t13_merge_and_rename_keep_everything_traceable() -> None:
    before, _r, rep0 = derive(ROWS, [], REVIEWS, {}, {}, {"USES"})
    assert before[DUP.id()].lifecycle is m.Lifecycle.REJECTED
    assert any(r.startswith("orphaned_ack") for r in rep0)
    after, redirects, rep = derive(
        ROWS, [], REVIEWS, {"neo-dup": "neo"}, {"uses": "USES"}, {"USES"}
    )
    redir = {r.old_id: r for r in redirects}
    assert set(after) == {K.id(), KUZU.id()} and redir[DUP.id()].new_id == K.id()
    assert redir[DUP.id()].cause == "merge+rename"
    merged = after[K.id()]
    assert {e.occurrence.record_id[:1] for e in merged.evidence} == {"a", "b"}
    assert DUP.id() in merged.aliases and merged.lifecycle is m.Lifecycle.ACCEPTED
    assert any(r.startswith("merged_reviews_disagree") for r in rep)
    c = merged.conflicts[0]
    assert c.other == KUZU.id() and c.acknowledged and c.overlap_from == D("2026-11-03")
    assert not any(r.startswith("orphaned_ack") for r in rep)


def test_t13_undoing_a_merge_restores_the_claims() -> None:
    undone, red, _rep = derive(ROWS, [], REVIEWS, {}, {"uses": "USES"}, {"USES"})
    renamed = canonical(DUP, {}, {"uses": "USES"})
    left = {r.old_id: r for r in red}
    assert left[DUP.id()].cause == "rename" and left[DUP.id()].new_id == renamed.id()
    assert set(undone) == {K.id(), KUZU.id(), renamed.id()}
    assert {e.occurrence.record_id[:1] for e in undone[renamed.id()].evidence} == {"b"}
    assert undone[renamed.id()].lifecycle is m.Lifecycle.REJECTED


# ── the SQL TRUE predicate (H.3) and the properties ──────────────────────────────────


def _period_row(cid: str, seq: int, p: m.Period) -> dict[str, object]:
    def iso(d: date | None) -> str | None:
        return d.isoformat() if d else None

    return {
        "claim_id": cid, "seq": seq, "true_from": iso(p.true_from), "true_to": iso(p.true_to),
        "link_end": iso(p.link_end), "timeless": int(p.timeless), "undated": int(p.undated),
        "stated": int(p.stated), "disputed": int(p.disputed),
    }  # fmt: skip


def _sql_true(db: sqlite3.Connection, cid: str, d: date, today: date) -> bool:
    row = db.execute(TRUE_ON_SQL, {"c": cid, "d": d.isoformat(), "today": today.isoformat()})
    return bool(row.fetchone()[0])


def test_sql_true_predicate_agrees_on_every_example() -> None:
    db, _sql = _schema()
    for ci, (_name, c, _expect) in enumerate(_examples()):
        cid = f"case{ci}"
        _insert(db, "claims", _claim_row(cid))
        for seq, p in enumerate(c.periods):
            _insert(db, "claim_periods", _period_row(cid, seq, p))
        for k in range(-400, 200, 3):
            d = TODAY + timedelta(days=k)
            assert _sql_true(db, cid, d, TODAY) == (c.at(d, TODAY) == "true"), (cid, d)


_DAY = hs.integers(0, 40).map(lambda n: D("2026-11-01") + timedelta(days=n))
_ROW = hs.tuples(
    hs.sampled_from(["implied", "stated", "undated", "timeless"]),
    _DAY,
    _DAY,
    hs.one_of(hs.none(), _DAY),
)


def _mk(i: int, spec: tuple[str, date, date, date | None], src: str) -> m.Evidence:
    kind, sd, vf, vt = spec
    if kind == "timeless":
        return ev(f"{i}", src, timeless=True)
    if kind == "undated":
        e = ev(f"{i}", src)
        return m.Evidence(**{**e.model_dump(), "valid_to": vt}) if vt else e
    vfrom = vf if kind == "stated" else None
    vto = vt if vt and (vfrom is None or vt > vfrom) else None
    return ev(f"{i}", src, stated=sd.isoformat(), vf=vfrom.isoformat() if vfrom else None,
              vt=vto.isoformat() if vto else None)  # fmt: skip


@settings(max_examples=200, deadline=None)
@given(
    hs.lists(_ROW, min_size=1, max_size=4),
    hs.lists(_ROW, min_size=1, max_size=4),
    hs.one_of(hs.none(), _DAY),
    _DAY,
    _DAY,
)
def test_summary_sql_and_conflicts_match_validity(
    rows_a: list[tuple[str, date, date, date | None]],
    rows_b: list[tuple[str, date, date, date | None]],
    end: date | None,
    d: date,
    today: date,
) -> None:
    ea = [_mk(i, r, "vault:a.md") for i, r in enumerate(rows_a)]
    eb = [_mk(i + 10, r, "vault:b.md") for i, r in enumerate(rows_b)]
    links = [("0" * 16, "z" * 16, end)] if end else []
    got = derive([(K, e) for e in ea] + [(KUZU, e) for e in eb], links, [], {}, {}, {"USES"})[0]
    a, b = got[K.id()], got[KUZU.id()]
    db, _sql = _schema()
    for c in (a, b):
        _insert(db, "claims", _claim_row(c.id))
        for n, p in enumerate(c.periods):
            assert p.true_on(d, today) == (p.at(d, today) == "true")
            _insert(db, "claim_periods", _period_row(c.id, n, p))
        assert _sql_true(db, c.id, d, today) == (c.at(d, today) == "true")
    both = a.at(d, today) == "true" and b.at(d, today) == "true"
    assert any(c.active_on(d, today) for c in a.conflicts if c.other == b.id) == both
