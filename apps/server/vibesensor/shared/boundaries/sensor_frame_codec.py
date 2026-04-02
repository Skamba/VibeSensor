"""Boundary normalization helpers for diagnostics sample rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.sensor_frame import SensorFrame

type SensorFrameInput = SensorFrame | Mapping[str, object]


def normalize_sensor_frames(samples: Sequence[SensorFrameInput]) -> list[SensorFrame]:
    """Normalize boundary sample rows into canonical typed ``SensorFrame`` objects."""

    return [
        sample if isinstance(sample, SensorFrame) else SensorFrame.from_dict(sample)
        for sample in samples
    ]


def sensor_frames_to_json_objects(samples: Sequence[SensorFrame]) -> list[JsonObject]:
    """Serialize typed sensor frames at an explicit JSON boundary."""

    return [sample.to_dict() for sample in samples]
