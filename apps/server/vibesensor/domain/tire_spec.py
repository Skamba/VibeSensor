"""Tire geometry value object for vehicle order analysis."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "TireSpec",
]


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
