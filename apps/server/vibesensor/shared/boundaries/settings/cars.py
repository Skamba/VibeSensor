"""Shared boundary helpers for car-settings HTTP payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from vibesensor.domain import CarOrderReferenceSourceStatus, VehicleFieldConfidence
from vibesensor.shared.types.car_config import (
    CarConfigPayload,
    CarConfigUpdatePayload,
    CarOrderReferenceStatusPayload,
    CarsSnapshot,
)
from vibesensor.shared.types.settings_types import analysis_settings_payload_from_mapping


def car_config_update_payload_from_mapping(payload: Mapping[str, object]) -> CarConfigUpdatePayload:
    """Project a request-like mapping into the canonical car update payload."""

    update: CarConfigUpdatePayload = {}
    name = payload.get("name")
    if isinstance(name, str):
        update["name"] = name
    car_type = payload.get("type")
    if isinstance(car_type, str):
        update["type"] = car_type
    aspects = payload.get("aspects")
    if isinstance(aspects, Mapping):
        update["aspects"] = analysis_settings_payload_from_mapping(aspects)
    variant = payload.get("variant")
    if isinstance(variant, str):
        update["variant"] = variant
    order_reference_status = payload.get("order_reference_status")
    if isinstance(order_reference_status, Mapping):
        update["order_reference_status"] = _car_order_reference_status_payload_from_mapping(
            order_reference_status
        )
    return update


def cars_response_payload(snapshot: CarsSnapshot) -> dict[str, object]:
    """Project a typed car snapshot into the canonical HTTP response payload."""

    cars: list[dict[str, object]] = [_car_response_payload(payload) for payload in snapshot.cars]
    payload: dict[str, object] = {"cars": cars, "active_car_id": snapshot.active_car_id}
    return payload


def _car_response_payload(payload: CarConfigPayload) -> dict[str, object]:
    response: dict[str, object] = {
        "id": payload["id"],
        "name": payload["name"],
        "type": payload["type"],
        "aspects": {key: value for key, value in payload["aspects"].items()},
    }
    variant = payload.get("variant")
    if variant is not None:
        response["variant"] = variant
    order_reference_status = payload.get("order_reference_status")
    if order_reference_status is not None:
        response["order_reference_status"] = {
            key: value for key, value in order_reference_status.items()
        }
    return response


def _car_order_reference_status_payload_from_mapping(
    payload: Mapping[str, object],
) -> CarOrderReferenceStatusPayload:
    status: CarOrderReferenceStatusPayload = {}
    selection_source_status = payload.get("selection_source_status")
    if selection_source_status in {"compat_projection", "exact_row", "manual_entry"}:
        status["selection_source_status"] = cast(
            CarOrderReferenceSourceStatus,
            selection_source_status,
        )
    for key in (
        "tire_dimensions_confidence",
        "current_gear_ratio_confidence",
        "final_drive_ratio_confidence",
        "transmission_confidence",
    ):
        value = payload.get(key)
        if value in {
            "official_exact",
            "official_derived",
            "reputable_secondary_crosschecked",
            "family_default",
            "unverified",
            "user_confirmed",
        }:
            status[key] = cast(VehicleFieldConfidence, value)
    transmission_name = payload.get("transmission_name")
    if isinstance(transmission_name, str):
        status["transmission_name"] = transmission_name
    return status


__all__ = ["car_config_update_payload_from_mapping", "cars_response_payload"]
