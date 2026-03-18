"""Typed internal snapshot objects for run-attached interpretation context.

These are canonical internal model concepts — not aggregate roots, not
boundary payload shapes.

``AnalysisSettingsSnapshot`` — typed analysis-settings context.
``RunContextSnapshot`` — run-attached interpretive snapshot containing
settings and optional car context.
``SpeedStatsSnapshot`` — speed summary for reconstruction/interpretation.
``DrivingPhaseSummary`` — phase summary for reconstruction/interpretation.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import ClassVar

from .car import CarSnapshot, OrderReferenceSpec

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "AnalysisSettingsSnapshot",
    "DrivingPhaseSummary",
    "RunContextSnapshot",
    "RunMetadataSnapshot",
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
                value = float(raw)  # type: ignore[arg-type]
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
                if isinstance(value, (int, float)) and math.isfinite(float(value))
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

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict suitable for JSON / boundary payloads."""
        return {
            "min_kmh": self.min_kmh,
            "max_kmh": self.max_kmh,
            "mean_kmh": self.mean_kmh,
            "stddev_kmh": self.stddev_kmh,
            "range_kmh": self.range_kmh,
            "steady_speed": self.steady_speed,
            "sample_count": self.sample_count,
        }


# ---------------------------------------------------------------------------
# DrivingPhaseSummary
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DrivingPhaseSummary:
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

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict suitable for JSON / boundary payloads."""
        return {
            "phase_counts": dict(self.phase_counts),
            "phase_pcts": dict(self.phase_pcts),
            "total_samples": self.total_samples,
            "segment_count": self.segment_count,
            "has_cruise": self.has_cruise,
            "has_acceleration": self.has_acceleration,
            "cruise_pct": self.cruise_pct,
            "idle_pct": self.idle_pct,
            "speed_unknown_pct": self.speed_unknown_pct,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> DrivingPhaseSummary:
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


# ---------------------------------------------------------------------------
# RunMetadataSnapshot
# ---------------------------------------------------------------------------


def _str_or(d: Mapping[str, object], key: str, default: str = "") -> str:
    v = d.get(key)
    if v is None:
        return default
    return str(v)


def _opt_str(d: Mapping[str, object], key: str) -> str | None:
    v = d.get(key)
    if v is None:
        return None
    return str(v)


def _opt_float_raw(d: Mapping[str, object], key: str) -> float | None:
    v = d.get(key)
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


@dataclass(frozen=True, slots=True)
class RunMetadataSnapshot:
    """Typed internal representation of recording-identification metadata.

    Covers fields NOT already owned by ``AnalysisSettingsSnapshot``,
    ``CarSnapshot``, ``RunContextSnapshot``, or ``OrderReferenceSpec``.
    """

    run_id: str = ""
    case_id: str = ""
    sensor_mac: str | None = None
    sensor_model: str | None = None
    firmware_version: str | None = None
    raw_sample_rate_hz: float | None = None
    feature_interval_s: float | None = None
    summary_version: int = 1

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must be a non-empty string")
        if self.summary_version < 1:
            raise ValueError("summary_version must be >= 1")

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> RunMetadataSnapshot:
        """Parse from a raw metadata mapping."""
        return cls(
            run_id=_str_or(raw, "run_id", _str_or(raw, "recording_id", "")),
            case_id=_str_or(raw, "case_id", ""),
            sensor_mac=_opt_str(raw, "sensor_mac"),
            sensor_model=_opt_str(raw, "sensor_model"),
            firmware_version=_opt_str(raw, "firmware_version"),
            raw_sample_rate_hz=_opt_float_raw(raw, "raw_sample_rate_hz"),
            feature_interval_s=_opt_float_raw(raw, "feature_interval_s"),
            summary_version=_int_or(raw, "_summary_version", 1),
        )
