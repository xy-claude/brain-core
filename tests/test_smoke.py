"""Chassis smoke test — proves the package imports and ships a version."""

from __future__ import annotations

import brain_core


def test_package_imports() -> None:
    assert brain_core is not None


def test_version_is_string() -> None:
    assert isinstance(brain_core.__version__, str)
    assert brain_core.__version__.count(".") == 2
