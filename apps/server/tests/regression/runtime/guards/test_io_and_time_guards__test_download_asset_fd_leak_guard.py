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
from unittest.mock import MagicMock, patch

import pytest

from vibesensor.firmware_cache import FirmwareCacheConfig, GitHubReleaseFetcher


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


class TestDownloadAssetFdLeakGuard:
    """When os.fdopen fails, the raw fd must be closed."""

    def test_fd_closed_when_fdopen_fails(self, tmp_path: Path) -> None:
        cfg = FirmwareCacheConfig(firmware_repo="test/repo")
        fetcher = GitHubReleaseFetcher(cfg)

        dest = tmp_path / "firmware.bin"

        # Patch urlopen to provide a fake response, and os.fdopen to fail
        fake_resp = MagicMock()
        fake_resp.read.return_value = b"data"
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: None

        with (
            patch("vibesensor.firmware_cache.urlopen", return_value=fake_resp),
            patch("os.fdopen", side_effect=OSError("mock fdopen failure")),
            patch("os.close") as mock_close,
        ):
            with pytest.raises(OSError, match="mock fdopen failure"):
                fetcher._download_asset("https://example.com/fw.bin", dest)

            # os.close should have been called with the leaked fd
            assert mock_close.called
