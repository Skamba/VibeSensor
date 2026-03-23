"""Accelerometer sensor-unit constants.

Keeps hardware-specific constants out of the core analysis pipeline.
"""

from __future__ import annotations

from typing import Final

__all__ = ["ADXL345_SCALE_G_PER_LSB", "SENSOR_MODEL"]

ADXL345_SCALE_G_PER_LSB: Final[float] = 1.0 / 256.0
"""Physical scale factor (g per LSB) for the ADXL345 accelerometer."""

SENSOR_MODEL: Final[str] = "ADXL345"
"""Canonical sensor model name recorded in run metadata."""
