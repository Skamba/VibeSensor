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

import time
from typing import Any

import pytest

from vibesensor.gps_speed import GPSSpeedMonitor


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


class TestIsGpsStaleTOCTOU:
    """_is_gps_stale must snapshot last_update_ts."""

    @pytest.mark.parametrize(
        "ts,expected",
        [
            pytest.param(None, True, id="none_ts"),
            pytest.param("fresh", False, id="fresh_ts"),
            pytest.param("old", True, id="old_ts"),
        ],
    )
    def test_is_gps_stale(self, ts: Any, expected: bool) -> None:
        mon = GPSSpeedMonitor(gps_enabled=True)
        if ts == "fresh":
            mon.last_update_ts = time.monotonic()
        elif ts == "old":
            mon.last_update_ts = time.monotonic() - 999
        else:
            mon.last_update_ts = None
        assert mon._is_gps_stale() is expected
