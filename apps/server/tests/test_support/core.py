"""Core metadata, vehicle-profile, and frequency helpers for tests."""

from __future__ import annotations

import hashlib
from functools import cache
from typing import Any

from vibesensor.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)

TIRE_CIRC = tire_circumference_m_from_spec(
    DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"],
    DEFAULT_ANALYSIS_SETTINGS["tire_aspect_pct"],
    DEFAULT_ANALYSIS_SETTINGS["rim_in"],
    deflection_factor=DEFAULT_ANALYSIS_SETTINGS.get("tire_deflection_factor"),
)
FINAL_DRIVE = DEFAULT_ANALYSIS_SETTINGS["final_drive_ratio"]
GEAR_RATIO = DEFAULT_ANALYSIS_SETTINGS["current_gear_ratio"]

# Canonical sensor names / corners
SENSOR_FL = "front-left"
SENSOR_FR = "front-right"
SENSOR_RL = "rear-left"
SENSOR_RR = "rear-right"
ALL_WHEEL_SENSORS = [SENSOR_FL, SENSOR_FR, SENSOR_RL, SENSOR_RR]

# Non-wheel sensor names for multi-sensor scenarios
SENSOR_ENGINE = "engine-bay"
SENSOR_DRIVESHAFT = "driveshaft-tunnel"
SENSOR_TRANSMISSION = "transmission"
SENSOR_TRUNK = "trunk"
SENSOR_DRIVER_SEAT = "driver-seat"
SENSOR_FRONT_SUBFRAME = "front-subframe"
SENSOR_REAR_SUBFRAME = "rear-subframe"
SENSOR_PASSENGER_SEAT = "front-passenger-seat"

NON_WHEEL_SENSORS = [
    SENSOR_ENGINE,
    SENSOR_DRIVESHAFT,
    SENSOR_TRANSMISSION,
    SENSOR_TRUNK,
    SENSOR_DRIVER_SEAT,
    SENSOR_FRONT_SUBFRAME,
    SENSOR_REAR_SUBFRAME,
    SENSOR_PASSENGER_SEAT,
]

# Corner code → canonical sensor name
CORNER_SENSORS = {
    "FL": SENSOR_FL,
    "FR": SENSOR_FR,
    "RL": SENSOR_RL,
    "RR": SENSOR_RR,
}

# Speed bands
SPEED_LOW = 50.0  # km/h  (wheel_1x ≈ 6.5 Hz with default tires, above MIN_ANALYSIS_FREQ_HZ)
SPEED_MID = 60.0
SPEED_HIGH = 100.0
SPEED_VERY_HIGH = 120.0

# ---------------------------------------------------------------------------
# Car profiles – five realistic vehicle configurations for cross-profile
# parameterised testing.  Each profile overrides tire geometry and drivetrain
# ratios that affect wheel/engine frequency calculations.
# ---------------------------------------------------------------------------

CAR_PROFILES: list[dict[str, Any]] = [
    {
        "name": "performance_suv",
        "tire_width_mm": 285.0,
        "tire_aspect_pct": 30.0,
        "rim_in": 21.0,
        "final_drive_ratio": 3.08,
        "current_gear_ratio": 0.64,
    },
    {
        "name": "economy_sedan",
        "tire_width_mm": 205.0,
        "tire_aspect_pct": 55.0,
        "rim_in": 16.0,
        "final_drive_ratio": 3.94,
        "current_gear_ratio": 0.73,
    },
    {
        "name": "sports_coupe",
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
        "final_drive_ratio": 3.27,
        "current_gear_ratio": 0.85,
    },
    {
        "name": "off_road_truck",
        "tire_width_mm": 265.0,
        "tire_aspect_pct": 70.0,
        "rim_in": 17.0,
        "final_drive_ratio": 3.73,
        "current_gear_ratio": 0.75,
    },
    {
        "name": "compact_city",
        "tire_width_mm": 195.0,
        "tire_aspect_pct": 65.0,
        "rim_in": 15.0,
        "final_drive_ratio": 4.06,
        "current_gear_ratio": 0.68,
    },
]

CAR_PROFILE_IDS: list[str] = [p["name"] for p in CAR_PROFILES]


def _normalize_wheel_slot(name: str) -> str | None:
    normalized = name.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "fl": SENSOR_FL,
        "fr": SENSOR_FR,
        "rl": SENSOR_RL,
        "rr": SENSOR_RR,
    }
    if normalized in aliases:
        return aliases[normalized]
    axle = "front" if "front" in normalized else "rear" if "rear" in normalized else None
    side = "left" if "left" in normalized else "right" if "right" in normalized else None
    if axle and side:
        return f"{axle}-{side}"
    return None


def _corner_transfer_fraction(fault_sensor: str, sink_sensor: str) -> float:
    """Deterministic transfer fraction for structure-borne coupling."""
    fault = _normalize_wheel_slot(fault_sensor)
    sink = _normalize_wheel_slot(sink_sensor)
    # Non-corner sensors still pick up cabin/chassis energy.
    if fault is None or sink is None:
        return 0.32
    if fault == sink:
        return 1.0
    fault_axle, fault_side = fault.split("-", maxsplit=1)
    sink_axle, sink_side = sink.split("-", maxsplit=1)
    if fault_side == sink_side and fault_axle != sink_axle:
        return 0.52
    if fault_axle == sink_axle and fault_side != sink_side:
        return 0.48
    return 0.40


def _fault_transfer_fraction(
    fault_sensor: str,
    sink_sensor: str,
    *,
    override: float | None,
) -> float:
    if sink_sensor == fault_sensor:
        return 1.0
    if override is not None:
        return max(0.0, min(1.0, override))
    # Keep realistic coupling while preserving clear localization headroom.
    return _corner_transfer_fraction(fault_sensor, sink_sensor) * 0.58


@cache
def _profile_circ_cached(
    tire_width_mm: int,
    tire_aspect_pct: int,
    rim_in: int,
    tire_deflection_factor: float | None,
) -> float:
    circ = tire_circumference_m_from_spec(
        tire_width_mm,
        tire_aspect_pct,
        rim_in,
        deflection_factor=tire_deflection_factor,
    )
    assert circ is not None and circ > 0
    return circ


def profile_circ(profile: dict[str, Any]) -> float:
    """Compute tire circumference for a car profile."""
    return _profile_circ_cached(
        profile["tire_width_mm"],
        profile["tire_aspect_pct"],
        profile["rim_in"],
        profile.get("tire_deflection_factor"),
    )


def profile_wheel_hz(profile: dict[str, Any], speed_kmh: float) -> float:
    """Compute wheel-1x Hz for a car profile at *speed_kmh*."""
    circ = profile_circ(profile)
    hz = wheel_hz_from_speed_kmh(speed_kmh, circ)
    assert hz is not None and hz > 0
    return hz


@cache
def _profile_metadata_base(
    tire_width_mm: int,
    tire_aspect_pct: int,
    rim_in: int,
    tire_deflection_factor: float | None,
    final_drive_ratio: float,
    current_gear_ratio: float,
) -> tuple[tuple[str, Any], ...]:
    return tuple(
        standard_metadata(
            tire_circumference_m=_profile_circ_cached(
                tire_width_mm,
                tire_aspect_pct,
                rim_in,
                tire_deflection_factor,
            ),
            final_drive_ratio=final_drive_ratio,
            current_gear_ratio=current_gear_ratio,
        ).items(),
    )


def profile_metadata(profile: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Build run metadata for a specific car profile."""
    meta = dict(
        _profile_metadata_base(
            profile["tire_width_mm"],
            profile["tire_aspect_pct"],
            profile["rim_in"],
            profile.get("tire_deflection_factor"),
            profile["final_drive_ratio"],
            profile["current_gear_ratio"],
        ),
    )
    meta.update(overrides)
    return meta


# ---------------------------------------------------------------------------
# Stable deterministic hash (replaces Python hash() which varies per process)
# ---------------------------------------------------------------------------


@cache
def _stable_hash(s: str) -> int:
    """Return a stable positive integer derived from *s* (deterministic across runs)."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def standard_metadata(*, language: str = "en", **overrides: Any) -> dict[str, Any]:
    """Return a minimal valid run-metadata dict."""
    meta: dict[str, Any] = {
        "tire_circumference_m": TIRE_CIRC,
        "raw_sample_rate_hz": 800.0,
        "final_drive_ratio": FINAL_DRIVE,
        "current_gear_ratio": GEAR_RATIO,
        "sensor_model": "ADXL345",
        "units": {"accel_x_g": "g"},
        "language": language,
    }
    meta.update(overrides)
    return meta


# ---------------------------------------------------------------------------
# Frequency helpers
# ---------------------------------------------------------------------------


def wheel_hz(speed_kmh: float) -> float:
    """Compute wheel-1x frequency for *speed_kmh*."""
    hz = wheel_hz_from_speed_kmh(speed_kmh, TIRE_CIRC)
    assert hz is not None and hz > 0
    return hz


def engine_hz(
    speed_kmh: float,
    gear_ratio: float = GEAR_RATIO,
    final_drive: float = FINAL_DRIVE,
) -> float:
    """Rough engine-1x Hz from speed (2-stroke assumption for simplicity)."""
    whz = wheel_hz(speed_kmh)
    return whz * final_drive * gear_ratio


# ---------------------------------------------------------------------------
# Single-sample builder
# ---------------------------------------------------------------------------
