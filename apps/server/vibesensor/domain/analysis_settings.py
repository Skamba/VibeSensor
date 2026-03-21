"""Analysis-settings snapshot value object and sanitation rules."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import ClassVar

from ._numeric import coerce_float
from ._snapshot_parse import _float_or
from .car import OrderReferenceSpec

_LOGGER = logging.getLogger(__name__)

__all__ = ["AnalysisSettingsSnapshot"]


@dataclass(frozen=True, slots=True)
class AnalysisSettingsSnapshot:
    """Typed internal analysis-settings context used by runtime and
    use-case logic.

    Raw tire fields (``tire_width_mm``, ``tire_aspect_pct``, ``rim_in``)
    are construction inputs for ``from_dict()`` persistence compatibility.
    Behavioral tire geometry access goes through ``order_reference_spec``.
    """

    # -- Validation constants (single source of truth) -------------------------

    POSITIVE_REQUIRED_KEYS: ClassVar[frozenset[str]] = frozenset(
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
    NON_NEGATIVE_KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "speed_uncertainty_pct",
            "tire_diameter_uncertainty_pct",
            "final_drive_uncertainty_pct",
            "gear_uncertainty_pct",
            "min_abs_band_hz",
        },
    )
    _BOUNDS: ClassVar[dict[str, tuple[float, float]]] = {
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
    DEFAULTS: ClassVar[dict[str, float]] = {
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

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> AnalysisSettingsSnapshot:
        """Parse from flat mapping. Missing keys default to ``0.0``."""
        return cls(
            tire_width_mm=_float_or(d, "tire_width_mm"),
            tire_aspect_pct=_float_or(d, "tire_aspect_pct"),
            rim_in=_float_or(d, "rim_in"),
            final_drive_ratio=_float_or(d, "final_drive_ratio"),
            current_gear_ratio=_float_or(d, "current_gear_ratio"),
            wheel_bandwidth_pct=_float_or(d, "wheel_bandwidth_pct"),
            driveshaft_bandwidth_pct=_float_or(d, "driveshaft_bandwidth_pct"),
            engine_bandwidth_pct=_float_or(d, "engine_bandwidth_pct"),
            speed_uncertainty_pct=_float_or(d, "speed_uncertainty_pct"),
            tire_diameter_uncertainty_pct=_float_or(d, "tire_diameter_uncertainty_pct"),
            final_drive_uncertainty_pct=_float_or(d, "final_drive_uncertainty_pct"),
            gear_uncertainty_pct=_float_or(d, "gear_uncertainty_pct"),
            min_abs_band_hz=_float_or(d, "min_abs_band_hz"),
            max_band_half_width_pct=_float_or(d, "max_band_half_width_pct"),
            tire_deflection_factor=_float_or(d, "tire_deflection_factor", 1.0),
        )

    @staticmethod
    def sanitize(
        payload: Mapping[str, object],
        allowed_keys: Mapping[str, float] | None = None,
    ) -> dict[str, float]:
        """Validate and filter analysis settings, dropping invalid values with logging.

        *allowed_keys* defaults to :data:`DEFAULTS`.
        """
        allowed = allowed_keys if allowed_keys is not None else AnalysisSettingsSnapshot.DEFAULTS
        out: dict[str, float] = {}
        for key in allowed:
            raw = payload.get(key)
            if raw is None:
                continue
            try:
                value = coerce_float(raw)
            except (TypeError, ValueError):
                _LOGGER.debug("Dropping non-numeric analysis setting %s=%r", key, raw)
                continue
            if not math.isfinite(value):
                _LOGGER.debug("Dropping non-finite analysis setting %s=%r", key, raw)
                continue
            if key in AnalysisSettingsSnapshot.POSITIVE_REQUIRED_KEYS and value <= 0:
                _LOGGER.debug("Dropping non-positive analysis setting %s=%r", key, value)
                continue
            if key in AnalysisSettingsSnapshot.NON_NEGATIVE_KEYS and value < 0:
                _LOGGER.debug("Dropping negative analysis setting %s=%r", key, value)
                continue
            bounds = AnalysisSettingsSnapshot._BOUNDS.get(key)
            if bounds is not None:
                lower, upper = bounds
                if value < lower:
                    _LOGGER.info("Clamped analysis setting %s from %r to %r", key, value, lower)
                    value = lower
                elif value > upper:
                    _LOGGER.info("Clamped analysis setting %s from %r to %r", key, value, upper)
                    value = upper
            out[key] = value
        attempted = [k for k in allowed if payload.get(k) is not None]
        if attempted and not out:
            _LOGGER.warning(
                "sanitize: all %d submitted keys were invalid and dropped: %s",
                len(attempted),
                attempted,
            )
        return out

    @property
    def order_reference_spec(self) -> OrderReferenceSpec | None:
        """Project the captured flat settings into an ``OrderReferenceSpec``.

        This is a run-time snapshot view over persisted analysis settings, not
        a second owner of order-reference meaning.
        """
        return OrderReferenceSpec.from_settings(asdict(self))
