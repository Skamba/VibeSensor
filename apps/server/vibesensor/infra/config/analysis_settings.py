"""Analysis settings — defaults, validation, and tire/wheel geometry helpers.

Provides ``DEFAULT_ANALYSIS_SETTINGS``, ``sanitize_settings()``, and tire/wheel
geometry helpers.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_ANALYSIS_SETTINGS",
    "NON_NEGATIVE_KEYS",
    "POSITIVE_REQUIRED_KEYS",
    "sanitize_settings",
]

import logging
from collections.abc import Mapping
from math import isfinite

LOGGER = logging.getLogger(__name__)

# Validation sets for analysis/car aspect settings (single source of truth).
POSITIVE_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "tire_width_mm",
        "tire_aspect_pct",
        "rim_in",
        "final_drive_ratio",
        "current_gear_ratio",
        "wheel_bandwidth_pct",
        "driveshaft_bandwidth_pct",
        "engine_bandwidth_pct",
        "max_band_half_width_pct",
        "tire_deflection_factor",
    },
)
NON_NEGATIVE_KEYS: frozenset[str] = frozenset(
    {
        "speed_uncertainty_pct",
        "tire_diameter_uncertainty_pct",
        "final_drive_uncertainty_pct",
        "gear_uncertainty_pct",
        "min_abs_band_hz",
    },
)

_BOUNDS: dict[str, tuple[float, float]] = {
    "wheel_bandwidth_pct": (0.1, 100.0),
    "driveshaft_bandwidth_pct": (0.1, 100.0),
    "engine_bandwidth_pct": (0.1, 100.0),
    "speed_uncertainty_pct": (0.0, 100.0),
    "tire_diameter_uncertainty_pct": (0.0, 100.0),
    "final_drive_uncertainty_pct": (0.0, 100.0),
    "gear_uncertainty_pct": (0.0, 100.0),
    "final_drive_ratio": (0.1, 20.0),
    "current_gear_ratio": (0.1, 20.0),
    "min_abs_band_hz": (0.0, 500.0),
    "max_band_half_width_pct": (0.1, 100.0),
    "tire_width_mm": (100.0, 500.0),
    "tire_aspect_pct": (10.0, 90.0),
    "rim_in": (10.0, 30.0),
    "tire_deflection_factor": (0.85, 1.0),
}

DEFAULT_ANALYSIS_SETTINGS: dict[str, float] = {
    "tire_width_mm": 285.0,
    "tire_aspect_pct": 30.0,
    "rim_in": 21.0,
    "final_drive_ratio": 3.08,
    "current_gear_ratio": 0.64,
    "wheel_bandwidth_pct": 5.0,
    "driveshaft_bandwidth_pct": 4.5,
    "engine_bandwidth_pct": 5.2,
    "speed_uncertainty_pct": 1.0,
    "tire_diameter_uncertainty_pct": 1.0,
    "final_drive_uncertainty_pct": 0.1,
    "gear_uncertainty_pct": 0.2,
    "min_abs_band_hz": 0.2,
    "max_band_half_width_pct": 6.0,
    "tire_deflection_factor": 0.97,
}


def sanitize_settings(
    payload: Mapping[str, object],
    allowed_keys: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Validate and filter analysis settings, dropping invalid values with logging.

    *allowed_keys* defaults to :data:`DEFAULT_ANALYSIS_SETTINGS`.
    """
    allowed = allowed_keys if allowed_keys is not None else DEFAULT_ANALYSIS_SETTINGS
    out: dict[str, float] = {}
    for key in allowed:
        raw = payload.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            LOGGER.debug("Dropping non-numeric analysis setting %s=%r", key, raw)
            continue
        if not isfinite(value):
            LOGGER.debug("Dropping non-finite analysis setting %s=%r", key, raw)
            continue
        if key in POSITIVE_REQUIRED_KEYS and value <= 0:
            LOGGER.debug("Dropping non-positive analysis setting %s=%r", key, value)
            continue
        if key in NON_NEGATIVE_KEYS and value < 0:
            LOGGER.debug("Dropping negative analysis setting %s=%r", key, value)
            continue
        bounds = _BOUNDS.get(key)
        if bounds is not None:
            lower, upper = bounds
            if value < lower:
                LOGGER.info("Clamped analysis setting %s from %r to %r", key, value, lower)
                value = lower
            elif value > upper:
                LOGGER.info("Clamped analysis setting %s from %r to %r", key, value, upper)
                value = upper
        out[key] = value
    attempted = [k for k in allowed if payload.get(k) is not None]
    if attempted and not out:
        LOGGER.warning(
            "sanitize_settings: all %d submitted keys were invalid and dropped: %s",
            len(attempted),
            attempted,
        )
    return out

