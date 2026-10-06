"""Order-reference value object and helper math for vehicle diagnostics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypedDict

from vibesensor.domain.tire_spec import AxleTireSetup, TireSpec

__all__ = [
    "OrderFrequencies",
    "OrderReferenceSpec",
    "order_reference_mapping_from_spec",
    "wheel_hz_from_speed_kmh",
]

_KMH_TO_MPS = 1.0 / 3.6


def _wheel_hz_from_speed_mps(speed_mps: float, tire_circumference_m: float) -> float | None:
    if not math.isfinite(speed_mps) or speed_mps <= 0:
        return None
    if not math.isfinite(tire_circumference_m) or tire_circumference_m <= 0:
        return None
    result = speed_mps / tire_circumference_m
    return result if math.isfinite(result) else None


def wheel_hz_from_speed_kmh(speed_kmh: float, tire_circumference_m: float) -> float | None:
    """Wheel rotational frequency (Hz) from vehicle speed (km/h) and tire circumference (m).

    Returns ``None`` for non-positive or non-finite inputs or results.
    """
    if not math.isfinite(speed_kmh) or speed_kmh <= 0:
        return None
    return _wheel_hz_from_speed_mps(speed_kmh * _KMH_TO_MPS, tire_circumference_m)


class OrderFrequencies(TypedDict, total=False):
    """Rotational order frequencies (Hz) per family; a family without its references is absent."""

    wheel_hz: float
    wheel_uncertainty_pct: float
    drive_hz: float
    drive_uncertainty_pct: float
    engine_hz: float
    engine_uncertainty_pct: float


@dataclass(frozen=True, slots=True)
class OrderReferenceSpec:
    """Typed owner of tire geometry and driveline/reference-order math."""

    tire_setup: AxleTireSetup
    final_drive_ratio: float
    current_gear_ratio: float
    speed_uncertainty_pct: float
    tire_diameter_uncertainty_pct: float
    final_drive_uncertainty_pct: float
    gear_uncertainty_pct: float

    @property
    def tire_spec(self) -> TireSpec:
        """Compatibility tire spec for flat boundary consumers."""

        return self.tire_setup.boundary_tire_spec

    @property
    def default_axle_for_speed(self) -> str:
        return self.tire_setup.default_axle_for_speed

    @property
    def tire_circumference_m(self) -> float:
        """Resolved tire circumference in metres for order-analysis math."""
        return self.tire_setup.effective_tire_circumference_m

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
        return _wheel_hz_from_speed_mps(speed_mps, self.tire_circumference_m)

    def engine_hz(self, speed_mps: float) -> float | None:
        """Engine rotational frequency (Hz) from vehicle speed (m/s)."""
        whz = self.wheel_hz(speed_mps)
        if whz is None or not self.supports_engine_reference:
            return None
        result = whz * self.final_drive_ratio * self.current_gear_ratio
        return result if math.isfinite(result) else None

    def wheel_hz_from_speed_kmh(self, speed_kmh: float) -> float | None:
        return wheel_hz_from_speed_kmh(speed_kmh, self.tire_circumference_m)

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

    def engine_rpm_from_speed_kmh(self, speed_kmh: float) -> float | None:
        engine_hz = self.engine_hz_from_speed_kmh(speed_kmh)
        if engine_hz is None:
            return None
        engine_rpm = engine_hz * 60.0
        return engine_rpm if math.isfinite(engine_rpm) else None

    def orders_hz_from_speed_mps(self, speed_mps: float | None) -> OrderFrequencies:
        """Order frequencies for each family the references support.

        Wheel orders need the tire, driveshaft orders also the final drive, and
        engine orders also the gear ratio; a missing reference drops only its
        own family.
        """
        orders: OrderFrequencies = {}
        if speed_mps is None or not math.isfinite(speed_mps) or speed_mps <= 0:
            return orders
        wheel_hz = self.wheel_hz_from_speed_mps(speed_mps)
        if wheel_hz is None:
            return orders
        orders["wheel_hz"] = wheel_hz
        orders["wheel_uncertainty_pct"] = self.wheel_uncertainty_pct
        drive_hz = self.driveshaft_hz_from_wheel_hz(wheel_hz)
        if drive_hz is None or drive_hz <= 0:
            return orders
        orders["drive_hz"] = drive_hz
        orders["drive_uncertainty_pct"] = self.drive_uncertainty_pct
        engine_hz = self.engine_hz_from_wheel_hz(wheel_hz)
        if engine_hz is not None and engine_hz > 0:
            orders["engine_hz"] = engine_hz
            orders["engine_uncertainty_pct"] = self.engine_uncertainty_pct
        return orders


def _combined_relative_uncertainty(*parts: float) -> float:
    sum_sq = 0.0
    for part in parts:
        if part > 0 and math.isfinite(part):
            sum_sq += part * part
    return math.sqrt(sum_sq)


def order_reference_mapping_from_spec(spec: OrderReferenceSpec) -> dict[str, float | str]:
    """Project an order-reference spec into the flat settings mapping boundary."""

    boundary_tire = spec.tire_spec
    payload: dict[str, float | str] = {
        "tire_width_mm": boundary_tire.width_mm,
        "tire_aspect_pct": boundary_tire.aspect_pct,
        "rim_in": boundary_tire.rim_in,
        "speed_uncertainty_pct": spec.speed_uncertainty_pct,
        "tire_diameter_uncertainty_pct": spec.tire_diameter_uncertainty_pct,
        "final_drive_uncertainty_pct": spec.final_drive_uncertainty_pct,
        "gear_uncertainty_pct": spec.gear_uncertainty_pct,
        "tire_deflection_factor": boundary_tire.deflection_factor,
    }
    # A missing ratio stays missing rather than turning into 0.0.
    if spec.final_drive_ratio > 0:
        payload["final_drive_ratio"] = spec.final_drive_ratio
    if spec.current_gear_ratio > 0:
        payload["current_gear_ratio"] = spec.current_gear_ratio
    setup = spec.tire_setup
    if setup.is_staggered or setup.default_axle_for_speed != "rear":
        payload.update(
            {
                "front_tire_width_mm": setup.front.width_mm,
                "front_tire_aspect_pct": setup.front.aspect_pct,
                "front_rim_in": setup.front.rim_in,
                "rear_tire_width_mm": setup.rear.width_mm,
                "rear_tire_aspect_pct": setup.rear.aspect_pct,
                "rear_rim_in": setup.rear.rim_in,
                "default_axle_for_speed": setup.default_axle_for_speed,
            }
        )
    return payload
