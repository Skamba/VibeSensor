from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.shared.utils.json_utils import sanitize_value


def test_create_run_sanitizes_non_finite_metadata(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-nan", "2026-01-01T00:00:00Z", {"tire_circumference_m": float("nan")})
    run = db.get_run("run-nan")
    assert run is not None
    assert run["metadata"]["tire_circumference_m"] is None


def test_list_runs_clamps_negative_limit_to_all_rows(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    for i in range(5):
        db.create_run(f"run-{i}", "2026-01-01T00:00:00Z", {"source": "test"})
        db.finalize_run(f"run-{i}", "2026-01-01T00:10:00Z")

    result = db.list_runs(limit=-1)
    assert len(result) == 5


def test_resolve_keyset_offset_rejects_invalid_table(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-guard", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-guard", [{"i": i} for i in range(3)])

    with pytest.raises(ValueError, match="invalid table name"):
        db._resolve_keyset_offset("injected_table", "run-guard", 1)


def test_append_samples_empty_run_id_raises(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    with pytest.raises(ValueError, match="run_id"):
        db.append_samples("", [{"i": 1}])


def test_append_samples_whitespace_run_id_raises(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    with pytest.raises(ValueError, match="run_id"):
        db.append_samples("   ", [{"i": 1}])


def test_iter_run_samples_negative_offset_raises(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-neg-off", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-neg-off", [{"i": i} for i in range(3)])

    with pytest.raises(ValueError, match="offset"):
        list(db.iter_run_samples("run-neg-off", offset=-1))


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
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-ok", "2026-01-01T00:00:00Z", {"sensor_model": "a", "sample_rate_hz": 100})
    db.append_samples("run-ok", [{"i": i} for i in range(5)])
    db.finalize_run("run-ok", "2026-01-01T00:10:00Z")
    db.store_analysis("run-ok", {"findings": [], "top_causes": [], "warnings": []})
    assert db.verify_run_integrity("run-ok") == []


def test_verify_run_integrity_sample_count_mismatch(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-m", "2026-01-01T00:00:00Z", {"sensor_model": "a", "sample_rate_hz": 100})
    db.append_samples("run-m", [{"i": i} for i in range(5)])
    db.finalize_run("run-m", "2026-01-01T00:10:00Z")
    db.store_analysis("run-m", {"findings": [], "top_causes": [], "warnings": []})
    # Manually corrupt sample_count
    with db._cursor() as cur:
        cur.execute("UPDATE runs SET sample_count = 99 WHERE run_id = 'run-m'")
    problems = db.verify_run_integrity("run-m")
    assert any("sample_count mismatch" in p for p in problems)


def test_verify_run_integrity_complete_without_analysis(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-na", "2026-01-01T00:00:00Z", {"sensor_model": "a", "sample_rate_hz": 100})
    db.finalize_run("run-na", "2026-01-01T00:10:00Z")
    # Force status to complete without analysis
    with db._cursor() as cur:
        cur.execute("UPDATE runs SET status = 'complete' WHERE run_id = 'run-na'")
    problems = db.verify_run_integrity("run-na")
    assert any("missing analysis_json" in p for p in problems)


def test_verify_run_integrity_run_not_found(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    assert db.verify_run_integrity("no-such-run") == ["run not found"]


# -- metadata validation warning tests ----------------------------------------


def test_create_run_warns_on_missing_metadata_keys(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    with caplog.at_level("WARNING"):
        db.create_run("run-w", "2026-01-01T00:00:00Z", {"source": "test"})
    assert "missing recommended keys" in caplog.text
    assert "sensor_model" in caplog.text
    assert "sample_rate_hz" in caplog.text


def test_create_run_no_warning_when_metadata_complete(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    meta = {"sensor_model": "a", "sample_rate_hz": 100}
    with caplog.at_level("WARNING"):
        db.create_run("run-ok", "2026-01-01T00:00:00Z", meta)
    assert "missing recommended keys" not in caplog.text


# -- analysis summary validation warning tests --------------------------------


def test_store_analysis_warns_on_missing_summary_keys(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    meta = {"sensor_model": "a", "sample_rate_hz": 100}
    db.create_run("run-w2", "2026-01-01T00:00:00Z", meta)
    db.finalize_run("run-w2", "2026-01-01T00:10:00Z")
    with caplog.at_level("WARNING"):
        db.store_analysis("run-w2", {"score": 42})
    assert "missing expected keys" in caplog.text


# -- atomic state transition tests ---------------------------------------------


def test_store_analysis_rejects_terminal_status(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-t", "2026-01-01T00:00:00Z", {"sensor_model": "a", "sample_rate_hz": 100})
    db.finalize_run("run-t", "2026-01-01T00:10:00Z")
    db.store_analysis("run-t", {"findings": [], "top_causes": [], "warnings": []})
    # Second store_analysis should return False (already complete)
    assert db.store_analysis("run-t", {"findings": []}) is False


def test_store_analysis_error_rejects_terminal_status(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-te", "2026-01-01T00:00:00Z", {"sensor_model": "a", "sample_rate_hz": 100})
    db.finalize_run("run-te", "2026-01-01T00:10:00Z")
    db.store_analysis("run-te", {"findings": [], "top_causes": [], "warnings": []})
    # Error after complete should return False
    assert db.store_analysis_error("run-te", "late failure") is False
