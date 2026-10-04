"""Data checks on stored run rows: degraded runs warn, rows without strength are refused."""

from __future__ import annotations

import pytest
from test_support.report_helpers import RUN_END, report_sample, suitability_by_key
from test_support.report_helpers import analysis_metadata as make_metadata
from test_support.report_helpers import analysis_sample as make_sample
from test_support.report_helpers import report_run_metadata as run_metadata
from test_support.report_record_builders import sample_log_records, summarize_records


def test_degraded_run_warns_on_every_data_check() -> None:
    """No speed, one sensor, no references, clipped samples and dropped frames."""
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(15):
        row = report_sample(
            idx,
            speed_kmh=None,
            dominant_freq_hz=14.0,
            peak_amp_g=0.08,
            add_index_accel_offset=True,
            include_secondary_peak=True,
        )
        row["client_id"] = "solo-1"
        row["client_name"] = "front-left wheel"
        row["frames_dropped_total"] = idx * 2
        row["queue_overflow_drops"] = idx
        if idx in {0, 5, 10}:
            row["accel_x_g"] = 15.9
        records.append(row)
    records.append(RUN_END)

    suitability = suitability_by_key(summarize_records(records))

    for key in (
        "SUITABILITY_CHECK_SPEED_VARIATION",
        "SUITABILITY_CHECK_SENSOR_COVERAGE",
        "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
        "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
        "SUITABILITY_CHECK_FRAME_INTEGRITY",
    ):
        assert suitability[key]["state"] == "warn", key


def test_a_run_without_rows_summarizes_to_zero_rows() -> None:
    assert summarize_records(sample_log_records(n_samples=0))["rows"] == 0


def test_rows_without_precomputed_strength_metrics_are_refused() -> None:
    row = make_sample(0.0, 80.0, 0.02)
    row.pop("vibration_strength_db", None)
    run_end = {
        "record_type": "run_end",
        "schema_version": "v2-jsonl",
        "run_id": "test-run",
        "end_time_utc": "2025-01-01T00:00:10+00:00",
    }

    with pytest.raises(ValueError, match="Missing required precomputed strength metrics"):
        summarize_records([make_metadata(), row, run_end])
