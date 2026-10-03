"""Summaries of in-memory run records: basics, language, empty runs, strength-metric guard."""

from __future__ import annotations

import pytest
from test_support.report_helpers import analysis_metadata as _make_metadata
from test_support.report_helpers import analysis_sample as _make_sample
from test_support.report_record_builders import sample_log_records, summarize_records

_END = {
    "record_type": "run_end",
    "schema_version": "v2-jsonl",
    "run_id": "test-run",
    "end_time_utc": "2025-01-01T00:00:10+00:00",
}


def test_summary_basics() -> None:
    result = summarize_records(sample_log_records(n_samples=20))
    assert result["run_id"] == "test-run"
    assert result["rows"] == 20
    assert isinstance(result["speed_breakdown"], list)
    assert isinstance(result["findings"], list)


def test_summary_in_dutch() -> None:
    assert summarize_records(sample_log_records(n_samples=10), lang="nl")["lang"] == "nl"


def test_summary_without_samples() -> None:
    assert summarize_records(sample_log_records(n_samples=0))["rows"] == 0


def test_missing_precomputed_strength_metrics_raise() -> None:
    sample = _make_sample(0.0, 80.0, 0.02)
    sample.pop("vibration_strength_db", None)
    with pytest.raises(ValueError, match="Missing required precomputed strength metrics"):
        summarize_records([_make_metadata(), sample, _END])


def test_partially_missing_precomputed_strength_metrics_are_allowed() -> None:
    sample_missing = _make_sample(0.0, 80.0, 0.02)
    sample_missing.pop("vibration_strength_db", None)
    sample_valid = _make_sample(0.5, 82.0, 0.021)

    summary = summarize_records([_make_metadata(), sample_missing, sample_valid, _END])

    assert summary["rows"] == 2
    assert summary["findings"] is not None
