"""BrainConfig validation + yaml loading tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from central_brain.config import BrainConfig


def write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "brain.yaml"
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


def test_minimal_yaml(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, "name: my-bot\n")
    cfg = BrainConfig.from_yaml(path)
    assert cfg.name == "my-bot"
    assert cfg.capabilities == ["memory", "decisions", "reflection"]
    assert cfg.memory.hsam.enabled is True
    assert cfg.reflection.auto_on_session_end is True


def test_full_yaml_round_trip(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        """
        name: journal-bot
        version: 1.0.0
        workspace:
          data_dir: ./custom-data
        capabilities:
          - memory
          - reflection
        memory:
          hsam:
            enabled: false
            subdir: archive
        reflection:
          auto_on_session_end: false
        logging:
          level: debug
          format: plain
        """,
    )
    cfg = BrainConfig.from_yaml(path)
    assert cfg.name == "journal-bot"
    assert cfg.version == "1.0.0"
    assert cfg.workspace.data_dir == Path("./custom-data")
    assert cfg.capabilities == ["memory", "reflection"]
    assert cfg.memory.hsam.enabled is False
    assert cfg.memory.hsam.subdir == "archive"
    assert cfg.reflection.auto_on_session_end is False
    assert cfg.logging.level == "debug"
    assert cfg.logging.format == "plain"


def test_missing_name_fails(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, "version: 1.0.0\n")
    with pytest.raises(ValidationError):
        BrainConfig.from_yaml(path)


def test_empty_name_fails(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, "name: '   '\n")
    with pytest.raises(ValidationError, match="name must not be empty"):
        BrainConfig.from_yaml(path)


def test_unknown_capability_fails(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        """
        name: x
        capabilities:
          - memory
          - telepathy
        """,
    )
    with pytest.raises(ValidationError):
        BrainConfig.from_yaml(path)


def test_unknown_top_level_field_fails(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        """
        name: x
        garbage: stuff
        """,
    )
    with pytest.raises(ValidationError):
        BrainConfig.from_yaml(path)


def test_invalid_log_level_fails(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        """
        name: x
        logging:
          level: verbose
        """,
    )
    with pytest.raises(ValidationError):
        BrainConfig.from_yaml(path)


def test_not_a_mapping_fails(tmp_path: Path) -> None:
    path = tmp_path / "brain.yaml"
    path.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        BrainConfig.from_yaml(path)


def test_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        BrainConfig.from_yaml(tmp_path / "nope.yaml")
