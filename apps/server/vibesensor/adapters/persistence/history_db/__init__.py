"""SQLite-backed history persistence adapters built on a shared engine."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vibesensor.adapters.persistence.history_db._client_names_repository import (
    ClientNameRepository,
)
from vibesensor.adapters.persistence.history_db._engine import SQLiteHistoryEngine
from vibesensor.adapters.persistence.history_db._run_repository import RunHistoryRepository
from vibesensor.adapters.persistence.history_db._settings_repository import (
    SettingsSnapshotRepository,
)

__all__ = [
    "ClientNameRepository",
    "HistoryPersistenceAdapters",
    "RunHistoryRepository",
    "SQLiteHistoryEngine",
    "SettingsSnapshotRepository",
    "create_history_persistence_adapters",
    "create_history_persistence_adapters_async",
]

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HistoryPersistenceAdapters:
    """Concrete persistence collaborators built over one SQLite history engine."""

    lifecycle: SQLiteHistoryEngine
    run_repository: RunHistoryRepository
    settings_snapshot_repository: SettingsSnapshotRepository
    client_name_repository: ClientNameRepository

    def open(self) -> None:
        self.lifecycle.open()

    async def aopen(self) -> None:
        await self.lifecycle.aopen()

    def close(self) -> object:
        return self.lifecycle.close()

    async def aclose(self) -> None:
        await self.lifecycle.aclose()


def _build_history_persistence_adapters(
    db_path: Path,
    *,
    corruption_reporter: Callable[[str], None] | None = None,
) -> HistoryPersistenceAdapters:
    lifecycle = SQLiteHistoryEngine(
        db_path,
        corruption_reporter=corruption_reporter,
    )
    cursor_provider = lifecycle._cursor
    return HistoryPersistenceAdapters(
        lifecycle=lifecycle,
        run_repository=RunHistoryRepository(
            cursor_provider=cursor_provider,
            write_transaction_cursor_provider=lifecycle.write_transaction_cursor,
        ),
        settings_snapshot_repository=SettingsSnapshotRepository(
            cursor_provider=cursor_provider,
        ),
        client_name_repository=ClientNameRepository(
            cursor_provider=cursor_provider,
        ),
    )


def create_history_persistence_adapters(
    db_path: Path,
    *,
    corruption_reporter: Callable[[str], None] | None = None,
) -> HistoryPersistenceAdapters:
    """Build and open the shared history engine plus narrow repositories on top of it."""
    history = _build_history_persistence_adapters(
        db_path,
        corruption_reporter=corruption_reporter,
    )
    history.open()
    return history


async def create_history_persistence_adapters_async(
    db_path: Path,
    *,
    corruption_reporter: Callable[[str], None] | None = None,
) -> HistoryPersistenceAdapters:
    history = _build_history_persistence_adapters(
        db_path,
        corruption_reporter=corruption_reporter,
    )
    await history.aopen()
    return history
