"""Analysis-settings snapshot value object."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from vibesensor.shared.analysis_settings_schema import (
    ANALYSIS_SETTINGS_BOUNDS,
    ANALYSIS_SETTINGS_DEFAULTS,
    ANALYSIS_SETTINGS_NON_NEGATIVE_KEYS,
    ANALYSIS_SETTINGS_POSITIVE_REQUIRED_KEYS,
)

__all__ = ["AnalysisSettingsSnapshot"]


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
    wheel_bandwidth_pct: float = 0.0
    driveshaft_bandwidth_pct: float = 0.0
    engine_bandwidth_pct: float = 0.0
    speed_uncertainty_pct: float = 0.0
    tire_diameter_uncertainty_pct: float = 0.0
    final_drive_uncertainty_pct: float = 0.0
    gear_uncertainty_pct: float = 0.0
    min_abs_band_hz: float = 0.0
    max_band_half_width_pct: float = 0.0
    tire_deflection_factor: float = 1.0
