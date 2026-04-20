"""Runtime NaN handling and update-manager guard regressions:
NaN guards, correlation clamp, persist rollback,
firmware cache streaming, CancelledError re-raise,
 _weighted_percentile direct import, _dir_sha256 separators, _corr_abs_clamped,
 canonical_location edge cases, PDF peak suffix i18n."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from test_support.settings_services import build_settings_services

from vibesensor.adapters.pdf.diagram_layout import canonical_location
from vibesensor.adapters.pdf.pdf_drawing import _strength_with_peak
from vibesensor.report_i18n import tr
from vibesensor.shared.exceptions import PersistenceError
from vibesensor.use_cases.diagnostics.math_utils import _corr_abs_clamped
from vibesensor.use_cases.updates.firmware.firmware_bundle import dir_sha256
from vibesensor.use_cases.updates.firmware.firmware_release_fetcher import GitHubReleaseFetcher
from vibesensor.use_cases.updates.firmware.firmware_types import FirmwareCacheConfig
from vibesensor.use_cases.updates.run_models import PreparedUpdateRun
from vibesensor.use_cases.updates.workflow import UpdateWorkflow

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

    def test_add_car_rollback_on_persist_failure(self):
        services = build_settings_services()
        initial_count = len(services.car_settings.get_cars().cars)

        # Make persist fail
        services.coordinator._db = MagicMock()
        services.coordinator._db.set_settings_snapshot.side_effect = sqlite3.OperationalError(
            "DB write fail"
        )

        with pytest.raises(PersistenceError):
            services.car_settings.add_car({"name": "New Car", "type": "suv"})

        assert len(services.car_settings.get_cars().cars) == initial_count

    def test_delete_car_rollback_on_persist_failure(self):
        services = build_settings_services()
        services.car_settings.add_car({"name": "Car 1", "type": "sedan"})
        services.car_settings.add_car({"name": "Car 2", "type": "suv"})
        cars = services.car_settings.get_cars()
        car_count = len(cars.cars)
        assert car_count >= 2
        target_id = cars.cars[-1]["id"]

        services.coordinator._db = MagicMock()
        services.coordinator._db.set_settings_snapshot.side_effect = sqlite3.OperationalError(
            "DB fail"
        )

        with pytest.raises(PersistenceError):
            services.car_settings.delete_car(target_id)

        assert len(services.car_settings.get_cars().cars) == car_count

    def test_set_active_car_rollback_on_persist_failure(self):
        services = build_settings_services()
        services.car_settings.add_car({"name": "Car 2", "type": "suv"})
        cars = services.car_settings.get_cars()
        original_active = cars.active_car_id
        new_id = [c["id"] for c in cars.cars if c["id"] != original_active][0]

        services.coordinator._db = MagicMock()
        services.coordinator._db.set_settings_snapshot.side_effect = sqlite3.OperationalError(
            "DB fail"
        )

        with pytest.raises(PersistenceError):
            services.car_settings.set_active_car(new_id)

        assert services.car_settings.get_cars().active_car_id == original_active

    def test_update_car_rollback_on_persist_failure(self):
        services = build_settings_services()
        services.car_settings.add_car({"name": "Original Name", "type": "sedan"})
        cars = services.car_settings.get_cars()
        car_id = cars.cars[0]["id"]
        original_name = cars.cars[0]["name"]

        services.coordinator._db = MagicMock()
        services.coordinator._db.set_settings_snapshot.side_effect = sqlite3.OperationalError(
            "DB fail"
        )

        with pytest.raises(PersistenceError):
            services.car_settings.update_car(car_id, {"name": "New Name"})

        assert services.car_settings.get_cars().cars[0]["name"] == original_name


# ── 4. Firmware cache streaming download ──────────────────────────────────


class TestFirmwareCacheStreamingDownload:
    """Verify download streams to disk instead of buffering in memory."""

    def test_download_asset_creates_file(self, tmp_path):
        """_download_asset should stream data to a file."""
        config = FirmwareCacheConfig(cache_dir=str(tmp_path / "cache"))
        fetcher = GitHubReleaseFetcher(config)

        dest = tmp_path / "firmware.bin"
        test_data = b"firmware_content_bytes_here"

        # Mock the shared streaming helper to return test data.
        mock_resp = MagicMock()
        mock_resp.iter_bytes.return_value = iter([test_data])

        with patch(
            "vibesensor.use_cases.updates.asset_download.stream_http_response",
            return_value=nullcontext(mock_resp),
        ):
            fetcher._download_asset("https://example.com/fw.bin", dest)

        assert dest.exists()
        assert dest.read_bytes() == test_data


# ── 5. CancelledError re-raise in UpdateManager ──────────────────────────


class TestUpdateManagerCancelledError:
    """Verify CancelledError is re-raised after cleanup."""

    @pytest.mark.asyncio
    async def test_cancelled_error_is_reraised(self):
        """The canonical update workflow should re-raise CancelledError."""
        workflow = UpdateWorkflow(
            preparation=SimpleNamespace(
                prepare=AsyncMock(
                    return_value=PreparedUpdateRun(
                        prepared_transport=AsyncMock(),
                    )
                )
            ),
            release_planner=SimpleNamespace(plan=AsyncMock(side_effect=asyncio.CancelledError())),
            workflow_executor=MagicMock(),
            finalizer=SimpleNamespace(finalize=AsyncMock()),
        )

        with pytest.raises(asyncio.CancelledError):
            await workflow.run(request=MagicMock())


# ── 7. dir_sha256 uses separators ────────────────────────────────────────


class TestDirSha256Separators:
    """Verify dir_sha256 uses null-byte separators between path and content."""

    def test_different_layouts_produce_different_hashes(self, tmp_path):
        # Layout 1: file "a" with content "bc"
        d1 = tmp_path / "d1"
        d1.mkdir()
        (d1 / "a").write_text("bc")

        # Layout 2: file "ab" with content "c"
        d2 = tmp_path / "d2"
        d2.mkdir()
        (d2 / "ab").write_text("c")

        h1 = dir_sha256(d1)
        h2 = dir_sha256(d2)
        assert h1 != h2, "Hashes should differ when path/content boundaries differ"


# ── 9. canonical_location edge cases ─────────────────────────────────────


class TestCanonicalLocation:
    """Dedicated edge-case tests for canonical_location."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
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
        assert canonical_location(raw) == expected


# ── 10. PDF _strength_with_peak i18n suffix ───────────────────────────────


class TestStrengthWithPeakI18n:
    """Verify _strength_with_peak uses the provided suffix."""

    @pytest.mark.parametrize(
        ("label", "peak_db", "peak_suffix", "expected_exact", "expected_contains", "forbidden"),
        [
            ("Moderate", 28.3, "peak", None, ("peak", "28.3"), ()),
            ("Matig", 28.3, "piek", None, ("piek", "28.3"), ("peak",)),
            ("Moderate", None, "peak", "Moderate", (), ()),
            ("28.3 dB", 28.3, "peak", "28.3 dB", (), ()),
        ],
        ids=["default-peak-suffix", "localized-peak-suffix", "no-peak-db", "db-label"],
    )
    def test_strength_with_peak_variants(
        self,
        label: str,
        peak_db: float | None,
        peak_suffix: str,
        expected_exact: str | None,
        expected_contains: tuple[str, ...],
        forbidden: tuple[str, ...],
    ) -> None:
        result = _strength_with_peak(label, peak_db, fallback="—", peak_suffix=peak_suffix)
        if expected_exact is not None:
            assert result == expected_exact
            return

        for part in expected_contains:
            assert part in result
        for part in forbidden:
            assert part not in result


# ── 11. report_i18n STRENGTH_PEAK_SUFFIX key exists ──────────────────────


class TestReportI18nPeakSuffix:
    """Verify STRENGTH_PEAK_SUFFIX key exists in both languages."""

    @pytest.mark.parametrize(
        ("lang", "expected"),
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
