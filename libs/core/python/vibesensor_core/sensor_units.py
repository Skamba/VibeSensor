"""Accelerometer sensor-unit helpers.

Maps sensor model strings to their physical scale factor (g per LSB),
keeping hardware-specific constants out of the core analysis pipeline.
"""
from __future__ import annotations

from typing import Final

_ADXL345_SCALE_G_PER_LSB: Final[float] = 1.0 / 256.0


def get_accel_scale_g_per_lsb(sensor_model: str | None) -> float | None:
    """Return the g-per-LSB scale factor for *sensor_model*, or ``None`` if unknown.

    Currently supports ``"adxl345"`` (case-insensitive substring match).
    """
    if not isinstance(sensor_model, str):
        return None
    normalized = sensor_model.strip().lower()
    if not normalized:
        return None
    if "adxl345" in normalized:
        return _ADXL345_SCALE_G_PER_LSB
    return None
