"""History DB schema plus open-time schema enforcement and incompatible-DB backup."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from vibesensor.common.json_utils import json_text_dumps

LOGGER = logging.getLogger(__name__)

__all__ = ["SCHEMA_SQL", "SCHEMA_VERSION", "ensure_schema", "quick_check_problems"]


SCHEMA_VERSION = 15

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS runs (
    run_id                  TEXT PRIMARY KEY,
    case_id                 TEXT,
    status                  TEXT NOT NULL DEFAULT 'recording'
                            CHECK (status IN ('recording', 'analyzing', 'complete', 'error')),
    start_time_utc          TEXT NOT NULL,
    end_time_utc            TEXT,
    metadata_json           TEXT NOT NULL,
    car_name                TEXT,
    raw_capture_manifest_json TEXT,
    whole_run_artifact_manifest_json TEXT,
    analysis_json           TEXT,
    error_message           TEXT,
    sample_count            INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL,
    analysis_started_at     TEXT,
    analysis_completed_at   TEXT
);

CREATE TABLE IF NOT EXISTS samples_v2 (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    timestamp_utc         TEXT,
    t_s                   REAL,
    analysis_window_start_us INTEGER,
    analysis_window_end_us INTEGER,
    analysis_window_synced INTEGER,
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
    top_peaks             TEXT
);

CREATE INDEX IF NOT EXISTS idx_samples_v2_run_id ON samples_v2(run_id);
CREATE INDEX IF NOT EXISTS idx_samples_v2_run_time ON samples_v2(run_id, t_s);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);
CREATE INDEX IF NOT EXISTS idx_runs_status_created_at ON runs(status, created_at);

CREATE TABLE IF NOT EXISTS settings_snapshot (
    id          INTEGER PRIMARY KEY CHECK(id = 1),
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS client_names (
    client_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


_SUMMARY_EXPORT_COLUMNS = (
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
_USER_TABLES_SQL = """
SELECT name FROM sqlite_master
WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
"""


def ensure_schema(conn: sqlite3.Connection, db_path: Path) -> None:
    """Create or re-apply the current schema; back up and reject anything else.

    Runs on the freshly opened writer connection before any other access.
    """
    row = conn.execute("PRAGMA user_version").fetchone()
    version = int(row[0]) if row is not None else 0
    if version == 0:
        user_tables = {str(name) for (name,) in conn.execute(_USER_TABLES_SQL).fetchall()}
        if "schema_meta" in user_tables:
            _raise_incompatible_database(
                db_path,
                version=version,
                reason="legacy-schema-meta",
                message=(
                    f"Database at {db_path} uses a legacy schema_meta table "
                    f"incompatible with the current v{SCHEMA_VERSION} format."
                ),
            )
        if user_tables:
            _raise_incompatible_database(
                db_path,
                version=version,
                reason="unexpected-user-tables",
                message=(
                    f"Database at {db_path} has user tables but no schema version and is "
                    f"incompatible with the current v{SCHEMA_VERSION} format."
                ),
            )
        conn.executescript(SCHEMA_SQL)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        return
    if version == SCHEMA_VERSION:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        return
    if version > SCHEMA_VERSION:
        _raise_incompatible_database(
            db_path,
            version=version,
            reason="newer-schema",
            message=(
                f"History DB schema version {version} is newer than supported {SCHEMA_VERSION}."
            ),
        )
    _raise_incompatible_database(
        db_path,
        version=version,
        reason="unsupported-schema",
        message=f"Database schema v{version} is incompatible with current v{SCHEMA_VERSION}.",
    )


def quick_check_problems(conn: sqlite3.Connection) -> list[str]:
    """Return ``PRAGMA quick_check`` findings other than ``ok``."""
    return [
        str(row[0]) for row in conn.execute("PRAGMA quick_check").fetchall() if str(row[0]) != "ok"
    ]


def _raise_incompatible_database(
    db_path: Path,
    *,
    version: int,
    reason: str,
    message: str,
) -> None:
    try:
        backup_path, summary_export_path = _protect_incompatible_database(
            db_path,
            version=version,
            reason=reason,
        )
    except Exception as exc:
        raise RuntimeError(
            f"{message} Automatic backup before rejection failed for {db_path}: {exc}. "
            "The database was left untouched; keep it and back it up manually before any reset."
        ) from exc
    export_note = (
        f" Run-summary export written to {summary_export_path}."
        if summary_export_path is not None
        else " Run-summary export was not available for this schema."
    )
    raise RuntimeError(f"{message} Backup written to {backup_path}.{export_note}")


def _protect_incompatible_database(
    db_path: Path,
    *,
    version: int,
    reason: str,
) -> tuple[Path, Path | None]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = db_path.parent / "history-db-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stem = db_path.stem or "history"
    backup_path = backup_dir / f"{stem}.incompatible-v{version}-{reason}-{timestamp}.db"
    summary_export_path = (
        backup_dir / f"{stem}.incompatible-v{version}-{reason}-{timestamp}.run-summaries.jsonl"
    )

    source_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    backup_conn = sqlite3.connect(str(backup_path))
    try:
        source_conn.backup(backup_conn)
    finally:
        backup_conn.close()
        source_conn.close()

    exported_summary = _export_incompatible_run_summaries(
        backup_path=backup_path,
        summary_export_path=summary_export_path,
    )
    return backup_path, exported_summary


def _export_incompatible_run_summaries(
    *,
    backup_path: Path,
    summary_export_path: Path,
) -> Path | None:
    conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        table_names = {str(row[0]) for row in conn.execute(_USER_TABLES_SQL)}
        if "runs" not in table_names:
            return None
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(runs)")}
        export_columns = [column for column in _SUMMARY_EXPORT_COLUMNS if column in columns]
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
