"""Canonical boundary package for typed ``SensorFrame`` payload codecs.

Shared field ownership lives in ``fields.py``. ``mapping.py`` and ``rows.py``
stay as the narrow JSON/object and ordered-row adapters.
"""

from ..codecs.sensor_frame_values import SensorFrameDecodeError
from .fields import SENSOR_FRAME_FIELD_NAMES
from .mapping import (
    sensor_frame_from_mapping,
    sensor_frame_to_json_object,
    sensor_frames_from_mappings,
    sensor_frames_to_json_objects,
)
from .rows import (
    sensor_frame_from_row,
    sensor_frame_to_row_values,
    sensor_frames_from_rows,
)

__all__ = [
    "SENSOR_FRAME_FIELD_NAMES",
    "SensorFrameDecodeError",
    "sensor_frame_from_mapping",
    "sensor_frame_from_row",
    "sensor_frame_to_json_object",
    "sensor_frame_to_row_values",
    "sensor_frames_from_mappings",
    "sensor_frames_from_rows",
    "sensor_frames_to_json_objects",
]
