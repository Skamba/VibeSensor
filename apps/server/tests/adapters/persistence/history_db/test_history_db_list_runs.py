"""Focused list-run projection and migration coverage for HistoryDB."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from test_support.history_db_async import execute_statements as _execute_statements
from test_support.history_db_async import fetch_one as _fetch_one
from test_support.history_db_lifecycle import build_history_db
from test_support.history_db_lifecycle import (
    make_run_metadata as _metadata,
)

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.adapters.persistence.history_db._schema import SCHEMA_VERSION
from vibesensor.shared.boundaries.runs.metadata import run_metadata_to_json_object

_V11_RUNS_SCHEMA = """\
CREATE TABLE runs (
    run_id                  TEXT PRIMARY KEY,
    case_id                 TEXT,
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
"""


def test_list_runs_includes_recorded_car_name(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    db.run_repository.create_run(
        "run-car",
        "2026-01-01T00:00:00Z",
        _metadata("run-car", active_car_snapshot={"name": "Track Car"}),
    )

    run = db.run_repository.list_runs()[0]

    assert run.car_name == "Track Car"


def test_list_runs_uses_denormalized_car_name_when_metadata_json_is_invalid(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    db.run_repository.create_run(
        "run-car",
        "2026-01-01T00:00:00Z",
        _metadata("run-car", active_car_snapshot={"name": "Track Car"}),
    )
    _execute_statements(
        db.lifecycle,
        (
            "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
            ("[1, 2, 3]", "run-car"),
        ),
    )

    run = db.run_repository.list_runs()[0]

    assert run.car_name == "Track Car"


def test_schema_version_11_migrates_run_car_name_backfill(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    metadata_json = json.dumps(
        run_metadata_to_json_object(
            _metadata("run-legacy", active_car_snapshot={"name": "Legacy Car"})
        )
    )
    insert_sql = (
        "INSERT INTO runs (run_id, status, start_time_utc, metadata_json, "
        "sample_count, created_at) VALUES (?, 'recording', ?, ?, ?, ?)"
    )
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_V11_RUNS_SCHEMA)
    conn.execute(
        insert_sql,
        (
            "run-legacy",
            "2026-01-01T00:00:00Z",
            metadata_json,
            0,
            "2026-01-01T00:00:01Z",
        ),
    )
    conn.execute("PRAGMA user_version = 11")
    conn.commit()
    conn.close()

    db = create_history_persistence_adapters(db_path)

    run = db.run_repository.list_runs()[0]
    version_row = _fetch_one(db.lifecycle, "PRAGMA user_version")
    car_name_row = _fetch_one(
        db.lifecycle,
        "SELECT car_name FROM runs WHERE run_id = ?",
        ("run-legacy",),
    )

    assert run.car_name == "Legacy Car"
    assert version_row == (SCHEMA_VERSION,)
    assert car_name_row == ("Legacy Car",)


def test_update_run_metadata_refreshes_list_run_car_name(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    db.run_repository.create_run(
        "run-meta",
        "2026-01-01T00:00:00Z",
        _metadata("run-meta", active_car_snapshot={"name": "Track Car"}),
    )

    updated = db.run_repository.update_run_metadata(
        "run-meta",
        _metadata("run-meta", active_car_snapshot={"name": "Updated Car"}),
    )

    listed_run = db.run_repository.list_runs()[0]

    assert updated is True
    assert listed_run.car_name == "Updated Car"


def test_list_runs_projects_degraded_raw_capture_finalize_state(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    db.run_repository.create_run(
        "run-degraded",
        "2026-01-01T00:00:00Z",
        _metadata(
            "run-degraded",
            raw_capture_finalize={
                "status": "timeout",
                "queue_depth": 3,
                "error_summary": "raw capture finalize timed out",
            },
        ),
    )

    run = db.run_repository.list_runs()[0]

    assert run.lifecycle is not None
    assert run.lifecycle.raw_capture == "degraded"
    assert run.lifecycle.post_analysis == "pending"
    assert run.artifact_availability is not None
    assert run.artifact_availability.raw_capture == "degraded"
    assert run.raw_capture_finalize is not None
    assert run.raw_capture_finalize.status == "timeout"
    assert run.raw_capture_finalize.queue_depth == 3
    assert run.raw_capture_finalize.error_summary == "raw capture finalize timed out"


def test_get_run_projects_raw_capture_finalize_state(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    db.run_repository.create_run(
        "run-degraded",
        "2026-01-01T00:00:00Z",
        _metadata(
            "run-degraded",
            raw_capture_finalize={
                "status": "failed",
                "queue_depth": 1,
                "error_summary": "write worker crashed",
            },
        ),
    )

    run = db.run_repository.get_run("run-degraded")

    assert run is not None
    assert run.lifecycle is not None
    assert run.lifecycle.raw_capture == "degraded"
    assert run.lifecycle.post_analysis == "pending"
    assert run.artifact_availability is not None
    assert run.artifact_availability.raw_capture == "degraded"
    assert run.raw_capture_finalize is not None
    assert run.raw_capture_finalize.status == "failed"
    assert run.raw_capture_finalize.queue_depth == 1
    assert run.raw_capture_finalize.error_summary == "write worker crashed"
    assert run.metadata.raw_capture_finalize is not None
    assert run.metadata.raw_capture_finalize.status == "failed"
