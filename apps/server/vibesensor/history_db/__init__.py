"""SQLite-backed persistence for the VibeSensor server.

Stores run history (metadata, samples, analysis), application settings
and client names in a single file – lightweight enough for a
Raspberry Pi 3A+.

Schema v5 stores time-series samples as typed columns in ``samples_v2``,
providing fast write/read and compact storage on Raspberry Pi class
hardware.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from ..json_types import JsonObject, JsonValue, is_json_object
from ..json_utils import safe_json_dumps, safe_json_loads
from ..runlog import utc_now_iso
from ._run_reads import HistoryRunReadMixin
from ._run_writes import HistoryRunWriteMixin
from ._schema import ANALYSIS_SCHEMA_VERSION as ANALYSIS_SCHEMA_VERSION
from ._schema import HistorySchemaMixin
from ._schema import RunStatus as RunStatus

LOGGER = logging.getLogger(__name__)


class HistoryDB(
    HistoryRunWriteMixin,
    HistoryRunReadMixin,
    HistorySchemaMixin,
):
    """Thin wrapper around a SQLite database for run history."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = RLock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = sqlite3.connect(db_path, check_same_thread=False)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA wal_autocheckpoint=500")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._ensure_schema()
        except sqlite3.Error:
            self._conn.close()
            raise

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @contextmanager
    def _cursor(self, *, commit: bool = True) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            if self._conn is None:
                raise RuntimeError("HistoryDB is closed")
            cur = self._conn.cursor()
            try:
                yield cur
                if commit:
                    self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
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

    @contextmanager
    def read_transaction(self) -> Iterator[None]:
        """Hold a single read transaction across multi-step read operations."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("HistoryDB is closed")
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN")
                yield
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    # -- settings_kv persistence (inlined from _settings.py) ------------------

    def get_setting(self, key: str) -> JsonValue | None:
        with self._cursor(commit=False) as cur:
            cur.execute("SELECT value_json FROM settings_kv WHERE key = ?", (key,))
            row = cur.fetchone()
        if row is None:
            return None
        return safe_json_loads(row[0], context=f"setting {key}")

    def set_setting(self, key: str, value: JsonValue) -> None:
        now = utc_now_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings_kv (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (key, safe_json_dumps(value), now),
            )

    def get_settings_snapshot(self) -> JsonObject | None:
        snapshot = self.get_setting("settings_snapshot")
        return snapshot if is_json_object(snapshot) else None

    def set_settings_snapshot(self, snapshot: JsonObject) -> None:
        self.set_setting("settings_snapshot", snapshot)

    # -- client_names persistence (inlined from _client_names.py) -------------

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
