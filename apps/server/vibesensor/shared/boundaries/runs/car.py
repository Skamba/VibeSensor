"""Boundary codecs for persisted run-car metadata."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.shared.boundaries.codecs.scalars import text_or_none
from vibesensor.shared.types.car_config import (
    car_order_reference_status_from_mapping,
    car_order_reference_status_json_object_from_domain,
)
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.run_schema import RunCarMetadata

__all__ = [
    "run_car_metadata_from_mapping",
    "run_car_metadata_to_json_object",
]


def run_car_metadata_from_mapping(payload: object) -> RunCarMetadata | None:
    """Decode one raw mapping into the minimal persisted run-car metadata model."""

    if not isinstance(payload, Mapping):
        return None
    run_car = RunCarMetadata(
        car_id=text_or_none(payload.get("id")),
        name=text_or_none(payload.get("name")),
        car_type=text_or_none(payload.get("type")),
        variant=text_or_none(payload.get("variant")),
        order_reference_status=(
            car_order_reference_status_from_mapping(order_reference_status)
            if isinstance(
                (order_reference_status := payload.get("order_reference_status")),
                Mapping,
            )
            else None
        ),
    )
    if (
        run_car.car_id is None
        and run_car.name is None
        and run_car.car_type is None
        and run_car.variant is None
    ):
        return None
    return run_car


def run_car_metadata_to_json_object(run_car: RunCarMetadata | None) -> JsonObject | None:
    """Project typed run-car metadata into the canonical persisted JSON shape."""

    if run_car is None:
        return None
    payload: JsonObject = {
        "id": run_car.car_id,
        "name": run_car.name,
        "type": run_car.car_type,
        "variant": run_car.variant,
    }
    if run_car.order_reference_status is not None:
        payload["order_reference_status"] = car_order_reference_status_json_object_from_domain(
            run_car.order_reference_status
        )
    return payload
