"""Incremental schema migration support for HistoryDB.

Each migration function upgrades the database from one schema version to
the next.  The runner applies them sequentially inside a single
transaction so the upgrade is atomic.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Type alias: a migration function takes a cursor and performs DDL/DML.
MigrationFn = Callable[[sqlite3.Cursor], None]


# ---------------------------------------------------------------------------
# Migration functions — one per (from_version → from_version + 1)
# ---------------------------------------------------------------------------


def _migrate_v4_to_v5(cur: sqlite3.Cursor) -> None:
    """v4 → v5: add analysis tracking columns and structured samples table."""

    # -- Add new columns to ``runs`` (ignore if they already exist) ----------
    existing = {row[1] for row in cur.execute("PRAGMA table_info(runs)").fetchall()}
    for col, typedef in (
        ("analysis_version", "INTEGER"),
        ("analysis_started_at", "TEXT"),
        ("analysis_completed_at", "TEXT"),
    ):
        if col not in existing:
            cur.execute(f"ALTER TABLE runs ADD COLUMN {col} {typedef}")  # noqa: S608

    # -- Create samples_v2 table and indexes --------------------------------
    cur.execute(
        """\
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
)"""
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_samples_v2_run_id ON samples_v2(run_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_samples_v2_run_time ON samples_v2(run_id, t_s)")

    LOGGER.info("Migrated history DB schema v4 → v5")


# -- registry ----------------------------------------------------------------

# Ordered mapping from *source* version to the function that migrates one step.
_MIGRATIONS: dict[int, MigrationFn] = {
    4: _migrate_v4_to_v5,
}


# -- public helpers ----------------------------------------------------------


def backup_database(db_path: Path, from_version: int) -> Path:
    """Create a backup of the database file before migration.

    Returns the path to the backup file.
    """
    backup_path = db_path.with_suffix(f".bak-v{from_version}")
    shutil.copy2(db_path, backup_path)
    LOGGER.info("Backed up database to %s before migration", backup_path)
    return backup_path


def run_migrations(
    conn: sqlite3.Connection,
    from_version: int,
    to_version: int,
) -> None:
    """Apply all registered migrations from *from_version* to *to_version*.

    All steps run inside a single transaction so the upgrade is atomic.
    On failure the transaction is rolled back and the caller should fall
    back to the pre-migration backup.
    """
    if from_version >= to_version:
        raise ValueError(
            f"Cannot migrate from v{from_version} to v{to_version} "
            "(source must be older than target)"
        )

    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        for step in range(from_version, to_version):
            fn = _MIGRATIONS.get(step)
            if fn is None:
                raise RuntimeError(
                    f"No migration registered for v{step} → v{step + 1}. "
                    f"Cannot upgrade from schema v{from_version} to v{to_version}."
                )
            fn(cur)
        cur.execute(
            "UPDATE schema_meta SET value = ? WHERE key = 'version'",
            (str(to_version),),
        )
        conn.commit()
        LOGGER.info("Schema migration complete: v%d → v%d", from_version, to_version)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
