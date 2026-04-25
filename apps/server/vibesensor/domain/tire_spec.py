"""Tire geometry value objects for vehicle order analysis."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "AxleTireSetup",
    "TireSpeedAxle",
    "TireSpec",
]

type TireSpeedAxle = Literal["front", "rear", "average"]


@dataclass(frozen=True, slots=True)
class TireSpec:
    """Validated tire dimensions with derived geometry."""

    width_mm: float
    aspect_pct: float
    rim_in: float
    deflection_factor: float = 1.0

    @classmethod
    def from_aspects(
        cls,
        aspects: Mapping[str, float],
        *,
        deflection_factor: float = 1.0,
    ) -> TireSpec | None:
        """Return a ``TireSpec`` if all three dimensions are present and valid."""
        width = aspects.get("tire_width_mm")
        aspect = aspects.get("tire_aspect_pct")
        rim = aspects.get("rim_in")
        if width is None or aspect is None or rim is None:
            return None
        if not (math.isfinite(width) and math.isfinite(aspect) and math.isfinite(rim)):
            return None
        if width <= 0 or aspect <= 0 or rim <= 0:
            return None
        df = float(deflection_factor) if math.isfinite(deflection_factor) else 1.0
        if df <= 0 or df > 1.0:
            df = 1.0
        return cls(width_mm=width, aspect_pct=aspect, rim_in=rim, deflection_factor=df)

    @property
    def sidewall_mm(self) -> float:
        """Tire sidewall height in millimetres."""
        return self.width_mm * (self.aspect_pct / 100.0)

    @property
    def diameter_mm(self) -> float:
        """Overall tire diameter in millimetres."""
        return (self.rim_in * 25.4) + (2.0 * self.sidewall_mm)

    @property
    def circumference_m(self) -> float:
        """Tire circumference in metres (deflection-adjusted)."""
        return self.diameter_mm / 1000.0 * math.pi * self.deflection_factor


@dataclass(frozen=True, slots=True)
class AxleTireSetup:
    """Canonical tire setup that can represent square or staggered axles."""

    front: TireSpec
    rear: TireSpec
    default_axle_for_speed: TireSpeedAxle = "rear"
    source_confidence: str | None = None

    @classmethod
    def square(
        cls,
        spec: TireSpec,
        *,
        default_axle_for_speed: TireSpeedAxle = "rear",
        source_confidence: str | None = None,
    ) -> AxleTireSetup:
        return cls(
            front=spec,
            rear=spec,
            default_axle_for_speed=default_axle_for_speed,
            source_confidence=source_confidence,
        )

    @property
    def is_staggered(self) -> bool:
        return self.front != self.rear

    @property
    def boundary_tire_spec(self) -> TireSpec:
        """Compatibility tire spec for flat boundary projections."""

        if self.default_axle_for_speed == "rear":
            return self.rear
        return self.front

    @property
    def effective_tire_circumference_m(self) -> float:
        """Resolved tire circumference used by order-analysis math."""

        if self.default_axle_for_speed == "front":
            return self.front.circumference_m
        if self.default_axle_for_speed == "rear":
            return self.rear.circumference_m
        return (self.front.circumference_m + self.rear.circumference_m) / 2.0
