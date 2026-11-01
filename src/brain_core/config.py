"""Configuration schema for ``brain.yaml``.

Consumed by :class:`brain_core.agent.Agent` via ``Agent.from_config(path)``.

Pydantic v2 validates the schema; field-level ``Literal`` types reject
unknown capability names at load time instead of at first call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

Capability = Literal["memory", "decisions", "reflection"]


def _default_capabilities() -> list[Capability]:
    return ["memory", "decisions", "reflection"]


class WorkspaceConfig(BaseModel):
    """Filesystem layout for agent state."""

    model_config = ConfigDict(extra="forbid")

    data_dir: Path = Path("./data")


class HSAMConfig(BaseModel):
    """HSAM (daily markdown archive) settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    subdir: str = "hsam"


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hsam: HSAMConfig = Field(default_factory=HSAMConfig)


class ReflectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_on_session_end: bool = True


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["debug", "info", "warning", "error"] = "info"
    format: Literal["json", "plain"] = "json"


class HindsightConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = "http://127.0.0.1:8888"
    bank: str


class GraphConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: Path
    python: str = "python3"


class StoresConfig(BaseModel):
    """Where the agent's memory already lives (v0.2). SQLite is always on; the rest are optional."""

    model_config = ConfigDict(extra="forbid")

    vault: Path | None = None
    hindsight: HindsightConfig | None = None
    graph: GraphConfig | None = None


class SessionConfig(BaseModel):
    """Files ``brain_session`` reads at start and writes at end. Paths are relative to the vault."""

    model_config = ConfigDict(extra="forbid")

    brief: str = "daily_brief.md"
    executive: str = "executive_state.md"
    inbox: str = "inbox_staged.md"
    critique: str = "session_critique.md"
    sync: str = "last_standalone_session.md"
    mental_models: list[str] = Field(default_factory=lambda: ["active-priorities"])
    queue: str | None = None  # Hindsight amnesia queue (jsonl), drained at end
    marker: str | None = None  # clean-close marker; default data_dir/last_close.txt


class StatusConfig(BaseModel):
    """What ``brain_status`` measures as always-loaded context. Globs, relative to brain.yaml."""

    model_config = ConfigDict(extra="forbid")

    context_files: list[str] = Field(default_factory=lambda: ["CLAUDE.md", ".claude/rules/*.md"])


class BrainConfig(BaseModel):
    """Top-level ``brain.yaml`` schema.

    Minimal valid YAML is a single ``name:`` key — all other fields have
    defaults. Unknown fields at any level raise ``ValidationError``.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = "0.1.0"
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    capabilities: list[Capability] = Field(default_factory=_default_capabilities)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    reflection: ReflectionConfig = Field(default_factory=ReflectionConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    stores: StoresConfig = Field(default_factory=StoresConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    status: StatusConfig = Field(default_factory=StatusConfig)

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
