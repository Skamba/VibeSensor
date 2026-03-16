from __future__ import annotations

import pytest

from vibesensor.sensor_units import get_accel_scale_g_per_lsb


def test_adxl345_returns_expected_scale() -> None:
    result = get_accel_scale_g_per_lsb("ADXL345")
    assert result is not None
    assert abs(result - 1.0 / 256.0) < 1e-12


@pytest.mark.parametrize(
    "name",
    ["adxl345", "Adxl345", "sensor-adxl345-v2"],
    ids=["lowercase", "mixed_case", "extra_text"],
)
def test_adxl345_recognized(name: str) -> None:
    assert get_accel_scale_g_per_lsb(name) is not None


@pytest.mark.parametrize(
    "value",
    ["LIS3DH", "", "  ", None, 42],
    ids=["unknown", "empty", "whitespace", "none", "int"],
)
def test_returns_none_for_invalid(value: object) -> None:
    assert get_accel_scale_g_per_lsb(value) is None
