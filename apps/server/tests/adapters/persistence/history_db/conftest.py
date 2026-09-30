"""Shared fixtures for HistoryDB adapter tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.history_db import (
    HistoryPersistenceAdapters,
    create_history_persistence_adapters,
)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[HistoryPersistenceAdapters]:
    """A fresh HistoryDB at ``tmp_path / "history.db"``, closed after the test."""
    adapters = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        yield adapters
    finally:
        adapters.lifecycle.close()
