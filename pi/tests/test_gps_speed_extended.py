from __future__ import annotations

from vibesensor.gps_speed import GPSSpeedMonitor


# -- effective_speed_mps -------------------------------------------------------


def test_gps_speed_has_priority_over_override() -> None:
    m = GPSSpeedMonitor(gps_enabled=True)
    m.speed_mps = 10.0
    m.override_speed_mps = 25.0
    assert m.effective_speed_mps == 10.0


def test_override_used_when_no_gps() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    m.override_speed_mps = 25.0
    assert m.effective_speed_mps == 25.0


def test_effective_none_when_nothing_set() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    assert m.effective_speed_mps is None


# -- set_speed_override_kmh ---------------------------------------------------


def test_override_converts_kmh_to_mps() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    result = m.set_speed_override_kmh(72.0)
    assert result == 72.0
    assert m.override_speed_mps is not None
    assert abs(m.override_speed_mps - 20.0) < 1e-9


def test_override_none_clears() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    m.set_speed_override_kmh(90.0)
    m.set_speed_override_kmh(None)
    assert m.override_speed_mps is None


def test_override_zero_clears() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    m.set_speed_override_kmh(90.0)
    m.set_speed_override_kmh(0.0)
    assert m.override_speed_mps is None


def test_override_negative_clears() -> None:
    m = GPSSpeedMonitor(gps_enabled=False)
    m.set_speed_override_kmh(90.0)
    m.set_speed_override_kmh(-10.0)
    assert m.override_speed_mps is None


# -- integer speed_mps ---------------------------------------------------------


def test_integer_speed_mps_treated_as_float() -> None:
    """speed_mps set to int should still be returned as float via effective_speed_mps."""
    m = GPSSpeedMonitor(gps_enabled=True)
    m.speed_mps = 10  # type: ignore[assignment]
    result = m.effective_speed_mps
    assert result is not None
    assert isinstance(result, float)
    assert result == 10.0
