"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from vibesensor.gps_speed import GPSSpeedMonitor
from vibesensor.registry import ClientRegistry
from vibesensor.settings_store import SettingsStore
from vibesensor.udp_control_tx import UDPControlPlane
from vibesensor.ws_hub import _ws_debug_enabled


def _make_store_with_sensor() -> SettingsStore:
    """Create a SettingsStore with one pre-registered sensor."""
    store = SettingsStore(db=None)
    store.set_sensor("aabbccddeeff", {"name": "Test", "location": "trunk"})
    return store


def _make_gps_monitor() -> GPSSpeedMonitor:
    return GPSSpeedMonitor(gps_enabled=True)


def _make_control_plane() -> UDPControlPlane:
    return UDPControlPlane(ClientRegistry(), "127.0.0.1", 0)


class TestWSDebugLazy:
    def test_ws_debug_function_exists(self) -> None:
        assert callable(_ws_debug_enabled)

    def test_ws_debug_toggleable_at_runtime(self) -> None:
        # Ensure it's off
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIBESENSOR_WS_DEBUG", None)
            assert _ws_debug_enabled() is False

        # Turn it on at runtime
        with patch.dict(os.environ, {"VIBESENSOR_WS_DEBUG": "1"}):
            assert _ws_debug_enabled() is True

        # Turn it back off
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIBESENSOR_WS_DEBUG", None)
            assert _ws_debug_enabled() is False
