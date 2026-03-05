"""Runtime NaN handling and update-manager guard regressions:
NaN guards, correlation clamp, persist rollback,
firmware cache streaming, CancelledError re-raise, _normalize_lang dedup,
_weighted_percentile direct import, _dir_sha256 separators, _corr_abs_clamped,
_canonical_location edge cases, PDF peak suffix i18n."""

from __future__ import annotations

import asyncio
import math
from unittest.mock import MagicMock

import pytest
from vibesensor_core.vibration_strength import vibration_strength_db_scalar

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


class TestVibrationStrengthNanGuard:
    """Verify NaN inputs do not propagate through vibration_strength_db_scalar."""

    @pytest.mark.parametrize(
        "peak, floor",
        [
            (0.001, float("nan")),
            (float("nan"), 0.001),
            (float("nan"), float("nan")),
            (0.001, float("inf")),
        ],
    )
    def test_non_finite_input_returns_finite(self, peak: float, floor: float) -> None:
        result = vibration_strength_db_scalar(peak_band_rms_amp_g=peak, floor_amp_g=floor)
        assert math.isfinite(result), f"Expected finite, got {result}"

    def test_normal_values_unchanged(self):
        result = vibration_strength_db_scalar(peak_band_rms_amp_g=0.01, floor_amp_g=0.001)
        assert math.isfinite(result)
        assert result > 0  # peak > floor → positive dB
