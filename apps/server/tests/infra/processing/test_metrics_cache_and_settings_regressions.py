"""Metrics cache, settings rollback, and counter-delta regressions."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from test_support.settings_services import PersistedSettingsServices, build_settings_services

from vibesensor.domain import normalize_sensor_id
from vibesensor.infra.processing import ClientBuffer, SignalProcessor
from vibesensor.shared.exceptions import PersistenceError
from vibesensor.use_cases.diagnostics._counters import counter_delta

# ---------------------------------------------------------------------------
# counter_delta shared helper
# ---------------------------------------------------------------------------


class TestCounterDelta:
    """Test the shared counter_delta helper extracted from findings/summary."""

    def test_empty_list(self) -> None:
        assert counter_delta([]) == 0

    def test_single_value(self) -> None:
        assert counter_delta([5.0]) == 0

    def test_monotonic_increase(self) -> None:
        assert counter_delta([0.0, 1.0, 3.0, 6.0]) == 6

    def test_reset_ignored(self) -> None:
        # Counter resets (decreases) should be ignored, only increases counted
        assert counter_delta([0.0, 5.0, 2.0, 7.0]) == 10  # 5 + 0 + 5

    def test_all_same_value(self) -> None:
        assert counter_delta([3.0, 3.0, 3.0]) == 0

    def test_negative_values(self) -> None:
        assert counter_delta([-2.0, 0.0, 3.0]) == 5  # 2 + 3

    def test_float_precision(self) -> None:
        result = counter_delta([0.0, 0.1, 0.3])
        assert result == 0  # int truncation of 0.3


# ---------------------------------------------------------------------------
# ClientBuffer.invalidate_caches
# ---------------------------------------------------------------------------


class TestClientBufferInvalidateCaches:
    """Verify the extracted invalidate_caches method works correctly."""

    def test_clears_all_cache_fields(self) -> None:
        buf = ClientBuffer(
            data=np.zeros((3, 100), dtype=np.float32),
            capacity=100,
        )
        # Simulate cached state
        buf.cached_spectrum_payload = {"freq": [1, 2]}
        buf.cached_spectrum_payload_generation = 5

        buf.invalidate_caches()

        assert buf.cached_spectrum_payload is None
        assert buf.cached_spectrum_payload_generation == -1


# ---------------------------------------------------------------------------
# SignalProcessor compute_metrics generation guard
# ---------------------------------------------------------------------------


class TestComputeMetricsGenerationGuard:
    """Phase 3 should not overwrite fresher results with stale ones."""

    def test_stale_generation_does_not_overwrite(self) -> None:
        sp = SignalProcessor(
            sample_rate_hz=1000,
            waveform_seconds=2,
            waveform_display_hz=50,
            fft_n=256,
        )
        client = "test-client"
        # Ingest enough samples to compute
        chunk = np.random.default_rng(42).standard_normal((512, 3)).astype(np.float32) * 0.01
        sp.ingest(client, chunk, sample_rate_hz=1000)

        # First compute
        sp.compute_metrics(client)

        with sp._store.lock:
            buf = sp._store.buffers[client]
            gen_after_first = buf.compute_generation
            # Artificially advance the compute generation to simulate a fresher result
            buf.compute_generation = gen_after_first + 100

        # Compute again — this should NOT overwrite because snap_ingest_gen < compute_generation
        sp.compute_metrics(client)

        with sp._store.lock:
            buf = sp._store.buffers[client]
            # Should still be the artificially advanced generation
            assert buf.compute_generation == gen_after_first + 100


# ---------------------------------------------------------------------------
# SettingsStore rollback on persist failure
# ---------------------------------------------------------------------------


class TestSettingsStoreRollbackDbFailure:
    """Verify all mutating methods roll back in-memory state on PersistenceError."""

    @pytest.fixture
    def store(self) -> PersistedSettingsServices:
        services = build_settings_services()
        cars = services.car_settings.add_car({"name": "Test Car", "type": "sedan"})
        services.car_settings.set_active_car(cars.cars[0]["id"])
        return services

    def test_update_active_car_aspects_rollback(self, store: PersistedSettingsServices) -> None:
        cars = store.car_settings.get_cars()
        original_aspects = dict(cars.cars[0].get("aspects", {}))
        store.coordinator._db = MagicMock()
        store.coordinator._db.set_settings_snapshot.side_effect = OSError("disk full")

        with pytest.raises(PersistenceError):
            store.analysis_settings.update_active_car_aspects({"tire_width": 999})

        # Aspects should be rolled back
        current = store.car_settings.get_cars()
        assert current.cars[0].get("aspects", {}) == original_aspects

    def test_update_speed_source_rollback(self, store: PersistedSettingsServices) -> None:
        original = store.speed_source_settings.get_speed_source()
        store.coordinator._db = MagicMock()
        store.coordinator._db.set_settings_snapshot.side_effect = OSError("disk full")

        with pytest.raises(PersistenceError):
            store.speed_source_settings.update_speed_source({"mode": "gps"})

        # Speed source should be rolled back
        assert store.speed_source_settings.get_speed_source() == original

    def test_set_language_rollback(self, store: PersistedSettingsServices) -> None:
        original = store.ui_preferences.language
        store.coordinator._db = MagicMock()
        store.coordinator._db.set_settings_snapshot.side_effect = OSError("disk full")

        with pytest.raises(PersistenceError):
            new_lang = "nl" if original == "en" else "en"
            store.ui_preferences.set_language(new_lang)

        assert store.ui_preferences.language == original

    def test_set_speed_unit_rollback(self, store: PersistedSettingsServices) -> None:
        original = store.ui_preferences.speed_unit
        store.coordinator._db = MagicMock()
        store.coordinator._db.set_settings_snapshot.side_effect = OSError("disk full")

        with pytest.raises(PersistenceError):
            new_unit = "mps" if original == "kmh" else "kmh"
            store.ui_preferences.set_speed_unit(new_unit)

        assert store.ui_preferences.speed_unit == original

    def test_assign_sensor_location_rollback_new_sensor(
        self,
        store: PersistedSettingsServices,
    ) -> None:
        mac = "AA:BB:CC:DD:EE:FF"
        store.coordinator._db = MagicMock()
        store.coordinator._db.set_settings_snapshot.side_effect = OSError("disk full")

        with pytest.raises(PersistenceError):
            store.sensor_settings.assign_sensor_location(mac, "front_left_wheel")

        # Sensor should not exist after rollback
        sensors = store.sensor_settings.get_sensors()
        normalized = normalize_sensor_id(mac)
        assert normalized not in sensors

    def test_assign_sensor_location_rollback_existing_sensor(
        self,
        store: PersistedSettingsServices,
    ) -> None:
        mac = "11:22:33:44:55:66"
        store.sensor_settings.assign_sensor_location(mac, "rear_left_wheel")
        store.coordinator._db = MagicMock()
        store.coordinator._db.set_settings_snapshot.side_effect = OSError("disk full")

        with pytest.raises(PersistenceError):
            store.sensor_settings.assign_sensor_location(mac, "front_left_wheel")

        # Should have original values
        sensors = store.sensor_settings.get_sensors()
        normalized = normalize_sensor_id(mac)
        assert sensors[normalized]["name"] == "Rear Left Wheel"
        assert sensors[normalized]["location_code"] == "rear_left_wheel"
