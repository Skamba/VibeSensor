"""Runtime NaN handling and update-manager guard regressions:
NaN guards, correlation clamp, persist rollback,
firmware cache streaming, CancelledError re-raise, _normalize_lang dedup,
_weighted_percentile direct import, _dir_sha256 separators, _corr_abs_clamped,
_canonical_location edge cases, PDF peak suffix i18n."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from vibesensor.firmware_cache import FirmwareCacheConfig, GitHubReleaseFetcher
from vibesensor.update.manager import UpdateManager, UpdateState


class TestUpdateManagerCancelledError:
    """Verify CancelledError is re-raised after cleanup."""

    @pytest.mark.asyncio
    async def test_cancelled_error_is_reraised(self):
        """_run_update should re-raise CancelledError."""
        mgr = UpdateManager.__new__(UpdateManager)
        mgr._status = MagicMock()
        mgr._status.phase = MagicMock()
        mgr._status.state = UpdateState.running
        mgr._status.issues = []
        mgr._status.finished_at = None
        mgr._log_lines = []
        mgr._redact_secrets = set()
        mgr._state_store = MagicMock()
        mgr._state_store.save = MagicMock()

        async def mock_inner(ssid, password):
            raise asyncio.CancelledError()

        mgr._run_update_inner = mock_inner
        mgr._add_issue = MagicMock()
        mgr._log = MagicMock()
        mgr._persist_status = MagicMock()

        async def noop_restore():
            pass

        mgr._restore_hotspot = noop_restore
        mgr._collect_runtime_details = MagicMock(return_value={})

        with pytest.raises(asyncio.CancelledError):
            await mgr._run_update("ssid", "pass")


class TestFirmwareCacheStreamingDownload:
    """Verify download streams to disk instead of buffering in memory."""

    def test_download_asset_creates_file(self, tmp_path):
        """_download_asset should stream data to a file."""
        config = FirmwareCacheConfig(cache_dir=str(tmp_path / "cache"))
        fetcher = GitHubReleaseFetcher(config)

        dest = tmp_path / "firmware.bin"
        test_data = b"firmware_content_bytes_here"

        # Mock urlopen to return test data
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [test_data, b""]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: None

        with patch("vibesensor.firmware_cache.urlopen", return_value=mock_resp):
            fetcher._download_asset("https://example.com/fw.bin", dest)

        assert dest.exists()
        assert dest.read_bytes() == test_data
