"""Shared fixtures for HistoryDB adapter tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.history_db import HistoryDB


@pytest.fixture
def db(tmp_path: Path) -> Iterator[HistoryDB]:
    """A fresh HistoryDB at ``tmp_path / "history.db"``, closed after the test."""
    adapters = HistoryDB(tmp_path / "history.db")
    try:
        yield adapters
    finally:
        adapters.close()
