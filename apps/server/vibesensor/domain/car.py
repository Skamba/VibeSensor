"""The vehicle under test.

``Car`` owns identity, user-facing name, vehicle type, and geometry aspects
(tire dimensions, gear ratios) that drive order analysis.  ``TireSpec``
encapsulates the three standard tire dimensions and derived geometry.
Configuration and persistence details remain in ``CarConfig``.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

__all__ = [
    "Car",
    "TireSpec",
]


@dataclass(frozen=True, slots=True)
class TireSpec:
    """Validated tire dimensions with derived geometry.

    Create via :meth:`from_aspects` when reading from a ``Car.aspects``
    dict; use the constructor directly when the three values are already
    known and validated.
    """

    width_mm: float
    aspect_pct: float
    rim_in: float
    deflection_factor: float = 1.0

    @classmethod
    def from_aspects(
        cls,
        aspects: dict[str, float],
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
class Car:
    """The vehicle under test.

    Owns identity, user-facing name, vehicle type, and geometry aspects
    (tire dimensions, gear ratios) that drive order analysis.
    Configuration and persistence details remain in ``CarConfig``.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "Unnamed Car"
    car_type: str = "sedan"
    aspects: dict[str, float] = field(default_factory=dict)
    variant: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            object.__setattr__(self, "name", "Unnamed Car")
        for key in ("tire_width_mm", "tire_aspect_pct", "rim_in"):
            val = self.aspects.get(key)
            if val is not None and (not math.isfinite(val) or val < 0):
                raise ValueError(
                    f"Car.aspects[{key!r}] must be a positive finite number, got {val}"
                )

    # -- queries -----------------------------------------------------------

    @property
    def display_name(self) -> str:
        """Human-readable name with type suffix."""
        if self.car_type:
            return f"{self.name} ({self.car_type})"
        return self.name

    @property
    def tire_spec(self) -> TireSpec | None:
        """Parsed tire dimensions, or ``None`` if incomplete."""
        return TireSpec.from_aspects(self.aspects)

    @property
    def tire_width_mm(self) -> float | None:
        return self.aspects.get("tire_width_mm")

    @property
    def tire_aspect_pct(self) -> float | None:
        return self.aspects.get("tire_aspect_pct")

    @property
    def rim_in(self) -> float | None:
        """Rim diameter in inches (aspects key ``rim_in``)."""
        return self.aspects.get("rim_in")

    @property
    def tire_circumference_m(self) -> float | None:
        """Compute tire circumference in metres from aspect specs.

        Returns ``None`` if any required dimension is missing or invalid.
        """
        spec = self.tire_spec
        return spec.circumference_m if spec else None
