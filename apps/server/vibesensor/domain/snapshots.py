"""Typed internal snapshot objects for run-attached interpretation context.

These are canonical internal model concepts — not aggregate roots, not
boundary payload shapes.

``AnalysisSettingsSnapshot`` — typed analysis-settings context.
``RunContextSnapshot`` — run-attached interpretive snapshot containing
settings and optional car context.
``SpeedStatsSnapshot`` — speed summary for reconstruction/interpretation.
``PhaseSummarySnapshot`` — phase summary for reconstruction/interpretation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from types import MappingProxyType

from .car import CarSnapshot, OrderReferenceSpec, TireSpec

__all__ = [
    "AnalysisSettingsSnapshot",
    "PhaseSummarySnapshot",
    "RunContextSnapshot",
    "SpeedStatsSnapshot",
]


def _float_or(d: Mapping[str, object], key: str, default: float = 0.0) -> float:
    v = d.get(key)
    if v is None:
        return default
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _bool_or(d: Mapping[str, object], key: str, default: bool = False) -> bool:  # noqa: FBT001, FBT002
    v = d.get(key)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return default


def _int_or(d: Mapping[str, object], key: str, default: int = 0) -> int:
    v = d.get(key)
    if v is None:
        return default
    try:
        return int(v)  # type: ignore[call-overload,no-any-return]
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# AnalysisSettingsSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisSettingsSnapshot:
    """Typed internal analysis-settings context used by runtime and
    use-case logic.

    Raw tire fields (``tire_width_mm``, ``tire_aspect_pct``, ``rim_in``)
    are construction inputs for ``from_dict()`` persistence compatibility.
    Behavioral tire geometry access goes through ``order_reference_spec``.
    """

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

    @property
    def order_reference_spec(self) -> OrderReferenceSpec | None:
        """Derive ``OrderReferenceSpec`` from these settings.

        Returns ``None`` if tire geometry is missing/invalid.
        """
        tire = TireSpec.from_aspects(
            {
                "tire_width_mm": self.tire_width_mm,
                "tire_aspect_pct": self.tire_aspect_pct,
                "rim_in": self.rim_in,
            },
            deflection_factor=self.tire_deflection_factor,
        )
        if tire is None:
            return None
        return OrderReferenceSpec(
            tire_spec=tire,
            final_drive_ratio=self.final_drive_ratio,
            current_gear_ratio=self.current_gear_ratio,
            wheel_bandwidth_pct=self.wheel_bandwidth_pct,
            driveshaft_bandwidth_pct=self.driveshaft_bandwidth_pct,
            engine_bandwidth_pct=self.engine_bandwidth_pct,
            speed_uncertainty_pct=self.speed_uncertainty_pct,
            tire_diameter_uncertainty_pct=self.tire_diameter_uncertainty_pct,
            final_drive_uncertainty_pct=self.final_drive_uncertainty_pct,
            gear_uncertainty_pct=self.gear_uncertainty_pct,
            min_abs_band_hz=self.min_abs_band_hz,
            max_band_half_width_pct=self.max_band_half_width_pct,
        )


# ---------------------------------------------------------------------------
# RunContextSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunContextSnapshot:
    """Run-attached interpretive snapshot containing analysis settings
    and optional car context.
    """

    analysis_settings: AnalysisSettingsSnapshot = field(default_factory=AnalysisSettingsSnapshot)
    car: CarSnapshot | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> RunContextSnapshot:
        """Parse from a nested mapping.

        Expects keys ``"analysis_settings_snapshot"`` and optionally
        ``"active_car_snapshot"``.
        """
        raw_settings = d.get("analysis_settings_snapshot")
        if isinstance(raw_settings, Mapping):
            settings = AnalysisSettingsSnapshot.from_dict(raw_settings)
        else:
            settings = AnalysisSettingsSnapshot()

        raw_car = d.get("active_car_snapshot")
        car: CarSnapshot | None = None
        if isinstance(raw_car, Mapping):
            car = CarSnapshot.from_dict(raw_car)

        return cls(analysis_settings=settings, car=car)

    def to_metadata_dict(self) -> dict[str, object]:
        settings_dict = asdict(self.analysis_settings)
        metadata: dict[str, object] = {
            "analysis_settings_snapshot": {
                key: value
                for key, value in settings_dict.items()
                if isinstance(value, (int, float)) and not math.isnan(value)
            },
        }
        if self.car is not None:
            metadata["active_car_snapshot"] = self.car.to_dict()
        return metadata

    @property
    def order_reference_spec(self) -> OrderReferenceSpec | None:
        """Convenience — delegates to analysis settings."""
        return self.analysis_settings.order_reference_spec

    @property
    def has_car_context(self) -> bool:
        return self.car is not None

    @property
    def active_car_id(self) -> str | None:
        return self.car.car_id if self.car is not None else None

    @property
    def car_name(self) -> str | None:
        return self.car.name if self.car is not None else None

    @property
    def car_type(self) -> str | None:
        return self.car.car_type if self.car is not None else None

    @property
    def car_variant(self) -> str | None:
        return self.car.variant if self.car is not None else None


# ---------------------------------------------------------------------------
# SpeedStatsSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpeedStatsSnapshot:
    """Typed internal speed-summary snapshot for reconstruction and
    interpretation support.
    """

    min_kmh: float | None = None
    max_kmh: float | None = None
    mean_kmh: float | None = None
    stddev_kmh: float | None = None
    range_kmh: float | None = None
    steady_speed: bool = False
    sample_count: int = 0

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> SpeedStatsSnapshot:
        """Parse from flat mapping. Missing keys default sensibly."""

        def _opt_float(key: str) -> float | None:
            v = d.get(key)
            if v is None:
                return None
            try:
                f = float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
            return f if math.isfinite(f) else None

        return cls(
            min_kmh=_opt_float("min_kmh"),
            max_kmh=_opt_float("max_kmh"),
            mean_kmh=_opt_float("mean_kmh"),
            stddev_kmh=_opt_float("stddev_kmh"),
            range_kmh=_opt_float("range_kmh"),
            steady_speed=_bool_or(d, "steady_speed"),
            sample_count=_int_or(d, "sample_count"),
        )


# ---------------------------------------------------------------------------
# PhaseSummarySnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PhaseSummarySnapshot:
    """Typed internal phase-summary snapshot for reconstruction and
    interpretation support.
    """

    phase_counts: Mapping[str, int] = field(default_factory=dict)
    phase_pcts: Mapping[str, float] = field(default_factory=dict)
    total_samples: int = 0
    segment_count: int = 0
    has_cruise: bool = False
    has_acceleration: bool = False
    cruise_pct: float = 0.0
    idle_pct: float = 0.0
    speed_unknown_pct: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.phase_counts, MappingProxyType):
            object.__setattr__(self, "phase_counts", MappingProxyType(dict(self.phase_counts)))
        if not isinstance(self.phase_pcts, MappingProxyType):
            object.__setattr__(self, "phase_pcts", MappingProxyType(dict(self.phase_pcts)))

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> PhaseSummarySnapshot:
        """Parse from flat mapping. Missing keys default sensibly."""
        raw_counts = d.get("phase_counts")
        phase_counts: dict[str, int] = {}
        if isinstance(raw_counts, dict):
            for k, v in raw_counts.items():
                if isinstance(k, str):
                    try:
                        phase_counts[k] = int(v)
                    except (TypeError, ValueError):
                        pass

        raw_pcts = d.get("phase_pcts")
        phase_pcts: dict[str, float] = {}
        if isinstance(raw_pcts, dict):
            for k, v in raw_pcts.items():
                if isinstance(k, str):
                    try:
                        phase_pcts[k] = float(v)
                    except (TypeError, ValueError):
                        pass

        # Fall back to phase_counts/phase_pcts sub-dicts for historical
        # data that may lack top-level has_*/pct keys.
        def _flag_fb(key: str, phase_key: str) -> bool:
            v = d.get(key)
            if v is not None:
                return bool(v)
            return phase_counts.get(phase_key, 0) > 0

        def _pct_fb(key: str, phase_key: str) -> float:
            v = _float_or(d, key)
            if v != 0.0 or key in d:
                return v
            return phase_pcts.get(phase_key, 0.0)

        return cls(
            phase_counts=phase_counts,
            phase_pcts=phase_pcts,
            total_samples=_int_or(d, "total_samples"),
            segment_count=_int_or(d, "segment_count"),
            has_cruise=_flag_fb("has_cruise", "cruise"),
            has_acceleration=_flag_fb("has_acceleration", "acceleration"),
            cruise_pct=_pct_fb("cruise_pct", "cruise"),
            idle_pct=_pct_fb("idle_pct", "idle"),
            speed_unknown_pct=_pct_fb("speed_unknown_pct", "speed_unknown"),
        )
