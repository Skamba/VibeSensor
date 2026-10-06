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
    sensor_frame_top_peaks_from_row_value,
)
from vibesensor.recording.sensor_frame_values import strict_optional_float

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


def selection_row_values(row: Sequence[object]) -> tuple[int, float, float, float, float]:
    """Decode one ``SELECTION_SELECT_SQL_COLS`` row; raises ``SensorFrameDecodeError``."""
    row_id = cast(int, row[0])
    source = f"samples_v2 row id={row_id}"
    t_s = strict_optional_float(row[1], field="t_s", source=source)
    strength_db = strict_optional_float(row[2], field="vibration_strength_db", source=source)
    peak_amp_g = strict_optional_float(row[3], field="strength_peak_amp_g", source=source)
    peaks = sensor_frame_top_peaks_from_row_value(row[4], source=source)
    return (
        row_id,
        _nan_if_none(t_s),
        _nan_if_none(strength_db),
        _nan_if_none(peak_amp_g),
        max((peak.amp for peak in peaks), default=math.nan),
    )


def _nan_if_none(value: float | None) -> float:
    return math.nan if value is None else value
