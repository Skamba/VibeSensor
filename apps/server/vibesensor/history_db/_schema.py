"""Schema DDL and bootstrap helpers for HistoryDB."""

from __future__ import annotations

import logging
import sqlite3

from ._typing import HistoryCursorProvider

LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 6
"""Current schema version.

History:
  v5 — typed samples_v2 columns, WAL mode, run lifecycle fields.
  v6 — added composite indexes idx_samples_v2_client_time and
       idx_runs_status_created for faster per-sensor and filtered
       list queries.
"""

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id                  TEXT PRIMARY KEY,
    status                  TEXT NOT NULL DEFAULT 'recording',
    start_time_utc          TEXT NOT NULL,
    end_time_utc            TEXT,
    metadata_json           TEXT NOT NULL,
    analysis_json           TEXT,
    error_message           TEXT,
    sample_count            INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL,
    analysis_version        INTEGER,
    analysis_started_at     TEXT,
    analysis_completed_at   TEXT
);

CREATE TABLE IF NOT EXISTS samples_v2 (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    record_type           TEXT,
    schema_version        TEXT,
    timestamp_utc         TEXT,
    t_s                   REAL,
    client_id             TEXT,
    client_name           TEXT,
    location              TEXT,
    sample_rate_hz        INTEGER,
    speed_kmh             REAL,
    gps_speed_kmh         REAL,
    speed_source          TEXT,
    engine_rpm            REAL,
    engine_rpm_source     TEXT,
    gear                  REAL,
    final_drive_ratio     REAL,
    accel_x_g             REAL,
    accel_y_g             REAL,
    accel_z_g             REAL,
    dominant_freq_hz      REAL,
    dominant_axis         TEXT,
    vibration_strength_db REAL,
    strength_bucket       TEXT,
    strength_peak_amp_g   REAL,
    strength_floor_amp_g  REAL,
    frames_dropped_total  INTEGER DEFAULT 0,
    queue_overflow_drops  INTEGER DEFAULT 0,
    top_peaks             TEXT,
    top_peaks_x           TEXT,
    top_peaks_y           TEXT,
    top_peaks_z           TEXT,
    extra_json            TEXT
);

CREATE INDEX IF NOT EXISTS idx_samples_v2_run_id ON samples_v2(run_id);
CREATE INDEX IF NOT EXISTS idx_samples_v2_run_time ON samples_v2(run_id, t_s);
CREATE INDEX IF NOT EXISTS idx_samples_v2_client_time ON samples_v2(client_id, t_s);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);
CREATE INDEX IF NOT EXISTS idx_runs_status_created ON runs(status, created_at);

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

_MIGRATION_SQL_V5_TO_V6 = """\
CREATE INDEX IF NOT EXISTS idx_samples_v2_client_time ON samples_v2(client_id, t_s);
CREATE INDEX IF NOT EXISTS idx_runs_status_created ON runs(status, created_at);
"""


def _migrate_v5_to_v6(cur: sqlite3.Cursor) -> None:
    """Apply schema v5 → v6 migration: add composite indexes.

    Uses ``CREATE INDEX IF NOT EXISTS`` so the migration is idempotent and
    safe to retry if the subsequent version-bump write fails.
    """
    for stmt in _MIGRATION_SQL_V5_TO_V6.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            cur.execute(stmt)
    LOGGER.info("Applied schema migration v5 → v6 (added composite indexes)")


class HistorySchemaMixin:
    """Mixin responsible for ensuring the SQLite schema exists and is supported."""

    __slots__ = ()

    def _ensure_schema(self: HistoryCursorProvider) -> None:
        with self._cursor() as cur:
            cur.executescript(SCHEMA_SQL)
        with self._cursor() as cur:
            cur.execute("SELECT value FROM schema_meta WHERE key = ?", ("version",))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
                    ("version", str(SCHEMA_VERSION)),
                )
                return
            try:
                version = int(str(row[0]))
            except (ValueError, TypeError):
                LOGGER.error(
                    "Corrupted schema_meta version value %r; resetting to %s",
                    row[0],
                    SCHEMA_VERSION,
                )
                cur.execute(
                    "UPDATE schema_meta SET value = ? WHERE key = 'version'",
                    (str(SCHEMA_VERSION),),
                )
                return
            if version == SCHEMA_VERSION:
                return
            if version == 5:
                _migrate_v5_to_v6(cur)
                cur.execute(
                    "UPDATE schema_meta SET value = ? WHERE key = 'version'",
                    (str(SCHEMA_VERSION),),
                )
                return
            raise RuntimeError(
                f"Unsupported history DB schema version {version}; "
                f"expected {SCHEMA_VERSION}. Delete the database file to recreate."
            )
