"""Guard the shared sensor model and acceleration-scale constants."""

from __future__ import annotations

from vibesensor.shared.sensor_units import ADXL345_SCALE_G_PER_LSB, SENSOR_MODEL


def test_sensor_units_constants() -> None:
    assert abs(ADXL345_SCALE_G_PER_LSB - 1.0 / 256.0) < 1e-12
    assert SENSOR_MODEL == "ADXL345"
