"""Runtime NaN handling and update-manager guard regressions:
NaN guards, correlation clamp, persist rollback,
firmware cache streaming, CancelledError re-raise, _normalize_lang dedup,
_weighted_percentile direct import, _dir_sha256 separators, _corr_abs_clamped,
_canonical_location edge cases, PDF peak suffix i18n."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from vibesensor.analysis.helpers import _corr_abs_clamped
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


class TestCorrAbsClamped:
    """Verify _corr_abs_clamped clamps to [0, 1]."""

    def test_perfect_correlation_clamped(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _corr_abs_clamped(x, y)
        assert 0 <= result <= 1.0

    def test_anticorrelation_clamped(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [5.0, 4.0, 3.0, 2.0, 1.0]
        result = _corr_abs_clamped(x, y)
        assert 0 <= result <= 1.0

    def test_near_identical_values_clamped(self):
        """When values are nearly identical, _corr_abs may return None (zero variance)."""
        # Tiny perturbation — std dev may be zero → None from _corr_abs
        x = [1.0000000001, 1.0000000002, 1.0000000003]
        y = [1.0000000001, 1.0000000002, 1.0000000003]
        result = _corr_abs_clamped(x, y)
        # Either None (zero variance) or clamped to [0, 1]
        assert result is None or result <= 1.0
