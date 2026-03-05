"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import vibesensor.udp_control_tx as udp_control_tx_mod
from vibesensor.gps_speed import GPSSpeedMonitor
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


class TestUdpControlTxAll:
    def test_has_all_export(self) -> None:
        assert hasattr(udp_control_tx_mod, "__all__")
        assert "UDPControlPlane" in udp_control_tx_mod.__all__

    def test_internal_class_not_in_all(self) -> None:
        assert "ControlDatagramProtocol" not in udp_control_tx_mod.__all__
