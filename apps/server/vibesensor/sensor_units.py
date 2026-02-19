from __future__ import annotations

from typing import Final

_ADXL345_SCALE_G_PER_LSB: Final[float] = 1.0 / 256.0


def get_accel_scale_g_per_lsb(sensor_model: str | None) -> float | None:
    if not isinstance(sensor_model, str):
        return None
    normalized = sensor_model.strip().lower()
    if not normalized:
        return None
    if "adxl345" in normalized:
        return _ADXL345_SCALE_G_PER_LSB
    return None


__all__ = ["get_accel_scale_g_per_lsb"]
