"""Episodic event log tests."""

from __future__ import annotations

import pytest

from central_brain.memory import Event, log_event, recent_events
from central_brain.storage import Database


def test_log_event_round_trip(db: Database) -> None:
    event = log_event(
        db,
        event_type="user_message",
        payload={"text": "hello"},
        session_id="s1",
    )
    assert event.id > 0
    assert event.event_type == "user_message"
    assert event.payload == {"text": "hello"}
    assert event.session_id == "s1"


def test_log_event_without_payload_or_session(db: Database) -> None:
    event = log_event(db, event_type="ping")
    assert event.payload == {}
    assert event.session_id is None


def test_log_event_rejects_empty_type(db: Database) -> None:
    with pytest.raises(ValueError, match="event_type must not be empty"):
        log_event(db, event_type="   ")


def test_recent_events_newest_first(db: Database) -> None:
    log_event(db, event_type="e", payload={"n": 1})
    log_event(db, event_type="e", payload={"n": 2})
    log_event(db, event_type="e", payload={"n": 3})
    events = recent_events(db)
    assert [e.payload["n"] for e in events] == [3, 2, 1]


def test_recent_events_filters_by_session(db: Database) -> None:
    log_event(db, event_type="e", session_id="sA")
    log_event(db, event_type="e", session_id="sB")
    log_event(db, event_type="e", session_id="sA")

    in_a = recent_events(db, session_id="sA")
    assert len(in_a) == 2
    assert all(e.session_id == "sA" for e in in_a)


def test_recent_events_filters_by_type(db: Database) -> None:
    log_event(db, event_type="user_message")
    log_event(db, event_type="tool_call")
    log_event(db, event_type="user_message")

    msgs = recent_events(db, event_type="user_message")
    assert len(msgs) == 2
    assert all(e.event_type == "user_message" for e in msgs)


def test_recent_events_respects_limit(db: Database) -> None:
    for i in range(5):
        log_event(db, event_type="e", payload={"n": i})
    assert len(recent_events(db, limit=2)) == 2


def test_recent_events_limit_must_be_positive(db: Database) -> None:
    with pytest.raises(ValueError):
        recent_events(db, limit=0)


def test_event_dataclass_is_frozen() -> None:
    from datetime import datetime as _dt

    event = Event(
        id=1,
        event_type="e",
        payload={},
        session_id=None,
        occurred_at=_dt(2024, 1, 1),
    )
    with pytest.raises(AttributeError):
        event.event_type = "x"  # type: ignore[misc]
