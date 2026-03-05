"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import pytest

from vibesensor.car_library import CAR_LIBRARY, get_models_for_brand_type, get_variants_for_model
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


class TestCarLibraryCopies:
    def test_get_models_returns_copies(self) -> None:
        if not CAR_LIBRARY:
            pytest.skip("No car library data loaded")
        brand = CAR_LIBRARY[0].get("brand")
        car_type = CAR_LIBRARY[0].get("type")
        models = get_models_for_brand_type(brand, car_type)
        if not models:
            pytest.skip("No models found")
        # Mutate the returned dict
        models[0]["MUTATED"] = True
        # Original library should NOT be mutated
        for entry in CAR_LIBRARY:
            assert "MUTATED" not in entry

    def test_get_variants_returns_copies(self) -> None:
        if not CAR_LIBRARY:
            pytest.skip("No car library data loaded")
        for entry in CAR_LIBRARY:
            variants = entry.get("variants") or []
            if variants:
                result = get_variants_for_model(entry["brand"], entry["type"], entry["model"])
                if result:
                    result[0]["MUTATED"] = True
                    # Original should NOT be mutated
                    assert "MUTATED" not in variants[0]
                    return
        pytest.skip("No entries with variants found")
