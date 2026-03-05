"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import threading

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


class TestCmdSeqLock:
    def test_udp_control_plane_has_cmd_seq_lock(self) -> None:
        cp = _make_control_plane()
        assert hasattr(cp, "_cmd_seq_lock")
        assert isinstance(cp._cmd_seq_lock, type(threading.Lock()))

    def test_next_cmd_seq_increments_atomically(self) -> None:
        cp = _make_control_plane()
        initial = cp._cmd_seq
        seq1 = cp._next_cmd_seq()
        seq2 = cp._next_cmd_seq()
        assert seq1 == (initial + 1) & 0xFFFFFFFF
        assert seq2 == (initial + 2) & 0xFFFFFFFF
