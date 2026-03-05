"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import inspect

import vibesensor.analysis_settings as analysis_settings_mod
from vibesensor.analysis_settings import sanitize_settings
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


class TestAnalysisSettingsOrder:
    def test_default_settings_defined_before_sanitize(self) -> None:
        source = inspect.getsource(analysis_settings_mod)
        # DEFAULT_ANALYSIS_SETTINGS must appear before def sanitize_settings
        defaults_pos = source.index("DEFAULT_ANALYSIS_SETTINGS: dict")
        sanitize_pos = source.index("def sanitize_settings(")
        assert defaults_pos < sanitize_pos, (
            "DEFAULT_ANALYSIS_SETTINGS must be defined before sanitize_settings"
        )

    def test_sanitize_settings_works_with_defaults(self) -> None:
        result = sanitize_settings({"tire_width_mm": 225.0})
        assert "tire_width_mm" in result
        assert result["tire_width_mm"] == 225.0
