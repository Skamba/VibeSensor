from __future__ import annotations

import math
import time

from vibesensor.gps_speed import GPSSpeedMonitor


def test_effective_speed_prefers_override_over_gps() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    monitor.manual_source_selected = True
    monitor.set_speed_override_kmh(90.0)
    assert monitor.effective_speed_mps is not None
    assert abs(monitor.effective_speed_mps - 25.0) < 1e-9

    monitor.speed_mps = 12.5
    # override takes priority over GPS when manual source selected
    assert abs((monitor.effective_speed_mps or 0.0) - 25.0) < 1e-9


def test_set_speed_override_zero_sets_stationary() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    monitor.set_speed_override_kmh(80.0)
    assert monitor.override_speed_mps is not None

    # Zero is a valid speed (vehicle is stationary)
    monitor.set_speed_override_kmh(0.0)
    assert monitor.override_speed_mps == 0.0


def test_manual_selected_with_override_returns_override() -> None:
    """When manual source is selected and override is set, return override."""
    import time

    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.manual_source_selected = True
    monitor.override_speed_mps = 25.0
    monitor.speed_mps = 30.0
    monitor.last_update_ts = time.monotonic()

    assert abs((monitor.effective_speed_mps or 0.0) - 25.0) < 1e-9
    assert monitor.fallback_active is False


def test_manual_selected_no_override_falls_through_to_gps() -> None:
    """When manual source is selected but no override is set, fall through to GPS."""
    import time

    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.manual_source_selected = True
    # No override set
    monitor.speed_mps = 30.0
    monitor.last_update_ts = time.monotonic()

    # Should return GPS speed instead of None
    assert monitor.effective_speed_mps is not None
    assert abs((monitor.effective_speed_mps or 0.0) - 30.0) < 1e-9


def test_manual_selected_no_override_no_gps_returns_none() -> None:
    """When manual source selected, no override, no GPS → None."""
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.manual_source_selected = True
    monitor.speed_mps = None

    assert monitor.effective_speed_mps is None


def test_resolve_speed_legacy_override_has_priority() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.manual_source_selected = None
    monitor.override_speed_mps = 12.0
    monitor.speed_mps = 20.0
    monitor.last_update_ts = time.monotonic()

    resolved = monitor.resolve_speed()
    assert resolved.speed_mps == 12.0
    assert resolved.source == "manual"
    assert resolved.fallback_active is False


def test_resolve_speed_stale_gps_falls_back_to_manual_override() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.manual_source_selected = False
    monitor.speed_mps = 22.0
    monitor.last_update_ts = time.monotonic() - 30.0
    monitor.override_speed_mps = 11.0
    monitor.connection_state = "connected"
    monitor.stale_timeout_s = 5.0

    resolved = monitor.resolve_speed()
    assert resolved.speed_mps == 11.0
    assert resolved.source == "fallback_manual"
    assert resolved.fallback_active is True


def test_set_fallback_settings_clamps_timeout_and_ignores_invalid_mode() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=True)
    monitor.set_fallback_settings(stale_timeout_s=0.1, fallback_mode="invalid")
    assert monitor.stale_timeout_s == 3.0
    assert monitor.fallback_mode == "manual"

    monitor.set_fallback_settings(stale_timeout_s=999.0, fallback_mode="manual")
    assert monitor.stale_timeout_s == 120.0
    assert monitor.fallback_mode == "manual"


def test_set_speed_override_rejects_negative_and_non_finite_values() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    assert monitor.set_speed_override_kmh(-1.0) is None
    assert monitor.override_speed_mps is None

    assert monitor.set_speed_override_kmh(math.inf) is None
    assert monitor.override_speed_mps is None

    assert monitor.set_speed_override_kmh(math.nan) is None
    assert monitor.override_speed_mps is None


def test_helper_parsers_reject_bool_and_invalid_values() -> None:
    assert GPSSpeedMonitor._read_non_negative_metric({"epx": True}, "epx") is None
    assert GPSSpeedMonitor._read_non_negative_metric({"epx": -1}, "epx") is None
    assert GPSSpeedMonitor._read_non_negative_metric({"epx": 1.5}, "epx") == 1.5

    assert GPSSpeedMonitor._tpv_mode({"mode": True}) is None
    assert GPSSpeedMonitor._tpv_mode({"mode": 3}) == 3
