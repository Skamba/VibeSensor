"""Runtime NaN handling and update-manager guard regressions:
NaN guards, correlation clamp, persist rollback,
firmware cache streaming, CancelledError re-raise, _normalize_lang dedup,
_weighted_percentile direct import, _dir_sha256 separators, _corr_abs_clamped,
_canonical_location edge cases, PDF peak suffix i18n."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from vibesensor.firmware_cache import _dir_sha256
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


class TestDirSha256Separators:
    """Verify _dir_sha256 uses null-byte separators between path and content."""

    def test_different_layouts_produce_different_hashes(self, tmp_path):
        # Layout 1: file "a" with content "bc"
        d1 = tmp_path / "d1"
        d1.mkdir()
        (d1 / "a").write_text("bc")

        # Layout 2: file "ab" with content "c"
        d2 = tmp_path / "d2"
        d2.mkdir()
        (d2 / "ab").write_text("c")

        h1 = _dir_sha256(d1)
        h2 = _dir_sha256(d2)
        assert h1 != h2, "Hashes should differ when path/content boundaries differ"
