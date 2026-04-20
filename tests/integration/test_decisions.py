"""Decisions capability tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from central_brain.decisions import (
    Decision,
    complete,
    decide,
    get_decision,
    list_decisions,
    reverse,
)
from central_brain.storage import Database


def test_decide_round_trip(db: Database) -> None:
    d = decide(db, action="deploy", reversible=True)
    assert d.id > 0
    assert d.action == "deploy"
    assert d.reversible is True
    assert d.risk == "medium"
    assert d.confidence == "medium"
    assert d.reasoning is None
    assert d.alternatives == []
    assert d.status == "active"
    assert d.reversed_by is None


def test_decide_with_all_fields(db: Database) -> None:
    d = decide(
        db,
        action="migrate to postgres",
        reversible=False,
        risk="high",
        confidence="low",
        reasoning="sqlite is hitting limits",
        alternatives=["shard sqlite", "use duckdb"],
    )
    assert d.action == "migrate to postgres"
    assert d.reversible is False
    assert d.risk == "high"
    assert d.confidence == "low"
    assert d.reasoning == "sqlite is hitting limits"
    assert d.alternatives == ["shard sqlite", "use duckdb"]


def test_decide_rejects_empty_action(db: Database) -> None:
    with pytest.raises(ValueError, match="action must not be empty"):
        decide(db, action="   \n\t  ", reversible=True)


def test_decide_rejects_invalid_risk(db: Database) -> None:
    with pytest.raises(ValueError, match="risk must be one of"):
        decide(db, action="x", reversible=True, risk="catastrophic")  # type: ignore[arg-type]


def test_decide_rejects_invalid_confidence(db: Database) -> None:
    with pytest.raises(ValueError, match="confidence must be one of"):
        decide(db, action="x", reversible=True, confidence="gut-feeling")  # type: ignore[arg-type]


def test_reverse_simple(db: Database) -> None:
    d = decide(db, action="bad plan", reversible=True)
    reversed_d = reverse(db, d.id)
    assert reversed_d.status == "reversed"
    assert reversed_d.reversed_by is None


def test_reverse_with_replaced_by(db: Database) -> None:
    old = decide(db, action="old plan", reversible=True)
    new = decide(db, action="new plan", reversible=True)
    reversed_old = reverse(db, old.id, replaced_by=new.id)
    assert reversed_old.status == "reversed"
    assert reversed_old.reversed_by == new.id

    # Replacement stays active
    refreshed_new = get_decision(db, new.id)
    assert refreshed_new is not None
    assert refreshed_new.status == "active"


def test_reverse_replaced_by_must_exist(db: Database) -> None:
    d = decide(db, action="x", reversible=True)
    with pytest.raises(ValueError, match="no replacement decision"):
        reverse(db, d.id, replaced_by=999999)


def test_reverse_replaced_by_cannot_be_self(db: Database) -> None:
    d = decide(db, action="x", reversible=True)
    with pytest.raises(ValueError, match="cannot be the same"):
        reverse(db, d.id, replaced_by=d.id)


def test_reverse_is_idempotent_on_reversed(db: Database) -> None:
    d = decide(db, action="x", reversible=True)
    first = reverse(db, d.id)
    second = reverse(db, d.id)
    assert first == second


def test_reverse_raises_if_completed(db: Database) -> None:
    d = decide(db, action="x", reversible=True)
    complete(db, d.id)
    with pytest.raises(ValueError, match="cannot reverse a completed"):
        reverse(db, d.id)


def test_reverse_raises_if_missing(db: Database) -> None:
    with pytest.raises(ValueError, match="no decision with id"):
        reverse(db, 999999)


def test_complete_round_trip(db: Database) -> None:
    d = decide(db, action="deploy", reversible=True)
    completed = complete(db, d.id)
    assert completed.status == "completed"


def test_complete_is_idempotent_on_completed(db: Database) -> None:
    d = decide(db, action="x", reversible=True)
    first = complete(db, d.id)
    second = complete(db, d.id)
    assert first == second


def test_complete_raises_if_reversed(db: Database) -> None:
    d = decide(db, action="x", reversible=True)
    reverse(db, d.id)
    with pytest.raises(ValueError, match="cannot complete a reversed"):
        complete(db, d.id)


def test_complete_raises_if_missing(db: Database) -> None:
    with pytest.raises(ValueError, match="no decision with id"):
        complete(db, 999999)


def test_get_decision_returns_none_if_missing(db: Database) -> None:
    assert get_decision(db, 999999) is None


def test_list_decisions_newest_first(db: Database) -> None:
    d1 = decide(db, action="first", reversible=True)
    d2 = decide(db, action="second", reversible=True)
    d3 = decide(db, action="third", reversible=True)
    all_decisions = list_decisions(db)
    assert [d.id for d in all_decisions] == [d3.id, d2.id, d1.id]


def test_list_decisions_filters_by_status(db: Database) -> None:
    active = decide(db, action="active one", reversible=True)
    to_reverse = decide(db, action="reverse me", reversible=True)
    to_complete = decide(db, action="complete me", reversible=True)
    reverse(db, to_reverse.id)
    complete(db, to_complete.id)

    assert [d.id for d in list_decisions(db, status="active")] == [active.id]
    assert [d.id for d in list_decisions(db, status="reversed")] == [to_reverse.id]
    assert [d.id for d in list_decisions(db, status="completed")] == [to_complete.id]


def test_list_decisions_respects_limit(db: Database) -> None:
    for i in range(5):
        decide(db, action=f"d{i}", reversible=True)
    assert len(list_decisions(db, limit=2)) == 2


def test_list_decisions_rejects_bad_limit(db: Database) -> None:
    with pytest.raises(ValueError, match="limit must be"):
        list_decisions(db, limit=0)


def test_list_decisions_rejects_bad_status(db: Database) -> None:
    with pytest.raises(ValueError, match="status must be one of"):
        list_decisions(db, status="invalid")  # type: ignore[arg-type]


def test_decision_dataclass_is_frozen() -> None:
    d = Decision(
        id=1,
        action="x",
        reversible=True,
        risk="medium",
        confidence="medium",
        reasoning=None,
        alternatives=[],
        status="active",
        reversed_by=None,
        created_at=datetime(2024, 1, 1),
    )
    with pytest.raises(AttributeError):
        d.status = "completed"  # type: ignore[misc]


def test_reversible_persists_as_bool(db: Database) -> None:
    """SQLite stores as INTEGER; API must return real Python bool."""
    d = decide(db, action="x", reversible=False)
    refreshed = get_decision(db, d.id)
    assert refreshed is not None
    assert refreshed.reversible is False
    assert isinstance(refreshed.reversible, bool)
