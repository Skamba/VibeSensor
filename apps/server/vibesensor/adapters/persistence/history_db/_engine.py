"""Shared SQLite lifecycle/engine utilities for history persistence adapters."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, cast

import aiosqlite

from vibesensor.adapters.persistence.history_db._schema import (
    SCHEMA_SQL,
    SCHEMA_VERSION,
)
from vibesensor.shared.async_bridge import run_coro_blocking

LOGGER = logging.getLogger(__name__)

__all__ = ["SQLiteHistoryEngine"]


class _DualContextManager[CursorT]:
    """Context manager that supports both ``with`` and ``async with``."""

    __slots__ = ("_manager",)

    def __init__(self, manager: object) -> None:
        self._manager = manager

    def __enter__(self) -> CursorT:
        manager = cast(Any, self._manager)
        if hasattr(manager, "__aenter__"):
            result = run_coro_blocking(cast(Awaitable[CursorT], manager.__aenter__()))
        else:
            result = cast(CursorT, manager.__enter__())
        return _syncify_result(result)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        manager = cast(Any, self._manager)
        if hasattr(manager, "__aexit__"):
            return run_coro_blocking(
                cast(Awaitable[bool | None], manager.__aexit__(exc_type, exc, tb))
            )
        return cast(bool | None, manager.__exit__(exc_type, exc, tb))

    async def __aenter__(self) -> CursorT:
        manager = cast(Any, self._manager)
        if hasattr(manager, "__aenter__"):
            return cast(CursorT, await manager.__aenter__())
        return _asyncify_result(cast(CursorT, manager.__enter__()))

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        manager = cast(Any, self._manager)
        if hasattr(manager, "__aexit__"):
            return cast(bool | None, await manager.__aexit__(exc_type, exc, tb))
        return cast(bool | None, manager.__exit__(exc_type, exc, tb))


class _SyncCursorProxy:
    """Expose awaitable cursor methods through a synchronous API."""

    __slots__ = ("_cursor",)

    def __init__(self, cursor: object) -> None:
        self._cursor = cursor

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._cursor, name)
        if not callable(attr):
            return attr

        def _wrapped(*args: object, **kwargs: object) -> Any:
            result = attr(*args, **kwargs)
            if inspect.isawaitable(result):
                return run_coro_blocking(result)
            return result

        return _wrapped


class _AsyncCursorProxy:
    """Expose synchronous cursor methods through an awaitable API."""

    __slots__ = ("_cursor",)

    def __init__(self, cursor: object) -> None:
        self._cursor = cursor

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._cursor, name)
        if not callable(attr):
            return attr

        async def _wrapped(*args: object, **kwargs: object) -> Any:
            result = attr(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        return _wrapped


def _syncify_result[ResultT](value: ResultT) -> ResultT:
    if value is None:
        return value
    if hasattr(value, "execute") and (hasattr(value, "fetchone") or hasattr(value, "fetchall")):
        return cast(ResultT, _SyncCursorProxy(value))
    return value


def _asyncify_result[ResultT](value: ResultT) -> ResultT:
    if value is None:
        return value
    if hasattr(value, "execute") and (hasattr(value, "fetchone") or hasattr(value, "fetchall")):
        return cast(ResultT, _AsyncCursorProxy(value))
    return value


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
        async with _DualContextManager[aiosqlite.Cursor](cursor_provider(commit=False)) as cur:
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
        run_coro_blocking(self.aopen())

    async def aopen(self) -> None:
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
                await self._run_startup_quick_check_async()
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
        run_coro_blocking(self.aclose())

    async def aclose(self) -> None:
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
    async def _cursor_async(self, *, commit: bool = True) -> AsyncIterator[aiosqlite.Cursor]:
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

    def _cursor(self, *, commit: bool = True) -> _DualContextManager[aiosqlite.Cursor]:
        return _DualContextManager(self._cursor_async(commit=commit))

    @asynccontextmanager
    async def write_transaction_cursor_async(self) -> AsyncIterator[aiosqlite.Cursor]:
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

    def write_transaction_cursor(self) -> _DualContextManager[aiosqlite.Cursor]:
        return _DualContextManager(self.write_transaction_cursor_async())

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

    def _run_startup_quick_check(self) -> None:
        run_coro_blocking(self._run_startup_quick_check_async())

    async def _run_startup_quick_check_async(self) -> None:
        await run_startup_quick_check(
            cursor_provider=self._cursor,
            db_path=self.db_path,
            mark_corrupted=self._mark_corrupted,
        )
