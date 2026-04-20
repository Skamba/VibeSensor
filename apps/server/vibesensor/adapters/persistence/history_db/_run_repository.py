"""SQLite-backed run/history repository built on the shared history engine."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import aiosqlite

from vibesensor.adapters.persistence.history_db._engine import _DualContextManager
from vibesensor.adapters.persistence.history_db._queries import _HistoryDBQueryMixin
from vibesensor.adapters.persistence.history_db._run_lifecycle import _HistoryDBRunLifecycleMixin
from vibesensor.adapters.persistence.history_db._sample_io import _HistoryDBSampleIOMixin

__all__ = ["RunHistoryRepository"]

CursorProvider = Callable[..., AbstractAsyncContextManager[aiosqlite.Cursor]]
WriteTransactionCursorProvider = Callable[[], AbstractAsyncContextManager[aiosqlite.Cursor]]


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
        cursor_provider: CursorProvider,
        write_transaction_cursor_provider: WriteTransactionCursorProvider,
    ) -> None:
        self._cursor_provider = cursor_provider
        self._write_transaction_cursor_provider = write_transaction_cursor_provider

    def _cursor(self, *, commit: bool = True) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        return _DualContextManager(self._cursor_provider(commit=commit))

    def write_transaction_cursor(self) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        return _DualContextManager(self._write_transaction_cursor_provider())
