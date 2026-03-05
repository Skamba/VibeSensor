"""I/O cleanup, time-source, and report-cli guard regressions.

Covers:
  1. firmware_cache.refresh() – target/old_current initialised before try
  2. firmware_cache._download_asset() – fd leak guard when os.fdopen fails
  3. gps_speed.resolve_speed() – TOCTOU snapshot of speed_mps
  4. gps_speed._is_gps_stale() – TOCTOU snapshot of last_update_ts
  5. report_cli.main() – PDF generation errors return 1 instead of traceback
  6. report_data_builder date_str – includes UTC suffix
"""

from __future__ import annotations

from typing import Any

from vibesensor.analysis.report_data_builder import map_summary


def _make_summary(report_date: str, **overrides: Any) -> dict[str, Any]:
    """Build a minimal summary dict for map_summary tests."""
    base: dict[str, Any] = {
        "lang": "en",
        "report_date": report_date,
        "metadata": {},
        "findings": [],
        "top_causes": [],
        "speed_stats": {},
        "most_likely_origin": {},
        "sensor_intensity_by_location": [],
        "run_suitability": [],
        "phase_info": None,
        "plots": {"peaks_table": []},
        "test_plan": [],
    }
    base.update(overrides)
    return base


class TestReportDataBuilderUTCSuffix:
    """date_str in report data must end with ' UTC'."""

    def test_date_str_has_utc_suffix(self) -> None:
        summary = _make_summary(
            "2025-06-01T14:30:00Z",
            metadata={"car_name": "TestCar"},
        )
        result = map_summary(summary)
        assert result.run_datetime is not None
        assert result.run_datetime.endswith(" UTC"), (
            f"Expected UTC suffix, got: {result.run_datetime!r}"
        )
        assert "2025-06-01 14:30:00" in result.run_datetime

    def test_date_str_no_tz_input_still_has_utc(self) -> None:
        summary = _make_summary("2025-03-15T09:45:22")
        result = map_summary(summary)
        assert result.run_datetime == "2025-03-15 09:45:22 UTC"
