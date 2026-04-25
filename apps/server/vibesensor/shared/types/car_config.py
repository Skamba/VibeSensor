"""Shared car-configuration contracts and helpers."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

from vibesensor.domain import (
    CarOrderReferenceSourceStatus,
    CarOrderReferenceStatus,
    VehicleFieldConfidence,
)
from vibesensor.shared.analysis_settings_schema import (
    ANALYSIS_SETTINGS_DEFAULTS,
    sanitize_analysis_settings,
)
from vibesensor.shared.types.settings_types import (
    AnalysisSettingsPayload,
    analysis_settings_payload_from_mapping,
)

if TYPE_CHECKING:
    from vibesensor.domain import Car

__all__ = [
    "CarConfigPayload",
    "CarConfigUpdatePayload",
    "CarOrderReferenceStatusPayload",
    "CarsSnapshot",
    "car_from_persistence_dict",
    "car_order_reference_status_from_mapping",
    "car_to_persistence_dict",
    "new_car_id",
]


class CarConfigUpdatePayload(TypedDict, total=False):
    """Partial update payload for mutating one stored car configuration."""

    id: str
    name: str
    type: str
    aspects: AnalysisSettingsPayload
    variant: str
    order_reference_status: CarOrderReferenceStatusPayload


class CarOrderReferenceStatusPayload(TypedDict, total=False):
    """Persisted confidence metadata for selected drivetrain order-reference values."""

    selection_source_status: CarOrderReferenceSourceStatus
    final_drive_ratio_confidence: VehicleFieldConfidence
    current_gear_ratio_confidence: VehicleFieldConfidence
    transmission_name: str
    transmission_confidence: VehicleFieldConfidence
    requires_manual_confirmation: bool


class CarConfigPayload(TypedDict):
    """Canonical persisted/shared payload for one car configuration profile."""

    id: str
    name: str
    type: str
    aspects: AnalysisSettingsPayload
    variant: NotRequired[str]
    order_reference_status: NotRequired[CarOrderReferenceStatusPayload]


@dataclass(slots=True)
class CarsSnapshot:
    """Typed internal snapshot of car profiles plus active selection."""

    cars: list[CarConfigPayload] = field(default_factory=list)
    active_car_id: str | None = None


def new_car_id() -> str:
    """Generate a new unique car configuration ID."""
    return str(uuid.uuid4())


def car_from_persistence_dict(payload: Mapping[str, object]) -> Car:
    """Decode one persisted/shared car payload into the canonical domain object."""

    from vibesensor.domain import Car

    raw_aspects = payload.get("aspects")
    aspects: dict[str, float] = dict(ANALYSIS_SETTINGS_DEFAULTS)
    if isinstance(raw_aspects, Mapping):
        aspects.update(sanitize_analysis_settings(raw_aspects))
    raw_order_reference_status = payload.get("order_reference_status")
    return Car(
        id=_text_or_default(payload.get("id"), default=new_car_id(), max_length=128),
        name=_text_or_default(payload.get("name"), default="Unnamed Car", max_length=64),
        car_type=_text_or_default(payload.get("type"), default="sedan", max_length=32),
        aspects=aspects,
        variant=_optional_text(payload.get("variant"), max_length=64),
        order_reference_status=(
            car_order_reference_status_from_mapping(raw_order_reference_status)
            if isinstance(raw_order_reference_status, Mapping)
            else None
        ),
    )


def car_to_persistence_dict(car: Car) -> CarConfigPayload:
    """Serialize a domain ``Car`` to a plain dict for JSON persistence."""
    payload: CarConfigPayload = {
        "id": car.id,
        "name": car.name,
        "type": car.car_type,
        "aspects": analysis_settings_payload_from_mapping(car.aspects),
    }
    if car.variant:
        payload["variant"] = car.variant
    if car.order_reference_status is not None:
        payload["order_reference_status"] = _car_order_reference_status_payload(
            car.order_reference_status
        )
    return payload


def car_order_reference_status_from_mapping(
    payload: Mapping[str, object],
) -> CarOrderReferenceStatus:
    selection_source_status = payload.get("selection_source_status")
    if selection_source_status not in {"compat_projection", "exact_row", "manual_entry"}:
        selection_source_status = "manual_entry"
    return CarOrderReferenceStatus(
        selection_source_status=cast(CarOrderReferenceSourceStatus, selection_source_status),
        final_drive_ratio_confidence=_optional_confidence(
            payload.get("final_drive_ratio_confidence")
        ),
        current_gear_ratio_confidence=_optional_confidence(
            payload.get("current_gear_ratio_confidence")
        ),
        transmission_name=_optional_text(payload.get("transmission_name"), max_length=128),
        transmission_confidence=_optional_confidence(payload.get("transmission_confidence")),
    )


def _car_order_reference_status_payload(
    status: CarOrderReferenceStatus,
) -> CarOrderReferenceStatusPayload:
    payload: CarOrderReferenceStatusPayload = {
        "selection_source_status": status.selection_source_status,
        "requires_manual_confirmation": status.requires_manual_confirmation,
    }
    if status.final_drive_ratio_confidence is not None:
        payload["final_drive_ratio_confidence"] = status.final_drive_ratio_confidence
    if status.current_gear_ratio_confidence is not None:
        payload["current_gear_ratio_confidence"] = status.current_gear_ratio_confidence
    if status.transmission_name is not None:
        payload["transmission_name"] = status.transmission_name
    if status.transmission_confidence is not None:
        payload["transmission_confidence"] = status.transmission_confidence
    return payload


def _text_or_default(value: object, *, default: str, max_length: int) -> str:
    if value is not None:
        text = str(value).strip()[:max_length]
        if text:
            return text
    return default


def _optional_text(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()[:max_length]
    return text or None


def _optional_confidence(value: object) -> VehicleFieldConfidence | None:
    if value in {
        "official_exact",
        "official_derived",
        "reputable_secondary_crosschecked",
        "family_default",
        "unverified",
        "user_confirmed",
    }:
        return cast(VehicleFieldConfidence, value)
    return None
