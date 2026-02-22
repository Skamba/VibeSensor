from __future__ import annotations

from dataclasses import dataclass

from vibesensor.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_mps,
)
from vibesensor.constants import KMH_TO_MPS

DEFAULT_SPEED_KMH = 100.0
DEFAULT_TIRE_WIDTH_MM = DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"]
DEFAULT_TIRE_ASPECT_PCT = DEFAULT_ANALYSIS_SETTINGS["tire_aspect_pct"]
DEFAULT_RIM_IN = DEFAULT_ANALYSIS_SETTINGS["rim_in"]
DEFAULT_FINAL_DRIVE = DEFAULT_ANALYSIS_SETTINGS["final_drive_ratio"]
DEFAULT_GEAR_RATIO = DEFAULT_ANALYSIS_SETTINGS["current_gear_ratio"]


def calc_default_orders() -> dict[str, float]:
    speed_mps = DEFAULT_SPEED_KMH * KMH_TO_MPS
    circumference = tire_circumference_m_from_spec(
        DEFAULT_TIRE_WIDTH_MM, DEFAULT_TIRE_ASPECT_PCT, DEFAULT_RIM_IN
    )
    if circumference is None:
        raise ValueError("Failed to compute tire circumference from default specs")
    whz = wheel_hz_from_speed_mps(speed_mps, circumference)
    if whz is None:
        raise ValueError("Failed to compute wheel Hz from default speed/circumference")
    wheel_1x = whz
    shaft_1x = wheel_1x * DEFAULT_FINAL_DRIVE
    engine_1x = shaft_1x * DEFAULT_GEAR_RATIO
    return {
        "wheel_1x": float(wheel_1x),
        "wheel_2x": float(wheel_1x * 2.0),
        "shaft_1x": float(shaft_1x),
        "engine_1x": float(engine_1x),
        "engine_2x": float(engine_1x * 2.0),
    }


DEFAULT_ORDER_HZ = calc_default_orders()


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    tones: tuple[tuple[float, tuple[float, float, float]], ...]
    noise_std: float
    bump_probability: float
    bump_decay: float
    bump_strength: tuple[float, float, float]
    modulation_hz: float
    modulation_depth: float
    # When set, tone frequencies are order-based and were defined at this speed.
    # At runtime ``make_frame()`` scales them by ``current_speed / reference_speed``.
    # ``None`` means tone frequencies are absolute (e.g. engine_idle, rough_road).
    reference_speed_kmh: float | None = None


PROFILE_LIBRARY: dict[str, Profile] = {
    "engine_idle": Profile(
        name="engine_idle",
        tones=(
            (13.0, (170.0, 120.0, 250.0)),
            (26.0, (55.0, 40.0, 85.0)),
            (39.0, (30.0, 24.0, 45.0)),
        ),
        noise_std=22.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(18.0, 15.0, 28.0),
        modulation_hz=0.35,
        modulation_depth=0.10,
    ),
    "rough_road": Profile(
        name="rough_road",
        tones=(
            (8.0, (80.0, 90.0, 130.0)),
            (15.0, (105.0, 95.0, 140.0)),
            (34.0, (55.0, 45.0, 85.0)),
        ),
        noise_std=28.0,
        bump_probability=0.012,
        bump_decay=0.92,
        bump_strength=(45.0, 55.0, 80.0),
        modulation_hz=0.45,
        modulation_depth=0.16,
    ),
    "wheel_imbalance": Profile(
        name="wheel_imbalance",
        tones=(
            (DEFAULT_ORDER_HZ["wheel_1x"], (220.0, 125.0, 170.0)),
            (DEFAULT_ORDER_HZ["wheel_2x"], (80.0, 52.0, 72.0)),
            (DEFAULT_ORDER_HZ["wheel_1x"] * 0.52, (24.0, 18.0, 30.0)),
        ),
        noise_std=24.0,
        bump_probability=0.004,
        bump_decay=0.94,
        bump_strength=(30.0, 24.0, 45.0),
        modulation_hz=0.22,
        modulation_depth=0.12,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
    ),
    "wheel_mild_imbalance": Profile(
        name="wheel_mild_imbalance",
        tones=(
            (DEFAULT_ORDER_HZ["wheel_1x"], (105.0, 62.0, 80.0)),
            (DEFAULT_ORDER_HZ["wheel_2x"], (28.0, 18.0, 24.0)),
            (DEFAULT_ORDER_HZ["wheel_1x"] * 0.52, (8.0, 6.0, 10.0)),
        ),
        noise_std=14.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(10.0, 8.0, 14.0),
        modulation_hz=0.18,
        modulation_depth=0.08,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
    ),
    "rear_body": Profile(
        name="rear_body",
        tones=(
            (6.5, (70.0, 88.0, 120.0)),
            (14.0, (48.0, 60.0, 82.0)),
            (28.0, (34.0, 28.0, 50.0)),
        ),
        noise_std=22.0,
        bump_probability=0.006,
        bump_decay=0.95,
        bump_strength=(30.0, 34.0, 50.0),
        modulation_hz=0.28,
        modulation_depth=0.14,
    ),
}
