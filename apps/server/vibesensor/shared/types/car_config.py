"""Shared car-configuration contracts and helpers."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NotRequired, TypedDict

from vibesensor.shared.types.settings_types import (
    AnalysisSettingsPayload,
    analysis_settings_payload_from_mapping,
)

if TYPE_CHECKING:
    from vibesensor.domain import Car

__all__ = [
    "CarConfigPayload",
    "CarConfigUpdatePayload",
    "CarsSnapshot",
    "car_from_persistence_dict",
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


class CarConfigPayload(TypedDict):
    """Canonical persisted/shared payload for one car configuration profile."""

    id: str
    name: str
    type: str
    aspects: AnalysisSettingsPayload
    variant: NotRequired[str]


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
    from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot

    raw_aspects = payload.get("aspects")
    aspects: dict[str, float] = dict(AnalysisSettingsSnapshot.DEFAULTS)
    if isinstance(raw_aspects, Mapping):
        aspects.update(AnalysisSettingsSnapshot.sanitize(raw_aspects))
    return Car(
        id=_text_or_default(payload.get("id"), default=new_car_id(), max_length=128),
        name=_text_or_default(payload.get("name"), default="Unnamed Car", max_length=64),
        car_type=_text_or_default(payload.get("type"), default="sedan", max_length=32),
        aspects=aspects,
        variant=_optional_text(payload.get("variant"), max_length=64),
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
