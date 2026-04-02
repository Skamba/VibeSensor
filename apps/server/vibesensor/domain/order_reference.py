"""Order-reference value object and helper math for vehicle diagnostics."""

from __future__ import annotations

import math
from dataclasses import dataclass

from vibesensor.domain.tire_spec import TireSpec

__all__ = ["OrderReferenceSpec"]

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
def _combined_relative_uncertainty(*parts: float) -> float:
    sum_sq = 0.0
    for part in parts:
        if part > 0 and math.isfinite(part):
            sum_sq += part * part
    return math.sqrt(sum_sq)
