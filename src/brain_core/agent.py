"""Agent class — high-level API composing all brain-core capabilities.

Consumers touch this one object. Each method is a thin, typed pass-through
to a capability module; capability checks are enforced at the Agent
boundary so misconfigured agents fail fast with actionable errors.

Lifecycle::

    agent = Agent.from_config("./brain.yaml")
    agent.start_session("sess-1")
    agent.remember("Ada prefers dark mode", kind="preference")
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
from typing import Any, Self, cast, get_args

from brain_core.config import BrainConfig
from brain_core.distill import brain_distill
from brain_core.memory import episodic
from brain_core.memory.episodic import Event
from brain_core.recall import brain_recall
from brain_core.remember import brain_remember
from brain_core.session import session_end, session_start
from brain_core.status import brain_status
from brain_core.storage.db import Database
from brain_core.storage.migrator import migrate
from brain_core.stores import (
    GraphStore,
    HindsightStore,
    SqliteStore,
    Store,
    TranscriptStore,
    VaultStore,
)
from brain_core.stores.base import Kind


class Agent:
    """The five brain_* operations over every configured store, plus the session journal."""

    def __init__(
        self, config: BrainConfig, db: Database, data_dir: Path, config_path: Path | None = None
    ) -> None:
        self._config = config
        self._db = db
        self._data_dir = data_dir
        self.config_path = config_path
        self._current_session: str | None = None
        self._stores: list[Store] | None = None

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
        return cls(config=config, db=db, data_dir=data_dir, config_path=cfg_path)

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

    def resolve(self, p: Path | str) -> Path:
        """A path from brain.yaml: ``~`` expanded, relative ones anchored at the yaml's folder."""
        base = self.config_path.parent if self.config_path else Path.cwd()
        return _resolve_dir(base, Path(p).expanduser())

    @property
    def stores(self) -> list[Store]:
        """Every configured store (v0.2). SQLite first, then vault, Hindsight, graph as set."""
        if self._stores is None:
            s = self._config.stores
            self._stores = [SqliteStore(self._db)]
            if s.vault:
                self._stores.append(VaultStore(self.resolve(s.vault), owner=self.name.lower()))
            if s.hindsight:
                self._stores.append(HindsightStore(s.hindsight.url, s.hindsight.bank, self.name))
            self._stores.append(GraphStore(self._db))  # relations table in brain.db, always on
            if s.transcripts and self.config_path:
                cwd = (
                    self.resolve(s.transcripts_cwd)
                    if s.transcripts_cwd
                    else self.config_path.parent
                )
                self._stores.append(TranscriptStore(self._db, s.transcripts, cwd))
        return self._stores

    def brain_recall(
        self, query: str, scope: str = "all", fmt: str = "concise", limit: int = 10
    ) -> dict[str, Any]:
        """One query across every store, deduplicated and ranked. See :mod:`brain_core.recall`."""
        return brain_recall(self.stores, query, scope=scope, fmt=fmt, limit=limit)

    # ── session lifecycle ────────────────────────────────────────────────────

    def start_session(self, session_id: str) -> None:
        """Set the active session id, the default for log_event until :meth:`end_session`."""
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        self._current_session = session_id

    def end_session(self) -> None:
        self._current_session = None

    # ── memory ───────────────────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> Event:
        sid = session_id if session_id is not None else self._current_session
        return episodic.log_event(self._db, event_type, payload=payload, session_id=sid)

    def recent_events(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[Event]:
        return episodic.recent_events(
            self._db,
            session_id=session_id,
            event_type=event_type,
            limit=limit,
        )

    def brain_remember(
        self,
        text: str,
        kind: str,
        *,
        domain: str = "",
        source: str = "",
        mission: str | None = None,
        when: Date | None = None,
        force: bool = False,
        **extra: str,
    ) -> dict[str, Any]:
        """Write-through to every store with per-layer status. See :mod:`brain_core.remember`."""
        if kind not in get_args(Kind) or kind == "transcript":
            raise ValueError(
                f"kind must be one of {'|'.join(k for k in get_args(Kind) if k != 'transcript')}"
            )
        out = brain_remember(
            self.stores,
            text,
            cast(Kind, kind),
            domain=domain,
            source=source,
            mission=mission,
            when=when,
            force=force,
            **cast(dict[str, Any], extra),
        )
        # the session journal: brain_session('end') reports and summarises these
        episodic.log_event(
            self._db,
            "brain_remember",
            payload={
                "kind": kind,
                "id": out.get("id", ""),
                "status": out["status"],
                "text": out["text"][:200],
                "contradiction": "contradiction" in out,
            },
            session_id=self._current_session,
        )
        return out

    def brain_session(
        self,
        phase: str,
        session_id: str | None = None,
        *,
        executive_state: str | None = None,
        critique: str | None = None,
        sync: str | None = None,
    ) -> dict[str, Any]:
        """START block or END writes. See :mod:`brain_core.session`."""
        if phase == "start":
            return session_start(self, session_id)
        if phase == "end":
            return session_end(
                self, session_id, executive_state=executive_state, critique=critique, sync=sync
            )
        raise ValueError("phase must be 'start' or 'end'")

    def brain_distill(
        self,
        source: str,
        *,
        text: str | None = None,
        title: str | None = None,
        author: str | None = None,
        published: str | None = None,
    ) -> dict[str, Any]:
        """Capture a source into ``raw/``. See :mod:`brain_core.distill`."""
        return brain_distill(
            self, source, text=text, title=title, author=author, published=published
        )

    def brain_status(self) -> dict[str, Any]:
        """Health in one call. See :mod:`brain_core.status`."""
        return brain_status(self)

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


def _resolve_dir(base: Path, p: Path) -> Path:
    return p if p.is_absolute() else (base / p).resolve()
