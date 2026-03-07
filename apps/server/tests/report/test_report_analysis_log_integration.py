from __future__ import annotations

from pathlib import Path

import pytest
from _report_analysis_integration_helpers import write_test_log
from _report_helpers import analysis_metadata as _make_metadata
from _report_helpers import analysis_sample as _make_sample

from vibesensor.analysis import summarize_log
from vibesensor.runlog import append_jsonl_records, create_run_end_record


def test_summarize_log_basic(tmp_path: Path) -> None:
    log_path = tmp_path / "run.jsonl"
    write_test_log(log_path, n_samples=20)
    result = summarize_log(log_path)
    assert result["run_id"] == "test-run"
    assert result["rows"] == 20
    assert isinstance(result["speed_breakdown"], list)
    assert isinstance(result["findings"], list)


def test_summarize_log_nl(tmp_path: Path) -> None:
    log_path = tmp_path / "run.jsonl"
    write_test_log(log_path, n_samples=10)
    result = summarize_log(log_path, lang="nl")
    assert result["run_id"] == "test-run"


def test_summarize_log_no_samples(tmp_path: Path) -> None:
    log_path = tmp_path / "run.jsonl"
    write_test_log(log_path, n_samples=0)
    result = summarize_log(log_path)
    assert result["rows"] == 0


def test_summarize_log_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        summarize_log(tmp_path / "missing.jsonl")


def test_summarize_log_non_jsonl(tmp_path: Path) -> None:
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ValueError, match="Unsupported run format"):
        summarize_log(csv_path)


def test_summarize_log_missing_precomputed_strength_metrics_raises(tmp_path: Path) -> None:
    log_path = tmp_path / "run_missing_strength.jsonl"
    metadata = _make_metadata()
    sample = _make_sample(0.0, 80.0, 0.02)
    sample.pop("vibration_strength_db", None)
    end = create_run_end_record("test-run", "2025-01-01T00:00:10+00:00")
    append_jsonl_records(log_path, [metadata, sample, end])
    with pytest.raises(ValueError, match="Missing required precomputed strength metrics"):
        summarize_log(log_path)


def test_summarize_log_allows_partial_missing_precomputed_strength_metrics(tmp_path: Path) -> None:
    log_path = tmp_path / "run_partial_missing_strength.jsonl"
    metadata = _make_metadata()
    sample_missing = _make_sample(0.0, 80.0, 0.02)
    sample_missing.pop("vibration_strength_db", None)
    sample_valid = _make_sample(0.5, 82.0, 0.021)
    end = create_run_end_record("test-run", "2025-01-01T00:00:10+00:00")
    append_jsonl_records(log_path, [metadata, sample_missing, sample_valid, end])

    summary = summarize_log(log_path)
    assert summary["rows"] == 2
    assert summary["findings"] is not None
