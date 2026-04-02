"""The vehicle under test and car-scoped interpretive context.

``Car`` owns identity, user-facing name, vehicle type, and geometry aspects
(tire dimensions, gear ratios) that drive order analysis. Supporting value
objects now live in dedicated modules: ``tire_spec.py`` owns tire geometry
and ``order_reference.py`` owns order-reference math. ``CarSnapshot`` stays
here as the typed internal car context attached to a run.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from vibesensor.domain.order_reference import OrderReferenceSpec
from vibesensor.domain.tire_spec import TireSpec
from vibesensor.shared.order_reference_settings import (
    normalize_order_reference_mapping,
    order_reference_mapping_from_spec,
    order_reference_spec_from_mapping,
)

__all__ = [
    "Car",
    "CarSnapshot",
    "OrderReferenceSpec",
    "TireSpec",
]


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


@dataclass(frozen=True, slots=True, init=False)
class Car:
    """The vehicle under test.

    Owns identity, user-facing name, vehicle type, and geometry aspects
    (tire dimensions, gear ratios) that drive order analysis.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "Unnamed Car"
    car_type: str = "sedan"
    variant: str | None = None
    order_reference_spec: OrderReferenceSpec | None = field(default=None, repr=False)
    _aspects: Mapping[str, float] = field(
        init=False,
        repr=False,
    )

    def __init__(
        self,
        *,
        id: str | None = None,
        name: str = "Unnamed Car",
        car_type: str = "sedan",
        aspects: Mapping[str, float] | None = None,
        variant: str | None = None,
        order_reference_spec: OrderReferenceSpec | None = None,
    ) -> None:
        object.__setattr__(self, "id", id or uuid.uuid4().hex)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "car_type", car_type)
        object.__setattr__(self, "variant", variant)
        object.__setattr__(self, "order_reference_spec", order_reference_spec)
        object.__setattr__(self, "_aspects", MappingProxyType({}))
        self._normalize_order_reference_state(aspects)

    def _normalize_order_reference_state(
        self,
        aspects: Mapping[str, float] | None,
    ) -> None:
        if not self.name or not self.name.strip():
            object.__setattr__(self, "name", "Unnamed Car")
        normalized_aspects = normalize_order_reference_mapping(aspects or {})
        spec = self.order_reference_spec or order_reference_spec_from_mapping(normalized_aspects)
        object.__setattr__(self, "order_reference_spec", spec)
        if spec is not None:
            normalized_aspects = order_reference_mapping_from_spec(spec)
        object.__setattr__(self, "_aspects", MappingProxyType(normalized_aspects))

    @property
    def aspects(self) -> Mapping[str, float]:
        return self._aspects

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
        spec = self.order_reference_spec
        return spec.tire_spec if spec is not None else None

    @property
    def tire_width_mm(self) -> float | None:
        spec = self.tire_spec
        return spec.width_mm if spec is not None else None

    @property
    def tire_aspect_pct(self) -> float | None:
        spec = self.tire_spec
        return spec.aspect_pct if spec is not None else None

    @property
    def rim_in(self) -> float | None:
        """Rim diameter in inches (aspects key ``rim_in``)."""
        spec = self.tire_spec
        return spec.rim_in if spec is not None else None

    @property
    def tire_circumference_m(self) -> float | None:
        """Compute tire circumference in metres from aspect specs.

        Returns ``None`` if any required dimension is missing or invalid.
        """
        spec = self.order_reference_spec
        return spec.tire_circumference_m if spec is not None else None
