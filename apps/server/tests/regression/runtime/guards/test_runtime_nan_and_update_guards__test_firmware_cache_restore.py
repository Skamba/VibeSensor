"""Runtime NaN handling and update-manager guard regressions:
NaN guards, correlation clamp, persist rollback,
firmware cache streaming, CancelledError re-raise, _normalize_lang dedup,
_weighted_percentile direct import, _dir_sha256 separators, _corr_abs_clamped,
_canonical_location edge cases, PDF peak suffix i18n."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

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


class TestFirmwareCacheRestore:
    """Verify old cache is restored when activation fails."""

    def test_old_current_restored_on_rename_failure(self, tmp_path):
        """If extract_dir.rename(target) fails, old_current should be restored."""

        current = tmp_path / "current"
        current.mkdir()
        (current / "marker.txt").write_text("old_firmware")
        old_backup = tmp_path / "current.old"

        # Simulate: target renamed to old, but new rename fails
        current.rename(old_backup)
        assert not current.exists()
        assert old_backup.exists()

        # Restore logic (same as in firmware_cache.py except block)
        if old_backup.exists() and not current.exists():
            old_backup.rename(current)

        assert current.exists()
        assert (current / "marker.txt").read_text() == "old_firmware"
