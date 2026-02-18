"""Tests for vibesensor.constants and shared vehicle dynamics helpers."""

from __future__ import annotations

from vibesensor.analysis_settings import (
    engine_rpm_from_wheel_hz,
    wheel_hz_from_speed_kmh,
    wheel_hz_from_speed_mps,
)
from vibesensor.constants import (
    KMH_TO_MPS,
    MPS_TO_KMH,
    PEAK_BANDWIDTH_HZ,
    PEAK_SEPARATION_HZ,
    SILENCE_DB,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_mps_kmh_round_trip() -> None:
    assert abs(MPS_TO_KMH * KMH_TO_MPS - 1.0) < 1e-15


def test_kmh_to_mps_value() -> None:
    assert abs(100.0 * KMH_TO_MPS - 27.7778) < 0.001


def test_silence_db_is_negative() -> None:
    assert SILENCE_DB < 0


def test_peak_constants_positive() -> None:
    assert PEAK_BANDWIDTH_HZ > 0
    assert PEAK_SEPARATION_HZ > 0


# ---------------------------------------------------------------------------
# wheel_hz helpers
# ---------------------------------------------------------------------------


def test_wheel_hz_from_speed_kmh_basic() -> None:
    result = wheel_hz_from_speed_kmh(100.0, 2.0)
    assert result is not None
    expected = (100.0 * KMH_TO_MPS) / 2.0
    assert abs(result - expected) < 1e-9


def test_wheel_hz_from_speed_kmh_zero_speed() -> None:
    assert wheel_hz_from_speed_kmh(0.0, 2.0) is None


def test_wheel_hz_from_speed_kmh_zero_circumference() -> None:
    assert wheel_hz_from_speed_kmh(100.0, 0.0) is None


def test_wheel_hz_from_speed_kmh_negative() -> None:
    assert wheel_hz_from_speed_kmh(-10.0, 2.0) is None
    assert wheel_hz_from_speed_kmh(100.0, -1.0) is None


def test_wheel_hz_from_speed_mps_basic() -> None:
    result = wheel_hz_from_speed_mps(27.78, 2.0)
    assert result is not None
    assert abs(result - 27.78 / 2.0) < 1e-9


def test_wheel_hz_from_speed_mps_zero() -> None:
    assert wheel_hz_from_speed_mps(0.0, 2.0) is None
    assert wheel_hz_from_speed_mps(10.0, 0.0) is None


def test_wheel_hz_mps_kmh_consistency() -> None:
    """Both wheel_hz helpers must agree for the same physical speed."""
    speed_kmh = 90.0
    speed_mps = speed_kmh * KMH_TO_MPS
    circ = 2.1
    from_kmh = wheel_hz_from_speed_kmh(speed_kmh, circ)
    from_mps = wheel_hz_from_speed_mps(speed_mps, circ)
    assert from_kmh is not None
    assert from_mps is not None
    assert abs(from_kmh - from_mps) < 1e-9


# ---------------------------------------------------------------------------
# engine_rpm helper
# ---------------------------------------------------------------------------


def test_engine_rpm_basic() -> None:
    rpm = engine_rpm_from_wheel_hz(10.0, 3.08, 0.64)
    expected = 10.0 * 3.08 * 0.64 * 60.0
    assert abs(rpm - expected) < 1e-9


def test_engine_rpm_zero_wheel_hz() -> None:
    assert engine_rpm_from_wheel_hz(0.0, 3.08, 0.64) == 0.0
