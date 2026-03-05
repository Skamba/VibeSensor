"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import inspect

import vibesensor.diagnostics_shared as diagnostics_shared_mod
from vibesensor.diagnostics_shared import as_float_or_none
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


class TestAsFloatOrNoneImport:
    def test_diagnostics_shared_uses_full_name(self) -> None:
        """diagnostics_shared should import as_float_or_none, not _as_float."""
        source = inspect.getsource(diagnostics_shared_mod)
        assert "as _as_float" not in source, (
            "diagnostics_shared should not alias as_float_or_none to _as_float"
        )
        assert "as_float_or_none" in source

    def test_as_float_or_none_accessible_from_diagnostics_shared(self) -> None:
        assert as_float_or_none(3.14) == 3.14
        assert as_float_or_none(None) is None
