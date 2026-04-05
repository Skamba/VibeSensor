"""Shared boundary helpers for speed-source HTTP payloads."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import SpeedSourceKind
from vibesensor.shared.types.speed_source_config import SpeedSourcePayload, SpeedSourceUpdatePayload


def speed_source_update_payload_from_mapping(
    payload: Mapping[str, object],
) -> SpeedSourceUpdatePayload:
    """Project a request-like mapping into the canonical speed-source update payload."""

    update: SpeedSourceUpdatePayload = {}
    speed_source = payload.get("speed_source")
    if isinstance(speed_source, SpeedSourceKind):
        update["speedSource"] = speed_source
    elif isinstance(speed_source, str):
        update["speedSource"] = SpeedSourceKind(speed_source)
    manual_speed_kph = payload.get("manual_speed_kph")
    if isinstance(manual_speed_kph, (int, float)) and not isinstance(manual_speed_kph, bool):
        update["manualSpeedKph"] = float(manual_speed_kph)
    stale_timeout_s = payload.get("stale_timeout_s")
    if isinstance(stale_timeout_s, (int, float)) and not isinstance(stale_timeout_s, bool):
        update["staleTimeoutS"] = float(stale_timeout_s)
    obd_device_mac = payload.get("obd_device_mac")
    if isinstance(obd_device_mac, str):
        update["obdDeviceMac"] = obd_device_mac
    obd_device_name = payload.get("obd_device_name")
    if isinstance(obd_device_name, str):
        update["obdDeviceName"] = obd_device_name
    return update


def speed_source_response_payload(payload: SpeedSourcePayload) -> dict[str, object]:
    """Project the canonical speed-source payload into the HTTP response shape."""

    return {
        "speed_source": payload["speedSource"],
        "manual_speed_kph": payload["manualSpeedKph"],
        "stale_timeout_s": payload["staleTimeoutS"],
        "obd_device_mac": payload.get("obdDeviceMac"),
        "obd_device_name": payload.get("obdDeviceName"),
    }


__all__ = ["speed_source_response_payload", "speed_source_update_payload_from_mapping"]
