"""Shared SQLite lifecycle/engine utilities for history persistence adapters."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from threading import RLock

from vibesensor.adapters.persistence.history_db._schema import (
    SCHEMA_SQL,
    SCHEMA_VERSION,
)

LOGGER = logging.getLogger(__name__)

__all__ = ["SQLiteHistoryEngine"]


def run_startup_quick_check(
    *,
    cursor_provider: Callable[..., AbstractContextManager[sqlite3.Cursor]],
    db_path: Path,
    mark_corrupted: Callable[[str], None],
) -> None:
    try:
        with cursor_provider(commit=False) as cur:
            cur.execute("PRAGMA quick_check")
            problems = [str(row[0]) for row in cur.fetchall() if str(row[0]) != "ok"]
    except sqlite3.Error:
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
        self._lock = RLock()
        self._read_lock = RLock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._use_separate_read_conn = str(db_path) != ":memory:"
        self._conn: sqlite3.Connection | None = sqlite3.connect(db_path, check_same_thread=False)
        self._read_conn: sqlite3.Connection | None = None
        try:
            self._configure_connection(self._conn, read_only=False)
            self._ensure_schema()
            self._run_startup_quick_check()
            if self._use_separate_read_conn:
                self._read_conn = sqlite3.connect(db_path, check_same_thread=False)
                self._configure_connection(self._read_conn, read_only=True)
        except sqlite3.Error:
            if self._read_conn is not None:
                self._read_conn.close()
            self._conn.close()
            raise

    @staticmethod
    def _configure_connection(conn: sqlite3.Connection, *, read_only: bool) -> None:
        conn.execute("PRAGMA journal_mode=WAL")
        if not read_only:
            conn.execute("PRAGMA wal_autocheckpoint=500")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        if read_only:
            conn.execute("PRAGMA query_only=ON")

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
        with self._read_lock:
            if self._read_conn is not None:
                self._read_conn.close()
                self._read_conn = None

    def _cursor_connection(
        self,
        *,
        commit: bool,
    ) -> tuple[sqlite3.Connection | None, RLock]:
        if not commit and self._read_conn is not None:
            return self._read_conn, self._read_lock
        return self._conn, self._lock

    @contextmanager
    def _cursor(self, *, commit: bool = True) -> Iterator[sqlite3.Cursor]:
        conn, lock = self._cursor_connection(commit=commit)
        with lock:
            if conn is None:
                raise RuntimeError("HistoryDB is closed")
            if commit:
                self._assert_write_allowed()
            cur = conn.cursor()
            completed = False
            try:
                yield cur
                if commit:
                    conn.commit()
                completed = True
            finally:
                if not completed:
                    self._rollback_transaction(conn, context="_cursor")
                cur.close()

    @contextmanager
    def write_transaction_cursor(self) -> Iterator[sqlite3.Cursor]:
        """Run a multi-step write sequence as one explicit transaction."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("HistoryDB is closed")
            self._assert_write_allowed()
            cur = self._conn.cursor()
            completed = False
            try:
                cur.execute("BEGIN IMMEDIATE")
                yield cur
                self._conn.commit()
                completed = True
            finally:
                if not completed:
                    self._rollback_transaction(self._conn, context="write_transaction_cursor")
                cur.close()

    @property
    def corruption_detected(self) -> bool:
        return self._corruption_details is not None

    @property
    def corruption_details(self) -> str | None:
        return self._corruption_details

    def _assert_write_allowed(self) -> None:
        if self._corruption_details is None:
            return
        raise sqlite3.DatabaseError(
            "History DB quick_check reported corruption for "
            f"{self.db_path}: {self._corruption_details}. Writes are disabled until "
            "the database is repaired or replaced."
        )

    def _mark_corrupted(self, details: str) -> None:
        self._corruption_details = details
        if self._corruption_reporter is not None:
            self._corruption_reporter(details)

    def _rollback_transaction(self, conn: sqlite3.Connection, *, context: str) -> None:
        if not conn.in_transaction:
            return
        try:
            conn.rollback()
        except sqlite3.Error:
            LOGGER.critical("History DB rollback failed during %s", context, exc_info=True)

    def _ensure_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript(SCHEMA_SQL)

        version = self._schema_version()

        if version == 0:
            with self._cursor(commit=False) as cur:
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_meta'"
                )
                if cur.fetchone() is not None:
                    raise RuntimeError(
                        f"Database at {self.db_path} uses a legacy "
                        "schema_meta table incompatible with the current "
                        f"v{SCHEMA_VERSION} format. Delete it to recreate."
                    )
            with self._cursor() as cur:
                cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
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

    def _schema_version(self) -> int:
        with self._cursor(commit=False) as cur:
            cur.execute("PRAGMA user_version")
            row = cur.fetchone()
        return int(row[0]) if row is not None else 0

    def _run_startup_quick_check(self) -> None:
        run_startup_quick_check(
            cursor_provider=self._cursor,
            db_path=self.db_path,
            mark_corrupted=self._mark_corrupted,
        )
