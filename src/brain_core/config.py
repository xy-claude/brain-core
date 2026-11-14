"""Configuration schema for ``brain.yaml``.

Consumed by :class:`brain_core.agent.Agent` via ``Agent.from_config(path)``.

Pydantic v2 validates the schema; unknown fields fail at load time, not at first call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkspaceConfig(BaseModel):
    """Filesystem layout for agent state."""

    model_config = ConfigDict(extra="forbid")

    data_dir: Path = Path("./data")


class HindsightConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = "http://127.0.0.1:8888"
    bank: str
    # false: still written to, and read by scope='hindsight', but not asked on every recall
    recall: bool = True


class GraphConfig(BaseModel):
    """Legacy Kuzu graph (external ``entity_graph.py`` CLI); only ``brain graph import`` uses it."""

    model_config = ConfigDict(extra="forbid")

    script: Path
    python: str = "python3"


class VectorsConfig(BaseModel):
    """The optional vector search beside the keyword index: ``brain-core-mcp[vectors]``.
    One embed worker per machine holds the model for every agent and exits when idle."""

    model_config = ConfigDict(extra="forbid")

    model: str = "Qwen/Qwen3-Embedding-0.6B"
    idle_minutes: float = 5  # how long the worker stays up after a call; 0 = exit after each


class StoresConfig(BaseModel):
    """Where the agent's memory already lives (v0.2). SQLite is always on; the rest are optional."""

    model_config = ConfigDict(extra="forbid")

    vault: Path | None = None
    hindsight: HindsightConfig | None = None
    transcripts: Path | None = None  # Claude Code projects root, e.g. ~/.claude/projects
    transcripts_cwd: Path | None = None  # the folder Claude Code runs in; default: brain.yaml's
    graph: GraphConfig | None = None
    notes: list[Path] = Field(default_factory=list)  # read-only markdown folders recall searches
    # read-only folders of older memory (an export from another tool): searched, ranked below
    archive: list[Path] = Field(default_factory=list)
    vectors: VectorsConfig | None = None  # absent: keyword search only


class RecallConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: int = 150  # how many records each search (keyword, vector) puts forward
    # agent: the calling agent reads the list and decides (free). model: brain-core asks a
    # model to pick the records that answer, or to say none does, before replying
    judge: Literal["agent", "model"] = "agent"
    judge_candidates: int = 50  # how many of the best candidates the model reads
    # as for `models`: api needs a key; claude is your own Claude Code login on your machine
    runner: Literal["api", "claude"] = "api"
    model: str | None = None  # default: judge.JUDGE_MODEL, the small model the eval measured
    judge_timeout: float = 60  # seconds a judge call may take before recall answers without it


class SessionConfig(BaseModel):
    """Files ``brain_session`` reads at start and writes at end. Paths are relative to the vault."""

    model_config = ConfigDict(extra="forbid")

    brief: str = "daily_brief.md"
    brief_tokens: int = 3000  # the SessionStart hook injects no more of the brief than this
    executive: str = "executive_state.md"
    inbox: str = "inbox_staged.md"
    critique: str = "session_critique.md"
    sync: str = "last_standalone_session.md"
    peers: list[str] = Field(default_factory=list)  # globs of other agents' sync files
    mental_models: list[str] = Field(default_factory=lambda: ["active-priorities"])
    queue: str | None = None  # Hindsight amnesia queue (jsonl), drained at end
    marker: str | None = None  # clean-close marker; default data_dir/last_close.txt


class ModelItem(BaseModel):
    """One mental model: a standing question, answered from the records that bear on it."""

    model_config = ConfigDict(extra="forbid")

    name: str  # the file is vault/models/<name>.md
    question: str
    search: str = ""  # extra words to find its records by
    kinds: list[str] = Field(default_factory=list)  # also read the newest records of these kinds


def _default_models() -> list[ModelItem]:
    return [
        ModelItem(
            name="active-priorities",
            question="What are the current priorities, missions and open loops, in order?",
            search="priority mission blocked pending next step deadline goal",
            kinds=["decision", "note"],
        ),
        ModelItem(
            name="working-style",
            question="How does the user prefer to work and be communicated with?",
            search="prefers wants dislikes style tone format rule always never",
            kinds=["correction", "pattern"],
        ),
        ModelItem(
            name="key-decisions",
            question="What was decided, why, and what was rejected?",
            search="decided chose rejected reason instead of because",
            kinds=["decision"],
        ),
        ModelItem(
            name="system-architecture",
            question="How is the system built: its parts, where they run, how they connect?",
            search="architecture service server database port runs deploy config path",
            kinds=["fact"],
        ),
        ModelItem(
            name="recurring-lessons",
            question="Which mistakes and lessons keep recurring, and what rule came of each?",
            search="lesson mistake again repeated rule correction verify",
            kinds=["correction"],
        ),
    ]


class ModelsConfig(BaseModel):
    """``brain models``: LLM-written briefings kept as cited markdown in ``vault/models/``."""

    model_config = ConfigDict(extra="forbid")

    # api: the Anthropic API with a key (the default). claude: your own Claude Code login,
    # for personal use on your own machine; you opt in by naming it.
    runner: Literal["api", "claude"] = "api"
    model: str | None = None  # default: Claude Code's own, or claude-opus-5-5 on the API
    records: int = 150  # read per question
    items: list[ModelItem] = Field(default_factory=_default_models)


class StatusConfig(BaseModel):
    """What ``brain_status`` measures as always-loaded context. Globs, relative to brain.yaml."""

    model_config = ConfigDict(extra="forbid")

    context_files: list[str] = Field(default_factory=lambda: ["CLAUDE.md", ".claude/rules/*.md"])


class BackupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    dir: str = "~/Backups/hindsight"
    keep: int = 14
    database_url: str = "pg0://hindsight"


class CronConfig(BaseModel):
    """``brain daily`` / ``brain weekly`` schedule (launchd) and the Hindsight backup."""

    model_config = ConfigDict(extra="forbid")

    daily: str = "06:07"
    weekly: str = "Sun 07:13"
    backup: BackupConfig = Field(default_factory=BackupConfig)
    update_check: bool = True  # brain daily asks PyPI once whether a newer brain-core exists


class BrainConfig(BaseModel):
    """Top-level ``brain.yaml`` schema.

    Minimal valid YAML is a single ``name:`` key — all other fields have
    defaults. Unknown fields at any level raise ``ValidationError``.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    stores: StoresConfig = Field(default_factory=StoresConfig)
    recall: RecallConfig = Field(default_factory=RecallConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    status: StatusConfig = Field(default_factory=StatusConfig)
    cron: CronConfig = Field(default_factory=CronConfig)
    models: ModelsConfig | None = None  # absent: no mental models are written

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v

    @classmethod
    def from_yaml(cls, path: Path | str) -> Self:
        """Load and validate a ``brain.yaml`` file.

        Raises:
            FileNotFoundError: if the file does not exist.
            ValueError: if the file is not a YAML mapping at the top level.
            pydantic.ValidationError: for any schema violation.
        """
        file_path = Path(path)
        with file_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(
                f"{file_path}: brain.yaml must be a YAML mapping at top level, "
                f"got {type(data).__name__}"
            )
        return cls.model_validate(data)
