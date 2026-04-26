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
from typing import Literal

from vibesensor.domain._order_reference_helpers import (
    normalize_order_reference_mapping,
    order_reference_mapping_from_spec,
    order_reference_spec_from_mapping,
)
from vibesensor.domain.order_reference import OrderReferenceSpec
from vibesensor.domain.tire_spec import AxleTireSetup, TireSpec
from vibesensor.domain.vehicle_configuration import VehicleFieldConfidence

__all__ = [
    "AxleTireSetup",
    "Car",
    "OrderAnalysisCarDataConfidence",
    "OrderAnalysisCarDataScope",
    "CarOrderReferenceStatus",
    "CarOrderReferenceSourceStatus",
    "CarSnapshot",
    "OrderReferenceSpec",
    "TireSpec",
]

CarOrderReferenceSourceStatus = Literal["exact_row", "manual_entry"]
OrderAnalysisCarDataScope = Literal["tire", "driveline", "engine_speed_derived"]

_ORDER_ANALYSIS_CONFIDENCE_RANK = {
    "official_exact": 0,
    "official_derived": 1,
    "user_confirmed": 2,
    "reputable_secondary_crosschecked": 3,
    "family_default": 4,
    "unverified": 5,
}


@dataclass(frozen=True, slots=True)
class OrderAnalysisCarDataConfidence:
    """The saved-car confidence that backs one order-analysis reference path."""

    scope: OrderAnalysisCarDataScope
    confidence: VehicleFieldConfidence


@dataclass(frozen=True, slots=True)
class CarOrderReferenceStatus:
    """Persisted confidence metadata for selected drivetrain order-reference values."""

    selection_source_status: CarOrderReferenceSourceStatus
    tire_dimensions_confidence: VehicleFieldConfidence | None = None
    final_drive_ratio_confidence: VehicleFieldConfidence | None = None
    current_gear_ratio_confidence: VehicleFieldConfidence | None = None
    transmission_name: str | None = None
    transmission_confidence: VehicleFieldConfidence | None = None

    @property
    def requires_manual_confirmation(self) -> bool:
        """Whether one selected drivetrain field should be confirmed manually."""

        return any(
            confidence in {"family_default", "unverified"}
            for confidence in (
                self.tire_dimensions_confidence,
                self.final_drive_ratio_confidence,
                self.current_gear_ratio_confidence,
                self.transmission_confidence,
            )
        )

    def with_user_confirmed_fields(
        self,
        *,
        tire_dimensions: bool = False,
        current_gear_ratio: bool = False,
        final_drive_ratio: bool = False,
    ) -> CarOrderReferenceStatus:
        """Return a copy with the selected order-reference fields user-confirmed."""

        return CarOrderReferenceStatus(
            selection_source_status=(
                "manual_entry"
                if tire_dimensions or current_gear_ratio or final_drive_ratio
                else self.selection_source_status
            ),
            tire_dimensions_confidence=(
                "user_confirmed" if tire_dimensions else self.tire_dimensions_confidence
            ),
            final_drive_ratio_confidence=(
                "user_confirmed" if final_drive_ratio else self.final_drive_ratio_confidence
            ),
            current_gear_ratio_confidence=(
                "user_confirmed" if current_gear_ratio else self.current_gear_ratio_confidence
            ),
            transmission_name=self.transmission_name,
            transmission_confidence=self.transmission_confidence,
        )

    def order_analysis_car_data_confidence(
        self,
        *,
        ref_sources: tuple[str, ...] = (),
        suspected_source: str | None = None,
    ) -> OrderAnalysisCarDataConfidence | None:
        """Return the relevant saved-car confidence for one order-analysis path."""

        scope = _order_analysis_scope(ref_sources=ref_sources, suspected_source=suspected_source)
        if scope is None:
            return None
        confidences: tuple[VehicleFieldConfidence | None, ...]
        if scope == "tire":
            confidences = (self.tire_dimensions_confidence,)
        elif scope == "driveline":
            confidences = (
                self.tire_dimensions_confidence,
                self.final_drive_ratio_confidence,
            )
        else:
            confidences = (
                self.tire_dimensions_confidence,
                self.final_drive_ratio_confidence,
                self.current_gear_ratio_confidence,
            )
        return OrderAnalysisCarDataConfidence(
            scope=scope,
            confidence=_weakest_vehicle_field_confidence(confidences),
        )


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
    aspects: Mapping[str, float | str] = field(default_factory=dict)
    order_reference_status: CarOrderReferenceStatus | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.aspects, MappingProxyType):
            object.__setattr__(self, "aspects", MappingProxyType(dict(self.aspects)))


def _order_analysis_scope(
    *,
    ref_sources: tuple[str, ...],
    suspected_source: str | None,
) -> OrderAnalysisCarDataScope | None:
    normalized_sources = {
        str(source).strip().lower() for source in ref_sources if str(source).strip()
    }
    if "speed+engine" in normalized_sources:
        return "engine_speed_derived"
    if "speed+tire+final_drive" in normalized_sources or "speed+driveshaft" in normalized_sources:
        return "driveline"
    if "speed+tire" in normalized_sources:
        return "tire"
    if normalized_sources:
        return None
    normalized_source = str(suspected_source or "").strip().lower()
    if normalized_source == "wheel/tire":
        return "tire"
    if normalized_source in {"driveline", "driveshaft"}:
        return "driveline"
    if normalized_source == "engine":
        return "engine_speed_derived"
    return None


def _weakest_vehicle_field_confidence(
    confidences: tuple[VehicleFieldConfidence | None, ...],
) -> VehicleFieldConfidence:
    effective_confidences = [
        confidence if confidence is not None else "unverified" for confidence in confidences
    ]
    return max(
        effective_confidences,
        key=lambda confidence: _ORDER_ANALYSIS_CONFIDENCE_RANK[confidence],
    )


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
    order_reference_status: CarOrderReferenceStatus | None = None
    order_reference_spec: OrderReferenceSpec | None = field(default=None, repr=False)
    _aspects: Mapping[str, float | str] = field(
        init=False,
        repr=False,
    )

    def __init__(
        self,
        *,
        id: str | None = None,
        name: str = "Unnamed Car",
        car_type: str = "sedan",
        aspects: Mapping[str, object] | None = None,
        variant: str | None = None,
        order_reference_status: CarOrderReferenceStatus | None = None,
        order_reference_spec: OrderReferenceSpec | None = None,
    ) -> None:
        object.__setattr__(self, "id", id or uuid.uuid4().hex)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "car_type", car_type)
        object.__setattr__(self, "variant", variant)
        object.__setattr__(self, "order_reference_status", order_reference_status)
        object.__setattr__(self, "order_reference_spec", order_reference_spec)
        object.__setattr__(self, "_aspects", MappingProxyType({}))
        self._normalize_order_reference_state(aspects)

    def _normalize_order_reference_state(
        self,
        aspects: Mapping[str, object] | None,
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
    def aspects(self) -> Mapping[str, float | str]:
        return self._aspects

    # -- queries -----------------------------------------------------------

    @property
    def display_name(self) -> str:
        """Human-readable name with type suffix."""
        if self.car_type:
            return f"{self.name} ({self.car_type})"
        return self.name

    @property
    def tire_setup(self) -> AxleTireSetup | None:
        spec = self.order_reference_spec
        return spec.tire_setup if spec is not None else None

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
