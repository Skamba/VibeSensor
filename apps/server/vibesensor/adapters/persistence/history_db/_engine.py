"""Shared SQLite lifecycle/engine utilities for history persistence adapters."""

from __future__ import annotations

import asyncio
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
from vibesensor.shared.boundaries.codecs.scalars import text_or_none
from vibesensor.shared.json_utils import json_text_dumps, safe_json_loads
from vibesensor.shared.types.json_types import is_json_object

LOGGER = logging.getLogger(__name__)

__all__ = ["SQLiteHistoryEngine", "run_startup_quick_check"]

_T = TypeVar("_T")


def _extract_run_car_name(metadata_json: object) -> str | None:
    parsed = safe_json_loads(
        str(metadata_json) if metadata_json is not None else None,
        context="history_db v11->v12 car_name migration",
    )
    if not is_json_object(parsed):
        return None
    active_car_snapshot = parsed.get("active_car_snapshot")
    if is_json_object(active_car_snapshot):
        nested_name = text_or_none(active_car_snapshot.get("name"))
        if nested_name:
            return nested_name
    return text_or_none(parsed.get("car_name"))


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
        if version == 11:
            await self._migrate_v11_to_v12()
            await self._migrate_v12_to_v13()
            await self._migrate_v13_to_v14()
            await self._migrate_v14_to_v15()
            async with self._cursor() as cur:
                await cur.executescript(SCHEMA_SQL)
            return
        if version == 12:
            await self._migrate_v12_to_v13()
            await self._migrate_v13_to_v14()
            await self._migrate_v14_to_v15()
            async with self._cursor() as cur:
                await cur.executescript(SCHEMA_SQL)
            return
        if version == 13:
            await self._migrate_v13_to_v14()
            await self._migrate_v14_to_v15()
            async with self._cursor() as cur:
                await cur.executescript(SCHEMA_SQL)
            return
        if version == 14:
            await self._migrate_v14_to_v15()
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

    async def _migrate_v11_to_v12(self) -> None:
        LOGGER.info("Migrating history DB schema v11 -> v12")
        async with self._cursor(commit=False) as cur:
            await cur.execute("PRAGMA table_info(runs)")
            columns = {str(row[1]) for row in await cur.fetchall()}
        if "car_name" not in columns:
            async with self._cursor() as cur:
                await cur.execute("ALTER TABLE runs ADD COLUMN car_name TEXT")
        async with self.write_transaction_cursor() as cur:
            await cur.execute("SELECT run_id, metadata_json FROM runs WHERE car_name IS NULL")
            rows = await cur.fetchall()
            if rows:
                await cur.executemany(
                    "UPDATE runs SET car_name = ? WHERE run_id = ?",
                    [
                        (_extract_run_car_name(metadata_json), str(run_id))
                        for run_id, metadata_json in rows
                    ],
                )
            await cur.execute("PRAGMA user_version = 12")

    async def _migrate_v12_to_v13(self) -> None:
        LOGGER.info("Migrating history DB schema v12 -> v13")
        async with self._cursor(commit=False) as cur:
            await cur.execute("PRAGMA table_info(runs)")
            columns = {str(row[1]) for row in await cur.fetchall()}
        if "raw_capture_manifest_json" not in columns:
            async with self._cursor() as cur:
                await cur.execute("ALTER TABLE runs ADD COLUMN raw_capture_manifest_json TEXT")
        async with self._cursor() as cur:
            await cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    async def _migrate_v13_to_v14(self) -> None:
        LOGGER.info("Migrating history DB schema v13 -> v14")
        async with self._cursor(commit=False) as cur:
            await cur.execute("PRAGMA table_info(runs)")
            columns = {str(row[1]) for row in await cur.fetchall()}
        if "whole_run_artifact_manifest_json" not in columns:
            async with self._cursor() as cur:
                await cur.execute(
                    "ALTER TABLE runs ADD COLUMN whole_run_artifact_manifest_json TEXT"
                )
        async with self._cursor() as cur:
            await cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    async def _migrate_v14_to_v15(self) -> None:
        LOGGER.info("Migrating history DB schema v14 -> v15")
        async with self._cursor(commit=False) as cur:
            await cur.execute("PRAGMA table_info(samples_v2)")
            columns = {str(row[1]) for row in await cur.fetchall()}
        if "analysis_window_start_us" not in columns:
            async with self._cursor() as cur:
                await cur.execute(
                    "ALTER TABLE samples_v2 ADD COLUMN analysis_window_start_us INTEGER"
                )
        if "analysis_window_end_us" not in columns:
            async with self._cursor() as cur:
                await cur.execute(
                    "ALTER TABLE samples_v2 ADD COLUMN analysis_window_end_us INTEGER"
                )
        if "analysis_window_synced" not in columns:
            async with self._cursor() as cur:
                await cur.execute(
                    "ALTER TABLE samples_v2 ADD COLUMN analysis_window_synced INTEGER"
                )
        async with self._cursor() as cur:
            await cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    async def _run_startup_quick_check(self) -> None:
        await run_startup_quick_check(
            cursor_provider=self._cursor,
            db_path=self.db_path,
            mark_corrupted=self._mark_corrupted,
        )
