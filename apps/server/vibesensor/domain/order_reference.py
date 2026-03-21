"""Order-reference value object and helper math for vehicle diagnostics."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from vibesensor.domain.tire_spec import TireSpec

__all__ = [
    "OrderReferenceSpec",
    "normalize_order_reference_mapping",
]

_ORDER_REFERENCE_KEYS: tuple[str, ...] = (
    "tire_width_mm",
    "tire_aspect_pct",
    "rim_in",
    "final_drive_ratio",
    "current_gear_ratio",
    "wheel_bandwidth_pct",
    "driveshaft_bandwidth_pct",
    "engine_bandwidth_pct",
    "speed_uncertainty_pct",
    "tire_diameter_uncertainty_pct",
    "final_drive_uncertainty_pct",
    "gear_uncertainty_pct",
    "min_abs_band_hz",
    "max_band_half_width_pct",
    "tire_deflection_factor",
)
_KMH_TO_MPS = 1.0 / 3.6


@dataclass(frozen=True, slots=True)
class OrderReferenceSpec:
    """Typed owner of tire geometry and driveline/reference-order math."""

    tire_spec: TireSpec
    final_drive_ratio: float
    current_gear_ratio: float
    wheel_bandwidth_pct: float
    driveshaft_bandwidth_pct: float
    engine_bandwidth_pct: float
    speed_uncertainty_pct: float
    tire_diameter_uncertainty_pct: float
    final_drive_uncertainty_pct: float
    gear_uncertainty_pct: float
    min_abs_band_hz: float
    max_band_half_width_pct: float

    @classmethod
    def from_settings(
        cls,
        settings: Mapping[str, object],
        deflection_factor: float | None = None,
    ) -> OrderReferenceSpec | None:
        """Build from a flat settings mapping.

        Returns ``None`` if tire geometry keys are missing or invalid.
        """
        resolved_deflection = _coerce_finite_float(
            settings.get("tire_deflection_factor"),
            default=1.0,
        )
        if deflection_factor is not None and math.isfinite(deflection_factor):
            resolved_deflection = float(deflection_factor)
        tire_inputs = {
            key: value
            for key in ("tire_width_mm", "tire_aspect_pct", "rim_in")
            if (value := _coerce_finite_float(settings.get(key), default=None)) is not None
        }
        tire = TireSpec.from_aspects(
            tire_inputs,
            deflection_factor=resolved_deflection if resolved_deflection is not None else 1.0,
        )
        if tire is None:
            return None

        def _f(key: str, default: float = 0.0) -> float:
            value = _coerce_finite_float(settings.get(key), default=default)
            return default if value is None else value

        return cls(
            tire_spec=tire,
            final_drive_ratio=_f("final_drive_ratio"),
            current_gear_ratio=_f("current_gear_ratio"),
            wheel_bandwidth_pct=_f("wheel_bandwidth_pct"),
            driveshaft_bandwidth_pct=_f("driveshaft_bandwidth_pct"),
            engine_bandwidth_pct=_f("engine_bandwidth_pct"),
            speed_uncertainty_pct=_f("speed_uncertainty_pct"),
            tire_diameter_uncertainty_pct=_f("tire_diameter_uncertainty_pct"),
            final_drive_uncertainty_pct=_f("final_drive_uncertainty_pct"),
            gear_uncertainty_pct=_f("gear_uncertainty_pct"),
            min_abs_band_hz=_f("min_abs_band_hz"),
            max_band_half_width_pct=_f("max_band_half_width_pct"),
        )

    def to_settings_dict(self) -> dict[str, float]:
        """Project to the flat settings mapping used at persistence boundaries."""
        return {
            "tire_width_mm": self.tire_spec.width_mm,
            "tire_aspect_pct": self.tire_spec.aspect_pct,
            "rim_in": self.tire_spec.rim_in,
            "final_drive_ratio": self.final_drive_ratio,
            "current_gear_ratio": self.current_gear_ratio,
            "wheel_bandwidth_pct": self.wheel_bandwidth_pct,
            "driveshaft_bandwidth_pct": self.driveshaft_bandwidth_pct,
            "engine_bandwidth_pct": self.engine_bandwidth_pct,
            "speed_uncertainty_pct": self.speed_uncertainty_pct,
            "tire_diameter_uncertainty_pct": self.tire_diameter_uncertainty_pct,
            "final_drive_uncertainty_pct": self.final_drive_uncertainty_pct,
            "gear_uncertainty_pct": self.gear_uncertainty_pct,
            "min_abs_band_hz": self.min_abs_band_hz,
            "max_band_half_width_pct": self.max_band_half_width_pct,
            "tire_deflection_factor": self.tire_spec.deflection_factor,
        }

    @property
    def tire_circumference_m(self) -> float:
        """Tire circumference in metres (deflection-adjusted)."""
        return self.tire_spec.circumference_m

    @property
    def has_engine_reference(self) -> bool:
        """Whether gear ratio is set (non-zero) for engine order analysis."""
        return self.current_gear_ratio != 0.0

    @property
    def supports_wheel_reference(self) -> bool:
        """Whether wheel-order calculations have usable tire geometry."""
        return self.tire_circumference_m > 0.0

    @property
    def supports_driveshaft_reference(self) -> bool:
        """Whether driveshaft-order calculations have usable driveline data."""
        return self.supports_wheel_reference and self.final_drive_ratio > 0.0

    @property
    def supports_engine_reference(self) -> bool:
        """Whether engine-order calculations have usable gear and driveline data."""
        return self.supports_driveshaft_reference and self.has_engine_reference

    @property
    def is_complete(self) -> bool:
        """Whether all required fields are present for order analysis."""
        return self.supports_driveshaft_reference

    @property
    def wheel_uncertainty_pct(self) -> float:
        return _combined_relative_uncertainty(
            self.speed_uncertainty_pct / 100.0,
            self.tire_diameter_uncertainty_pct / 100.0,
        )

    @property
    def drive_uncertainty_pct(self) -> float:
        return _combined_relative_uncertainty(
            self.wheel_uncertainty_pct,
            self.final_drive_uncertainty_pct / 100.0,
        )

    @property
    def engine_uncertainty_pct(self) -> float:
        return _combined_relative_uncertainty(
            self.drive_uncertainty_pct,
            self.gear_uncertainty_pct / 100.0,
        )

    def wheel_hz(self, speed_mps: float) -> float | None:
        """Wheel rotational frequency (Hz) from vehicle speed (m/s)."""
        if not math.isfinite(speed_mps) or speed_mps <= 0:
            return None
        circumference = self.tire_circumference_m
        if not math.isfinite(circumference) or circumference <= 0:
            return None
        result = speed_mps / circumference
        return result if math.isfinite(result) else None

    def engine_hz(self, speed_mps: float) -> float | None:
        """Engine rotational frequency (Hz) from vehicle speed (m/s)."""
        whz = self.wheel_hz(speed_mps)
        if whz is None or not self.is_complete or not self.has_engine_reference:
            return None
        result = whz * self.final_drive_ratio * self.current_gear_ratio
        return result if math.isfinite(result) else None

    def wheel_hz_from_speed_kmh(self, speed_kmh: float) -> float | None:
        if not math.isfinite(speed_kmh) or speed_kmh <= 0:
            return None
        return self.wheel_hz(speed_kmh * _KMH_TO_MPS)

    def wheel_hz_from_speed_mps(self, speed_mps: float) -> float | None:
        return self.wheel_hz(speed_mps)

    def driveshaft_hz_from_wheel_hz(self, wheel_hz: float) -> float | None:
        if not math.isfinite(wheel_hz) or wheel_hz <= 0 or not self.supports_driveshaft_reference:
            return None
        driveshaft_hz = wheel_hz * self.final_drive_ratio
        return driveshaft_hz if math.isfinite(driveshaft_hz) else None

    def driveshaft_hz_from_speed_kmh(self, speed_kmh: float) -> float | None:
        wheel_hz = self.wheel_hz_from_speed_kmh(speed_kmh)
        if wheel_hz is None:
            return None
        return self.driveshaft_hz_from_wheel_hz(wheel_hz)

    def engine_hz_from_wheel_hz(self, wheel_hz: float) -> float | None:
        driveshaft_hz = self.driveshaft_hz_from_wheel_hz(wheel_hz)
        if driveshaft_hz is None or not self.supports_engine_reference:
            return None
        engine_hz = driveshaft_hz * self.current_gear_ratio
        return engine_hz if math.isfinite(engine_hz) else None

    def engine_hz_from_speed_kmh(self, speed_kmh: float) -> float | None:
        wheel_hz = self.wheel_hz_from_speed_kmh(speed_kmh)
        if wheel_hz is None:
            return None
        return self.engine_hz_from_wheel_hz(wheel_hz)

    def engine_rpm_from_wheel_hz(self, wheel_hz: float) -> float | None:
        if wheel_hz == 0.0 and self.supports_engine_reference:
            return 0.0
        engine_hz = self.engine_hz_from_wheel_hz(wheel_hz)
        if engine_hz is None:
            return None
        engine_rpm = engine_hz * 60.0
        return engine_rpm if math.isfinite(engine_rpm) else None

    def engine_rpm_from_speed_kmh(self, speed_kmh: float) -> float | None:
        engine_hz = self.engine_hz_from_speed_kmh(speed_kmh)
        if engine_hz is None:
            return None
        engine_rpm = engine_hz * 60.0
        return engine_rpm if math.isfinite(engine_rpm) else None

    def orders_hz_from_speed_mps(self, speed_mps: float | None) -> dict[str, float] | None:
        if speed_mps is None or not math.isfinite(speed_mps) or speed_mps <= 0:
            return None
        if not self.supports_engine_reference:
            return None
        wheel_hz = self.wheel_hz_from_speed_mps(speed_mps)
        if wheel_hz is None:
            return None
        drive_hz = self.driveshaft_hz_from_wheel_hz(wheel_hz)
        engine_hz = self.engine_hz_from_wheel_hz(wheel_hz)
        if drive_hz is None or engine_hz is None:
            return None
        if not all(math.isfinite(v) and v > 0 for v in (wheel_hz, drive_hz, engine_hz)):
            return None
        return {
            "wheel_hz": wheel_hz,
            "drive_hz": drive_hz,
            "engine_hz": engine_hz,
            "wheel_uncertainty_pct": self.wheel_uncertainty_pct,
            "drive_uncertainty_pct": self.drive_uncertainty_pct,
            "engine_uncertainty_pct": self.engine_uncertainty_pct,
        }


def normalize_order_reference_mapping(aspects: Mapping[str, float]) -> dict[str, float]:
    """Normalize persisted/raw order-reference aspects to canonical finite floats."""
    normalized: dict[str, float] = {}
    for key in _ORDER_REFERENCE_KEYS:
        value = _coerce_finite_float(aspects.get(key), default=None)
        if value is None:
            continue
        if key in {"tire_width_mm", "tire_aspect_pct", "rim_in"} and value <= 0:
            raise ValueError(
                f"Car.aspects[{key!r}] must be a positive finite number, got {value}",
            )
        normalized[key] = value
    return normalized


def _coerce_finite_float(value: object, *, default: float | None) -> float | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _combined_relative_uncertainty(*parts: float) -> float:
    sum_sq = 0.0
    for part in parts:
        if part > 0 and math.isfinite(part):
            sum_sq += part * part
    return math.sqrt(sum_sq)
