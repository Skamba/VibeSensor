"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import time

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


class TestResolveSpeedAtomicSnapshot:
    def test_speed_mps_property_reads_from_snapshot(self) -> None:
        m = _make_gps_monitor()
        assert m.speed_mps is None
        m.speed_mps = 10.0
        assert m.speed_mps == 10.0
        assert m._speed_snapshot[0] == 10.0

    def test_speed_mps_setter_preserves_timestamp(self) -> None:
        m = _make_gps_monitor()
        ts = time.monotonic()
        m._speed_snapshot = (5.0, ts)
        m.speed_mps = 10.0
        # Timestamp should be preserved
        assert m._speed_snapshot == (10.0, ts)

    def test_resolve_speed_uses_snapshot_speed(self) -> None:
        m = _make_gps_monitor()
        # Write speed and timestamp atomically
        m._speed_snapshot = (10.0, time.monotonic())
        r = m.resolve_speed()
        assert r.speed_mps == 10.0
        assert r.source == "gps"

    def test_resolve_speed_snapshot_consistency(self) -> None:
        """Setting speed_mps and last_update_ts both update the snapshot."""
        m = _make_gps_monitor()
        m.speed_mps = 15.0
        m.last_update_ts = time.monotonic()
        r = m.resolve_speed()
        assert r.speed_mps == 15.0
        assert r.source == "gps"
