"""BrainConfig validation + yaml loading tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from brain_core.config import BrainConfig


def write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "brain.yaml"
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


def test_minimal_yaml(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, "name: my-bot\n")
    cfg = BrainConfig.from_yaml(path)
    assert cfg.name == "my-bot"
    assert cfg.session.brief == "daily_brief.md" and cfg.cron.backup.keep == 14


def test_full_yaml_round_trip(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        """
        name: journal-bot
        workspace:
          data_dir: ./custom-data
        session:
          mental_models: [active-priorities, user-style]
        cron:
          daily: "05:00"
        """,
    )
    cfg = BrainConfig.from_yaml(path)
    assert cfg.name == "journal-bot"
    assert cfg.workspace.data_dir == Path("./custom-data")
    assert cfg.session.mental_models == ["active-priorities", "user-style"]
    assert cfg.cron.daily == "05:00"


def test_missing_name_fails(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, "version: 1.0.0\n")
    with pytest.raises(ValidationError):
        BrainConfig.from_yaml(path)


def test_empty_name_fails(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, "name: '   '\n")
    with pytest.raises(ValidationError, match="name must not be empty"):
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


def test_not_a_mapping_fails(tmp_path: Path) -> None:
    path = tmp_path / "brain.yaml"
    path.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        BrainConfig.from_yaml(path)


def test_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        BrainConfig.from_yaml(tmp_path / "nope.yaml")


def test_notes_folders_are_a_list_of_paths(tmp_path: Path) -> None:
    (tmp_path / "brain.yaml").write_text("name: A\nstores:\n  notes: [~/shared, ./memory]\n")
    cfg = BrainConfig.from_yaml(tmp_path / "brain.yaml")
    assert [str(p) for p in cfg.stores.notes] == ["~/shared", "memory"]
