"""Metrics cache, settings rollback, and counter-delta regressions."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from vibesensor.settings_store import PersistenceError, SettingsStore


class TestSettingsStoreRollback:
    """Verify all mutating methods roll back in-memory state on PersistenceError."""

    @pytest.fixture
    def store(self) -> Any:
        s = SettingsStore()
        s.add_car({"name": "Test Car", "type": "sedan"})
        s.set_active_car(s.get_cars()["cars"][0]["id"])
        return s

    def test_update_active_car_aspects_rollback(self, store: Any) -> None:
        cars = store.get_cars()
        original_aspects = dict(cars["cars"][0].get("aspects", {}))

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.update_active_car_aspects({"tire_width": 999})

        # Aspects should be rolled back
        current = store.get_cars()
        assert current["cars"][0].get("aspects", {}) == original_aspects

    def test_update_speed_source_rollback(self, store: Any) -> None:
        original = store.get_speed_source()

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.update_speed_source({"mode": "gps"})

        # Speed source should be rolled back
        assert store.get_speed_source() == original

    def test_set_language_rollback(self, store: Any) -> None:
        original = store.language

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                new_lang = "nl" if original == "en" else "en"
                store.set_language(new_lang)

        assert store.language == original

    def test_set_speed_unit_rollback(self, store: Any) -> None:
        original = store.speed_unit

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                new_unit = "mps" if original == "kmh" else "kmh"
                store.set_speed_unit(new_unit)

        assert store.speed_unit == original

    def test_set_sensor_rollback_new_sensor(self, store: Any) -> None:
        mac = "AA:BB:CC:DD:EE:FF"

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.set_sensor(mac, {"name": "Test", "location": "front"})

        # Sensor should not exist after rollback
        sensors = store.get_sensors()
        normalized = mac.upper().replace(":", "")
        assert normalized not in sensors

    def test_set_sensor_rollback_existing_sensor(self, store: Any) -> None:
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
