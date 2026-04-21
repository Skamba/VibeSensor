"""Shared SQLite lifecycle/engine utilities for history persistence adapters."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar, cast

import aiosqlite

from vibesensor.adapters.persistence.history_db._schema import (
    SCHEMA_SQL,
    SCHEMA_VERSION,
)

LOGGER = logging.getLogger(__name__)

__all__ = ["SQLiteHistoryEngine", "run_startup_quick_check"]

_T = TypeVar("_T")


class _EngineLoopThread:
    """Single persistent event loop backing aiosqlite I/O for one engine instance.

    aiosqlite binds its worker thread to the event loop that opened the connection.
    A persistent loop keeps the connection usable across many sync/async callers
    without creating a fresh loop per request (which would orphan the worker thread).
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            name="history-db-loop",
            daemon=True,
        )
        self._thread.start()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def run_sync(self, coro: Awaitable[_T]) -> _T:
        future = asyncio.run_coroutine_threadsafe(cast(Any, coro), self._loop)
        return cast(_T, future.result())

    def stop(self) -> None:
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)
        if not self._loop.is_closed():
            self._loop.close()


def _current_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


@asynccontextmanager
async def _async_lock_context(lock: object) -> AsyncIterator[None]:
    manager = cast(Any, lock)
    if hasattr(manager, "__aenter__"):
        async with manager:
            yield
        return
    if hasattr(manager, "acquire") and hasattr(manager, "release"):
        await asyncio.to_thread(manager.acquire)
        try:
            yield
        finally:
            manager.release()
        return
    if hasattr(manager, "__enter__") and hasattr(manager, "__exit__"):
        with manager:
            yield
        return
    raise TypeError(f"Unsupported lock object: {type(lock)!r}")


async def run_startup_quick_check(
    *,
    cursor_provider: Callable[..., AbstractAsyncContextManager[aiosqlite.Cursor]],
    db_path: Path,
    mark_corrupted: Callable[[str], None],
) -> None:
    try:
        async with cursor_provider(commit=False) as cur:
            await cur.execute("PRAGMA quick_check")
            problems = [str(row[0]) for row in await cur.fetchall() if str(row[0]) != "ok"]
    except aiosqlite.Error:
        LOGGER.critical(
            "History DB quick_check failed during startup for %s",
            db_path,
            exc_info=True,
        )
        raise
    if problems:
        details = "; ".join(problems)
        mark_corrupted(details)
        LOGGER.critical(
            "History DB quick_check reported corruption for %s: %s",
            db_path,
            details,
        )


class SQLiteHistoryEngine:
    """Own SQLite lifecycle, current-schema enforcement, corruption, and cursors."""

    __slots__ = (
        "db_path",
        "_conn",
        "_corruption_details",
        "_corruption_reporter",
        "_lock",
        "_loop_thread",
        "_open_lock",
        "_read_conn",
        "_read_lock",
        "_use_separate_read_conn",
    )

    def __init__(
        self,
        db_path: Path,
        *,
        corruption_reporter: Callable[[str], None] | None = None,
    ) -> None:
        self.db_path = db_path
        self._corruption_reporter = corruption_reporter
        self._corruption_details: str | None = None
        self._lock = threading.Lock()
        self._open_lock = threading.Lock()
        self._read_lock = threading.Lock()
        self._use_separate_read_conn = str(db_path) != ":memory:"
        self._conn: aiosqlite.Connection | None = None
        self._read_conn: aiosqlite.Connection | None = None
        self._loop_thread: _EngineLoopThread | None = None

    def _ensure_loop_thread(self) -> _EngineLoopThread:
        if self._loop_thread is None:
            self._loop_thread = _EngineLoopThread()
        return self._loop_thread

    def _run_on_engine_loop(self, coro: Awaitable[_T]) -> _T:
        """Run *coro* on the engine's dedicated loop; safe from any caller thread.

        Sync callers block on the result. Async callers on a different loop should
        await via :py:meth:`_await_on_engine_loop` instead.
        """
        return self._ensure_loop_thread().run_sync(coro)

    async def _await_on_engine_loop(self, coro: Awaitable[_T]) -> _T:
        """Await *coro* from an external loop while executing it on the engine loop."""
        loop_thread = self._ensure_loop_thread()
        caller_loop = _current_loop()
        if caller_loop is loop_thread.loop:
            return await coro
        future = asyncio.run_coroutine_threadsafe(cast(Any, coro), loop_thread.loop)
        return cast(_T, await asyncio.wrap_future(future))

    @staticmethod
    async def _configure_connection(conn: aiosqlite.Connection, *, read_only: bool) -> None:
        await conn.execute("PRAGMA journal_mode=WAL")
        if not read_only:
            await conn.execute("PRAGMA wal_autocheckpoint=500")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA busy_timeout=5000")
        if read_only:
            await conn.execute("PRAGMA query_only=ON")

    def open(self) -> None:
        self._run_on_engine_loop(self._aopen_impl())

    async def aopen(self) -> None:
        await self._await_on_engine_loop(self._aopen_impl())

    async def _aopen_impl(self) -> None:
        async with _async_lock_context(self._open_lock):
            if self._conn is not None:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
            read_conn: aiosqlite.Connection | None = None
            try:
                await self._configure_connection(conn, read_only=False)
                self._conn = conn
                await self._ensure_schema()
                await self._run_startup_quick_check()
                if self._use_separate_read_conn:
                    read_conn = await aiosqlite.connect(self.db_path, check_same_thread=False)
                    await self._configure_connection(read_conn, read_only=True)
                self._read_conn = read_conn
            except aiosqlite.Error:
                self._conn = None
                if read_conn is not None:
                    await read_conn.close()
                await conn.close()
                raise

    def close(self) -> None:
        self._run_on_engine_loop(self._aclose_impl())
        if self._loop_thread is not None:
            self._loop_thread.stop()
            self._loop_thread = None

    async def aclose(self) -> None:
        await self._await_on_engine_loop(self._aclose_impl())
        if self._loop_thread is not None:
            loop_thread = self._loop_thread
            self._loop_thread = None
            await asyncio.to_thread(loop_thread.stop)

    async def _aclose_impl(self) -> None:
        async with _async_lock_context(self._lock):
            if self._conn is not None:
                await self._conn.close()
                self._conn = None
        async with _async_lock_context(self._read_lock):
            if self._read_conn is not None:
                await self._read_conn.close()
                self._read_conn = None

    def _cursor_connection(
        self,
        *,
        commit: bool,
    ) -> tuple[aiosqlite.Connection | None, object]:
        if not commit and self._read_conn is not None:
            return self._read_conn, self._read_lock
        return self._conn, self._lock

    @asynccontextmanager
    async def _cursor(self, *, commit: bool = True) -> AsyncIterator[aiosqlite.Cursor]:
        conn, lock = self._cursor_connection(commit=commit)
        async with _async_lock_context(lock):
            if conn is None:
                raise RuntimeError("HistoryDB is closed")
            if commit:
                self._assert_write_allowed()
            cur = await conn.cursor()
            completed = False
            try:
                yield cur
                if commit:
                    await conn.commit()
                completed = True
            finally:
                if not completed:
                    await self._rollback_transaction(conn, context="_cursor")
                await cur.close()

    @asynccontextmanager
    async def write_transaction_cursor(self) -> AsyncIterator[aiosqlite.Cursor]:
        """Run a multi-step write sequence as one explicit transaction."""
        async with _async_lock_context(self._lock):
            if self._conn is None:
                raise RuntimeError("HistoryDB is closed")
            self._assert_write_allowed()
            cur = await self._conn.cursor()
            completed = False
            try:
                await cur.execute("BEGIN IMMEDIATE")
                yield cur
                await self._conn.commit()
                completed = True
            finally:
                if not completed:
                    await self._rollback_transaction(self._conn, context="write_transaction_cursor")
                await cur.close()

    @property
    def corruption_detected(self) -> bool:
        return self._corruption_details is not None

    @property
    def corruption_details(self) -> str | None:
        return self._corruption_details

    def _assert_write_allowed(self) -> None:
        if self._corruption_details is None:
            return
        raise aiosqlite.DatabaseError(
            "History DB quick_check reported corruption for "
            f"{self.db_path}: {self._corruption_details}. Writes are disabled until "
            "the database is repaired or replaced."
        )

    def _mark_corrupted(self, details: str) -> None:
        self._corruption_details = details
        if self._corruption_reporter is not None:
            self._corruption_reporter(details)

    async def _rollback_transaction(self, conn: aiosqlite.Connection, *, context: str) -> None:
        if not conn.in_transaction:
            return
        try:
            await conn.rollback()
        except aiosqlite.Error:
            LOGGER.critical("History DB rollback failed during %s", context, exc_info=True)

    async def _ensure_schema(self) -> None:
        async with self._cursor() as cur:
            await cur.executescript(SCHEMA_SQL)

        version = await self._schema_version()

        if version == 0:
            async with self._cursor(commit=False) as cur:
                await cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_meta'"
                )
                if await cur.fetchone() is not None:
                    raise RuntimeError(
                        f"Database at {self.db_path} uses a legacy "
                        "schema_meta table incompatible with the current "
                        f"v{SCHEMA_VERSION} format. Delete it to recreate."
                    )
            async with self._cursor() as cur:
                await cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return

        if version == SCHEMA_VERSION:
            return
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"History DB schema version {version} is newer than "
                f"supported {SCHEMA_VERSION}. Delete {self.db_path} to recreate it.",
            )
        raise RuntimeError(
            f"Database schema v{version} is incompatible with current v{SCHEMA_VERSION}. "
            f"Delete the database file at {self.db_path} to recreate it."
        )

    async def _schema_version(self) -> int:
        async with self._cursor(commit=False) as cur:
            await cur.execute("PRAGMA user_version")
            row = await cur.fetchone()
        return int(row[0]) if row is not None else 0

    async def _run_startup_quick_check(self) -> None:
        await run_startup_quick_check(
            cursor_provider=self._cursor,
            db_path=self.db_path,
            mark_corrupted=self._mark_corrupted,
        )
