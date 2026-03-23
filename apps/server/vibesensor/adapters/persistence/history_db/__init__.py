"""SQLite-backed persistence for the VibeSensor server.

``HistoryDB`` remains the public entry point while internal lifecycle,
sample-I/O, and query helpers live in focused sibling modules.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from vibesensor.adapters.persistence.history_db._queries import _HistoryDBQueryMixin
from vibesensor.adapters.persistence.history_db._run_lifecycle import _HistoryDBRunLifecycleMixin
from vibesensor.adapters.persistence.history_db._sample_io import _HistoryDBSampleIOMixin
from vibesensor.adapters.persistence.history_db._schema import (
    SCHEMA_SQL,
    SCHEMA_VERSION,
)
from vibesensor.shared.boundaries.settings_snapshot import settings_snapshot_from_payload
from vibesensor.shared.json_utils import safe_json_dumps, safe_json_loads
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.backend_types import SettingsSnapshotPayload
from vibesensor.shared.types.json_types import is_json_object

# Re-export for public API.
__all__ = ["HistoryDB"]

LOGGER = logging.getLogger(__name__)

_CASE_ID_MIGRATION_SOURCE_VERSION = 8


class HistoryDB(_HistoryDBRunLifecycleMixin, _HistoryDBSampleIOMixin, _HistoryDBQueryMixin):
    """Thin wrapper around a SQLite database for run history."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
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

    # -- lifecycle ------------------------------------------------------------

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
            cur = conn.cursor()
            try:
                yield cur
                if commit:
                    conn.commit()
            except sqlite3.Error:
                if conn.in_transaction:
                    conn.rollback()
                raise
            finally:
                cur.close()

    @contextmanager
    def write_transaction_cursor(self) -> Iterator[sqlite3.Cursor]:
        """Run a multi-step write sequence as one explicit transaction."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("HistoryDB is closed")
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                yield cur
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    # -- schema ---------------------------------------------------------------

    def _ensure_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript(SCHEMA_SQL)

        with self._cursor(commit=False) as cur:
            cur.execute("PRAGMA user_version")
            version = cur.fetchone()[0]

        if version == 0:
            # Check for legacy schema_meta table (pre-v5 databases).
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
            # Fresh database — stamp with current version.
            with self._cursor() as cur:
                cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return

        if version == SCHEMA_VERSION:
            return
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"History DB schema version {version} is newer than "
                f"supported {SCHEMA_VERSION}. Cannot downgrade.",
            )
        if version == _CASE_ID_MIGRATION_SOURCE_VERSION:
            self._migrate_v8_to_v9_case_id()
            version = 9
        if version == 9:
            self._migrate_v9_to_v10_settings_table()
            return
        msg = (
            f"Database schema v{version} is incompatible with "
            f"current v{SCHEMA_VERSION}. "
            f"Delete the database file at {self.db_path} to recreate it."
        )
        raise RuntimeError(msg)

    @staticmethod
    def _has_runs_column(cur: sqlite3.Cursor, column_name: str) -> bool:
        cur.execute("PRAGMA table_info(runs)")
        return any(str(row[1]) == column_name for row in cur.fetchall())

    def _migrate_v8_to_v9_case_id(self) -> None:
        LOGGER.info("Migrating history DB at %s from schema v8 to v9", self.db_path)
        with self._cursor() as cur:
            if not self._has_runs_column(cur, "case_id"):
                cur.execute("ALTER TABLE runs ADD COLUMN case_id TEXT")

            cur.execute(
                "SELECT run_id, analysis_json FROM runs "
                "WHERE case_id IS NULL AND analysis_json IS NOT NULL"
            )
            updates: list[tuple[str, str]] = []
            for run_id, analysis_json in cur.fetchall():
                parsed_analysis = safe_json_loads(
                    analysis_json,
                    context=f"run {run_id} analysis during schema migration",
                )
                if not is_json_object(parsed_analysis):
                    continue
                case_id = parsed_analysis.get("case_id")
                if isinstance(case_id, str) and case_id.strip():
                    updates.append((case_id, str(run_id)))

            if updates:
                cur.executemany(
                    "UPDATE runs SET case_id = ? WHERE run_id = ? AND case_id IS NULL",
                    updates,
                )

            cur.execute("PRAGMA user_version = 9")

    def _migrate_v9_to_v10_settings_table(self) -> None:
        LOGGER.info("Migrating history DB at %s from schema v9 to v10", self.db_path)
        with self._cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS settings_snapshot ("
                "id INTEGER PRIMARY KEY CHECK(id = 1), "
                "value_json TEXT NOT NULL, "
                "updated_at TEXT NOT NULL)"
            )
            cur.execute(
                "INSERT OR IGNORE INTO settings_snapshot (id, value_json, updated_at) "
                "SELECT 1, value_json, updated_at FROM settings_kv "
                "WHERE key = 'settings_snapshot'"
            )
            cur.execute("DROP TABLE IF EXISTS settings_kv")
            cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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
            LOGGER.critical(
                "History DB quick_check reported corruption for %s: %s",
                self.db_path,
                "; ".join(problems),
            )

    # -- settings_snapshot persistence -----------------------------------------

    def get_settings_snapshot(self) -> SettingsSnapshotPayload | None:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT value_json FROM settings_snapshot WHERE id = 1")
            row = cur.fetchone()
        if row is None:
            return None
        snapshot = safe_json_loads(row[0], context="settings_snapshot")
        return settings_snapshot_from_payload(snapshot) if is_json_object(snapshot) else None

    def set_settings_snapshot(self, snapshot: SettingsSnapshotPayload) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings_snapshot (id, value_json, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (safe_json_dumps(snapshot), now),
            )

    # -- client_names persistence ---------------------------------------------

    def list_client_names(self) -> dict[str, str]:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT client_id, name FROM client_names")
            rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}

    def upsert_client_name(self, client_id: str, name: str) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO client_names (client_id, name, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(client_id) DO UPDATE SET name = excluded.name, "
                "updated_at = excluded.updated_at",
                (client_id, name, now),
            )

    def delete_client_name(self, client_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM client_names WHERE client_id = ?", (client_id,))
            return bool(int(cur.rowcount) > 0)
