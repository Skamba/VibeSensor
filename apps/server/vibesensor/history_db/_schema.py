"""Schema and shared constants for HistoryDB."""

from __future__ import annotations

import logging
from typing import Final

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Run-status constants (previously _run_common.py)
# ---------------------------------------------------------------------------


class RunStatus:
    """String constants for the ``runs.status`` column."""

    RECORDING: str = "recording"
    ANALYZING: str = "analyzing"
    COMPLETE: str = "complete"
    ERROR: str = "error"


RUN_TRANSITIONS: Final[dict[str | None, frozenset[str]]] = {
    None: frozenset({RunStatus.RECORDING}),
    RunStatus.RECORDING: frozenset({RunStatus.ANALYZING, RunStatus.COMPLETE, RunStatus.ERROR}),
    RunStatus.ANALYZING: frozenset({RunStatus.COMPLETE, RunStatus.ERROR}),
    RunStatus.COMPLETE: frozenset(),
    RunStatus.ERROR: frozenset(),
}


def can_transition_run(current_status: str | None, target_status: str) -> bool:
    """Return whether a run can legally move from ``current_status`` to ``target_status``."""
    return target_status in RUN_TRANSITIONS.get(current_status, frozenset())


ANALYSIS_SCHEMA_VERSION = 1

SCHEMA_VERSION = 5

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id                  TEXT PRIMARY KEY,
    status                  TEXT NOT NULL DEFAULT 'recording'
                            CHECK (status IN ('recording', 'analyzing', 'complete', 'error')),
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

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);

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
