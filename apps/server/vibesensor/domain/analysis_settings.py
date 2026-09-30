"""Analysis-settings snapshot value object."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

__all__ = ["AnalysisSettingsSnapshot"]

ANALYSIS_SETTINGS_POSITIVE_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "tire_width_mm",
        "tire_aspect_pct",
        "rim_in",
        "final_drive_ratio",
        "current_gear_ratio",
        "tire_deflection_factor",
    },
)

ANALYSIS_SETTINGS_NON_NEGATIVE_KEYS: frozenset[str] = frozenset(
    {
        "speed_uncertainty_pct",
        "tire_diameter_uncertainty_pct",
        "final_drive_uncertainty_pct",
        "gear_uncertainty_pct",
    },
)

ANALYSIS_SETTINGS_OPTIONAL_TIRE_SETUP_KEYS: tuple[str, ...] = (
    "front_tire_width_mm",
    "front_tire_aspect_pct",
    "front_rim_in",
    "rear_tire_width_mm",
    "rear_tire_aspect_pct",
    "rear_rim_in",
)

ANALYSIS_SETTINGS_BOUNDS: dict[str, tuple[float, float]] = {
    "speed_uncertainty_pct": (0.0, 100.0),
    "tire_diameter_uncertainty_pct": (0.0, 100.0),
    "final_drive_uncertainty_pct": (0.0, 100.0),
    "gear_uncertainty_pct": (0.0, 100.0),
    "final_drive_ratio": (0.1, 20.0),
    "current_gear_ratio": (0.1, 20.0),
    "tire_width_mm": (100.0, 500.0),
    "tire_aspect_pct": (10.0, 90.0),
    "rim_in": (10.0, 30.0),
    "front_tire_width_mm": (100.0, 500.0),
    "front_tire_aspect_pct": (10.0, 90.0),
    "front_rim_in": (10.0, 30.0),
    "rear_tire_width_mm": (100.0, 500.0),
    "rear_tire_aspect_pct": (10.0, 90.0),
    "rear_rim_in": (10.0, 30.0),
    "tire_deflection_factor": (0.85, 1.0),
}

ANALYSIS_SETTINGS_DEFAULTS: dict[str, float] = {
    "tire_width_mm": 285.0,
    "tire_aspect_pct": 30.0,
    "rim_in": 21.0,
    "final_drive_ratio": 3.08,
    "current_gear_ratio": 0.64,
    "speed_uncertainty_pct": 1.0,
    "tire_diameter_uncertainty_pct": 1.0,
    "final_drive_uncertainty_pct": 0.1,
    "gear_uncertainty_pct": 0.2,
    "tire_deflection_factor": 0.97,
}


@dataclass(frozen=True, slots=True)
class AnalysisSettingsSnapshot:
    """Typed internal analysis-settings context used by runtime and
    use-case logic.

    Behavioral tire geometry access goes through ``order_reference_spec``.
    """

    # -- Validation constants (single source of truth) -------------------------

    POSITIVE_REQUIRED_KEYS: ClassVar[frozenset[str]] = ANALYSIS_SETTINGS_POSITIVE_REQUIRED_KEYS
    NON_NEGATIVE_KEYS: ClassVar[frozenset[str]] = ANALYSIS_SETTINGS_NON_NEGATIVE_KEYS
    _BOUNDS: ClassVar[dict[str, tuple[float, float]]] = ANALYSIS_SETTINGS_BOUNDS
    DEFAULTS: ClassVar[dict[str, float]] = ANALYSIS_SETTINGS_DEFAULTS

    # -- Instance fields -------------------------------------------------------

    tire_width_mm: float = 0.0
    tire_aspect_pct: float = 0.0
    rim_in: float = 0.0
    final_drive_ratio: float = 0.0
    current_gear_ratio: float = 0.0
    speed_uncertainty_pct: float = 0.0
    tire_diameter_uncertainty_pct: float = 0.0
    final_drive_uncertainty_pct: float = 0.0
    gear_uncertainty_pct: float = 0.0
    tire_deflection_factor: float = 1.0
    front_tire_width_mm: float = 0.0
    front_tire_aspect_pct: float = 0.0
    front_rim_in: float = 0.0
    rear_tire_width_mm: float = 0.0
    rear_tire_aspect_pct: float = 0.0
    rear_rim_in: float = 0.0
    default_axle_for_speed: Literal["front", "rear", "average"] = "rear"
