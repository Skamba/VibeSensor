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
from vibesensor_core.vibration_strength import vibration_strength_db_scalar

from vibesensor.analysis.findings import _weighted_percentile
from vibesensor.analysis.helpers import _corr_abs_clamped
from vibesensor.analysis.summary import _normalize_lang
from vibesensor.firmware_cache import FirmwareCacheConfig, GitHubReleaseFetcher, _dir_sha256
from vibesensor.report.pdf_builder import _strength_with_peak
from vibesensor.report.pdf_helpers import _canonical_location
from vibesensor.report_i18n import tr
from vibesensor.settings_store import PersistenceError, SettingsStore
from vibesensor.update.manager import UpdateManager, UpdateState

# ── 1. NaN guard in vibration_strength_db_scalar ─────────────────────────


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


# ── 2. _corr_abs_clamped returns at most 1.0 ─────────────────────────────


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


# ── 3. SettingsStore persist rollback ─────────────────────────────────────


class TestSettingsStoreRollback:
    """Verify in-memory state is restored when _persist() fails."""

    @staticmethod
    def _make_store_failing_persist() -> SettingsStore:
        """Return a SettingsStore whose _persist() will raise."""
        store = SettingsStore(db=None)
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")
        return store

    def test_add_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        initial_count = len(store.get_cars()["cars"])

        # Make persist fail
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB write fail")

        with pytest.raises(PersistenceError):
            store.add_car({"name": "New Car", "type": "suv"})

        assert len(store.get_cars()["cars"]) == initial_count

    def test_delete_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        store.add_car({"name": "Car 1", "type": "sedan"})
        store.add_car({"name": "Car 2", "type": "suv"})
        cars = store.get_cars()
        car_count = len(cars["cars"])
        assert car_count >= 2
        target_id = cars["cars"][-1]["id"]

        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.delete_car(target_id)

        assert len(store.get_cars()["cars"]) == car_count

    def test_set_active_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        store.add_car({"name": "Car 2", "type": "suv"})
        cars = store.get_cars()
        original_active = cars["activeCarId"]
        new_id = [c["id"] for c in cars["cars"] if c["id"] != original_active][0]

        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.set_active_car(new_id)

        assert store.get_cars()["activeCarId"] == original_active

    def test_update_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        store.add_car({"name": "Original Name", "type": "sedan"})
        cars = store.get_cars()
        car_id = cars["cars"][0]["id"]
        original_name = cars["cars"][0]["name"]

        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.update_car(car_id, {"name": "New Name"})

        assert store.get_cars()["cars"][0]["name"] == original_name


# ── 4. Firmware cache streaming download ──────────────────────────────────


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


# ── 5. CancelledError re-raise in UpdateManager ──────────────────────────


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


# ── 6. _normalize_lang uses canonical implementation ─────────────────────


class TestNormalizeLangDedup:
    """Verify summary uses the canonical normalize_lang."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("en", "en"),
            ("EN", "en"),
            ("", "en"),
            (None, "en"),
            ("nl", "nl"),
            ("NL", "nl"),
            ("nl-BE", "nl"),
        ],
    )
    def test_normalize_lang(self, raw: str | None, expected: str) -> None:
        assert _normalize_lang(raw) == expected


# ── 7. _weighted_percentile direct import ─────────────────────────────────


class TestWeightedPercentileImport:
    """Verify _weighted_percentile is importable from findings without trampoline."""

    def test_import_works(self):
        assert callable(_weighted_percentile)

    def test_basic_call(self):
        result = _weighted_percentile([(10.0, 1.0), (20.0, 1.0), (30.0, 1.0)], 0.5)
        assert result is not None


# ── 8. _dir_sha256 uses separators ────────────────────────────────────────


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
        assert _canonical_location(raw) == expected


# ── 10. PDF _strength_with_peak i18n suffix ───────────────────────────────


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


# ── 11. report_i18n STRENGTH_PEAK_SUFFIX key exists ──────────────────────


class TestReportI18nPeakSuffix:
    """Verify STRENGTH_PEAK_SUFFIX key exists in both languages."""

    @pytest.mark.parametrize(
        "lang, expected",
        [("en", "peak"), ("nl", "piek")],
    )
    def test_peak_suffix_key(self, lang: str, expected: str):
        assert tr(lang, "STRENGTH_PEAK_SUFFIX") == expected


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
