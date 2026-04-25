"""Helpers for stable per-run sensor metadata snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from vibesensor.domain import normalize_sensor_id
from vibesensor.shared.sensor_metadata import resolve_sensor_presentation
from vibesensor.shared.types.run_schema import RunSensorMetadata
from vibesensor.shared.types.sensor_config import SensorConfigPayload

if TYPE_CHECKING:
    from vibesensor.shared.ports import ClientTracker, SensorMetadataReader


def build_run_sensor_snapshot(
    *,
    sensor_id: str,
    fallback_name: str,
    fallback_location_code: str,
    sample_rate_hz: int | None,
    firmware_version: str | None,
    sensors_by_mac: Mapping[str, SensorConfigPayload],
) -> RunSensorMetadata:
    """Build one stable run-scoped sensor snapshot from live metadata inputs."""

    display_name, location_code = resolve_sensor_presentation(
        sensor_id=sensor_id,
        sensors_by_mac=sensors_by_mac,
        fallback_name=fallback_name,
        fallback_location_code=fallback_location_code,
    )
    mount_orientation = _mount_orientation_or_none(
        sensor_id=sensor_id,
        sensors_by_mac=sensors_by_mac,
    )
    return RunSensorMetadata(
        sensor_id=sensor_id,
        display_name=display_name,
        location_code=location_code,
        mount_orientation=mount_orientation,
        sample_rate_hz=sample_rate_hz,
        firmware_version=firmware_version,
    )


def capture_run_sensor_snapshots(
    *,
    client_ids: Iterable[str],
    registry: ClientTracker,
    sensor_metadata_reader: SensorMetadataReader | None,
) -> dict[str, RunSensorMetadata]:
    """Capture deterministic run-start snapshots for the supplied client ids."""

    sensors_by_mac = sensor_metadata_reader.get_sensors() if sensor_metadata_reader else {}
    snapshots: dict[str, RunSensorMetadata] = {}
    normalized_client_ids = {
        str(client_id).strip() for client_id in client_ids if str(client_id).strip()
    }
    for client_id in sorted(normalized_client_ids):
        record = registry.get(client_id)
        if record is None:
            continue
        snapshots[client_id] = build_run_sensor_snapshot(
            sensor_id=str(getattr(record, "client_id", client_id) or client_id),
            fallback_name=str(getattr(record, "name", "") or ""),
            fallback_location_code=str(getattr(record, "location_code", "") or ""),
            sample_rate_hz=_sample_rate_hz_or_none(getattr(record, "sample_rate_hz", None)),
            firmware_version=_text_or_none(getattr(record, "firmware_version", None)),
            sensors_by_mac=sensors_by_mac,
        )
    return snapshots


def _sample_rate_hz_or_none(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        sample_rate_hz = value
    elif isinstance(value, float):
        sample_rate_hz = int(value)
    elif isinstance(value, str):
        try:
            sample_rate_hz = int(value)
        except ValueError:
            return None
    else:
        return None
    return sample_rate_hz if sample_rate_hz > 0 else None


def _text_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _mount_orientation_or_none(
    *,
    sensor_id: str,
    sensors_by_mac: Mapping[str, SensorConfigPayload],
) -> str | None:
    try:
        normalized_sensor_id = normalize_sensor_id(sensor_id)
    except ValueError:
        return None
    sensor = sensors_by_mac.get(normalized_sensor_id)
    if sensor is None:
        return None
    text = str(sensor.get("mount_orientation") or "").strip()
    return text or None
