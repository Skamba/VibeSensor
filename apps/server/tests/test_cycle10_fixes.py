# ruff: noqa: E501
"""Tests for Cycle 10 fixes: settings rollback, processing guards, counter_delta dedup."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

from vibesensor.analysis.helpers import counter_delta

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
        from vibesensor.processing import ClientBuffer

        buf = ClientBuffer(
            data=np.zeros((3, 100), dtype=np.float32),
            capacity=100,
        )
        # Simulate cached state
        buf.cached_spectrum_payload = {"freq": [1, 2]}
        buf.cached_spectrum_payload_generation = 5
        buf.cached_selected_payload = {"data": True}
        buf.cached_selected_payload_key = (1, 2, 3)

        buf.invalidate_caches()

        assert buf.cached_spectrum_payload is None
        assert buf.cached_spectrum_payload_generation == -1
        assert buf.cached_selected_payload is None
        assert buf.cached_selected_payload_key is None


# ---------------------------------------------------------------------------
# SignalProcessor compute_metrics generation guard
# ---------------------------------------------------------------------------


class TestComputeMetricsGenerationGuard:
    """Phase 3 should not overwrite fresher results with stale ones."""

    def test_stale_generation_does_not_overwrite(self) -> None:
        from vibesensor.processing import SignalProcessor

        sp = SignalProcessor(
            sample_rate_hz=1000,
            waveform_seconds=2,
            waveform_display_hz=50,
            fft_n=256,
        )
        client = "test-client"
        # Ingest enough samples to compute
        chunk = np.random.randn(512, 3).astype(np.float32) * 0.01
        sp.ingest(client, chunk, sample_rate_hz=1000)

        # First compute
        sp.compute_metrics(client)

        with sp._lock:
            buf = sp._buffers[client]
            gen_after_first = buf.compute_generation
            # Artificially advance the compute generation to simulate a fresher result
            buf.compute_generation = gen_after_first + 100

        # Compute again — this should NOT overwrite because snap_ingest_gen < compute_generation
        sp.compute_metrics(client)

        with sp._lock:
            buf = sp._buffers[client]
            # Should still be the artificially advanced generation
            assert buf.compute_generation == gen_after_first + 100


# ---------------------------------------------------------------------------
# SettingsStore rollback on persist failure
# ---------------------------------------------------------------------------


class TestSettingsStoreRollback:
    """Verify all mutating methods roll back in-memory state on PersistenceError."""

    @pytest.fixture
    def store(self) -> Any:
        from vibesensor.settings_store import SettingsStore

        s = SettingsStore()
        s.add_car({"name": "Test Car", "type": "sedan"})
        s.set_active_car(s.get_cars()["cars"][0]["id"])
        return s

    def test_update_active_car_aspects_rollback(self, store: Any) -> None:
        from vibesensor.settings_store import PersistenceError

        cars = store.get_cars()
        original_aspects = dict(cars["cars"][0].get("aspects", {}))

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.update_active_car_aspects({"tire_width": 999})

        # Aspects should be rolled back
        current = store.get_cars()
        assert current["cars"][0].get("aspects", {}) == original_aspects

    def test_update_speed_source_rollback(self, store: Any) -> None:
        from vibesensor.settings_store import PersistenceError

        original = store.get_speed_source()

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.update_speed_source({"mode": "gps"})

        # Speed source should be rolled back
        assert store.get_speed_source() == original

    def test_set_language_rollback(self, store: Any) -> None:
        from vibesensor.settings_store import PersistenceError

        original = store.language

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                new_lang = "nl" if original == "en" else "en"
                store.set_language(new_lang)

        assert store.language == original

    def test_set_speed_unit_rollback(self, store: Any) -> None:
        from vibesensor.settings_store import PersistenceError

        original = store.speed_unit

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                new_unit = "mps" if original == "kmh" else "kmh"
                store.set_speed_unit(new_unit)

        assert store.speed_unit == original

    def test_set_sensor_rollback_new_sensor(self, store: Any) -> None:
        from vibesensor.settings_store import PersistenceError

        mac = "AA:BB:CC:DD:EE:FF"

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.set_sensor(mac, {"name": "Test", "location": "front"})

        # Sensor should not exist after rollback
        sensors = store.get_sensors()
        normalized = mac.upper().replace(":", "")
        assert normalized not in sensors

    def test_set_sensor_rollback_existing_sensor(self, store: Any) -> None:
        from vibesensor.settings_store import PersistenceError

        mac = "11:22:33:44:55:66"
        # First create a sensor successfully
        store.set_sensor(mac, {"name": "Original", "location": "rear"})

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.set_sensor(mac, {"name": "Updated", "location": "front"})

        # Should have original values
        sensors = store.get_sensors()
        normalized = mac.upper().replace(":", "")
        assert sensors[normalized]["name"] == "Original"
        assert sensors[normalized]["location"] == "rear"
