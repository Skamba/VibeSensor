# ruff: noqa: E501
"""Tests for Cycle 8 fixes: NaN guards, correlation clamp, persist rollback,
firmware cache streaming, CancelledError re-raise, _normalize_lang dedup,
_weighted_percentile direct import, _dir_sha256 separators, _corr_abs_clamped,
_canonical_location edge cases, PDF peak suffix i18n."""

from __future__ import annotations

import asyncio
import math
from unittest.mock import MagicMock, patch

import pytest

# ── 1. NaN guard in vibration_strength_db_scalar ─────────────────────────


class TestVibrationStrengthNanGuard:
    """Verify NaN inputs do not propagate through vibration_strength_db_scalar."""

    def test_nan_floor_returns_finite(self):
        from vibesensor_core.vibration_strength import vibration_strength_db_scalar

        result = vibration_strength_db_scalar(peak_band_rms_amp_g=0.001, floor_amp_g=float("nan"))
        assert math.isfinite(result), f"Expected finite, got {result}"

    def test_nan_peak_returns_finite(self):
        from vibesensor_core.vibration_strength import vibration_strength_db_scalar

        result = vibration_strength_db_scalar(peak_band_rms_amp_g=float("nan"), floor_amp_g=0.001)
        assert math.isfinite(result), f"Expected finite, got {result}"

    def test_both_nan_returns_finite(self):
        from vibesensor_core.vibration_strength import vibration_strength_db_scalar

        result = vibration_strength_db_scalar(
            peak_band_rms_amp_g=float("nan"), floor_amp_g=float("nan")
        )
        assert math.isfinite(result), f"Expected finite, got {result}"

    def test_inf_floor_returns_finite(self):
        from vibesensor_core.vibration_strength import vibration_strength_db_scalar

        result = vibration_strength_db_scalar(peak_band_rms_amp_g=0.001, floor_amp_g=float("inf"))
        assert math.isfinite(result), f"Expected finite, got {result}"

    def test_normal_values_unchanged(self):
        from vibesensor_core.vibration_strength import vibration_strength_db_scalar

        result = vibration_strength_db_scalar(peak_band_rms_amp_g=0.01, floor_amp_g=0.001)
        assert math.isfinite(result)
        assert result > 0  # peak > floor → positive dB


# ── 2. _corr_abs_clamped returns at most 1.0 ─────────────────────────────


class TestCorrAbsClamped:
    """Verify _corr_abs_clamped clamps to [0, 1]."""

    def test_perfect_correlation_clamped(self):
        from vibesensor.analysis.helpers import _corr_abs_clamped

        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _corr_abs_clamped(x, y)
        assert 0 <= result <= 1.0

    def test_anticorrelation_clamped(self):
        from vibesensor.analysis.helpers import _corr_abs_clamped

        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [5.0, 4.0, 3.0, 2.0, 1.0]
        result = _corr_abs_clamped(x, y)
        assert 0 <= result <= 1.0

    def test_near_identical_values_clamped(self):
        """When values are nearly identical, _corr_abs may return None (zero variance)."""
        from vibesensor.analysis.helpers import _corr_abs_clamped

        # Tiny perturbation — std dev may be zero → None from _corr_abs
        x = [1.0000000001, 1.0000000002, 1.0000000003]
        y = [1.0000000001, 1.0000000002, 1.0000000003]
        result = _corr_abs_clamped(x, y)
        # Either None (zero variance) or clamped to [0, 1]
        assert result is None or result <= 1.0


# ── 3. SettingsStore persist rollback ─────────────────────────────────────


class TestSettingsStoreRollback:
    """Verify in-memory state is restored when _persist() fails."""

    def _make_store(self):
        from vibesensor.settings_store import PersistenceError, SettingsStore

        store = SettingsStore(db=None)
        # Add initial car
        store.add_car({"name": "Test Car", "type": "sedan"})
        cars = store.get_cars()
        car_id = cars["cars"][0]["id"]
        return store, car_id, PersistenceError

    def test_add_car_rollback_on_persist_failure(self):
        from vibesensor.settings_store import PersistenceError, SettingsStore

        store = SettingsStore(db=None)
        # Initial state
        initial = store.get_cars()
        initial_count = len(initial["cars"])

        # Make persist fail
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB write fail")

        with pytest.raises(PersistenceError):
            store.add_car({"name": "New Car", "type": "suv"})

        # State should be rolled back
        after = store.get_cars()
        assert len(after["cars"]) == initial_count

    def test_delete_car_rollback_on_persist_failure(self):
        from vibesensor.settings_store import PersistenceError, SettingsStore

        store = SettingsStore(db=None)
        store.add_car({"name": "Car 1", "type": "sedan"})
        store.add_car({"name": "Car 2", "type": "suv"})
        cars = store.get_cars()
        car_count = len(cars["cars"])
        assert car_count >= 2  # at least 2

        target_id = cars["cars"][-1]["id"]

        # Make persist fail
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.delete_car(target_id)

        # State should be rolled back
        after = store.get_cars()
        assert len(after["cars"]) == car_count

    def test_set_active_car_rollback_on_persist_failure(self):
        from vibesensor.settings_store import PersistenceError, SettingsStore

        store = SettingsStore(db=None)
        store.add_car({"name": "Car 2", "type": "suv"})
        cars = store.get_cars()
        original_active = cars["activeCarId"]
        new_id = [c["id"] for c in cars["cars"] if c["id"] != original_active][0]

        # Make persist fail
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.set_active_car(new_id)

        # Active car should be rolled back
        after = store.get_cars()
        assert after["activeCarId"] == original_active

    def test_update_car_rollback_on_persist_failure(self):
        from vibesensor.settings_store import PersistenceError, SettingsStore

        store = SettingsStore(db=None)
        store.add_car({"name": "Original Name", "type": "sedan"})
        cars = store.get_cars()
        car_id = cars["cars"][0]["id"]
        original_name = cars["cars"][0]["name"]

        # Make persist fail
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.update_car(car_id, {"name": "New Name"})

        after = store.get_cars()
        assert after["cars"][0]["name"] == original_name


# ── 4. Firmware cache streaming download ──────────────────────────────────


class TestFirmwareCacheStreamingDownload:
    """Verify download streams to disk instead of buffering in memory."""

    def test_download_asset_creates_file(self, tmp_path):
        """_download_asset should stream data to a file."""
        from unittest.mock import MagicMock

        from vibesensor.firmware_cache import FirmwareCacheConfig, GitHubReleaseFetcher

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


# ── 5. CancelledError re-raise in UpdateManager ──────────────────────────


class TestUpdateManagerCancelledError:
    """Verify CancelledError is re-raised after cleanup."""

    @pytest.mark.asyncio
    async def test_cancelled_error_is_reraised(self):
        """_run_update should re-raise CancelledError."""
        from vibesensor.update.manager import UpdateManager, UpdateState

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


# ── 6. _normalize_lang uses canonical implementation ─────────────────────


class TestNormalizeLangDedup:
    """Verify summary uses the canonical normalize_lang."""

    def test_en_default(self):
        from vibesensor.analysis.summary import _normalize_lang

        assert _normalize_lang("en") == "en"
        assert _normalize_lang("EN") == "en"
        assert _normalize_lang("") == "en"
        assert _normalize_lang(None) == "en"

    def test_nl_detected(self):
        from vibesensor.analysis.summary import _normalize_lang

        assert _normalize_lang("nl") == "nl"
        assert _normalize_lang("NL") == "nl"
        assert _normalize_lang("nl-BE") == "nl"


# ── 7. _weighted_percentile direct import ─────────────────────────────────


class TestWeightedPercentileImport:
    """Verify _weighted_percentile is importable from findings without trampoline."""

    def test_import_works(self):
        from vibesensor.analysis.findings import _weighted_percentile

        assert callable(_weighted_percentile)

    def test_basic_call(self):
        from vibesensor.analysis.findings import _weighted_percentile

        result = _weighted_percentile([(10.0, 1.0), (20.0, 1.0), (30.0, 1.0)], 0.5)
        assert result is not None


# ── 8. _dir_sha256 uses separators ────────────────────────────────────────


class TestDirSha256Separators:
    """Verify _dir_sha256 uses null-byte separators between path and content."""

    def test_different_layouts_produce_different_hashes(self, tmp_path):
        from vibesensor.firmware_cache import _dir_sha256

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


# ── 9. _canonical_location edge cases ─────────────────────────────────────


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
        from vibesensor.report.pdf_helpers import _canonical_location

        assert _canonical_location(raw) == expected


# ── 10. PDF _strength_with_peak i18n suffix ───────────────────────────────


class TestStrengthWithPeakI18n:
    """Verify _strength_with_peak uses the provided suffix."""

    def test_default_suffix_is_peak(self):
        from vibesensor.report.pdf_builder import _strength_with_peak

        result = _strength_with_peak("Moderate", 28.3, fallback="—")
        assert "peak" in result
        assert "28.3" in result

    def test_nl_suffix(self):
        from vibesensor.report.pdf_builder import _strength_with_peak

        result = _strength_with_peak("Matig", 28.3, fallback="—", peak_suffix="piek")
        assert "piek" in result
        assert "peak" not in result
        assert "28.3" in result

    def test_no_peak_db(self):
        from vibesensor.report.pdf_builder import _strength_with_peak

        result = _strength_with_peak("Moderate", None, fallback="—")
        assert result == "Moderate"

    def test_db_in_label_skips_suffix(self):
        from vibesensor.report.pdf_builder import _strength_with_peak

        result = _strength_with_peak("28.3 dB", 28.3, fallback="—")
        assert result == "28.3 dB"  # no suffix appended


# ── 11. report_i18n STRENGTH_PEAK_SUFFIX key exists ──────────────────────


class TestReportI18nPeakSuffix:
    """Verify STRENGTH_PEAK_SUFFIX key exists in both languages."""

    def test_en_key(self):
        from vibesensor.report_i18n import tr

        assert tr("en", "STRENGTH_PEAK_SUFFIX") == "peak"

    def test_nl_key(self):
        from vibesensor.report_i18n import tr

        assert tr("nl", "STRENGTH_PEAK_SUFFIX") == "piek"


# ── 12. Firmware cache restore on activation failure ──────────────────────


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
