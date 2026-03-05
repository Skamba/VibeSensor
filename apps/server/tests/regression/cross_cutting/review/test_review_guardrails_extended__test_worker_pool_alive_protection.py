"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import pytest

from vibesensor.gps_speed import GPSSpeedMonitor
from vibesensor.registry import ClientRegistry
from vibesensor.settings_store import SettingsStore
from vibesensor.udp_control_tx import UDPControlPlane
from vibesensor.worker_pool import WorkerPool


def _make_store_with_sensor() -> SettingsStore:
    """Create a SettingsStore with one pre-registered sensor."""
    store = SettingsStore(db=None)
    store.set_sensor("aabbccddeeff", {"name": "Test", "location": "trunk"})
    return store


def _make_gps_monitor() -> GPSSpeedMonitor:
    return GPSSpeedMonitor(gps_enabled=True)


def _make_control_plane() -> UDPControlPlane:
    return UDPControlPlane(ClientRegistry(), "127.0.0.1", 0)


class TestWorkerPoolAliveProtection:
    def test_submit_checks_alive_under_lock(self) -> None:
        pool = WorkerPool(max_workers=1)
        pool.shutdown()

        with pytest.raises(RuntimeError, match="shut down"):
            pool.submit(lambda: None)

    def test_shutdown_sets_alive_under_lock(self) -> None:
        pool = WorkerPool(max_workers=1)
        assert pool._alive is True
        pool.shutdown()
        assert pool._alive is False
