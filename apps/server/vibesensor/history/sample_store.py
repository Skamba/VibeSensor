"""Sample serialisation helpers for the ``samples_v2`` table.

Pure functions and schema constants that convert between canonical
:class:`~vibesensor.recording.sensor_frame.SensorFrame` objects and flat
SQLite row tuples. Extracted from :mod:`vibesensor.history.history_db`
to keep the schema-specific column definitions and conversion logic in one place.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np
import numpy.typing as npt

from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_fields import (
    SENSOR_FRAME_FIELD_NAMES,
    sensor_frame_from_row_payload,
    sensor_frame_to_row_payload,
    sensor_frame_top_peak_amp_from_row_value,
    sensor_frames_from_canonical_rows,
    storage_float_column,
    storage_top_peak_amp_column,
)
from vibesensor.recording.sensor_frame_values import (
    SensorFrameDecodeError,
    strict_optional_float,
)

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


def v2_rows_to_sensor_frames(rows: Sequence[tuple[object, ...]]) -> tuple[list[SensorFrame], int]:
    """Decode ``samples_v2`` rows in order; returns the frames and how many rows were corrupt.

    A batch of well-formed rows is decoded column by column; otherwise each row
    is decoded on its own and a corrupt one is skipped and logged.
    """
    frames = sensor_frames_from_canonical_rows(rows, row_offset=_V2_COL_OFFSET)
    if frames is not None:
        return frames, 0
    frames = []
    skipped = 0
    for row in rows:
        try:
            frames.append(v2_row_to_sensor_frame(row))
        except SensorFrameDecodeError as exc:
            skipped += 1
            LOGGER.warning("Skipping corrupt v2 sample row id=%s: %s", row[0], exc)
    return frames, skipped


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


# -- Light per-row projection ---------------------------------------------------

SELECTION_SELECT_SQL_COLS: str = "id, t_s, vibration_strength_db, strength_peak_amp_g, top_peaks"

type Float64Array = npt.NDArray[np.float64]
type Int64Array = npt.NDArray[np.int64]


@dataclass(frozen=True, slots=True, eq=False)
class SampleSelectionColumns:
    """A few decoded columns per ``samples_v2`` row, in id order, for picking rows to load.

    Missing values are NaN. ``top_peak_amp_g`` is the largest valid ``top_peaks``
    amplitude, decoded exactly as a full :class:`SensorFrame` decode would.
    """

    row_id: Int64Array
    t_s: Float64Array
    vibration_strength_db: Float64Array
    strength_peak_amp_g: Float64Array
    top_peak_amp_g: Float64Array

    def __len__(self) -> int:
        return int(self.row_id.shape[0])

    @classmethod
    def from_rows(
        cls, rows: Sequence[tuple[int, float, float, float, float]]
    ) -> SampleSelectionColumns:
        values = np.array(rows, dtype=np.float64).reshape(-1, 5)
        return cls(
            row_id=np.array([row[0] for row in rows], dtype=np.int64),
            t_s=values[:, 1].copy(),
            vibration_strength_db=values[:, 2].copy(),
            strength_peak_amp_g=values[:, 3].copy(),
            top_peak_amp_g=values[:, 4].copy(),
        )

    @classmethod
    def concatenate(cls, parts: Sequence[SampleSelectionColumns]) -> SampleSelectionColumns:
        if not parts:
            return cls.from_rows([])
        return cls(
            row_id=np.concatenate([part.row_id for part in parts]),
            t_s=np.concatenate([part.t_s for part in parts]),
            vibration_strength_db=np.concatenate([part.vibration_strength_db for part in parts]),
            strength_peak_amp_g=np.concatenate([part.strength_peak_amp_g for part in parts]),
            top_peak_amp_g=np.concatenate([part.top_peak_amp_g for part in parts]),
        )


def selection_columns_from_rows(
    rows: Sequence[Sequence[object]],
) -> tuple[SampleSelectionColumns, int]:
    """Decode ``SELECTION_SELECT_SQL_COLS`` rows; returns the columns and the corrupt-row count.

    A batch of well-formed rows is decoded column by column; otherwise each row
    is decoded on its own and a corrupt one is skipped and logged.
    """
    columns = _canonical_selection_columns(rows)
    if columns is not None:
        return columns, 0
    decoded: list[tuple[int, float, float, float, float]] = []
    skipped = 0
    for row in rows:
        try:
            decoded.append(selection_row_values(row))
        except SensorFrameDecodeError as exc:
            skipped += 1
            LOGGER.warning("Skipping corrupt v2 sample row id=%s: %s", row[0], exc)
    return SampleSelectionColumns.from_rows(decoded), skipped


def _canonical_selection_columns(
    rows: Sequence[Sequence[object]],
) -> SampleSelectionColumns | None:
    if not rows:
        return SampleSelectionColumns.from_rows([])
    if any(len(row) < 5 for row in rows):
        return None
    row_ids, *stored = list(zip(*rows, strict=False))[:5]
    if not set(map(type, row_ids)) <= {int}:
        return None
    floats: list[Float64Array] = []
    for values in stored[:3]:
        decoded = storage_float_column(values)
        if decoded is None:
            return None
        floats.append(np.array(decoded, dtype=np.float64))
    top_peak_amps = storage_top_peak_amp_column(stored[3])
    if top_peak_amps is None:
        return None
    return SampleSelectionColumns(
        row_id=np.array(row_ids, dtype=np.int64),
        t_s=floats[0],
        vibration_strength_db=floats[1],
        strength_peak_amp_g=floats[2],
        top_peak_amp_g=np.array(top_peak_amps, dtype=np.float64),
    )


def selection_row_values(row: Sequence[object]) -> tuple[int, float, float, float, float]:
    """Decode one ``SELECTION_SELECT_SQL_COLS`` row; raises ``SensorFrameDecodeError``."""
    row_id = cast(int, row[0])
    source = f"samples_v2 row id={row_id}"
    t_s = strict_optional_float(row[1], field="t_s", source=source)
    strength_db = strict_optional_float(row[2], field="vibration_strength_db", source=source)
    peak_amp_g = strict_optional_float(row[3], field="strength_peak_amp_g", source=source)
    top_peak_amp_g = sensor_frame_top_peak_amp_from_row_value(row[4], source=source)
    return (
        row_id,
        _nan_if_none(t_s),
        _nan_if_none(strength_db),
        _nan_if_none(peak_amp_g),
        _nan_if_none(top_peak_amp_g),
    )


def _nan_if_none(value: float | None) -> float:
    return math.nan if value is None else value
