from __future__ import annotations

from vibesensor_core.sensor_units import get_accel_scale_g_per_lsb


def test_adxl345_returns_expected_scale() -> None:
    result = get_accel_scale_g_per_lsb("ADXL345")
    assert result is not None
    assert abs(result - 1.0 / 256.0) < 1e-12


def test_adxl345_case_insensitive() -> None:
    assert get_accel_scale_g_per_lsb("adxl345") is not None
    assert get_accel_scale_g_per_lsb("Adxl345") is not None


def test_adxl345_with_extra_text() -> None:
    assert get_accel_scale_g_per_lsb("sensor-adxl345-v2") is not None


def test_unknown_sensor_returns_none() -> None:
    assert get_accel_scale_g_per_lsb("LIS3DH") is None


def test_empty_or_whitespace_returns_none() -> None:
    assert get_accel_scale_g_per_lsb("") is None
    assert get_accel_scale_g_per_lsb("  ") is None


def test_non_string_returns_none() -> None:
    assert get_accel_scale_g_per_lsb(None) is None
    assert get_accel_scale_g_per_lsb(42) is None
