"""Claims as a pure function of evidence, links, reviews, merges and renames (audit G.2, J.1).

Nothing here merges two different assertions, accepts anything, or looks at today's date: the
computed tier is the same whenever it is computed, and conflicts that hold only on "today"
are stored with scope ``current``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from itertools import combinations

from brain_core.knowledge.model import (
    Claim,
    ClaimKey,
    Conflict,
    Evidence,
    Lifecycle,
    Link,
    Period,
    Redirect,
    Review,
    Verification,
)

# TRUE on day :d for claim :c, from claim_periods alone: exactly Claim.at(d) == "true" (H.3)
TRUE_ON_SQL = """SELECT EXISTS (SELECT 1 FROM claim_periods p WHERE p.claim_id = :c
   AND (p.true_to IS NULL OR :d < p.true_to)
   AND ((p.stated = 1 AND p.true_from <= :d)
     OR (p.stated = 0 AND (p.timeless = 1
                           OR (p.true_from IS NOT NULL AND p.true_from <= :d)
                           OR (p.undated = 1 AND :d = :today)))))"""

Window = tuple[date, date]  # half-open [lo, hi); date.min / date.max: no bound


def build_periods(evidence: Sequence[Evidence], ends: Sequence[date]) -> list[Period]:
    """Split one claim's evidence into periods. A link end closes the open period; a row that
    starts on or after it opens the next one. Undated rows join the last period."""
    dated = sorted(
        ((s, e) for e in evidence if (s := e.start()[0]) is not None),
        key=lambda se: (se[0], se[1].occurrence.id(), se[1].rule),
    )
    stops = sorted(set(ends))
    groups: list[list[Evidence]] = []
    opened: date | None = None  # the start of the open period
    for s, e in dated:
        if opened is None or any(opened < x <= s for x in stops):
            groups.append([])
            opened = s
        groups[-1].append(e)
    if not groups:
        groups.append([])
    groups[-1].extend(e for e in evidence if e.start()[0] is None)
    out = []
    for g in groups:
        first = min((s for s, _x in (e.start() for e in g) if s), default=None)
        end = next((x for x in stops if first is None or x > first), None)
        out.append(Period(evidence=tuple(g), link_end=end))
    return out


def canonical(key: ClaimKey, merged: Mapping[str, str], renames: Mapping[str, str]) -> ClaimKey:
    """The key after merged_into chains (entity notes) and ontology renames."""

    def ent(x: str) -> str:
        seen: set[str] = set()
        while x in merged and x not in seen:
            seen.add(x)
            x = merged[x]
        return x

    return ClaimKey(
        subject=ent(key.subject),
        predicate=renames.get(key.predicate, key.predicate),
        role=key.role,
        object_entity=ent(key.object_entity) if key.object_entity else None,
        object_literal=key.object_literal,
        datatype=key.datatype,
    )


def _windows(p: Period) -> tuple[Window | None, Window | None]:
    """Where a period is TRUE, without reference to today: the dated window, and the window in
    which "today" is TRUE through an undated row (exactly `Period.true_on`)."""
    hi = p.true_to or date.max
    if p.stated:
        lo = p.true_from or date.min
        return ((lo, hi) if lo < hi else None), None
    dated = None
    if p.timeless:
        dated = (date.min, hi)
    elif p.true_from is not None and p.true_from < hi:
        dated = (p.true_from, hi)
    return dated, ((date.min, hi) if p.undated else None)


def _overlaps(a: Claim, b: Claim) -> list[tuple[str, date, date]]:
    """Every window where both are TRUE: interval rows for dated windows, current rows where
    an undated row is needed on at least one side."""
    out = []
    for pa in a.periods:
        da, ua = _windows(pa)
        for pb in b.periods:
            db_, ub = _windows(pb)
            if da and db_ and max(da[0], db_[0]) < min(da[1], db_[1]):
                out.append(("interval", max(da[0], db_[0]), min(da[1], db_[1])))
            for wa, wb in ((ua, db_), (da, ub), (ua, ub)):  # each pair has an undated side
                if wa and wb and max(wa[0], wb[0]) < min(wa[1], wb[1]):
                    out.append(("current", max(wa[0], wb[0]), min(wa[1], wb[1])))
    return sorted(set(out), key=lambda o: (o[0], o[1], o[2]))


def derive(
    rows: Sequence[tuple[ClaimKey, Evidence]],  # (key as derived from the text, evidence)
    links: Sequence[Link],
    reviews: Sequence[Review],
    merged: Mapping[str, str],  # entity id -> merged_into
    renames: Mapping[str, str],  # predicate -> current name
    functional: set[str] | Callable[[ClaimKey], bool],  # one current object per (subject, role)
) -> tuple[dict[str, Claim], list[Redirect], list[str]]:
    """Returns the claims, the claim redirects (old id -> current id) and what a person should
    look at. Reviews apply in ledger order; the later of two disagreeing ones wins (R item 9)."""
    is_functional = functional if callable(functional) else (lambda k: k.predicate in functional)
    report: list[str] = []
    aliases: dict[str, str] = {}
    causes: dict[str, str] = {}

    def retire(raw: ClaimKey, key: ClaimKey) -> None:
        if raw.id() != key.id() and raw.id() not in aliases:
            aliases[raw.id()] = key.id()
            moved = (raw.subject, raw.object_entity) != (key.subject, key.object_entity)
            renamed = raw.predicate != key.predicate
            causes[raw.id()] = (
                "merge+rename" if moved and renamed else "merge" if moved else "rename"
            )

    by: dict[str, tuple[ClaimKey, list[Evidence]]] = {}
    for raw, ev in rows:
        key = canonical(raw, merged, renames)
        retire(raw, key)
        by.setdefault(key.id(), (key, []))[1].append(ev)
    decided: dict[str, tuple[str, datetime, str]] = {}  # claim -> (action, when, key it was on)
    acks: list[tuple[str, str]] = []
    for r in sorted(reviews, key=lambda r: (r.recorded_at, r.key.id())):
        ckey = canonical(r.key, merged, renames)
        cid = ckey.id()
        retire(r.key, ckey)
        if r.action == "ack":
            other = canonical(r.other, merged, renames).id() if r.other else ""
            acks.append((cid, other))
            continue
        prev = decided.get(cid)
        if prev and prev[2] != r.key.id() and prev[0] != r.action:
            report.append(f"merged_reviews_disagree {cid[:8]}: {prev[0]} then {r.action}")
        decided[cid] = (r.action, r.recorded_at, r.key.id())
    claims: dict[str, Claim] = {}
    for cid, (key, evs) in by.items():
        records = {e.occurrence.record_id[:16] for e in evs}
        ends = [d for old, new, d in links if old[:16] in records and new[:16] not in records]
        ver = min((e.verification for e in evs), key=list(Verification).index)
        action, when = decided.get(cid, ("", None))[:2]
        if action in ("reject", "retract"):
            life = Lifecycle.REJECTED
        elif ver is Verification.UNVERIFIED:
            life = Lifecycle.CANDIDATE
        else:
            life = Lifecycle.ACCEPTED
        levels = [e.confidence for e in evs if e.confidence is not None]
        best = min(levels, key=lambda x: ("high", "medium", "low").index(x)) if levels else None
        claims[cid] = Claim(
            id=cid,
            key=key,
            lifecycle=life,
            verification=ver,
            origins=frozenset(e.origin for e in evs),
            confidence=best,
            evidence=evs,
            periods=build_periods(evs, ends),
            retracted_at=when if action == "retract" else None,
            aliases=frozenset(a for a, c in aliases.items() if c == cid),
        )
    groups: dict[tuple[str, str, str], list[Claim]] = {}
    for c in claims.values():
        if c.lifecycle is not Lifecycle.REJECTED and is_functional(c.key):
            groups.setdefault((c.key.subject, c.key.predicate, c.key.role), []).append(c)
    found: set[frozenset[str]] = set()
    for members in groups.values():
        for a, b in combinations(sorted(members, key=lambda c: c.id), 2):
            hits = _overlaps(a, b)
            if not hits:
                continue
            pair = frozenset((a.id, b.id))
            found.add(pair)
            ack = any(frozenset(x) == pair for x in acks)
            for scope, lo, hi in hits:
                for me, you in ((a, b), (b, a)):
                    me.conflicts.append(
                        Conflict(
                            other=you.id,
                            kind="functional_overlap",
                            scope=scope,  # type: ignore[arg-type]
                            overlap_from=None if lo == date.min else lo,
                            overlap_to=None if hi == date.max else hi,
                            acknowledged=ack,
                        )
                    )
    for x, y in acks:
        if frozenset((x, y)) not in found:
            report.append(f"orphaned_ack {x[:8]}/{y[:8]}: the pair no longer conflicts")
    redirects = [
        Redirect(kind="claim", old_id=o, new_id=n, cause=causes[o])  # type: ignore[arg-type]
        for o, n in sorted(aliases.items())
    ]
    return claims, redirects, report
