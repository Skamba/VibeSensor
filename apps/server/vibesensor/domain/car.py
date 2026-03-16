"""The vehicle under test and car-scoped interpretive context.

``Car`` owns identity, user-facing name, vehicle type, and geometry aspects
(tire dimensions, gear ratios) that drive order analysis.  ``TireSpec``
encapsulates the three standard tire dimensions and derived geometry.
``OrderReferenceSpec`` owns tire geometry and driveline/reference-order
interpretation.  ``CarSnapshot`` is typed internal car context attached
to a run.
Configuration and persistence details remain in ``CarConfig``.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

__all__ = [
    "Car",
    "CarSnapshot",
    "OrderReferenceSpec",
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


# ---------------------------------------------------------------------------
# OrderReferenceSpec — tire geometry + driveline/reference-order interpretation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderReferenceSpec:
    """Canonical typed owner of tire geometry and driveline/reference-order
    interpretation within a Car context.

    Owns the data needed to derive wheel, driveshaft, and engine reference
    frequencies from vehicle speed.
    """

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
        settings: Mapping[str, float],
        deflection_factor: float = 1.0,
    ) -> OrderReferenceSpec | None:
        """Build from a flat settings mapping.

        Returns ``None`` if tire geometry keys are missing or invalid.
        """
        tire = TireSpec.from_aspects(settings, deflection_factor=deflection_factor)
        if tire is None:
            return None

        def _f(key: str, default: float = 0.0) -> float:
            v = settings.get(key)
            if v is None or not math.isfinite(v):
                return default
            return float(v)

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

    # -- queries -----------------------------------------------------------

    @property
    def tire_circumference_m(self) -> float:
        """Tire circumference in metres (deflection-adjusted)."""
        return self.tire_spec.circumference_m

    @property
    def has_engine_reference(self) -> bool:
        """Whether gear ratio is set (non-zero) for engine order analysis."""
        return self.current_gear_ratio != 0.0

    @property
    def is_complete(self) -> bool:
        """Whether all required fields are present for order analysis."""
        return self.final_drive_ratio > 0.0 and self.tire_spec.circumference_m > 0.0


# ---------------------------------------------------------------------------
# CarSnapshot — typed internal car context attached to a run
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CarSnapshot:
    """Typed internal car context attached to a run.

    Not an aggregate — a supporting typed internal object for run-attached
    car interpretation context.
    """

    car_id: str | None = None
    name: str | None = None
    car_type: str | None = None
    variant: str | None = None
    aspects: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.aspects, MappingProxyType):
            object.__setattr__(self, "aspects", MappingProxyType(dict(self.aspects)))

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> CarSnapshot:
        """Parse from a flat mapping. Missing keys default to ``None``/empty."""
        raw_aspects = d.get("aspects")
        aspects: dict[str, float] = {}
        if isinstance(raw_aspects, dict):
            for k, v in raw_aspects.items():
                if isinstance(k, str):
                    try:
                        aspects[k] = float(v)
                    except (TypeError, ValueError):
                        pass
        return cls(
            car_id=_str_or_none(d.get("id") or d.get("car_id")),
            name=_str_or_none(d.get("name")),
            car_type=_str_or_none(d.get("type") or d.get("car_type")),
            variant=_str_or_none(d.get("variant")),
            aspects=aspects,
        )

    def to_dict(self) -> dict[str, object]:
        """Project to a persistence-compatible dict."""
        return {
            "id": self.car_id,
            "name": self.name,
            "type": self.car_type,
            "variant": self.variant,
            "aspects": dict(self.aspects),
        }


def _str_or_none(v: object) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


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
    aspects: Mapping[str, float] = field(default_factory=dict)
    variant: str | None = None
    order_reference_spec: OrderReferenceSpec | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            object.__setattr__(self, "name", "Unnamed Car")
        # Freeze aspects to enforce immutability of the domain object.
        if not isinstance(self.aspects, MappingProxyType):
            object.__setattr__(self, "aspects", MappingProxyType(dict(self.aspects)))
        for key in ("tire_width_mm", "tire_aspect_pct", "rim_in"):
            val = self.aspects.get(key)
            if val is not None and (not math.isfinite(val) or val <= 0):
                raise ValueError(
                    f"Car.aspects[{key!r}] must be a positive finite number, got {val}"
                )
        # Eagerly derive OrderReferenceSpec from aspects when tire geometry is present.
        deflection = self.aspects.get("tire_deflection_factor", 1.0)
        if not isinstance(deflection, (int, float)) or not math.isfinite(deflection):
            deflection = 1.0
        spec = OrderReferenceSpec.from_settings(dict(self.aspects), deflection_factor=deflection)
        object.__setattr__(self, "order_reference_spec", spec)

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
