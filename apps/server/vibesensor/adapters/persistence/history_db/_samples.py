"""Sample serialisation helpers for the ``samples_v2`` table.

Pure functions and schema constants that convert between canonical
:class:`~vibesensor.shared.types.sensor_frame.SensorFrame` objects and flat
SQLite row tuples. Extracted from :mod:`vibesensor.adapters.persistence.history_db`
to keep the schema-specific column definitions and conversion logic in one place.
"""

from __future__ import annotations

import logging
import math

from vibesensor.shared.boundaries.sensor_frame_codec import (
    SENSOR_FRAME_FIELD_NAMES,
    sensor_frame_from_row,
    sensor_frame_to_json_object,
)
from vibesensor.shared.boundaries.strength_metrics_codec import (
    strength_peak_payloads,
)
from vibesensor.shared.json_utils import safe_json_dumps
from vibesensor.shared.types.sensor_frame import SensorFrame

LOGGER = logging.getLogger(__name__)


# -- Schema column definitions ------------------------------------------------

_V2_COLUMNS: tuple[str, ...] = SENSOR_FRAME_FIELD_NAMES

# Columns whose values are JSON-serialised for storage.
_JSON_COLUMNS: frozenset[str] = frozenset({"top_peaks"})

V2_INSERT_SQL: str = (
    f"INSERT INTO samples_v2 ({', '.join(_V2_COLUMNS)}) "
    f"VALUES ({', '.join('?' * len(_V2_COLUMNS))})"
)

_V2_SELECT_COLS: tuple[str, ...] = ("id",) + _V2_COLUMNS
V2_SELECT_SQL_COLS: str = ", ".join(_V2_SELECT_COLS)

# Row offset: skip autoincrement id column in SELECT results.
_V2_COL_OFFSET: int = 1

# Allowed table names for keyset pagination.
ALLOWED_SAMPLE_TABLES: frozenset[str] = frozenset({"samples_v2"})

# Module-level binding avoids repeated attribute lookup in hot loops.
_isfinite = math.isfinite


# -- Row conversion -----------------------------------------------------------


def sample_to_v2_row(run_id: str, item: SensorFrame) -> tuple[object, ...]:
    """Convert a typed SensorFrame to a row tuple for ``samples_v2``."""
    d = sensor_frame_to_json_object(item)
    isfinite = _isfinite
    _get = d.get
    _json_cols = _JSON_COLUMNS

    vals: list[object] = []
    vals.append(run_id)
    for col in _V2_COLUMNS[1:]:
        raw = _get(col)
        if col in _json_cols:
            payload = strength_peak_payloads(item.top_peaks) if col == "top_peaks" else raw
            vals.append(safe_json_dumps(payload) if payload else None)
        elif isinstance(raw, float) and not isfinite(raw):
            vals.append(None)
        else:
            vals.append(raw)

    return tuple(vals)


def v2_row_to_sensor_frame(row: tuple[object, ...]) -> SensorFrame:
    """Reconstruct a typed SensorFrame from a ``samples_v2`` row."""
    row_id = row[0] if row else "?"
    return sensor_frame_from_row(
        row,
        row_offset=_V2_COL_OFFSET,
        source=f"samples_v2 row id={row_id}",
    )
