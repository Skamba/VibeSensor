"""Behavior tests for GPS fallback settings and manual overrides."""

from __future__ import annotations

import math

import pytest

from vibesensor.adapters.gps.gps_speed import (
    MAX_STALE_TIMEOUT_S,
    MIN_STALE_TIMEOUT_S,
    GPSSpeedMonitor,
)


class TestGPSFallbackSettings:
    """Cover fallback timeout clamping and manual-source toggles."""

    def test_set_fallback_settings_clamps_stale_timeout(self) -> None:
        monitor = GPSSpeedMonitor(gps_enabled=True)
        monitor.set_fallback_settings(stale_timeout_s=0.1)
        assert monitor.stale_timeout_s == MIN_STALE_TIMEOUT_S

        monitor.set_fallback_settings(stale_timeout_s=99999)
        assert monitor.stale_timeout_s == MAX_STALE_TIMEOUT_S

        monitor.set_fallback_settings(stale_timeout_s=30)
        assert monitor.stale_timeout_s == 30

    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_override_non_finite_clears(self, value: float) -> None:
        monitor = GPSSpeedMonitor(gps_enabled=False)
        monitor.set_speed_override_kmh(80.0)
        assert monitor.override_speed_mps is not None
        monitor.set_speed_override_kmh(value)
        assert monitor.override_speed_mps is None

    def test_set_manual_source_selected(self) -> None:
        monitor = GPSSpeedMonitor(gps_enabled=True)
        assert monitor.manual_source_selected is True
        monitor.set_manual_source_selected(True)
        assert monitor.manual_source_selected is True
        monitor.set_manual_source_selected(False)
        assert monitor.manual_source_selected is False


def test_set_speed_override_rejects_negative_and_non_finite_values() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    for invalid_kmh in (-1.0, math.inf, math.nan):
        assert monitor.set_speed_override_kmh(invalid_kmh) is None
    assert monitor.override_speed_mps is None
