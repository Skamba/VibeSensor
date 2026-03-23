"""Shared car-configuration contracts and helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from typing_extensions import NotRequired, TypedDict  # noqa: UP035 (Pydantic on Python 3.11)

from vibesensor.shared.types.settings_types import AnalysisSettingsPayload

if TYPE_CHECKING:
    from vibesensor.domain import Car

__all__ = [
    "CarConfigPayload",
    "CarConfigUpdatePayload",
    "CarsSnapshot",
    "car_to_persistence_dict",
    "new_car_id",
]


class CarConfigUpdatePayload(TypedDict, total=False):
    id: str
    name: str
    type: str
    aspects: AnalysisSettingsPayload
    variant: str


class CarConfigPayload(TypedDict):
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


def car_to_persistence_dict(car: Car) -> CarConfigPayload:
    """Serialize a domain ``Car`` to a plain dict for JSON persistence."""
    payload: CarConfigPayload = {
        "id": car.id,
        "name": car.name,
        "type": car.car_type,
        "aspects": dict(car.aspects),
    }
    if car.variant:
        payload["variant"] = car.variant
    return payload
