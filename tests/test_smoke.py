"""Chassis smoke test — proves the package imports and ships a version."""

from __future__ import annotations

import central_brain


def test_package_imports() -> None:
    assert central_brain is not None


def test_version_is_string() -> None:
    assert isinstance(central_brain.__version__, str)
    assert central_brain.__version__.count(".") == 2
