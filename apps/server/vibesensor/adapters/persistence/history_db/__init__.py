"""SQLite-backed history persistence adapters built on a shared engine."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

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
    "HistoryDB",
    "HistoryPersistenceAdapters",
    "RunHistoryRepository",
    "SQLiteHistoryEngine",
    "SettingsSnapshotRepository",
    "create_history_persistence_adapters",
]

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HistoryPersistenceAdapters:
    """Concrete persistence collaborators built over one SQLite history engine."""

    lifecycle: SQLiteHistoryEngine
    run_repository: RunHistoryRepository
    settings_snapshot_repository: SettingsSnapshotRepository
    client_name_repository: ClientNameRepository


def create_history_persistence_adapters(
    db_path: Path,
    *,
    corruption_reporter: Callable[[str], None] | None = None,
) -> HistoryPersistenceAdapters:
    """Build the shared history engine plus narrow repositories on top of it."""
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


class HistoryDB:
    """Compatibility facade over the split history persistence collaborators.

    New production wiring should prefer the narrow repositories returned by
    :func:`create_history_persistence_adapters`. This wrapper is retained so the
    focused history-db tests and any remaining legacy call sites can continue to
    exercise the same public surface while the app transitions to explicit
    injection of narrower persistence capabilities.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        corruption_reporter: Callable[[str], None] | None = None,
    ) -> None:
        self._engine = SQLiteHistoryEngine(
            db_path,
            corruption_reporter=corruption_reporter,
        )
        self._run_repository = RunHistoryRepository(
            cursor_provider=lambda *, commit=True: self._cursor(commit=commit),
            write_transaction_cursor_provider=lambda: self.write_transaction_cursor(),
        )
        self._settings_snapshot_repository = SettingsSnapshotRepository(
            cursor_provider=lambda *, commit=True: self._cursor(commit=commit),
        )
        self._client_name_repository = ClientNameRepository(
            cursor_provider=lambda *, commit=True: self._cursor(commit=commit),
        )

    def __getattr__(self, name: str) -> Any:
        for delegate in (
            self._run_repository,
            self._settings_snapshot_repository,
            self._client_name_repository,
            self._engine,
        ):
            try:
                return getattr(delegate, name)
            except AttributeError:
                continue
        raise AttributeError(f"{self.__class__.__name__!s} object has no attribute {name!r}")

    @property
    def _conn(self) -> sqlite3.Connection | None:
        return self._engine._conn

    @_conn.setter
    def _conn(self, value: sqlite3.Connection | None) -> None:
        self._engine._conn = value

    @property
    def _read_conn(self) -> sqlite3.Connection | None:
        return self._engine._read_conn

    @_read_conn.setter
    def _read_conn(self, value: sqlite3.Connection | None) -> None:
        self._engine._read_conn = value

    @property
    def _lock(self) -> RLock:
        return self._engine._lock

    @_lock.setter
    def _lock(self, value: RLock) -> None:
        self._engine._lock = value

    @property
    def _read_lock(self) -> RLock:
        return self._engine._read_lock

    @_read_lock.setter
    def _read_lock(self, value: RLock) -> None:
        self._engine._read_lock = value

    def close(self) -> None:
        self._engine.close()

    def _cursor_connection(
        self,
        *,
        commit: bool,
    ) -> tuple[sqlite3.Connection | None, RLock]:
        return self._engine._cursor_connection(commit=commit)

    @contextmanager
    def _cursor(self, *, commit: bool = True) -> Iterator[sqlite3.Cursor]:
        with self._engine._cursor(commit=commit) as cur:
            yield cur

    @contextmanager
    def write_transaction_cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._engine.write_transaction_cursor() as cur:
            yield cur

    def _assert_write_allowed(self) -> None:
        self._engine._assert_write_allowed()

    def _mark_corrupted(self, details: str) -> None:
        self._engine._mark_corrupted(details)

    def _ensure_schema(self) -> None:
        self._engine._ensure_schema()

    def _schema_version(self) -> int:
        return self._engine._schema_version()

    def _migration_step(self, version: int) -> tuple[int, Callable[[], None]] | None:
        return self._engine._migration_step(version)

    def _migration_backup_path(self, version: int) -> Path:
        return self._engine._migration_backup_path(version)

    def _create_migration_backup(self, version: int) -> Path:
        return self._engine._create_migration_backup(version)

    def _restore_migration_backup(self, backup_path: Path) -> None:
        self._engine._restore_migration_backup(backup_path)

    @staticmethod
    def _has_runs_column(cur: sqlite3.Cursor, column_name: str) -> bool:
        return SQLiteHistoryEngine._has_runs_column(cur, column_name)

    def _migrate_v8_to_v9_case_id(self) -> None:
        self._engine._migrate_v8_to_v9_case_id()

    def _migrate_v9_to_v10_settings_table(self) -> None:
        self._engine._migrate_v9_to_v10_settings_table()

    def _migrate_v10_to_v11_persisted_analysis_version(self) -> None:
        self._engine._migrate_v10_to_v11_persisted_analysis_version()

    def _run_startup_quick_check(self) -> None:
        try:
            with self._cursor(commit=False) as cur:
                cur.execute("PRAGMA quick_check")
                problems = [str(row[0]) for row in cur.fetchall() if str(row[0]) != "ok"]
        except sqlite3.Error:
            LOGGER.critical(
                "History DB quick_check failed during startup for %s",
                self.db_path,
                exc_info=True,
            )
            raise
        if problems:
            details = "; ".join(problems)
            self._mark_corrupted(details)
            LOGGER.critical(
                "History DB quick_check reported corruption for %s: %s",
                self.db_path,
                details,
            )
