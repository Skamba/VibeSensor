"""Runtime NaN handling and update-manager guard regressions:
NaN guards, correlation clamp, persist rollback,
firmware cache streaming, CancelledError re-raise, _normalize_lang dedup,
_weighted_percentile direct import, _dir_sha256 separators, _corr_abs_clamped,
_canonical_location edge cases, PDF peak suffix i18n."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from vibesensor.report.pdf_helpers import _canonical_location
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


class TestCanonicalLocation:
    """Dedicated edge-case tests for _canonical_location."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, ""),
            ("", ""),
            ("Front Left Wheel", "front-left wheel"),
            ("front_left_wheel", "front-left wheel"),
            ("FL", "front-left wheel"),
            ("FLwheel", "front-left wheel"),
            ("Front Right Wheel", "front-right wheel"),
            ("FR", "front-right wheel"),
            ("Rear Left Wheel", "rear-left wheel"),
            ("RL", "rear-left wheel"),
            ("Rear Right Wheel", "rear-right wheel"),
            ("RR", "rear-right wheel"),
            ("trunk", "trunk"),
            ("TRUNK", "trunk"),
            ("driveshaft tunnel", "driveshaft tunnel"),
            ("tunnel", "driveshaft tunnel"),
            ("engine bay", "engine bay"),
            ("Engine Bay", "engine bay"),
            ("driver seat", "driver seat"),
            ("Driver Seat", "driver seat"),
            ("dashboard", "dashboard"),
        ],
    )
    def test_canonical(self, raw, expected):
        assert _canonical_location(raw) == expected
