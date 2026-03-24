"""SQLite-backed run/history repository built on the shared history engine."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager

from vibesensor.adapters.persistence.history_db._queries import _HistoryDBQueryMixin
from vibesensor.adapters.persistence.history_db._run_lifecycle import _HistoryDBRunLifecycleMixin
from vibesensor.adapters.persistence.history_db._sample_io import _HistoryDBSampleIOMixin

__all__ = ["RunHistoryRepository"]


class RunHistoryRepository(
    _HistoryDBRunLifecycleMixin,
    _HistoryDBSampleIOMixin,
    _HistoryDBQueryMixin,
):
    """Run/sample/query persistence bound to one shared SQLite history engine."""

    __slots__ = ("_cursor_provider", "_write_transaction_cursor_provider")

    def __init__(
        self,
        *,
        cursor_provider: Callable[..., AbstractContextManager[sqlite3.Cursor]],
        write_transaction_cursor_provider: Callable[[], AbstractContextManager[sqlite3.Cursor]],
    ) -> None:
        self._cursor_provider = cursor_provider
        self._write_transaction_cursor_provider = write_transaction_cursor_provider

    def _cursor(self, *, commit: bool = True) -> AbstractContextManager[sqlite3.Cursor]:
        return self._cursor_provider(commit=commit)

    def write_transaction_cursor(self) -> AbstractContextManager[sqlite3.Cursor]:
        return self._write_transaction_cursor_provider()
