from __future__ import annotations

from vibesensor.gps_speed import GPSSpeedMonitor


def test_effective_speed_prefers_gps_over_override() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    monitor.set_speed_override_kmh(90.0)
    assert monitor.effective_speed_mps is not None
    assert abs(monitor.effective_speed_mps - 25.0) < 1e-9

    monitor.speed_mps = 12.5
    assert abs((monitor.effective_speed_mps or 0.0) - 12.5) < 1e-9


def test_set_speed_override_zero_clears_override() -> None:
    monitor = GPSSpeedMonitor(gps_enabled=False)
    monitor.set_speed_override_kmh(80.0)
    assert monitor.override_speed_mps is not None

    monitor.set_speed_override_kmh(0.0)
    assert monitor.override_speed_mps is None
    assert monitor.effective_speed_mps is None

