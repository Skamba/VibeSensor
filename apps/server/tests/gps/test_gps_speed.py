from __future__ import annotations

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
