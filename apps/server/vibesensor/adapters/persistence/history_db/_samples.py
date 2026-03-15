"""Sample serialisation helpers for the ``samples_v2`` table.

Pure functions and schema constants that convert between in-memory sample
dicts / :class:`~vibesensor.domain_models.SensorFrame` objects and flat
SQLite row tuples.  Extracted from :mod:`vibesensor.adapters.persistence.history_db` to keep the
schema-specific column definitions and conversion logic in one place.
"""

from __future__ import annotations

import logging
import math
from typing import TypeGuard

from vibesensor.adapters.udp.protocol import SensorFrame
from vibesensor.shared.types.json import JsonObject, JsonValue, is_json_array, is_json_object
from vibesensor.shared.utils.json_utils import safe_json_dumps, safe_json_loads

LOGGER = logging.getLogger(__name__)


def _is_json_scalar(value: object) -> TypeGuard[JsonValue]:
    return value is None or isinstance(value, (bool, int, float, str))


# -- Schema column definitions ------------------------------------------------

_V2_TYPED_COLS: tuple[str, ...] = (
    "run_id",
    "timestamp_utc",
    "t_s",
    "client_id",
    "client_name",
    "location",
    "sample_rate_hz",
    "speed_kmh",
    "gps_speed_kmh",
    "speed_source",
    "engine_rpm",
    "engine_rpm_source",
    "gear",
    "final_drive_ratio",
    "accel_x_g",
    "accel_y_g",
    "accel_z_g",
    "dominant_freq_hz",
    "dominant_axis",
    "vibration_strength_db",
    "strength_bucket",
    "strength_peak_amp_g",
    "strength_floor_amp_g",
    "frames_dropped_total",
    "queue_overflow_drops",
)

_V2_PEAK_COLS: tuple[str, ...] = ("top_peaks",)

_V2_INSERT_COLS: tuple[str, ...] = _V2_TYPED_COLS + _V2_PEAK_COLS
V2_INSERT_SQL: str = (
    f"INSERT INTO samples_v2 ({', '.join(_V2_INSERT_COLS)}) "
    f"VALUES ({', '.join('?' * len(_V2_INSERT_COLS))})"
)

_V2_SELECT_COLS: tuple[str, ...] = ("id",) + _V2_INSERT_COLS
V2_SELECT_SQL_COLS: str = ", ".join(_V2_SELECT_COLS)

# Row offsets for v2_row_to_dict (avoids len() at runtime).
_V2_TYPED_OFFSET: int = 1  # skip autoincrement id
_V2_PEAK_OFFSET: int = _V2_TYPED_OFFSET + len(_V2_TYPED_COLS)

# Allowed table names for keyset pagination.
ALLOWED_SAMPLE_TABLES: frozenset[str] = frozenset({"samples_v2"})

# Module-level binding avoids repeated attribute lookup in hot loops.
_isfinite = math.isfinite


# -- Row conversion -----------------------------------------------------------


def sample_to_v2_row(run_id: str, item: JsonObject | SensorFrame) -> tuple[object, ...]:
    """Convert a sample dict or SensorFrame to a row tuple for ``samples_v2``."""
    if isinstance(item, SensorFrame):
        raw_item = item.to_dict()
        if not is_json_object(raw_item):
            raise TypeError("SensorFrame.to_dict() must return a JSON object")
        d = raw_item
    else:
        d = item
    isfinite = _isfinite
    _get = d.get

    vals: list[object] = []

    vals.append(run_id)
    for col in _V2_TYPED_COLS[1:]:
        val = _get(col)
        if isinstance(val, float) and not isfinite(val):
            val = None
        vals.append(val)

    for col in _V2_PEAK_COLS:
        raw = _get(col)
        vals.append(safe_json_dumps(raw) if raw else None)

    return tuple(vals)


def v2_row_to_dict(row: tuple[object, ...]) -> JsonObject:
    """Reconstruct a sample dict from a ``samples_v2`` row.

    *row* layout: ``(id, <typed cols>, <peak cols>)``.
    """
    d: JsonObject = {}

    for i, col in enumerate(_V2_TYPED_COLS):
        val = row[_V2_TYPED_OFFSET + i]
        if _is_json_scalar(val):
            d[col] = val

    for i, col in enumerate(_V2_PEAK_COLS):
        raw = row[_V2_PEAK_OFFSET + i]
        if raw:
            parsed = safe_json_loads(raw, context=f"peak column {col}")  # type: ignore[arg-type]
            if is_json_array(parsed):
                d[col] = parsed
            else:
                if parsed is not None:
                    LOGGER.warning(
                        "v2_row_to_dict: peak column %r for row id=%s parsed to %s, "
                        "expected list; using []",
                        col,
                        row[0],
                        type(parsed).__name__,
                    )
                d[col] = []
        else:
            d[col] = []

    return d
