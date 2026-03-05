"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from vibesensor.gps_speed import GPSSpeedMonitor
from vibesensor.registry import ClientRegistry
from vibesensor.settings_store import PersistenceError, SettingsStore
from vibesensor.udp_control_tx import UDPControlPlane


def _make_store_with_sensor() -> SettingsStore:
    """Create a SettingsStore with one pre-registered sensor."""
    store = SettingsStore(db=None)
    store.set_sensor("aabbccddeeff", {"name": "Test", "location": "trunk"})
    return store


def _make_gps_monitor() -> GPSSpeedMonitor:
    return GPSSpeedMonitor(gps_enabled=True)


def _make_control_plane() -> UDPControlPlane:
    return UDPControlPlane(ClientRegistry(), "127.0.0.1", 0)


class TestRemoveSensorRollback:
    def test_remove_sensor_rolls_back_on_persist_failure(self) -> None:
        store = _make_store_with_sensor()
        assert "aabbccddeeff" in store.get_sensors()

        # Simulate persistence failure
        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.remove_sensor("aabbccddeeff")

        # Sensor should still be in memory after rollback
        assert "aabbccddeeff" in store.get_sensors()

    def test_remove_sensor_succeeds_normally(self) -> None:
        store = _make_store_with_sensor()
        assert store.remove_sensor("aabbccddeeff") is True
        assert "aabbccddeeff" not in store.get_sensors()

    def test_remove_sensor_nonexistent_returns_false(self) -> None:
        store = SettingsStore(db=None)
        assert store.remove_sensor("aabbccddeeff") is False
