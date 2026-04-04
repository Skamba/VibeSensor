"""Ordered storage-row SensorFrame boundary adapters."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.shared.types.sensor_frame import SensorFrame

from .fields import (
    SENSOR_FRAME_FIELD_NAMES,
    sensor_frame_from_row_payload,
    sensor_frame_to_row_payload,
)

__all__ = [
    "SENSOR_FRAME_FIELD_NAMES",
    "sensor_frame_from_row",
    "sensor_frame_to_row_values",
    "sensor_frames_from_rows",
]


def sensor_frame_from_row(
    row: Sequence[object],
    *,
    row_offset: int = 0,
    source: str = "sample row",
) -> SensorFrame:
    """Decode one ordered storage row into the canonical typed sample object."""

    return sensor_frame_from_row_payload(row, row_offset=row_offset, source=source)


def sensor_frames_from_rows(rows: Sequence[Sequence[object]]) -> list[SensorFrame]:
    """Decode ordered rows into canonical typed sample objects."""

    return [sensor_frame_from_row(row) for row in rows]


def sensor_frame_to_row_values(frame: SensorFrame) -> tuple[object, ...]:
    """Encode one typed sample into flat ordered row values for storage."""

    return sensor_frame_to_row_payload(frame)
