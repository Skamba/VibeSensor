"""The vehicle under test.

``Car`` owns identity, user-facing name, vehicle type, and geometry aspects
(tire dimensions, gear ratios) that drive order analysis.  Configuration
and persistence details remain in ``CarConfig``.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

__all__ = [
    "Car",
]


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

    # -- queries -----------------------------------------------------------

    @property
    def display_name(self) -> str:
        """Human-readable name with optional type suffix."""
        if self.car_type and self.car_type != "sedan":
            return f"{self.name} ({self.car_type})"
        return self.name

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

        Uses the standard sidewall/diameter formula:
        ``diameter = (rim_in × 25.4) + 2 × (width_mm × aspect_pct / 100)``
        ``circumference = π × diameter``

        Returns ``None`` if any required dimension is missing or invalid.
        """
        width = self.tire_width_mm
        aspect = self.tire_aspect_pct
        rim = self.rim_in
        if width is None or aspect is None or rim is None:
            return None
        if not (math.isfinite(width) and math.isfinite(aspect) and math.isfinite(rim)):
            return None
        if width <= 0 or aspect <= 0 or rim <= 0:
            return None
        sidewall_mm = width * (aspect / 100.0)
        diameter_mm = (rim * 25.4) + (2.0 * sidewall_mm)
        diameter_m = diameter_mm / 1000.0
        return diameter_m * math.pi
