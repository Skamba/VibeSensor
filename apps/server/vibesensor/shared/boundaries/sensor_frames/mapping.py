"""JSON/object-shaped SensorFrame boundary adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vibesensor.shared.boundaries.codecs.sensor_frame_values import SensorFrameDecodeError
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.sensor_frame import SensorFrame

from .fields import (
    sensor_frame_from_mapping_payload,
    sensor_frame_to_mapping_payload,
)

__all__ = [
    "SensorFrameDecodeError",
    "sensor_frame_from_mapping",
    "sensor_frame_to_json_object",
    "sensor_frames_from_mappings",
    "sensor_frames_to_json_objects",
]


def sensor_frame_from_mapping(
    record: Mapping[str, object],
    *,
    strict: bool = False,
    source: str = "sample payload",
) -> SensorFrame:
    """Decode one raw sample payload into the canonical typed sample object."""

    return sensor_frame_from_mapping_payload(
        record,
        strict=strict,
        source=source,
    )


def sensor_frames_from_mappings(rows: Sequence[Mapping[str, object]]) -> list[SensorFrame]:
    """Decode raw object payloads into canonical typed sample objects."""

    return [sensor_frame_from_mapping(row) for row in rows]


def sensor_frame_to_json_object(frame: SensorFrame) -> JsonObject:
    """Encode one typed sample for an explicit JSON boundary."""

    return sensor_frame_to_mapping_payload(frame)


def sensor_frames_to_json_objects(samples: Sequence[SensorFrame]) -> list[JsonObject]:
    """Serialize typed sensor frames only at an explicit JSON boundary."""

    return [sensor_frame_to_json_object(sample) for sample in samples]
