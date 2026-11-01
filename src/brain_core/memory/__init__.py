"""Memory capability: structured facts, episodic events, HSAM daily archive.

Public types:
    Fact, Event, HSAMDay — frozen dataclasses returned at the API boundary.

Public functions:
    remember, recall, supersede     — structured facts
    log_event, recent_events        — episodic event log
    append_today                    — HSAM daily markdown archive
"""

from brain_core.memory.episodic import Event, log_event, recent_events
from brain_core.memory.hsam import HSAMDay, append_today
from brain_core.memory.structured import Fact, recall, remember, supersede

__all__ = [
    "Event",
    "Fact",
    "HSAMDay",
    "append_today",
    "log_event",
    "recall",
    "recent_events",
    "remember",
    "supersede",
]
