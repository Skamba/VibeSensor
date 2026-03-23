"""Helpers for resolving static data files in source and installed layouts."""

from __future__ import annotations

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_SOURCE_DATA_DIR = _PACKAGE_DIR.parent / "data"
_PACKAGED_DATA_DIR = _PACKAGE_DIR / "data"


def resolve_static_data_file(file_name: str) -> Path:
    """Return the canonical source-tree data file or the packaged fallback path."""
    source_candidate = _SOURCE_DATA_DIR / file_name
    if source_candidate.exists():
        return source_candidate
    return _PACKAGED_DATA_DIR / file_name
