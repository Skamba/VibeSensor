"""SQLite-backed run/history repository built on the shared history engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import TypeVar

import aiosqlite

from vibesensor.adapters.persistence.history_db._engine import SQLiteHistoryEngine
from vibesensor.adapters.persistence.history_db._queries import _HistoryDBQueryMixin
from vibesensor.adapters.persistence.history_db._run_lifecycle import _HistoryDBRunLifecycleMixin
from vibesensor.adapters.persistence.history_db._sample_io import _HistoryDBSampleIOMixin

__all__ = ["RunHistoryRepository"]

_T = TypeVar("_T")
CursorProvider = Callable[..., AbstractAsyncContextManager[aiosqlite.Cursor]]
WriteTransactionCursorProvider = Callable[[], AbstractAsyncContextManager[aiosqlite.Cursor]]


class RunHistoryRepository(
    _HistoryDBRunLifecycleMixin,
    _HistoryDBSampleIOMixin,
    _HistoryDBQueryMixin,
):
    """Run/sample/query persistence bound to one shared SQLite history engine."""

    __slots__ = ("_cursor_provider", "_engine", "_write_transaction_cursor_provider")

    def __init__(
        self,
        *,
        engine: SQLiteHistoryEngine,
        cursor_provider: CursorProvider,
        write_transaction_cursor_provider: WriteTransactionCursorProvider,
    ) -> None:
        self._engine = engine
        self._cursor_provider = cursor_provider
        self._write_transaction_cursor_provider = write_transaction_cursor_provider

    def _cursor(self, *, commit: bool = True) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        return self._cursor_provider(commit=commit)

    def write_transaction_cursor(self) -> AbstractAsyncContextManager[aiosqlite.Cursor]:
        return self._write_transaction_cursor_provider()

    def _run_sync(self, coro: Awaitable[_T]) -> _T:
        return self._engine._run_on_engine_loop(coro)
