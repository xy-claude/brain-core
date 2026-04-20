"""Configuration schema for ``brain.yaml``.

Consumed by :class:`central_brain.agent.Agent` via ``Agent.from_config(path)``.

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
