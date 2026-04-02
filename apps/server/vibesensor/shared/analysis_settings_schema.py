"""Canonical analysis-settings schema and boundary sanitization helpers."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping

from vibesensor.domain._numeric import coerce_float

LOGGER = logging.getLogger(__name__)

ANALYSIS_SETTINGS_POSITIVE_REQUIRED_KEYS: frozenset[str] = frozenset(
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

ANALYSIS_SETTINGS_NON_NEGATIVE_KEYS: frozenset[str] = frozenset(
    {
        "speed_uncertainty_pct",
        "tire_diameter_uncertainty_pct",
        "final_drive_uncertainty_pct",
        "gear_uncertainty_pct",
        "min_abs_band_hz",
    },
)

ANALYSIS_SETTINGS_BOUNDS: dict[str, tuple[float, float]] = {
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

ANALYSIS_SETTINGS_DEFAULTS: dict[str, float] = {
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

ANALYSIS_SETTINGS_FIELDS: tuple[str, ...] = tuple(ANALYSIS_SETTINGS_DEFAULTS)

__all__ = [
    "ANALYSIS_SETTINGS_BOUNDS",
    "ANALYSIS_SETTINGS_DEFAULTS",
    "ANALYSIS_SETTINGS_FIELDS",
    "ANALYSIS_SETTINGS_NON_NEGATIVE_KEYS",
    "ANALYSIS_SETTINGS_POSITIVE_REQUIRED_KEYS",
    "sanitize_analysis_settings",
]


def sanitize_analysis_settings(
    payload: Mapping[str, object],
    allowed_keys: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Validate and normalize flat analysis-settings payloads."""

    allowed = allowed_keys if allowed_keys is not None else ANALYSIS_SETTINGS_DEFAULTS
    out: dict[str, float] = {}
    for key in allowed:
        raw = payload.get(key)
        if raw is None:
            continue
        try:
            value = coerce_float(raw)
        except (TypeError, ValueError):
            LOGGER.debug("Dropping non-numeric analysis setting %s=%r", key, raw)
            continue
        if not math.isfinite(value):
            LOGGER.debug("Dropping non-finite analysis setting %s=%r", key, raw)
            continue
        if key in ANALYSIS_SETTINGS_POSITIVE_REQUIRED_KEYS and value <= 0:
            LOGGER.debug("Dropping non-positive analysis setting %s=%r", key, value)
            continue
        if key in ANALYSIS_SETTINGS_NON_NEGATIVE_KEYS and value < 0:
            LOGGER.debug("Dropping negative analysis setting %s=%r", key, value)
            continue
        bounds = ANALYSIS_SETTINGS_BOUNDS.get(key)
        if bounds is not None:
            lower, upper = bounds
            if value < lower:
                LOGGER.info("Clamped analysis setting %s from %r to %r", key, value, lower)
                value = lower
            elif value > upper:
                LOGGER.info("Clamped analysis setting %s from %r to %r", key, value, upper)
                value = upper
        out[key] = value
    attempted = [key for key in allowed if payload.get(key) is not None]
    if attempted and not out:
        LOGGER.warning(
            "sanitize_analysis_settings: all %d submitted keys were invalid and dropped: %s",
            len(attempted),
            attempted,
        )
    return out
