"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import pytest

import vibesensor.locations as locations_mod
from vibesensor.gps_speed import GPSSpeedMonitor
from vibesensor.locations import is_wheel_location
from vibesensor.registry import ClientRegistry
from vibesensor.settings_store import SettingsStore
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


class TestNonWheelTokensModuleLevel:
    def test_non_wheel_tokens_is_module_constant(self) -> None:
        assert hasattr(locations_mod, "_NON_WHEEL_TOKENS")
        assert isinstance(locations_mod._NON_WHEEL_TOKENS, tuple)
        assert "seat" in locations_mod._NON_WHEEL_TOKENS
        assert "trunk" in locations_mod._NON_WHEEL_TOKENS

    @pytest.mark.parametrize(
        "location, expected",
        [
            ("driver_seat", False),
            ("transmission", False),
            ("front_left_wheel", True),
        ],
    )
    def test_is_wheel_location_classification(self, location: str, expected: bool) -> None:
        assert is_wheel_location(location) is expected
