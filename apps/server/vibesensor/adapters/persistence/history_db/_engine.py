"""Shared SQLite lifecycle/engine utilities for history persistence adapters."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import sqlite3
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, cast

import aiosqlite

from vibesensor.adapters.persistence.history_db._schema import (
    SCHEMA_SQL,
    SCHEMA_VERSION,
)
from vibesensor.shared.json_utils import json_text_dumps

LOGGER = logging.getLogger(__name__)

__all__ = ["HistoryDbEngineTimeoutError", "SQLiteHistoryEngine", "run_startup_quick_check"]

_T = TypeVar("_T")
_ENGINE_OPERATION_TIMEOUT_S = 10.0
_ENGINE_OPEN_TIMEOUT_S = 30.0
_ENGINE_SCHEMA_CHECK_TIMEOUT_S = 30.0
_ENGINE_QUICK_CHECK_TIMEOUT_S = 10.0
_ENGINE_CLOSE_TIMEOUT_S = 5.0
_ENGINE_SHUTDOWN_TIMEOUT_S = 5.0
_THREAD_LOCK_ACQUIRE_SLICE_S = 0.05


class HistoryDbEngineTimeoutError(TimeoutError):
    """Raised when a history DB operation outlives its engine-loop budget."""


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

    def run_sync(
        self,
        coro: Awaitable[_T],
        *,
        timeout_s: float,
        operation: str,
    ) -> _T:
        future = asyncio.run_coroutine_threadsafe(cast(Any, coro), self._loop)
        try:
            return cast(_T, future.result(timeout=timeout_s))
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise HistoryDbEngineTimeoutError(
                f"History DB engine operation '{operation}' timed out after {timeout_s:.2f}s"
            ) from exc

    def stop(self, *, timeout_s: float) -> bool:
        if self._loop.is_closed():
            return True
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=timeout_s)
        if self._thread.is_alive():
            return False
        if not self._loop.is_closed():
            self._loop.close()
        return True


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
        while True:
            acquire_attempt = asyncio.create_task(
                asyncio.to_thread(manager.acquire, True, _THREAD_LOCK_ACQUIRE_SLICE_S)
            )
            try:
                acquired = await acquire_attempt
            except asyncio.CancelledError:
                acquired = await acquire_attempt
                if acquired:
                    manager.release()
                raise
            if acquired:
                break
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
        "_engine_failure_reporter",
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
        engine_failure_reporter: Callable[[str, str], None] | None = None,
    ) -> None:
        self.db_path = db_path
        self._corruption_reporter = corruption_reporter
        self._engine_failure_reporter = engine_failure_reporter
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

    def _mark_engine_failure(self, reason: str, details: str) -> None:
        LOGGER.critical("History DB engine %s: %s", reason, details)
        if self._engine_failure_reporter is not None:
            self._engine_failure_reporter(reason, details)

    def _run_on_engine_loop(
        self,
        coro: Awaitable[_T],
        *,
        timeout_s: float = _ENGINE_OPERATION_TIMEOUT_S,
        operation: str = "operation",
    ) -> _T:
        """Run *coro* on the engine's dedicated loop; safe from any caller thread.

        Sync callers block on the result. Async callers on a different loop should
        await via :py:meth:`_await_on_engine_loop` instead.
        """
        try:
            return self._ensure_loop_thread().run_sync(
                coro,
                timeout_s=timeout_s,
                operation=operation,
            )
        except HistoryDbEngineTimeoutError as exc:
            self._mark_engine_failure(f"{operation}_timeout", str(exc))
            raise

    async def _await_on_engine_loop(
        self,
        coro: Awaitable[_T],
        *,
        timeout_s: float = _ENGINE_OPERATION_TIMEOUT_S,
        operation: str = "operation",
    ) -> _T:
        """Await *coro* from an external loop while executing it on the engine loop."""
        loop_thread = self._ensure_loop_thread()
        caller_loop = _current_loop()
        try:
            if caller_loop is loop_thread.loop:
                return await asyncio.wait_for(coro, timeout=timeout_s)
            future = asyncio.run_coroutine_threadsafe(cast(Any, coro), loop_thread.loop)
            try:
                return cast(
                    _T,
                    await asyncio.wait_for(
                        asyncio.shield(asyncio.wrap_future(future)),
                        timeout=timeout_s,
                    ),
                )
            except TimeoutError:
                future.cancel()
                raise
        except TimeoutError as exc:
            timeout_error = HistoryDbEngineTimeoutError(
                f"History DB engine operation '{operation}' timed out after {timeout_s:.2f}s"
            )
            self._mark_engine_failure(f"{operation}_timeout", str(timeout_error))
            raise timeout_error from exc

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
        self._run_on_engine_loop(
            self._aopen_impl(),
            timeout_s=_ENGINE_OPEN_TIMEOUT_S,
            operation="open",
        )

    async def aopen(self) -> None:
        await self._await_on_engine_loop(
            self._aopen_impl(),
            timeout_s=_ENGINE_OPEN_TIMEOUT_S,
            operation="open",
        )

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
                await self._with_engine_timeout(
                    self._ensure_schema(),
                    timeout_s=_ENGINE_SCHEMA_CHECK_TIMEOUT_S,
                    operation="schema_check",
                )
                await self._with_engine_timeout(
                    self._run_startup_quick_check(),
                    timeout_s=_ENGINE_QUICK_CHECK_TIMEOUT_S,
                    operation="startup_quick_check",
                )
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

    async def _with_engine_timeout(
        self,
        coro: Awaitable[_T],
        *,
        timeout_s: float,
        operation: str,
    ) -> _T:
        try:
            return await asyncio.wait_for(coro, timeout=timeout_s)
        except TimeoutError as exc:
            timeout_error = HistoryDbEngineTimeoutError(
                f"History DB engine operation '{operation}' timed out after {timeout_s:.2f}s"
            )
            self._mark_engine_failure(f"{operation}_timeout", str(timeout_error))
            raise timeout_error from exc

    def close(self) -> None:
        try:
            self._run_on_engine_loop(
                self._aclose_impl(),
                timeout_s=_ENGINE_CLOSE_TIMEOUT_S,
                operation="close",
            )
        finally:
            self._stop_loop_thread()

    async def aclose(self) -> None:
        try:
            await self._await_on_engine_loop(
                self._aclose_impl(),
                timeout_s=_ENGINE_CLOSE_TIMEOUT_S,
                operation="close",
            )
        finally:
            await asyncio.to_thread(self._stop_loop_thread)

    def _stop_loop_thread(self) -> None:
        if self._loop_thread is None:
            return
        stopped = self._loop_thread.stop(timeout_s=_ENGINE_SHUTDOWN_TIMEOUT_S)
        if stopped:
            self._loop_thread = None
            return
        self._mark_engine_failure(
            "shutdown_timeout",
            (
                "History DB engine loop did not stop within "
                f"{_ENGINE_SHUTDOWN_TIMEOUT_S:.2f}s; leaving loop open"
            ),
        )

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

    async def _user_table_names(self) -> set[str]:
        async with self._cursor(commit=False) as cur:
            await cur.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            )
            return {str(row[0]) for row in await cur.fetchall()}

    def _protect_incompatible_database(
        self,
        *,
        version: int,
        reason: str,
    ) -> tuple[Path, Path | None]:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = self.db_path.parent / "history-db-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stem = self.db_path.stem or "history"
        backup_path = backup_dir / f"{stem}.incompatible-v{version}-{reason}-{timestamp}.db"
        summary_export_path = (
            backup_dir / f"{stem}.incompatible-v{version}-{reason}-{timestamp}.run-summaries.jsonl"
        )

        source_conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        backup_conn = sqlite3.connect(str(backup_path))
        try:
            source_conn.backup(backup_conn)
        finally:
            backup_conn.close()
            source_conn.close()

        exported_summary = self._export_incompatible_run_summaries(
            backup_path=backup_path,
            summary_export_path=summary_export_path,
        )
        return backup_path, exported_summary

    @staticmethod
    def _export_incompatible_run_summaries(
        *,
        backup_path: Path,
        summary_export_path: Path,
    ) -> Path | None:
        conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
        try:
            table_names = {
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    """
                )
            }
            if "runs" not in table_names:
                return None
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(runs)")}
            export_columns = [
                column
                for column in (
                    "run_id",
                    "status",
                    "start_time_utc",
                    "end_time_utc",
                    "created_at",
                    "analysis_completed_at",
                    "sample_count",
                    "error_message",
                    "metadata_json",
                    "analysis_json",
                )
                if column in columns
            ]
            if "run_id" not in export_columns:
                return None
            order_column = next(
                (
                    column
                    for column in ("analysis_completed_at", "end_time_utc", "created_at", "run_id")
                    if column in columns
                ),
                "run_id",
            )
            rows = conn.execute(
                f"SELECT {', '.join(export_columns)} FROM runs ORDER BY {order_column} DESC"
            ).fetchall()
        finally:
            conn.close()

        with summary_export_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                payload = {column: row[index] for index, column in enumerate(export_columns)}
                handle.write(json_text_dumps(payload, sort_keys=True))
                handle.write("\n")
        return summary_export_path

    async def _raise_incompatible_database(
        self,
        *,
        version: int,
        reason: str,
        message: str,
    ) -> None:
        try:
            backup_path, summary_export_path = await asyncio.to_thread(
                self._protect_incompatible_database,
                version=version,
                reason=reason,
            )
        except Exception as exc:
            raise RuntimeError(
                f"{message} Automatic backup before rejection failed for {self.db_path}: {exc}. "
                "The database was left untouched; keep it and back it up manually before any reset."
            ) from exc
        export_note = (
            f" Run-summary export written to {summary_export_path}."
            if summary_export_path is not None
            else " Run-summary export was not available for this schema."
        )
        raise RuntimeError(f"{message} Backup written to {backup_path}.{export_note}")

    async def _rollback_transaction(self, conn: aiosqlite.Connection, *, context: str) -> None:
        if not conn.in_transaction:
            return
        try:
            await conn.rollback()
        except aiosqlite.Error:
            LOGGER.critical("History DB rollback failed during %s", context, exc_info=True)

    async def _ensure_schema(self) -> None:
        version = await self._schema_version()

        if version == 0:
            user_tables = await self._user_table_names()
            if "schema_meta" in user_tables:
                await self._raise_incompatible_database(
                    version=version,
                    reason="legacy-schema-meta",
                    message=(
                        f"Database at {self.db_path} uses a legacy schema_meta table "
                        f"incompatible with the current v{SCHEMA_VERSION} format."
                    ),
                )
            if user_tables:
                await self._raise_incompatible_database(
                    version=version,
                    reason="unexpected-user-tables",
                    message=(
                        f"Database at {self.db_path} has user tables but no schema version and is "
                        f"incompatible with the current v{SCHEMA_VERSION} format."
                    ),
                )
            async with self._cursor() as cur:
                await cur.executescript(SCHEMA_SQL)
                await cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return

        if version == SCHEMA_VERSION:
            async with self._cursor() as cur:
                await cur.executescript(SCHEMA_SQL)
            return
        if version > SCHEMA_VERSION:
            await self._raise_incompatible_database(
                version=version,
                reason="newer-schema",
                message=(
                    f"History DB schema version {version} is newer than supported {SCHEMA_VERSION}."
                ),
            )
        await self._raise_incompatible_database(
            version=version,
            reason="unsupported-schema",
            message=(f"Database schema v{version} is incompatible with current v{SCHEMA_VERSION}."),
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
