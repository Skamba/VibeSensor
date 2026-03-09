"""Analysis settings — defaults, validation, and thread-safe storage.

Provides ``DEFAULT_ANALYSIS_SETTINGS``, ``sanitize_settings()``, tire/wheel
geometry helpers, and ``AnalysisSettingsStore`` for runtime settings management.
"""

from __future__ import annotations

__all__ = [
    "AnalysisSettingsStore",
    "DEFAULT_ANALYSIS_SETTINGS",
    "NON_NEGATIVE_KEYS",
    "POSITIVE_REQUIRED_KEYS",
    "engine_rpm_from_wheel_hz",
    "sanitize_settings",
    "tire_circumference_m_from_spec",
    "wheel_hz_from_speed_kmh",
    "wheel_hz_from_speed_mps",
]

import logging
from collections.abc import Mapping
from math import isfinite, pi
from threading import RLock

from .constants import KMH_TO_MPS, SECONDS_PER_MINUTE

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


def tire_circumference_m_from_spec(
    tire_width_mm: float | None,
    tire_aspect_pct: float | None,
    rim_in: float | None,
    deflection_factor: float | None = None,
) -> float | None:
    """Compute tire circumference in metres from width/aspect/rim spec."""
    if tire_width_mm is None or tire_aspect_pct is None or rim_in is None:
        return None
    if not isfinite(tire_width_mm) or not isfinite(tire_aspect_pct) or not isfinite(rim_in):
        return None
    if tire_width_mm <= 0 or tire_aspect_pct <= 0 or rim_in <= 0:
        return None
    sidewall_mm = tire_width_mm * (tire_aspect_pct / 100.0)
    diameter_mm = (rim_in * 25.4) + (2.0 * sidewall_mm)
    diameter_m = diameter_mm / 1000.0
    if diameter_m <= 0:
        return None
    circumference = diameter_m * pi
    # Apply loaded rolling-radius deflection factor (default ~3%).
    # Under vehicle weight the effective rolling circumference is shorter
    # than the unloaded specification diameter, which shifts all predicted
    # rotational-order frequencies upward to match reality.
    if (
        deflection_factor is not None
        and isfinite(deflection_factor)
        and 0 < deflection_factor <= 1.0
    ):
        circumference *= deflection_factor
    return circumference


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


def engine_rpm_from_wheel_hz(
    wheel_hz: float, final_drive_ratio: float, gear_ratio: float
) -> float | None:
    """Engine RPM from wheel Hz, final-drive ratio, and current gear ratio.

    Returns ``None`` when any input is non-finite or when the drive ratios are
    non-positive, preventing silent propagation of ``inf``/``nan`` into
    downstream consumers.  A ``wheel_hz`` of zero (stopped vehicle) returns
    ``0.0`` as expected.
    """
    if not (isfinite(wheel_hz) and isfinite(final_drive_ratio) and isfinite(gear_ratio)):
        return None
    if final_drive_ratio <= 0 or gear_ratio <= 0:
        return None
    result = wheel_hz * final_drive_ratio * gear_ratio * SECONDS_PER_MINUTE
    return result if isfinite(result) else None


class AnalysisSettingsStore:
    """Thread-safe store for runtime analysis settings (tire specs, gear ratios, etc.)."""

    def __init__(self) -> None:
        """Initialise the store with default analysis settings."""
        self._lock = RLock()
        self._values: dict[str, float] = dict(DEFAULT_ANALYSIS_SETTINGS)

    @staticmethod
    def _sanitize(payload: dict[str, float]) -> dict[str, float]:
        return sanitize_settings(payload)

    def snapshot(self) -> dict[str, float]:
        """Return a thread-safe snapshot copy of the current analysis settings."""
        with self._lock:
            return dict(self._values)

    def update(self, payload: dict[str, float]) -> dict[str, float]:
        """Merge *payload* into the store (after validation) and return the new snapshot."""
        with self._lock:
            sanitized = self._sanitize(payload)
            changed = {
                k: (self._values.get(k), v)
                for k, v in sanitized.items()
                if self._values.get(k) != v
            }
            if changed:
                LOGGER.info(
                    "Analysis settings updated: %s",
                    ", ".join(f"{k}={old!r}→{new!r}" for k, (old, new) in changed.items()),
                )
            self._values.update(sanitized)
            return dict(self._values)
