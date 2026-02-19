"""SQLite-backed persistence for VibeSensor run history.

Stores run metadata, samples and analysis outputs in a single file –
lightweight enough for a Raspberry Pi 3A+.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

LOGGER = logging.getLogger(__name__)

# -- Schema -------------------------------------------------------------------

_SCHEMA_VERSION = 1

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
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS samples (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    sample_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_samples_run_id ON samples(run_id);
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
        with self._lock:
            self._conn.executescript(_SCHEMA_SQL)
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR IGNORE INTO schema_meta (key, value) VALUES (?, ?)",
                ("version", str(_SCHEMA_VERSION)),
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
                "INSERT INTO runs (run_id, status, start_time_utc, metadata_json, created_at) "
                "VALUES (?, 'recording', ?, ?, ?)",
                (run_id, start_time_utc, json.dumps(metadata, ensure_ascii=True), now),
            )

    def append_samples(self, run_id: str, samples: list[dict[str, Any]]) -> None:
        if not samples:
            return
        chunk_size = 256
        with self._cursor() as cur:
            for start in range(0, len(samples), chunk_size):
                batch = samples[start : start + chunk_size]
                cur.executemany(
                    "INSERT INTO samples (run_id, sample_json) VALUES (?, ?)",
                    ((run_id, json.dumps(s, ensure_ascii=True)) for s in batch),
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
                (json.dumps(analysis, ensure_ascii=True, default=str), run_id),
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
                "r.created_at, r.error_message, "
                "(SELECT COUNT(*) FROM samples s WHERE s.run_id = r.run_id) AS sample_count "
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
        with self._cursor() as cur:
            cur.execute(
                "SELECT sample_json FROM samples WHERE run_id = ? ORDER BY id",
                (run_id,),
            )
            return [json.loads(row[0]) for row in cur.fetchall()]

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
            cur.execute("SELECT run_id FROM runs WHERE status = 'recording' LIMIT 1")
            row = cur.fetchone()
        return row[0] if row else None
