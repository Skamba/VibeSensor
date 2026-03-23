"""Sample serialisation helpers for the ``samples_v2`` table.

Pure functions and schema constants that convert between canonical
:class:`~vibesensor.shared.types.sensor_frame.SensorFrame` objects and flat
SQLite row tuples. Extracted from :mod:`vibesensor.adapters.persistence.history_db`
to keep the schema-specific column definitions and conversion logic in one place.
"""

from __future__ import annotations

import logging
import math

from vibesensor.domain import StrengthPeak
from vibesensor.shared.json_utils import safe_json_dumps, safe_json_loads
from vibesensor.shared.types.json_types import is_json_array
from vibesensor.shared.types.sensor_frame import SensorFrame

LOGGER = logging.getLogger(__name__)


# -- Schema column definitions ------------------------------------------------

_V2_COLUMNS: tuple[str, ...] = (
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
    "top_peaks",
)

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
    d = item.to_dict()
    isfinite = _isfinite
    _get = d.get
    _json_cols = _JSON_COLUMNS

    vals: list[object] = []
    vals.append(run_id)
    for col in _V2_COLUMNS[1:]:
        raw = _get(col)
        if col in _json_cols:
            vals.append(safe_json_dumps(raw) if raw else None)
        elif isinstance(raw, float) and not isfinite(raw):
            vals.append(None)
        else:
            vals.append(raw)

    return tuple(vals)


def _row_optional_float(value: object, *, field: str, row_id: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"row id={row_id}: field {field} expected float-compatible value, got bool")
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if _isfinite(numeric) else None
    raise TypeError(
        f"row id={row_id}: field {field} expected float-compatible value, "
        f"got {type(value).__name__}"
    )


def _row_optional_int(value: object, *, field: str, row_id: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"row id={row_id}: field {field} expected int-compatible value, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise TypeError(
        f"row id={row_id}: field {field} expected int-compatible value, got {type(value).__name__}"
    )


def _row_top_peaks(value: object, *, row_id: object) -> tuple[StrengthPeak, ...]:
    if not value:
        return ()
    parsed = safe_json_loads(str(value), context="column top_peaks")
    if not is_json_array(parsed):
        if parsed is not None:
            LOGGER.warning(
                "v2_row_to_sensor_frame: column %r for row id=%s parsed to %s, "
                "expected list; using []",
                "top_peaks",
                row_id,
                type(parsed).__name__,
            )
        return ()
    peaks: list[StrengthPeak] = []
    for peak in parsed[:10]:
        if not isinstance(peak, dict):
            continue
        normalized_peak = StrengthPeak.from_dict(peak)
        if normalized_peak.is_valid:
            peaks.append(normalized_peak)
    return tuple(peaks)


def v2_row_to_sensor_frame(row: tuple[object, ...]) -> SensorFrame:
    """Reconstruct a typed SensorFrame from a ``samples_v2`` row."""
    row_id = row[0]
    (
        run_id,
        timestamp_utc,
        t_s,
        client_id,
        client_name,
        location,
        sample_rate_hz,
        speed_kmh,
        gps_speed_kmh,
        speed_source,
        engine_rpm,
        engine_rpm_source,
        gear,
        final_drive_ratio,
        accel_x_g,
        accel_y_g,
        accel_z_g,
        dominant_freq_hz,
        dominant_axis,
        vibration_strength_db,
        strength_bucket,
        strength_peak_amp_g,
        strength_floor_amp_g,
        frames_dropped_total,
        queue_overflow_drops,
        top_peaks_raw,
    ) = row[_V2_COL_OFFSET : _V2_COL_OFFSET + len(_V2_COLUMNS)]
    return SensorFrame(
        run_id=str(run_id or ""),
        timestamp_utc=str(timestamp_utc or ""),
        t_s=_row_optional_float(t_s, field="t_s", row_id=row_id),
        client_id=str(client_id or ""),
        client_name=str(client_name or ""),
        location=str(location or ""),
        sample_rate_hz=_row_optional_int(sample_rate_hz, field="sample_rate_hz", row_id=row_id),
        speed_kmh=_row_optional_float(speed_kmh, field="speed_kmh", row_id=row_id),
        gps_speed_kmh=_row_optional_float(gps_speed_kmh, field="gps_speed_kmh", row_id=row_id),
        speed_source=str(speed_source or ""),
        engine_rpm=_row_optional_float(engine_rpm, field="engine_rpm", row_id=row_id),
        engine_rpm_source=str(engine_rpm_source or ""),
        gear=_row_optional_float(gear, field="gear", row_id=row_id),
        final_drive_ratio=_row_optional_float(
            final_drive_ratio,
            field="final_drive_ratio",
            row_id=row_id,
        ),
        accel_x_g=_row_optional_float(accel_x_g, field="accel_x_g", row_id=row_id),
        accel_y_g=_row_optional_float(accel_y_g, field="accel_y_g", row_id=row_id),
        accel_z_g=_row_optional_float(accel_z_g, field="accel_z_g", row_id=row_id),
        dominant_freq_hz=_row_optional_float(
            dominant_freq_hz,
            field="dominant_freq_hz",
            row_id=row_id,
        ),
        dominant_axis=str(dominant_axis or ""),
        top_peaks=_row_top_peaks(top_peaks_raw, row_id=row_id),
        vibration_strength_db=_row_optional_float(
            vibration_strength_db,
            field="vibration_strength_db",
            row_id=row_id,
        ),
        strength_bucket=str(strength_bucket) if strength_bucket not in (None, "") else None,
        strength_peak_amp_g=_row_optional_float(
            strength_peak_amp_g,
            field="strength_peak_amp_g",
            row_id=row_id,
        ),
        strength_floor_amp_g=_row_optional_float(
            strength_floor_amp_g,
            field="strength_floor_amp_g",
            row_id=row_id,
        ),
        frames_dropped_total=(
            _row_optional_int(frames_dropped_total, field="frames_dropped_total", row_id=row_id)
            or 0
        ),
        queue_overflow_drops=(
            _row_optional_int(queue_overflow_drops, field="queue_overflow_drops", row_id=row_id)
            or 0
        ),
    )
