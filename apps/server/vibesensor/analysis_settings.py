from __future__ import annotations

import logging
from math import isfinite, pi
from threading import RLock

from .constants import KMH_TO_MPS

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
    }
)
NON_NEGATIVE_KEYS: frozenset[str] = frozenset(
    {
        "speed_uncertainty_pct",
        "tire_diameter_uncertainty_pct",
        "final_drive_uncertainty_pct",
        "gear_uncertainty_pct",
        "min_abs_band_hz",
    }
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
}


def sanitize_settings(
    payload: dict[str, object],
    allowed_keys: dict[str, float] | None = None,
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
            bounded = min(max(value, lower), upper)
            if bounded != value:
                LOGGER.info("Clamped analysis setting %s from %r to %r", key, value, bounded)
            value = bounded
        out[key] = value
    return out


DEFAULT_ANALYSIS_SETTINGS: dict[str, float] = {
    "tire_width_mm": 285.0,
    "tire_aspect_pct": 30.0,
    "rim_in": 21.0,
    "final_drive_ratio": 3.08,
    "current_gear_ratio": 0.64,
    "wheel_bandwidth_pct": 6.0,
    "driveshaft_bandwidth_pct": 5.6,
    "engine_bandwidth_pct": 6.2,
    "speed_uncertainty_pct": 0.6,
    "tire_diameter_uncertainty_pct": 1.2,
    "final_drive_uncertainty_pct": 0.2,
    "gear_uncertainty_pct": 0.5,
    "min_abs_band_hz": 0.4,
    "max_band_half_width_pct": 8.0,
}


def tire_circumference_m_from_spec(
    tire_width_mm: float | None,
    tire_aspect_pct: float | None,
    rim_in: float | None,
) -> float | None:
    if tire_width_mm is None or tire_aspect_pct is None or rim_in is None:
        return None
    if not all(isfinite(v) for v in (tire_width_mm, tire_aspect_pct, rim_in)):
        return None
    if tire_width_mm <= 0 or tire_aspect_pct <= 0 or rim_in <= 0:
        return None
    sidewall_mm = tire_width_mm * (tire_aspect_pct / 100.0)
    diameter_mm = (rim_in * 25.4) + (2.0 * sidewall_mm)
    diameter_m = diameter_mm / 1000.0
    if diameter_m <= 0:
        return None
    return diameter_m * pi


def wheel_hz_from_speed_kmh(speed_kmh: float, tire_circumference_m: float) -> float | None:
    """Wheel rotational frequency from vehicle speed (km/h) and tire circumference."""
    if not isfinite(speed_kmh) or not isfinite(tire_circumference_m):
        return None
    if speed_kmh <= 0 or tire_circumference_m <= 0:
        return None
    result = (speed_kmh * KMH_TO_MPS) / tire_circumference_m
    return result if isfinite(result) else None


def wheel_hz_from_speed_mps(speed_mps: float, tire_circumference_m: float) -> float | None:
    """Wheel rotational frequency from vehicle speed (m/s) and tire circumference."""
    if not isfinite(speed_mps) or not isfinite(tire_circumference_m):
        return None
    if speed_mps <= 0 or tire_circumference_m <= 0:
        return None
    result = speed_mps / tire_circumference_m
    return result if isfinite(result) else None


def engine_rpm_from_wheel_hz(wheel_hz: float, final_drive_ratio: float, gear_ratio: float) -> float:
    """Engine RPM from wheel Hz, final-drive ratio, and current gear ratio."""
    return wheel_hz * final_drive_ratio * gear_ratio * 60.0


class AnalysisSettingsStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._values: dict[str, float] = dict(DEFAULT_ANALYSIS_SETTINGS)

    @staticmethod
    def _sanitize(payload: dict[str, float]) -> dict[str, float]:
        return sanitize_settings(payload)

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)

    def update(self, payload: dict[str, float]) -> dict[str, float]:
        with self._lock:
            self._values.update(self._sanitize(payload))
            return dict(self._values)
