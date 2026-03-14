"""Tests for explicit summary boundary helper functions."""

from __future__ import annotations

from vibesensor.analysis._types import AnalysisSummary
from vibesensor.report.mapping import (
    summary_end_time_utc,
    summary_findings,
    summary_firmware_version,
    summary_metadata,
    summary_origin,
    summary_raw_sample_rate_hz,
    summary_record_length,
    summary_row_count,
    summary_run_suitability,
    summary_sample_rate_hz_text,
    summary_sensor_count_used,
    summary_sensor_intensity_by_location,
    summary_sensor_locations_active,
    summary_sensor_model,
    summary_speed_stats,
    summary_start_time_utc,
    summary_test_plan,
    summary_top_causes,
    summary_warnings,
)


def _minimal_summary(**overrides: object) -> AnalysisSummary:
    """Build a minimal SummaryData dict with overrides."""
    base: dict = {
        "file_name": "test",
        "run_id": "run-1",
        "rows": 10,
        "duration_s": 5.0,
        "record_length": "0:05",
        "lang": "en",
        "metadata": {"car_name": "Test Car"},
        "findings": [],
        "top_causes": [],
        "speed_stats": {
            "min_kmh": 50.0,
            "max_kmh": 100.0,
            "mean_kmh": 75.0,
            "stddev_kmh": 10.0,
            "range_kmh": 50.0,
            "steady_speed": False,
        },
        "most_likely_origin": {
            "location": "front_left",
            "alternative_locations": [],
            "suspected_source": "wheel/tire",
            "dominance_ratio": 2.0,
            "weak_spatial_separation": False,
        },
        "sensor_locations": ["front_left", "front_right"],
        "sensor_locations_connected_throughout": ["front_left"],
        "sensor_count_used": 2,
        "start_time_utc": "2025-01-01T10:00:00Z",
        "end_time_utc": "2025-01-01T10:00:05Z",
        "raw_sample_rate_hz": 100.0,
        "sensor_model": "MPU6050",
        "firmware_version": "1.0.0",
        "run_suitability": [],
        "warnings": [],
        "test_plan": [],
        "sensor_intensity_by_location": [],
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


class TestSummaryHelpers:
    def test_metadata(self) -> None:
        assert summary_metadata(_minimal_summary())["car_name"] == "Test Car"

    def test_row_count(self) -> None:
        assert summary_row_count(_minimal_summary(rows=42)) == 42

    def test_record_length(self) -> None:
        assert summary_record_length(_minimal_summary(record_length="1:30")) == "1:30"

    def test_record_length_none(self) -> None:
        assert summary_record_length(_minimal_summary(record_length=None)) is None

    def test_start_time_utc(self) -> None:
        assert summary_start_time_utc(_minimal_summary()) == "2025-01-01T10:00:00Z"

    def test_end_time_utc(self) -> None:
        assert summary_end_time_utc(_minimal_summary()) == "2025-01-01T10:00:05Z"

    def test_raw_sample_rate_hz(self) -> None:
        assert summary_raw_sample_rate_hz(_minimal_summary(raw_sample_rate_hz=200.0)) == 200.0

    def test_sensor_model(self) -> None:
        assert summary_sensor_model(_minimal_summary()) == "MPU6050"

    def test_firmware_version(self) -> None:
        assert summary_firmware_version(_minimal_summary()) == "1.0.0"

    def test_sensor_count_used(self) -> None:
        assert summary_sensor_count_used(_minimal_summary(sensor_count_used=3)) == 3

    def test_findings_empty(self) -> None:
        assert summary_findings(_minimal_summary()) == []

    def test_top_causes_empty(self) -> None:
        assert summary_top_causes(_minimal_summary()) == []

    def test_speed_stats(self) -> None:
        assert summary_speed_stats(_minimal_summary())["min_kmh"] == 50.0

    def test_origin(self) -> None:
        assert summary_origin(_minimal_summary())["location"] == "front_left"

    def test_sensor_locations_active_prefers_connected(self) -> None:
        assert summary_sensor_locations_active(_minimal_summary()) == ["front_left"]

    def test_sensor_locations_active_fallback(self) -> None:
        assert "front_left" in summary_sensor_locations_active(
            _minimal_summary(sensor_locations_connected_throughout=[])
        )

    def test_sample_rate_hz_text(self) -> None:
        assert summary_sample_rate_hz_text(_minimal_summary(raw_sample_rate_hz=100.0)) == "100"

    def test_sample_rate_hz_text_none(self) -> None:
        assert summary_sample_rate_hz_text(_minimal_summary(raw_sample_rate_hz=None)) is None

    def test_test_plan(self) -> None:
        plan = [{"what": "test something", "why": "to verify"}]
        assert len(summary_test_plan(_minimal_summary(test_plan=plan))) == 1

    def test_run_suitability(self) -> None:
        checks = [{"check": "SPEED", "state": "pass", "explanation": "ok"}]
        assert len(summary_run_suitability(_minimal_summary(run_suitability=checks))) == 1

    def test_warnings(self) -> None:
        warns = [{"title": "Low data", "severity": "warn"}]
        assert len(summary_warnings(_minimal_summary(warnings=warns))) == 1

    def test_sensor_intensity_by_location(self) -> None:
        intensity = [{"location": "front_left", "p95_intensity_db": 25.0}]
        assert (
            len(
                summary_sensor_intensity_by_location(
                    _minimal_summary(sensor_intensity_by_location=intensity)
                )
            )
            == 1
        )
