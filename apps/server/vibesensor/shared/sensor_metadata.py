"""Helpers for resolving canonical sensor metadata over runtime state."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import normalize_sensor_id
from vibesensor.shared.types.sensor_config import SensorConfigPayload

__all__ = ["resolve_sensor_presentation"]


def resolve_sensor_presentation(
    *,
    sensor_id: str,
    sensors_by_mac: Mapping[str, SensorConfigPayload],
    fallback_name: str,
    fallback_location_code: str,
) -> tuple[str, str]:
    """Return canonical display metadata for *sensor_id* with runtime fallbacks.

    Persisted sensor settings are authoritative when they contain a custom name
    or location. A stored name equal to the normalized sensor identifier is
    treated as the default placeholder, so live runtime naming can still supply
    the visible label in that case.
    """

    try:
        normalized_sensor_id = normalize_sensor_id(sensor_id)
    except ValueError:
        return fallback_name, fallback_location_code
    sensor = sensors_by_mac.get(normalized_sensor_id)
    if sensor is None:
        return fallback_name, fallback_location_code

    raw_name = str(sensor.get("name") or "").strip()
    resolved_name = fallback_name if not raw_name or raw_name == normalized_sensor_id else raw_name
    raw_location = str(sensor.get("location_code") or "").strip()
    resolved_location = raw_location or fallback_location_code
    return resolved_name, resolved_location
