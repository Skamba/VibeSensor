"""Shared boundary helpers for sensor-settings HTTP payloads."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.shared.types.sensor_config import SensorConfigUpdatePayload, SensorsByMacPayload


def sensor_config_update_payload_from_mapping(
    payload: Mapping[str, object],
) -> SensorConfigUpdatePayload:
    """Project a request-like mapping into the canonical sensor update payload."""

    update: SensorConfigUpdatePayload = {}
    name = payload.get("name")
    if isinstance(name, str):
        update["name"] = name
    location_code = payload.get("location_code")
    if isinstance(location_code, str):
        update["location_code"] = location_code
    return update


def sensors_response_payload(sensors_by_mac: SensorsByMacPayload) -> dict[str, object]:
    """Project persisted sensor metadata into the canonical HTTP response payload."""

    payload: dict[str, object] = {"sensors_by_mac": _sensor_payloads(sensors_by_mac)}
    return payload


def _sensor_payloads(sensors_by_mac: SensorsByMacPayload) -> dict[str, object]:
    payload: dict[str, object] = {}
    for mac, sensor in sensors_by_mac.items():
        payload[mac] = {
            "name": sensor["name"],
            "location_code": sensor["location_code"],
        }
    return payload


__all__ = ["sensor_config_update_payload_from_mapping", "sensors_response_payload"]
