from __future__ import annotations

from vibesensor.shared.sensor_units import ADXL345_SCALE_G_PER_LSB, SENSOR_MODEL


def test_adxl345_scale_constant() -> None:
    assert abs(ADXL345_SCALE_G_PER_LSB - 1.0 / 256.0) < 1e-12


def test_sensor_model_constant() -> None:
    assert SENSOR_MODEL == "ADXL345"
