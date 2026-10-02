"""Sample serialisation helpers for the ``samples_v2`` table.

Pure functions and schema constants that convert between canonical
:class:`~vibesensor.shared.types.sensor_frame.SensorFrame` objects and flat
SQLite row tuples. Extracted from :mod:`vibesensor.adapters.persistence.history_db`
to keep the schema-specific column definitions and conversion logic in one place.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from vibesensor.shared.boundaries.sensor_frames.fields import (
    SENSOR_FRAME_FIELD_NAMES,
    sensor_frame_from_row_payload,
    sensor_frame_to_row_payload,
)
from vibesensor.shared.types.sensor_frame import SensorFrame

LOGGER = logging.getLogger(__name__)


# -- Schema column definitions ------------------------------------------------

_V2_COLUMNS: tuple[str, ...] = SENSOR_FRAME_FIELD_NAMES

V2_INSERT_SQL: str = (
    f"INSERT INTO samples_v2 ({', '.join(_V2_COLUMNS)}) "
    f"VALUES ({', '.join('?' * len(_V2_COLUMNS))})"
)

_V2_SELECT_COLS: tuple[str, ...] = ("id",) + _V2_COLUMNS
V2_SELECT_SQL_COLS: str = ", ".join(_V2_SELECT_COLS)

# Row offset: skip autoincrement id column in SELECT results.
_V2_COL_OFFSET: int = 1

# -- Row conversion -----------------------------------------------------------


def sample_to_v2_row(run_id: str, item: SensorFrame) -> tuple[object, ...]:
    """Convert a typed SensorFrame to a row tuple for ``samples_v2``."""
    row = sensor_frame_to_row_values(item)
    return (run_id, *row[1:])


def v2_row_to_sensor_frame(row: tuple[object, ...]) -> SensorFrame:
    """Reconstruct a typed SensorFrame from a ``samples_v2`` row."""
    row_id = row[0] if row else "?"
    return sensor_frame_from_row(
        row,
        row_offset=_V2_COL_OFFSET,
        source=f"samples_v2 row id={row_id}",
    )


def sensor_frame_from_row(
    row: Sequence[object],
    *,
    row_offset: int = 0,
    source: str = "sample row",
) -> SensorFrame:
    """Decode one ordered storage row into the canonical typed sample object."""

    return sensor_frame_from_row_payload(row, row_offset=row_offset, source=source)


def sensor_frame_to_row_values(frame: SensorFrame) -> tuple[object, ...]:
    """Encode one typed sample into flat ordered row values for storage."""

    return sensor_frame_to_row_payload(frame)
