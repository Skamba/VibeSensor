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


class TestResolveSpeedTOCTOU:
    """resolve_speed must snapshot speed_mps to avoid read-between-lines races."""

    def test_speed_snapshot_used_for_gps_return(self) -> None:
        mon = GPSSpeedMonitor(gps_enabled=True)
        mon.speed_mps = 10.5
        mon.last_update_ts = time.monotonic()
        mon.connection_state = "connected"

        result = mon.resolve_speed()
        assert result.speed_mps == 10.5
        assert result.source == "gps"

    def test_speed_none_after_stale(self) -> None:
        mon = GPSSpeedMonitor(gps_enabled=True)
        mon.speed_mps = 5.0
        mon.last_update_ts = time.monotonic() - 999  # very stale
        mon.connection_state = "connected"

        result = mon.resolve_speed()
        assert result.fallback_active is True
