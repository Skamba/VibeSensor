"""Tests for SummaryView typed accessor."""

from __future__ import annotations

from vibesensor.analysis._types import AnalysisSummary
from vibesensor.report.mapping import SummaryView


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


class TestSummaryView:
    def test_metadata(self) -> None:
        view = SummaryView(_minimal_summary())
        assert view.metadata["car_name"] == "Test Car"

    def test_row_count(self) -> None:
        view = SummaryView(_minimal_summary(rows=42))
        assert view.row_count == 42

    def test_record_length(self) -> None:
        view = SummaryView(_minimal_summary(record_length="1:30"))
        assert view.record_length == "1:30"

    def test_record_length_none(self) -> None:
        view = SummaryView(_minimal_summary(record_length=None))
        assert view.record_length is None

    def test_start_time_utc(self) -> None:
        view = SummaryView(_minimal_summary())
        assert view.start_time_utc == "2025-01-01T10:00:00Z"

    def test_end_time_utc(self) -> None:
        view = SummaryView(_minimal_summary())
        assert view.end_time_utc == "2025-01-01T10:00:05Z"

    def test_raw_sample_rate_hz(self) -> None:
        view = SummaryView(_minimal_summary(raw_sample_rate_hz=200.0))
        assert view.raw_sample_rate_hz == 200.0

    def test_sensor_model(self) -> None:
        view = SummaryView(_minimal_summary())
        assert view.sensor_model == "MPU6050"

    def test_firmware_version(self) -> None:
        view = SummaryView(_minimal_summary())
        assert view.firmware_version == "1.0.0"

    def test_sensor_count_used(self) -> None:
        view = SummaryView(_minimal_summary(sensor_count_used=3))
        assert view.sensor_count_used == 3

    def test_findings_empty(self) -> None:
        view = SummaryView(_minimal_summary())
        assert view.findings == []

    def test_top_causes_empty(self) -> None:
        view = SummaryView(_minimal_summary())
        assert view.top_causes == []

    def test_speed_stats(self) -> None:
        view = SummaryView(_minimal_summary())
        assert view.speed_stats["min_kmh"] == 50.0

    def test_origin(self) -> None:
        view = SummaryView(_minimal_summary())
        assert view.origin["location"] == "front_left"

    def test_sensor_locations_active_prefers_connected(self) -> None:
        view = SummaryView(_minimal_summary())
        assert view.sensor_locations_active == ["front_left"]

    def test_sensor_locations_active_fallback(self) -> None:
        view = SummaryView(_minimal_summary(sensor_locations_connected_throughout=[]))
        assert "front_left" in view.sensor_locations_active

    def test_sample_rate_hz_text(self) -> None:
        view = SummaryView(_minimal_summary(raw_sample_rate_hz=100.0))
        assert view.sample_rate_hz_text == "100"

    def test_sample_rate_hz_text_none(self) -> None:
        view = SummaryView(_minimal_summary(raw_sample_rate_hz=None))
        assert view.sample_rate_hz_text is None

    def test_data_returns_underlying_dict(self) -> None:
        summary = _minimal_summary()
        view = SummaryView(summary)
        assert view.data is summary

    def test_test_plan(self) -> None:
        plan = [{"what": "test something", "why": "to verify"}]
        view = SummaryView(_minimal_summary(test_plan=plan))
        assert len(view.test_plan) == 1

    def test_run_suitability(self) -> None:
        checks = [{"check": "SPEED", "state": "pass", "explanation": "ok"}]
        view = SummaryView(_minimal_summary(run_suitability=checks))
        assert len(view.run_suitability) == 1

    def test_warnings(self) -> None:
        warns = [{"title": "Low data", "severity": "warn"}]
        view = SummaryView(_minimal_summary(warnings=warns))
        assert len(view.warnings) == 1

    def test_sensor_intensity_by_location(self) -> None:
        intensity = [{"location": "front_left", "p95_intensity_db": 25.0}]
        view = SummaryView(_minimal_summary(sensor_intensity_by_location=intensity))
        assert len(view.sensor_intensity_by_location) == 1
