"""SQLite-backed persistence for the VibeSensor server.

Stores run history (metadata, samples, analysis), application settings
and client names in a single file – lightweight enough for a
Raspberry Pi 3A+.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from .domain_models import SensorFrame

LOGGER = logging.getLogger(__name__)

# -- Schema -------------------------------------------------------------------

_SCHEMA_VERSION = 3

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id         TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'recording',
    start_time_utc TEXT NOT NULL,
    end_time_utc   TEXT,
    metadata_json  TEXT NOT NULL,
    analysis_json  TEXT,
    error_message  TEXT,
    sample_count   INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS samples (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    sample_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_samples_run_id ON samples(run_id);

CREATE TABLE IF NOT EXISTS settings_kv (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS client_names (
    client_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


class HistoryDB:
    """Thin wrapper around a SQLite database for run history."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = RLock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _cursor(self):
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def _ensure_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript(_SCHEMA_SQL)
        with self._cursor() as cur:
            cur.execute("SELECT value FROM schema_meta WHERE key = ?", ("version",))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
                    ("version", str(_SCHEMA_VERSION)),
                )
                return
            version = int(str(row[0]))
            if version < 1:
                raise RuntimeError(
                    f"Unsupported history DB schema version {version}; expected {_SCHEMA_VERSION}"
                )
            if version < _SCHEMA_VERSION:
                if version < 2:
                    self._migrate_v1_to_v2()
                if version < 3:
                    self._migrate_v2_to_v3()
                cur.execute(
                    "UPDATE schema_meta SET value = ? WHERE key = ?",
                    (str(_SCHEMA_VERSION), "version"),
                )
            elif version != _SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported history DB schema version {version}; expected {_SCHEMA_VERSION}"
                )

    def _migrate_v1_to_v2(self) -> None:
        with self._lock:
            self._conn.execute(
                "ALTER TABLE runs ADD COLUMN sample_count INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.execute(
                "UPDATE runs SET sample_count = "
                "(SELECT COUNT(*) FROM samples s WHERE s.run_id = runs.run_id)"
            )

    def _migrate_v2_to_v3(self) -> None:
        """Add settings_kv and client_names tables."""
        with self._lock:
            self._conn.executescript(
                """\
CREATE TABLE IF NOT EXISTS settings_kv (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS client_names (
    client_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""
            )

    # -- write ----------------------------------------------------------------

    def create_run(
        self,
        run_id: str,
        start_time_utc: str,
        metadata: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                ("Recovered stale recording on new run creation",),
            )
            cur.execute(
                "INSERT INTO runs (run_id, status, start_time_utc, metadata_json, created_at) "
                "VALUES (?, 'recording', ?, ?, ?)",
                (run_id, start_time_utc, json.dumps(metadata, ensure_ascii=False), now),
            )

    def append_samples(
        self, run_id: str, samples: list[dict[str, Any]] | list[SensorFrame]
    ) -> None:
        if not samples:
            return

        def _to_json(item: dict[str, Any] | SensorFrame) -> str:
            d = item.to_dict() if isinstance(item, SensorFrame) else item
            return json.dumps(d, ensure_ascii=False)

        chunk_size = 256
        with self._cursor() as cur:
            for start in range(0, len(samples), chunk_size):
                batch = samples[start : start + chunk_size]
                cur.executemany(
                    "INSERT INTO samples (run_id, sample_json) VALUES (?, ?)",
                    ((run_id, _to_json(s)) for s in batch),
                )
            cur.execute(
                "UPDATE runs SET sample_count = sample_count + ? WHERE run_id = ?",
                (len(samples), run_id),
            )

    def finalize_run(self, run_id: str, end_time_utc: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'analyzing', end_time_utc = ? WHERE run_id = ?",
                (end_time_utc, run_id),
            )

    def store_analysis(self, run_id: str, analysis: dict[str, Any]) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'complete', analysis_json = ? WHERE run_id = ?",
                (json.dumps(analysis, ensure_ascii=False, default=str), run_id),
            )

    def store_analysis_error(self, run_id: str, error: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE run_id = ?",
                (error, run_id),
            )

    # -- read -----------------------------------------------------------------

    def list_runs(self) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT r.run_id, r.status, r.start_time_utc, r.end_time_utc, "
                "r.created_at, r.error_message, r.sample_count "
                "FROM runs r ORDER BY r.created_at DESC"
            )
            rows = cur.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            run_id, status, start, end, created, error, sample_count = row
            entry: dict[str, Any] = {
                "run_id": run_id,
                "status": status,
                "start_time_utc": start,
                "end_time_utc": end,
                "created_at": created,
                "sample_count": sample_count,
            }
            if error:
                entry["error_message"] = error
            result.append(entry)
        return result

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT run_id, status, start_time_utc, end_time_utc, "
                "metadata_json, analysis_json, error_message, created_at "
                "FROM runs WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        rid, status, start, end, meta_json, analysis_json, error, created = row
        entry: dict[str, Any] = {
            "run_id": rid,
            "status": status,
            "start_time_utc": start,
            "end_time_utc": end,
            "metadata": json.loads(meta_json) if meta_json else {},
            "created_at": created,
        }
        if analysis_json:
            entry["analysis"] = json.loads(analysis_json)
        if error:
            entry["error_message"] = error
        return entry

    def get_run_samples(self, run_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for batch in self.iter_run_samples(run_id):
            rows.extend(batch)
        return rows

    def iter_run_samples(
        self, run_id: str, batch_size: int = 1000, offset: int = 0
    ) -> Iterator[list[dict[str, Any]]]:
        size = max(1, int(batch_size))
        last_id: int | None = None
        if offset > 0:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT id FROM samples WHERE run_id = ? ORDER BY id LIMIT 1 OFFSET ?",
                    (run_id, max(0, int(offset)) - 1),
                )
                row = cur.fetchone()
                if row:
                    last_id = row[0]
                else:
                    return
        while True:
            with self._cursor() as cur:
                if last_id is None:
                    cur.execute(
                        "SELECT id, sample_json FROM samples WHERE run_id = ? ORDER BY id LIMIT ?",
                        (run_id, size),
                    )
                else:
                    cur.execute(
                        "SELECT id, sample_json FROM samples"
                        " WHERE run_id = ? AND id > ? ORDER BY id LIMIT ?",
                        (run_id, last_id, size),
                    )
                batch_rows = cur.fetchall()
            if not batch_rows:
                return
            last_id = batch_rows[-1][0]
            yield [json.loads(row[1]) for row in batch_rows]

    def get_run_metadata(self, run_id: str) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute("SELECT metadata_json FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        if row is None:
            return None
        return json.loads(row[0]) if row[0] else None

    def get_run_analysis(self, run_id: str) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT analysis_json FROM runs WHERE run_id = ? AND status = 'complete'",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return json.loads(row[0]) if row[0] else None

    def get_run_status(self, run_id: str) -> str | None:
        with self._cursor() as cur:
            cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        return row[0] if row else None

    def delete_run(self, run_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return cur.rowcount > 0

    def get_active_run_id(self) -> str | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT run_id FROM runs WHERE status = 'recording' "
                "ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
        return row[0] if row else None

    def recover_stale_recording_runs(self) -> int:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'error', error_message = ? WHERE status = 'recording'",
                ("Recovered stale recording during startup",),
            )
            return cur.rowcount

    # -- settings KV ----------------------------------------------------------

    def get_setting(self, key: str) -> Any | None:
        with self._cursor() as cur:
            cur.execute("SELECT value_json FROM settings_kv WHERE key = ?", (key,))
            row = cur.fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set_setting(self, key: str, value: Any) -> None:
        now = datetime.now(UTC).isoformat()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings_kv (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False), now),
            )

    def get_settings_snapshot(self) -> dict[str, Any] | None:
        return self.get_setting("settings_snapshot")

    def set_settings_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.set_setting("settings_snapshot", snapshot)

    # -- client names ---------------------------------------------------------

    def list_client_names(self) -> dict[str, str]:
        with self._cursor() as cur:
            cur.execute("SELECT client_id, name FROM client_names")
            rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}

    def upsert_client_name(self, client_id: str, name: str) -> None:
        now = datetime.now(UTC).isoformat()
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
            return cur.rowcount > 0
