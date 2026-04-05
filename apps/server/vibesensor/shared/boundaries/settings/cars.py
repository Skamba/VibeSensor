"""Shared boundary helpers for car-settings HTTP payloads."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.shared.types.car_config import (
    CarConfigPayload,
    CarConfigUpdatePayload,
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
    return response


__all__ = ["car_config_update_payload_from_mapping", "cars_response_payload"]
