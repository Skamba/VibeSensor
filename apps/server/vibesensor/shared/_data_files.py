"""Helpers for resolving packaged static data files."""

from __future__ import annotations

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_PACKAGE_ROOT = _PACKAGE_DIR.parent
_DATA_DIR = _PACKAGE_ROOT / "data"


def resolve_static_data_file(file_name: str) -> Path:
    """Return the canonical packaged static data path."""
    return _DATA_DIR / file_name
