"""HistoryDB input sanitization and warning-path coverage."""

from __future__ import annotations

import json
from typing import cast

import numpy as np
import pytest
from test_support.history_db_lifecycle import create_recording_run
from test_support.history_db_lifecycle import make_analysis_summary as _analysis
from test_support.history_db_lifecycle import make_run_metadata as _metadata
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.persistence.history_db._history_db import HistoryDB
from vibesensor.common.json_utils import sanitize_value
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames.mapping import sensor_frame_from_mapping
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary


def test_create_run_sanitizes_non_finite_metadata(db: HistoryDB) -> None:
    create_recording_run(db, "run-nan", reference_context={"tire_circumference_m": float("nan")})
    run = db.get_run("run-nan")
    assert run is not None
    assert run.metadata.wheel_circumference_m is None
    assert run.metadata.tire_circumference_m is None


def test_list_runs_clamps_negative_limit_to_all_rows(db: HistoryDB) -> None:
    for i in range(5):
        db.create_run(f"run-{i}", "2026-01-01T00:00:00Z", _metadata(f"run-{i}"))
        db.finalize_run(f"run-{i}", "2026-01-01T00:10:00Z")

    result = db.list_runs(limit=-1)
    assert len(result) == 5


@pytest.mark.parametrize("run_id", [pytest.param("", id="empty"), pytest.param("   ", id="blank")])
def test_append_samples_rejects_missing_run_id(db: HistoryDB, run_id: str) -> None:
    with pytest.raises(ValueError, match="run_id"):
        db.append_samples(run_id, [sensor_frame_from_mapping({"i": 1})])


@pytest.mark.parametrize(
    ("value", "expected", "expected_type"),
    [
        pytest.param(np.float32(1.5), 1.5, float, id="float32"),
        pytest.param(np.float64(2.5), 2.5, float, id="float64"),
        pytest.param(np.int32(42), 42, int, id="int32"),
        pytest.param(np.int64(99), 99, int, id="int64"),
        pytest.param(np.float64(float("nan")), None, type(None), id="nan"),
        pytest.param(np.float32(float("inf")), None, type(None), id="inf"),
    ],
)
def test_sanitize_value_handles_numpy_scalars(
    value: object, expected: object, expected_type: type
) -> None:
    result = sanitize_value(value)
    assert result == expected
    assert type(result) is expected_type


def test_sanitize_value_handles_nested_numpy() -> None:
    data = {"a": np.float32(1.0), "b": [np.int64(2), np.float64(float("nan"))]}
    result = sanitize_value(data)
    assert result == {"a": 1.0, "b": [2, None]}
    json.dumps(result)


def test_sanitize_value_handles_numpy_arrays() -> None:
    arr = np.array([1.0, 2.0, float("nan")])
    result = sanitize_value(arr)
    assert result == [1.0, 2.0, None]
    json.dumps(result)

    arr2d = np.array([[1.0, 2.0], [3.0, 4.0]])
    result2d = sanitize_value(arr2d)
    assert result2d == [[1.0, 2.0], [3.0, 4.0]]
    json.dumps(result2d)


# -- metadata validation warning tests ----------------------------------------


def test_create_run_warns_on_missing_metadata_keys(
    db: HistoryDB,
    caplog: pytest.LogCaptureFixture,
) -> None:
    incomplete_meta = run_metadata_from_mapping(
        {
            "run_id": "run-w",
            "start_time_utc": "2026-01-01T00:00:00Z",
            "source": "test",
        }
    )
    with caplog.at_level("WARNING"):
        db.create_run("run-w", "2026-01-01T00:00:00Z", incomplete_meta)
    assert "missing recommended keys" in caplog.text
    assert "raw_sample_rate_hz" in caplog.text


def test_create_run_no_warning_when_metadata_complete(
    db: HistoryDB,
    caplog: pytest.LogCaptureFixture,
) -> None:
    meta = _metadata("run-ok", sensor_model="a", raw_sample_rate_hz=100)
    with caplog.at_level("WARNING"):
        db.create_run("run-ok", "2026-01-01T00:00:00Z", meta)
    assert "missing recommended keys" not in caplog.text


# -- analysis summary validation warning tests --------------------------------


def test_store_analysis_warns_on_missing_summary_keys(
    db: HistoryDB,
    caplog: pytest.LogCaptureFixture,
) -> None:
    meta = _metadata("run-w2", sensor_model="a", raw_sample_rate_hz=100)
    db.create_run("run-w2", "2026-01-01T00:00:00Z", meta)
    db.finalize_run("run-w2", "2026-01-01T00:10:00Z")
    incomplete_summary = cast(AnalysisSummary, {"run_id": "run-w2", "score": 42})
    with caplog.at_level("WARNING"):
        db.store_analysis("run-w2", make_persisted_analysis(incomplete_summary))
    assert "missing expected keys" in caplog.text


# -- atomic state transition tests ---------------------------------------------


def test_store_analysis_rejects_terminal_status(db: HistoryDB) -> None:
    create_recording_run(db, "run-t", sensor_model="a", sample_rate_hz=100)
    db.finalize_run("run-t", "2026-01-01T00:10:00Z")
    db.store_analysis("run-t", make_persisted_analysis(_analysis("run-t")))
    # Second store_analysis should return False (already complete)
    assert (
        db.store_analysis(
            "run-t",
            make_persisted_analysis(_analysis("run-t", top_causes=["unexpected"])),
        )
        is False
    )


def test_store_analysis_error_rejects_terminal_status(db: HistoryDB) -> None:
    create_recording_run(db, "run-te", sensor_model="a", sample_rate_hz=100)
    db.finalize_run("run-te", "2026-01-01T00:10:00Z")
    db.store_analysis("run-te", make_persisted_analysis(_analysis("run-te")))
    # Error after complete should return False
    assert db.store_analysis_error("run-te", "late failure") is False
