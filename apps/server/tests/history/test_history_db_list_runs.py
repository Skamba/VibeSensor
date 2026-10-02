"""Focused list-run projection coverage for HistoryDB."""

from __future__ import annotations

from test_support.history_db_lifecycle import create_recording_run
from test_support.history_db_lifecycle import make_run_metadata as _metadata
from test_support.history_db_sql import execute_statements as _execute_statements

from vibesensor.history.history_db import HistoryDB


def test_list_runs_includes_recorded_car_name(db: HistoryDB) -> None:
    create_recording_run(db, "run-car", active_car_snapshot={"name": "Track Car"})

    run = db.list_runs()[0]

    assert run.car_name == "Track Car"


def test_list_runs_uses_denormalized_car_name_when_metadata_json_is_invalid(
    db: HistoryDB,
) -> None:
    create_recording_run(db, "run-car", active_car_snapshot={"name": "Track Car"})
    _execute_statements(
        db,
        (
            "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
            ("[1, 2, 3]", "run-car"),
        ),
    )

    run = db.list_runs()[0]

    assert run.car_name == "Track Car"


def test_update_run_metadata_refreshes_list_run_car_name(db: HistoryDB) -> None:
    create_recording_run(db, "run-meta", active_car_snapshot={"name": "Track Car"})

    updated = db.update_run_metadata(
        "run-meta",
        _metadata("run-meta", active_car_snapshot={"name": "Updated Car"}),
    )

    listed_run = db.list_runs()[0]

    assert updated is True
    assert listed_run.car_name == "Updated Car"


def test_list_runs_projects_degraded_raw_capture_finalize_state(
    db: HistoryDB,
) -> None:
    db.create_run(
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

    run = db.list_runs()[0]

    assert run.lifecycle is not None
    assert run.lifecycle.raw_capture == "degraded"
    assert run.lifecycle.post_analysis == "pending"
    assert run.artifact_availability is not None
    assert run.artifact_availability.raw_capture == "degraded"
    assert run.raw_capture_finalize is not None
    assert run.raw_capture_finalize.status == "timeout"
    assert run.raw_capture_finalize.queue_depth == 3
    assert run.raw_capture_finalize.error_summary == "raw capture finalize timed out"


def test_get_run_projects_raw_capture_finalize_state(db: HistoryDB) -> None:
    db.create_run(
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

    run = db.get_run("run-degraded")

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
