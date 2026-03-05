"""Runtime NaN handling and update-manager guard regressions:
NaN guards, correlation clamp, persist rollback,
firmware cache streaming, CancelledError re-raise, _normalize_lang dedup,
_weighted_percentile direct import, _dir_sha256 separators, _corr_abs_clamped,
_canonical_location edge cases, PDF peak suffix i18n."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from vibesensor.report.pdf_builder import _strength_with_peak
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


class TestStrengthWithPeakI18n:
    """Verify _strength_with_peak uses the provided suffix."""

    def test_default_suffix_is_peak(self):
        result = _strength_with_peak("Moderate", 28.3, fallback="—")
        assert "peak" in result
        assert "28.3" in result

    def test_nl_suffix(self):
        result = _strength_with_peak("Matig", 28.3, fallback="—", peak_suffix="piek")
        assert "piek" in result
        assert "peak" not in result
        assert "28.3" in result

    def test_no_peak_db(self):
        result = _strength_with_peak("Moderate", None, fallback="—")
        assert result == "Moderate"

    def test_db_in_label_skips_suffix(self):
        result = _strength_with_peak("28.3 dB", 28.3, fallback="—")
        assert result == "28.3 dB"  # no suffix appended
