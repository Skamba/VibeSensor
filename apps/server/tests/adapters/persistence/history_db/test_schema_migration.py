"""Tests for the database schema versioning system."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.adapters.persistence.history_db._schema import SCHEMA_VERSION

# -- helpers -----------------------------------------------------------------


def _create_v4_database(db_path: Path) -> None:
    """Create a minimal v4 schema database for migration testing."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """\
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO schema_meta (key, value) VALUES ('version', '4');

CREATE TABLE runs (
    run_id          TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'recording',
    start_time_utc  TEXT NOT NULL,
    end_time_utc    TEXT,
    metadata_json   TEXT NOT NULL,
    analysis_json   TEXT,
    error_message   TEXT,
    sample_count    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);

CREATE TABLE settings_kv (
    key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE client_names (
    client_id TEXT PRIMARY KEY, name TEXT NOT NULL, updated_at TEXT NOT NULL
);
""",
    )
    conn.commit()
    conn.close()


def _create_v8_database(
    db_path: Path,
    *,
    analysis_json: str | None = None,
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """\
PRAGMA user_version = 8;

CREATE TABLE runs (
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
    analysis_started_at     TEXT,
    analysis_completed_at   TEXT
);

CREATE TABLE samples_v2 (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
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
    top_peaks             TEXT
);

CREATE INDEX IF NOT EXISTS idx_samples_v2_run_id ON samples_v2(run_id);
CREATE INDEX IF NOT EXISTS idx_samples_v2_run_time ON samples_v2(run_id, t_s);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);

CREATE TABLE settings_kv (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE client_names (
    client_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""
    )
    conn.execute(
        "INSERT INTO runs (run_id, status, start_time_utc, end_time_utc, metadata_json, "
        "analysis_json, created_at, analysis_started_at, analysis_completed_at) "
        "VALUES (?, 'complete', ?, ?, ?, ?, ?, ?, ?)",
        (
            "legacy-run",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:05:00Z",
            '{"source":"legacy"}',
            analysis_json,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:05:01Z",
            "2026-01-01T00:05:02Z",
        ),
    )
    conn.commit()
    conn.close()


# -- HistoryDB integration tests ---------------------------------------------


def test_historydb_rejects_v4_database(tmp_path: Path) -> None:
    """HistoryDB should refuse to open an incompatible older database."""
    db_path = tmp_path / "history.db"
    _create_v4_database(db_path)

    with pytest.raises(RuntimeError, match="incompatible"):
        HistoryDB(db_path)


def test_historydb_migrates_v8_database_without_manufacturing_case_id(tmp_path: Path) -> None:
    from vibesensor.shared.boundaries.diagnostic_case import diagnostic_case_from_summary

    db_path = tmp_path / "history.db"
    _create_v8_database(db_path, analysis_json='{"findings": [], "top_causes": [], "warnings": []}')

    db = HistoryDB(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        columns = {
            str(row[1]): str(row[2]) for row in conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        case_id = conn.execute(
            "SELECT case_id FROM runs WHERE run_id = ?",
            ("legacy-run",),
        ).fetchone()[0]
    finally:
        conn.close()

    run = db.get_run("legacy-run")

    assert columns["case_id"] == "TEXT"
    assert version == SCHEMA_VERSION
    assert case_id is None
    assert run is not None
    assert "case_id" not in run
    with pytest.raises(
        ValueError,
        match="legacy summary without authoritative case_id",
    ):
        diagnostic_case_from_summary(run["analysis"])
    db.close()


def test_historydb_migrates_v8_database_backfills_case_id_from_analysis_summary(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "history.db"
    _create_v8_database(
        db_path,
        analysis_json=(
            '{"case_id": "case-from-summary", "findings": [], "top_causes": [], "warnings": []}'
        ),
    )

    db = HistoryDB(db_path)

    run = db.get_run("legacy-run")

    assert run is not None
    assert run["case_id"] == "case-from-summary"
    db.close()


def test_historydb_migrated_v8_case_id_supports_forward_only_followup_attachment(
    tmp_path: Path,
) -> None:
    from vibesensor.shared.boundaries.diagnostic_case import diagnostic_case_from_summary

    db_path = tmp_path / "history.db"
    _create_v8_database(
        db_path,
        analysis_json=(
            '{"case_id": "case-from-summary", "findings": [], "top_causes": [], "warnings": []}'
        ),
    )

    db = HistoryDB(db_path)

    legacy_run = db.get_run("legacy-run")

    assert legacy_run is not None
    assert legacy_run["case_id"] == "case-from-summary"
    assert diagnostic_case_from_summary(legacy_run["analysis"]).case_id == "case-from-summary"

    db.create_run(
        "followup-run",
        "2026-01-02T00:00:00Z",
        {
            "source": "followup",
            "sensor_model": "fixture-sensor",
            "sample_rate_hz": 400,
        },
    )

    assert (
        db.finalize_run(
            "followup-run",
            "2026-01-02T00:05:00Z",
            metadata={
                "source": "followup",
                "sensor_model": "fixture-sensor",
                "sample_rate_hz": 400,
                "step": 2,
            },
            case_id=legacy_run["case_id"],
        )
        is True
    )
    db.close()

    reopened_db = HistoryDB(db_path)
    try:
        migrated_legacy_run = reopened_db.get_run("legacy-run")
        followup_run = reopened_db.get_run("followup-run")
    finally:
        reopened_db.close()

    assert migrated_legacy_run is not None
    assert migrated_legacy_run["case_id"] == "case-from-summary"
    assert followup_run is not None
    assert followup_run["case_id"] == "case-from-summary"


def test_historydb_newer_version_raises(tmp_path: Path) -> None:
    """HistoryDB should refuse to open a database with a newer schema version."""
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    db.close()

    conn = sqlite3.connect(str(db_path))
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        HistoryDB(db_path)


def test_historydb_fresh_db_works_normally(tmp_path: Path) -> None:
    """A fresh database (no existing file) should work as before."""
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2026-01-01T00:00:00Z", {"source": "test"})
    run = db.get_run("r1")
    assert run is not None
    assert run["run_id"] == "r1"
    db.close()


def test_historydb_fresh_db_includes_case_id_column(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")

    conn = sqlite3.connect(str(tmp_path / "history.db"))
    try:
        columns = {
            str(row[1]): str(row[2]) for row in conn.execute("PRAGMA table_info(runs)").fetchall()
        }
    finally:
        conn.close()

    assert columns["case_id"] == "TEXT"
    db.close()


def test_historydb_current_version_no_migration(tmp_path: Path) -> None:
    """An existing current-version database should not trigger migration or backup."""
    db = HistoryDB(tmp_path / "history.db")
    db.close()

    db2 = HistoryDB(tmp_path / "history.db")
    db2.close()

    conn = sqlite3.connect(str(tmp_path / "history.db"))
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()

    assert version == SCHEMA_VERSION

    backup = tmp_path / f"history.bak-v{SCHEMA_VERSION}"
    assert not backup.exists()
