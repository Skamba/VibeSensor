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

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from vibesensor.firmware_cache import FirmwareCache, FirmwareCacheConfig


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


class TestFirmwareCacheRefreshUnboundGuard:
    """target/old_current must be defined before the try block so the
    except handler never raises UnboundLocalError."""

    def test_exception_before_activation_does_not_raise_unbound(self, tmp_path: Path) -> None:
        """If download_bundle raises, the except block should not crash."""
        cfg = FirmwareCacheConfig(
            firmware_repo="test/repo",
            cache_dir=str(tmp_path / "fw"),
        )
        cache = FirmwareCache(cfg)

        # Fake fetcher that raises during download
        fetcher = MagicMock()
        fetcher.find_release.return_value = {"tag_name": "v999"}
        fetcher.find_firmware_asset.return_value = {"name": "fw.zip"}
        fetcher.download_bundle.side_effect = RuntimeError("download failed")

        with pytest.raises(RuntimeError, match="download failed"):
            cache.refresh(fetcher=fetcher)
