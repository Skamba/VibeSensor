"""Tests for Cycle 2 (session 3) fixes – a.k.a. cycle-11 in the global sequence.

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
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ------------------------------------------------------------------
# 1. firmware_cache.refresh() – UnboundLocalError guard
# ------------------------------------------------------------------

class TestFirmwareCacheRefreshUnboundGuard:
    """target/old_current must be defined before the try block so the
    except handler never raises UnboundLocalError."""

    def test_exception_before_activation_does_not_raise_unbound(self, tmp_path: Path) -> None:
        """If download_bundle raises, the except block should not crash."""
        from vibesensor.firmware_cache import FirmwareCache, FirmwareCacheConfig

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

        # The key assertion is that we got RuntimeError, NOT UnboundLocalError.


# ------------------------------------------------------------------
# 2. firmware_cache._download_asset() – fd leak guard
# ------------------------------------------------------------------

class TestDownloadAssetFdLeakGuard:
    """When os.fdopen fails, the raw fd must be closed."""

    def test_fd_closed_when_fdopen_fails(self, tmp_path: Path) -> None:
        from vibesensor.firmware_cache import FirmwareCacheConfig, GitHubReleaseFetcher

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


# ------------------------------------------------------------------
# 3. gps_speed.resolve_speed() – TOCTOU snapshot
# ------------------------------------------------------------------

class TestResolveSpeedTOCTOU:
    """resolve_speed must snapshot speed_mps to avoid read-between-lines races."""

    def test_speed_snapshot_used_for_gps_return(self) -> None:
        from vibesensor.gps_speed import GPSSpeedMonitor

        mon = GPSSpeedMonitor(gps_enabled=True)
        mon.speed_mps = 10.5
        mon.last_update_ts = time.monotonic()
        mon.connection_state = "connected"

        result = mon.resolve_speed()
        assert result.speed_mps == 10.5
        assert result.source == "gps"

    def test_speed_none_after_stale(self) -> None:
        from vibesensor.gps_speed import GPSSpeedMonitor

        mon = GPSSpeedMonitor(gps_enabled=True)
        mon.speed_mps = 5.0
        mon.last_update_ts = time.monotonic() - 999  # very stale
        mon.connection_state = "connected"

        result = mon.resolve_speed()
        assert result.fallback_active is True


# ------------------------------------------------------------------
# 4. gps_speed._is_gps_stale() – TOCTOU snapshot
# ------------------------------------------------------------------

class TestIsGpsStaleTOCTOU:
    """_is_gps_stale must snapshot last_update_ts."""

    def test_none_ts_is_stale(self) -> None:
        from vibesensor.gps_speed import GPSSpeedMonitor

        mon = GPSSpeedMonitor(gps_enabled=True)
        mon.last_update_ts = None
        assert mon._is_gps_stale() is True

    def test_fresh_ts_not_stale(self) -> None:
        from vibesensor.gps_speed import GPSSpeedMonitor

        mon = GPSSpeedMonitor(gps_enabled=True)
        mon.last_update_ts = time.monotonic()
        assert mon._is_gps_stale() is False

    def test_old_ts_is_stale(self) -> None:
        from vibesensor.gps_speed import GPSSpeedMonitor

        mon = GPSSpeedMonitor(gps_enabled=True)
        mon.last_update_ts = time.monotonic() - 999
        assert mon._is_gps_stale() is True


# ------------------------------------------------------------------
# 5. report_cli – PDF generation error handling
# ------------------------------------------------------------------

class TestReportCliErrorHandling:
    """PDF generation failures should return exit code 1, not raise."""

    def test_pdf_build_failure_returns_1(self, tmp_path: Path) -> None:
        from vibesensor.report_cli import main

        run_file = tmp_path / "test_run.jsonl"
        run_file.write_text('{"event": "meta"}\n')

        with (
            patch("vibesensor.report_cli.summarize_log", return_value={"some": "summary"}),
            patch(
                "vibesensor.report_cli.build_report_pdf",
                side_effect=RuntimeError("PDF engine failed"),
            ),
            patch("vibesensor.report_cli.map_summary", return_value={}),
            patch(
                "vibesensor.report_cli.parse_args",
                return_value=MagicMock(
                    input=run_file, output=None, summary_json=None
                ),
            ),
        ):
            result = main()
            assert result == 1

    def test_pdf_build_success_returns_0(self, tmp_path: Path) -> None:
        from vibesensor.report_cli import main

        run_file = tmp_path / "test_run.jsonl"
        run_file.write_text('{"event": "meta"}\n')

        with (
            patch("vibesensor.report_cli.summarize_log", return_value={"some": "summary"}),
            patch("vibesensor.report_cli.build_report_pdf", return_value=b"%PDF-1.4 fake"),
            patch("vibesensor.report_cli.map_summary", return_value={}),
            patch(
                "vibesensor.report_cli.parse_args",
                return_value=MagicMock(
                    input=run_file, output=tmp_path / "out.pdf", summary_json=None
                ),
            ),
        ):
            result = main()
            assert result == 0
            assert (tmp_path / "out.pdf").exists()


# ------------------------------------------------------------------
# 6. report_data_builder – UTC suffix on date_str
# ------------------------------------------------------------------

class TestReportDataBuilderUTCSuffix:
    """date_str in report data must end with ' UTC'."""

    def test_date_str_has_utc_suffix(self) -> None:
        from vibesensor.analysis.report_data_builder import map_summary

        summary: dict[str, Any] = {
            "lang": "en",
            "report_date": "2025-06-01T14:30:00Z",
            "metadata": {"car_name": "TestCar"},
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
        result = map_summary(summary)
        assert result.run_datetime is not None
        assert result.run_datetime.endswith(" UTC"), (
            f"Expected UTC suffix, got: {result.run_datetime!r}"
        )
        assert "2025-06-01 14:30:00" in result.run_datetime

    def test_date_str_no_tz_input_still_has_utc(self) -> None:
        from vibesensor.analysis.report_data_builder import map_summary

        summary: dict[str, Any] = {
            "lang": "en",
            "report_date": "2025-03-15T09:45:22",
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
        result = map_summary(summary)
        assert result.run_datetime == "2025-03-15 09:45:22 UTC"
