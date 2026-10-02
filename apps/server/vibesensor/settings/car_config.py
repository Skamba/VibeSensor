"""Shared car-configuration contracts and helpers."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, NotRequired, TypedDict, cast

from pydantic import StringConstraints

from vibesensor.domain.car import CarOrderReferenceSourceStatus, CarOrderReferenceStatus
from vibesensor.domain.vehicle_configuration import VehicleFieldConfidence
from vibesensor.settings.analysis_settings_schema import (
    ANALYSIS_SETTINGS_DEFAULTS,
    sanitize_analysis_settings,
)
from vibesensor.settings.settings_types import (
    AnalysisSettingsPayload,
    analysis_settings_payload_from_mapping,
)

if TYPE_CHECKING:
    from vibesensor.domain.car import Car

__all__ = [
    "CarConfigPayload",
    "CarConfigUpdatePayload",
    "CarOrderReferenceStatusPayload",
    "CarsSnapshot",
    "car_from_persistence_dict",
    "car_order_reference_status_payload_from_domain",
    "car_order_reference_status_from_mapping",
    "car_to_persistence_dict",
    "new_car_id",
]


_CarText = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class CarOrderReferenceStatusPayload(TypedDict):
    """Persisted/HTTP confidence metadata for selected drivetrain order-reference values.

    Confidence values stay plain strings at this boundary;
    ``car_order_reference_status_from_mapping`` keeps only the known vocabulary.
    """

    selection_source_status: CarOrderReferenceSourceStatus
    requires_manual_confirmation: bool
    tire_dimensions_confidence: NotRequired[str | None]
    final_drive_ratio_confidence: NotRequired[str | None]
    current_gear_ratio_confidence: NotRequired[str | None]
    transmission_name: NotRequired[str | None]
    transmission_confidence: NotRequired[str | None]


class CarConfigPayload(TypedDict):
    """One car profile as persisted in the settings snapshot and served over HTTP."""

    id: str
    name: str
    type: str
    aspects: AnalysisSettingsPayload
    variant: NotRequired[str | None]
    order_reference_status: NotRequired[CarOrderReferenceStatusPayload | None]


class CarConfigUpdatePayload(TypedDict, total=False):
    """Create/update request body for one car profile; omitted or null fields stay unchanged."""

    name: _CarText | None
    type: _CarText | None
    aspects: AnalysisSettingsPayload | None
    variant: _CarText | None
    order_reference_status: CarOrderReferenceStatusPayload | None


@dataclass(slots=True)
class CarsSnapshot:
    """Car profiles plus the active selection, as held in memory and served over HTTP."""

    cars: list[CarConfigPayload]
    active_car_id: str | None


def new_car_id() -> str:
    """Generate a new unique car configuration ID."""
    return str(uuid.uuid4())


def car_from_persistence_dict(payload: Mapping[str, object]) -> Car:
    """Decode one persisted/shared car payload into the canonical domain object."""

    from vibesensor.domain.car import Car

    raw_aspects = payload.get("aspects")
    aspects: dict[str, float | str] = dict(ANALYSIS_SETTINGS_DEFAULTS)
    if isinstance(raw_aspects, Mapping):
        for key, value in sanitize_analysis_settings(raw_aspects).items():
            if isinstance(value, float | str):
                aspects[key] = value
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
        payload["order_reference_status"] = car_order_reference_status_payload_from_domain(
            car.order_reference_status
        )
    return payload


def car_order_reference_status_from_mapping(
    payload: Mapping[str, object],
) -> CarOrderReferenceStatus:
    selection_source_status = payload.get("selection_source_status")
    if selection_source_status not in {"exact_row", "manual_entry"}:
        selection_source_status = "manual_entry"
    return CarOrderReferenceStatus(
        selection_source_status=cast(CarOrderReferenceSourceStatus, selection_source_status),
        tire_dimensions_confidence=_optional_confidence(payload.get("tire_dimensions_confidence")),
        final_drive_ratio_confidence=_optional_confidence(
            payload.get("final_drive_ratio_confidence")
        ),
        current_gear_ratio_confidence=_optional_confidence(
            payload.get("current_gear_ratio_confidence")
        ),
        transmission_name=_optional_text(payload.get("transmission_name"), max_length=128),
        transmission_confidence=_optional_confidence(payload.get("transmission_confidence")),
    )


def car_order_reference_status_payload_from_domain(
    status: CarOrderReferenceStatus,
) -> CarOrderReferenceStatusPayload:
    payload: CarOrderReferenceStatusPayload = {
        "selection_source_status": status.selection_source_status,
        "requires_manual_confirmation": status.requires_manual_confirmation,
    }
    if status.tire_dimensions_confidence is not None:
        payload["tire_dimensions_confidence"] = status.tire_dimensions_confidence
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
        return value
    return None
