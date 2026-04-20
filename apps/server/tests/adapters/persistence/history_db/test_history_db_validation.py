"""HistoryDB input sanitization, integrity checks, and warning-path coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from test_support.history_db_async import execute_statements
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frame_from_mapping
from vibesensor.shared.json_utils import sanitize_value
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.run_schema import RunMetadata


def _metadata(run_id: str, **overrides: object) -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2026-01-01T00:00:00Z",
        "sensor_model": "fixture-sensor",
        "raw_sample_rate_hz": 800,
        "sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "source": "test",
    }
    payload.update(overrides)
    return run_metadata_from_mapping(payload)


def _analysis(run_id: str, **overrides: object) -> AnalysisSummary:
    payload: dict[str, object] = {
        "run_id": run_id,
        "findings": [],
        "top_causes": [],
        "warnings": [],
    }
    payload.update(overrides)
    return cast(AnalysisSummary, payload)


def test_create_run_sanitizes_non_finite_metadata(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run(
        "run-nan",
        "2026-01-01T00:00:00Z",
        _metadata("run-nan", reference_context={"tire_circumference_m": float("nan")}),
    )
    run = db.run_repository.get_run("run-nan")
    assert run is not None
    assert run.metadata.wheel_circumference_m is None
    assert run.metadata.tire_circumference_m is None


def test_list_runs_clamps_negative_limit_to_all_rows(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    for i in range(5):
        db.run_repository.create_run(f"run-{i}", "2026-01-01T00:00:00Z", _metadata(f"run-{i}"))
        db.run_repository.finalize_run(f"run-{i}", "2026-01-01T00:10:00Z")

    result = db.run_repository.list_runs(limit=-1)
    assert len(result) == 5


def test_resolve_keyset_offset_rejects_invalid_table(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-guard", "2026-01-01T00:00:00Z", _metadata("run-guard"))
    db.run_repository.append_samples(
        "run-guard", [sensor_frame_from_mapping({"i": i}) for i in range(3)]
    )

    with pytest.raises(ValueError, match="invalid table name"):
        db.run_repository._resolve_keyset_offset("injected_table", "run-guard", 1)


def test_append_samples_empty_run_id_raises(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    with pytest.raises(ValueError, match="run_id"):
        db.run_repository.append_samples("", [sensor_frame_from_mapping({"i": 1})])


def test_append_samples_whitespace_run_id_raises(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    with pytest.raises(ValueError, match="run_id"):
        db.run_repository.append_samples("   ", [sensor_frame_from_mapping({"i": 1})])


def test_iter_run_samples_negative_offset_raises(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-neg-off", "2026-01-01T00:00:00Z", _metadata("run-neg-off"))
    db.run_repository.append_samples(
        "run-neg-off", [sensor_frame_from_mapping({"i": i}) for i in range(3)]
    )

    with pytest.raises(ValueError, match="offset"):
        list(db.run_repository.iter_run_samples("run-neg-off", offset=-1))


def test_sanitize_value_handles_numpy_scalars() -> None:
    import numpy as np

    assert sanitize_value(np.float32(1.5)) == 1.5
    assert isinstance(sanitize_value(np.float32(1.5)), float)

    assert sanitize_value(np.float64(2.5)) == 2.5
    assert isinstance(sanitize_value(np.float64(2.5)), float)

    assert sanitize_value(np.int32(42)) == 42
    assert isinstance(sanitize_value(np.int32(42)), int)

    assert sanitize_value(np.int64(99)) == 99
    assert isinstance(sanitize_value(np.int64(99)), int)

    assert sanitize_value(np.float64(float("nan"))) is None
    assert sanitize_value(np.float32(float("inf"))) is None


def test_sanitize_value_handles_nested_numpy() -> None:
    import numpy as np

    data = {"a": np.float32(1.0), "b": [np.int64(2), np.float64(float("nan"))]}
    result = sanitize_value(data)
    assert result == {"a": 1.0, "b": [2, None]}
    json.dumps(result)


def test_sanitize_value_handles_numpy_arrays() -> None:
    import numpy as np

    arr = np.array([1.0, 2.0, float("nan")])
    result = sanitize_value(arr)
    assert result == [1.0, 2.0, None]
    json.dumps(result)

    arr2d = np.array([[1.0, 2.0], [3.0, 4.0]])
    result2d = sanitize_value(arr2d)
    assert result2d == [[1.0, 2.0], [3.0, 4.0]]
    json.dumps(result2d)


# -- verify_run_integrity tests -----------------------------------------------


def test_verify_run_integrity_clean_run(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run(
        "run-ok",
        "2026-01-01T00:00:00Z",
        _metadata("run-ok", sensor_model="a", sample_rate_hz=100),
    )
    db.run_repository.append_samples(
        "run-ok", [sensor_frame_from_mapping({"i": i}) for i in range(5)]
    )
    db.run_repository.finalize_run("run-ok", "2026-01-01T00:10:00Z")
    db.run_repository.store_analysis("run-ok", make_persisted_analysis(_analysis("run-ok")))
    assert db.run_repository.verify_run_integrity("run-ok") == []


def test_verify_run_integrity_sample_count_mismatch(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run(
        "run-m",
        "2026-01-01T00:00:00Z",
        _metadata("run-m", sensor_model="a", sample_rate_hz=100),
    )
    db.run_repository.append_samples(
        "run-m", [sensor_frame_from_mapping({"i": i}) for i in range(5)]
    )
    db.run_repository.finalize_run("run-m", "2026-01-01T00:10:00Z")
    db.run_repository.store_analysis("run-m", make_persisted_analysis(_analysis("run-m")))
    # Manually corrupt sample_count
    execute_statements(
        db.lifecycle,
        ("UPDATE runs SET sample_count = 99 WHERE run_id = 'run-m'", ()),
    )
    problems = db.run_repository.verify_run_integrity("run-m")
    assert any("sample_count mismatch" in p for p in problems)


def test_verify_run_integrity_complete_without_analysis(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run(
        "run-na",
        "2026-01-01T00:00:00Z",
        _metadata("run-na", sensor_model="a", sample_rate_hz=100),
    )
    db.run_repository.finalize_run("run-na", "2026-01-01T00:10:00Z")
    # Force status to complete without analysis
    execute_statements(
        db.lifecycle,
        ("UPDATE runs SET status = 'complete' WHERE run_id = 'run-na'", ()),
    )
    problems = db.run_repository.verify_run_integrity("run-na")
    assert any("missing analysis_json" in p for p in problems)


def test_verify_run_integrity_run_not_found(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    assert db.run_repository.verify_run_integrity("no-such-run") == ["run not found"]


# -- metadata validation warning tests ----------------------------------------


def test_create_run_warns_on_missing_metadata_keys(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    incomplete_meta = run_metadata_from_mapping(
        {
            "run_id": "run-w",
            "start_time_utc": "2026-01-01T00:00:00Z",
            "source": "test",
        }
    )
    with caplog.at_level("WARNING"):
        db.run_repository.create_run("run-w", "2026-01-01T00:00:00Z", incomplete_meta)
    assert "missing recommended keys" in caplog.text
    assert "raw_sample_rate_hz" in caplog.text


def test_create_run_no_warning_when_metadata_complete(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    meta = _metadata("run-ok", sensor_model="a", raw_sample_rate_hz=100)
    with caplog.at_level("WARNING"):
        db.run_repository.create_run("run-ok", "2026-01-01T00:00:00Z", meta)
    assert "missing recommended keys" not in caplog.text


# -- analysis summary validation warning tests --------------------------------


def test_store_analysis_warns_on_missing_summary_keys(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    meta = _metadata("run-w2", sensor_model="a", raw_sample_rate_hz=100)
    db.run_repository.create_run("run-w2", "2026-01-01T00:00:00Z", meta)
    db.run_repository.finalize_run("run-w2", "2026-01-01T00:10:00Z")
    incomplete_summary = cast(AnalysisSummary, {"run_id": "run-w2", "score": 42})
    with caplog.at_level("WARNING"):
        db.run_repository.store_analysis("run-w2", make_persisted_analysis(incomplete_summary))
    assert "missing expected keys" in caplog.text


# -- atomic state transition tests ---------------------------------------------


def test_store_analysis_rejects_terminal_status(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run(
        "run-t",
        "2026-01-01T00:00:00Z",
        _metadata("run-t", sensor_model="a", sample_rate_hz=100),
    )
    db.run_repository.finalize_run("run-t", "2026-01-01T00:10:00Z")
    db.run_repository.store_analysis("run-t", make_persisted_analysis(_analysis("run-t")))
    # Second store_analysis should return False (already complete)
    assert (
        db.run_repository.store_analysis(
            "run-t",
            make_persisted_analysis(_analysis("run-t", top_causes=["unexpected"])),
        )
        is False
    )


def test_store_analysis_error_rejects_terminal_status(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run(
        "run-te",
        "2026-01-01T00:00:00Z",
        _metadata("run-te", sensor_model="a", sample_rate_hz=100),
    )
    db.run_repository.finalize_run("run-te", "2026-01-01T00:10:00Z")
    db.run_repository.store_analysis("run-te", make_persisted_analysis(_analysis("run-te")))
    # Error after complete should return False
    assert db.run_repository.store_analysis_error("run-te", "late failure") is False
