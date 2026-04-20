"""Agent class — high-level API composing all central-brain capabilities.

Consumers touch this one object. Each method is a thin, typed pass-through
to a capability module; capability checks are enforced at the Agent
boundary so misconfigured agents fail fast with actionable errors.

Lifecycle::

    agent = Agent.from_config("./brain.yaml")
    agent.start_session("sess-1")
    agent.remember("Sir prefers dark mode", kind="preference")
    agent.decide(action="deploy", reversible=True, risk="medium")
    ctx = agent.gather_context()        # uses current session
    summary = agent.template_summary()  # zero-LLM fallback
    agent.save_reflection(what_went_well=summary)
    agent.end_session()
    agent.close()

Or as a context manager::

    with Agent.from_config("./brain.yaml") as agent:
        ...
"""

from __future__ import annotations

from datetime import date as Date
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from central_brain.config import BrainConfig
from central_brain.decisions import classifier
from central_brain.decisions.classifier import Confidence, Decision, Risk, Status
from central_brain.memory import episodic, hsam, structured
from central_brain.memory.episodic import Event
from central_brain.memory.hsam import HSAMDay
from central_brain.memory.structured import Fact, FactKind
from central_brain.reflection import session as reflection_session
from central_brain.reflection.session import SessionContext, SessionReflection
from central_brain.storage.db import Database
from central_brain.storage.migrator import migrate


class Agent:
    """Composed entry point over memory + decisions + reflection capabilities."""

    def __init__(self, config: BrainConfig, db: Database, data_dir: Path) -> None:
        self._config = config
        self._db = db
        self._data_dir = data_dir
        self._current_session: str | None = None

    # ── construction ─────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config_path: Path | str) -> Self:
        """Load ``brain.yaml``, open SQLite, apply migrations, return Agent.

        Workspace paths in the YAML are resolved relative to the config file
        itself (not the caller's cwd). The ``data_dir`` is created on demand.
        """
        cfg_path = Path(config_path).resolve()
        config = BrainConfig.from_yaml(cfg_path)

        data_dir = _resolve_dir(cfg_path.parent, config.workspace.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)

        db = Database.connect(data_dir / "brain.db")
        migrate(db)
        return cls(config=config, db=db, data_dir=data_dir)

    # ── introspection ────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def config(self) -> BrainConfig:
        return self._config

    @property
    def db(self) -> Database:
        """Escape hatch for raw SQL. Prefer the typed methods."""
        return self._db

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def current_session(self) -> str | None:
        return self._current_session

    # ── session lifecycle ────────────────────────────────────────────────────

    def start_session(self, session_id: str) -> None:
        """Set the active session id. Used as the default for log_event and
        reflection calls until :meth:`end_session`."""
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        self._current_session = session_id

    def end_session(self) -> None:
        self._current_session = None

    # ── memory ───────────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        kind: FactKind = "fact",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Fact:
        self._require_capability("memory")
        return structured.remember(self._db, content, kind=kind, tags=tags, metadata=metadata)

    def recall(
        self,
        query: str | None = None,
        kind: FactKind | None = None,
        limit: int = 10,
        include_superseded: bool = False,
    ) -> list[Fact]:
        self._require_capability("memory")
        return structured.recall(
            self._db,
            query=query,
            kind=kind,
            limit=limit,
            include_superseded=include_superseded,
        )

    def supersede(
        self,
        old_fact_id: int,
        new_content: str,
        kind: FactKind = "fact",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Fact:
        self._require_capability("memory")
        return structured.supersede(
            self._db,
            old_fact_id,
            new_content,
            kind=kind,
            tags=tags,
            metadata=metadata,
        )

    def log_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> Event:
        self._require_capability("memory")
        sid = session_id if session_id is not None else self._current_session
        return episodic.log_event(self._db, event_type, payload=payload, session_id=sid)

    def recent_events(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[Event]:
        self._require_capability("memory")
        return episodic.recent_events(
            self._db,
            session_id=session_id,
            event_type=event_type,
            limit=limit,
        )

    def append_today(self, text: str, today: Date | None = None) -> HSAMDay:
        """Append text to today's HSAM archive.

        Raises:
            RuntimeError: if the memory capability is disabled, or HSAM is
                disabled in ``brain.yaml``.
        """
        self._require_capability("memory")
        if not self._config.memory.hsam.enabled:
            raise RuntimeError("HSAM is disabled in brain.yaml (memory.hsam.enabled)")
        return hsam.append_today(
            self._db,
            workspace=self._data_dir,
            text=text,
            subdir=self._config.memory.hsam.subdir,
            today=today,
        )

    # ── decisions ────────────────────────────────────────────────────────────

    def decide(
        self,
        action: str,
        reversible: bool,
        risk: Risk = "medium",
        confidence: Confidence = "medium",
        reasoning: str | None = None,
        alternatives: list[str] | None = None,
    ) -> Decision:
        self._require_capability("decisions")
        return classifier.decide(
            self._db,
            action=action,
            reversible=reversible,
            risk=risk,
            confidence=confidence,
            reasoning=reasoning,
            alternatives=alternatives,
        )

    def reverse(self, decision_id: int, replaced_by: int | None = None) -> Decision:
        self._require_capability("decisions")
        return classifier.reverse(self._db, decision_id, replaced_by=replaced_by)

    def complete(self, decision_id: int) -> Decision:
        self._require_capability("decisions")
        return classifier.complete(self._db, decision_id)

    def list_decisions(self, status: Status | None = None, limit: int = 50) -> list[Decision]:
        self._require_capability("decisions")
        return classifier.list_decisions(self._db, status=status, limit=limit)

    # ── reflection ───────────────────────────────────────────────────────────

    def gather_context(
        self,
        session_id: str | None = None,
        event_limit: int = 20,
        decision_limit: int = 20,
    ) -> SessionContext:
        self._require_capability("reflection")
        sid = self._require_session(session_id)
        return reflection_session.gather_session_context(
            self._db,
            session_id=sid,
            event_limit=event_limit,
            decision_limit=decision_limit,
        )

    def save_reflection(
        self,
        session_id: str | None = None,
        what_went_well: str | None = None,
        what_to_improve: str | None = None,
        apply_next_session: str | None = None,
        auto_generated: bool = False,
    ) -> SessionReflection:
        self._require_capability("reflection")
        sid = self._require_session(session_id)
        return reflection_session.save_reflection(
            self._db,
            session_id=sid,
            what_went_well=what_went_well,
            what_to_improve=what_to_improve,
            apply_next_session=apply_next_session,
            auto_generated=auto_generated,
        )

    def template_summary(self, session_id: str | None = None) -> str:
        self._require_capability("reflection")
        ctx = self.gather_context(session_id=session_id)
        return reflection_session.template_summary(ctx)

    # ── lifecycle ────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    # ── internal ─────────────────────────────────────────────────────────────

    def _require_capability(self, name: str) -> None:
        if name not in self._config.capabilities:
            raise RuntimeError(
                f"capability {name!r} is not enabled in brain.yaml "
                f"(enabled: {list(self._config.capabilities)})"
            )

    def _require_session(self, explicit: str | None) -> str:
        if explicit is not None:
            if not explicit.strip():
                raise ValueError("session_id must not be empty")
            return explicit
        if self._current_session is None:
            raise RuntimeError("no active session — call start_session() or pass session_id")
        return self._current_session


def _resolve_dir(base: Path, p: Path) -> Path:
    return p if p.is_absolute() else (base / p).resolve()
