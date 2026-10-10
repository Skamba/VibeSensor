"""Low-level samples_v2 row encoding and decoding coverage."""

from __future__ import annotations

import contextlib
import json
from dataclasses import fields

import numpy as np
import pytest

from vibesensor.history.sample_store import (
    _V2_COL_OFFSET,
    _V2_COLUMNS,
    SampleSelectionColumns,
    sample_to_v2_row,
    selection_columns_from_rows,
    selection_row_values,
    v2_row_to_sensor_frame,
    v2_rows_to_sensor_frames,
)
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_mapping import sensor_frame_from_mapping
from vibesensor.recording.sensor_frame_values import SensorFrameDecodeError


def _frame() -> SensorFrame:
    return sensor_frame_from_mapping(
        {
            "run_id": "run-1",
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "t_s": 1.25,
            "analysis_window_start_us": 750000,
            "analysis_window_end_us": 1250000,
            "analysis_window_synced": True,
            "client_id": "client-1",
            "client_name": "Front left",
            "location": "front_left",
            "sample_rate_hz": 800,
            "speed_kmh": 42.5,
            "gps_speed_kmh": 43.0,
            "speed_source": "gps",
            "engine_rpm": 2100.0,
            "engine_rpm_source": "obd",
            "gear": 4.0,
            "final_drive_ratio": 3.55,
            "accel_x_g": 0.1,
            "accel_y_g": 0.2,
            "accel_z_g": 0.3,
            "dominant_freq_hz": 56.0,
            "dominant_axis": "x",
            "top_peaks": [{"hz": 56.0, "amp_g": 0.42}],
            "vibration_strength_db": 12.3,
            "strength_bucket": "moderate",
            "strength_peak_amp_g": 0.42,
            "strength_floor_amp_g": 0.02,
            "frames_dropped_total": 5,
            "queue_overflow_drops": 2,
        }
    )


def test_v2_row_to_sensor_frame_round_trips_typed_row() -> None:
    frame = _frame()
    row = (123, *sample_to_v2_row(frame.run_id, frame))
    assert v2_row_to_sensor_frame(row) == frame


def test_v2_row_to_sensor_frame_rejects_non_numeric_scalar_columns() -> None:
    frame = _frame()
    row = list((123, *sample_to_v2_row(frame.run_id, frame)))
    row[_V2_COL_OFFSET + _V2_COLUMNS.index("sample_rate_hz")] = "fast"

    with pytest.raises(SensorFrameDecodeError, match="sample_rate_hz"):
        v2_row_to_sensor_frame(tuple(row))


def _row(row_id: int, **overrides: object) -> tuple[object, ...]:
    """A stored row of ``_frame()`` with some columns replaced by raw stored values."""
    frame = _frame()
    row = [row_id, *sample_to_v2_row(frame.run_id, frame)]
    for column, value in overrides.items():
        row[_V2_COL_OFFSET + _V2_COLUMNS.index(column)] = value
    return tuple(row)


_PEAKS_JSON = (
    '[{"hz":56.0,"amp":0.42,"vibration_strength_db":12.3,"strength_bucket":"l2",'
    '"local_floor_amp_g":0.01},{"hz":0.0,"amp":0.5},{"hz":20,"amp":0.1}]'
)
_CANONICAL_ROWS = [
    _row(1),
    _row(2, top_peaks=None, speed_kmh=None, analysis_window_synced=0, strength_bucket=None),
    _row(3, top_peaks=_PEAKS_JSON, accel_x_g=float("inf"), gear=None),
    _row(4, top_peaks=json.dumps([{"hz": float(i + 1), "amp": 0.1} for i in range(12)])),
    _row(5, top_peaks="[]", client_name=None, frames_dropped_total=None),
]


def _field_types(frame: SensorFrame) -> list[str]:
    return [type(getattr(frame, field.name)).__name__ for field in fields(SensorFrame)]


def _one_row_at_a_time(rows: list[tuple[object, ...]]) -> list[SensorFrame]:
    frames = []
    for row in rows:
        with contextlib.suppress(SensorFrameDecodeError):
            frames.append(v2_row_to_sensor_frame(row))
    return frames


def test_v2_rows_to_sensor_frames_matches_one_row_at_a_time() -> None:
    frames, skipped = v2_rows_to_sensor_frames(_CANONICAL_ROWS)

    expected = _one_row_at_a_time(_CANONICAL_ROWS)
    assert skipped == 0
    assert frames == expected
    assert [_field_types(frame) for frame in frames] == [_field_types(f) for f in expected]


@pytest.mark.parametrize(
    ("overrides", "corrupt"),
    [
        pytest.param({"speed_kmh": 80}, False, id="integer-in-float-column"),
        pytest.param({"sample_rate_hz": 800.0}, False, id="float-in-integer-column"),
        pytest.param({"analysis_window_start_us": 2**60}, False, id="integer-past-float-precision"),
        pytest.param({"top_peaks": '[{"hz":"56","amp":0.4}]'}, False, id="text-peak-number"),
        pytest.param({"top_peaks": '[{"hz":56.0,"amp":null}]'}, False, id="null-peak-amp"),
        pytest.param({"top_peaks": '[{"hz":56.0,"amp":NaN}]'}, False, id="nan-token"),
        pytest.param(
            {"top_peaks": '[{"hz":56.0,"amp":0.4,"strength_bucket":" l2 "}]'},
            False,
            id="untrimmed-bucket",
        ),
        pytest.param({"top_peaks": '[42, {"hz":56.0,"amp":0.4}]'}, False, id="non-object-peak"),
        pytest.param({"sample_rate_hz": "fast"}, True, id="text-in-integer-column"),
        pytest.param({"top_peaks": "{not json"}, True, id="invalid-peak-json"),
        pytest.param({"top_peaks": '{"hz":56.0}'}, True, id="peak-object-not-list"),
    ],
)
def test_v2_rows_to_sensor_frames_decodes_unusual_rows_like_one_row_at_a_time(
    overrides: dict[str, object], corrupt: bool
) -> None:
    rows = [*_CANONICAL_ROWS, _row(6, **overrides)]

    frames, skipped = v2_rows_to_sensor_frames(rows)

    expected = _one_row_at_a_time(rows)
    assert skipped == int(corrupt)
    assert len(expected) == len(rows) - int(corrupt)
    assert frames == expected
    assert [_field_types(frame) for frame in frames] == [_field_types(f) for f in expected]


def _selection_rows(rows: list[tuple[object, ...]]) -> list[tuple[object, ...]]:
    columns = ("t_s", "vibration_strength_db", "strength_peak_amp_g", "top_peaks")
    return [
        (row[0], *(row[_V2_COL_OFFSET + _V2_COLUMNS.index(column)] for column in columns))
        for row in rows
    ]


def _selection_one_row_at_a_time(rows: list[tuple[object, ...]]) -> SampleSelectionColumns:
    decoded = []
    for row in rows:
        with contextlib.suppress(SensorFrameDecodeError):
            decoded.append(selection_row_values(row))
    return SampleSelectionColumns.from_rows(decoded)


def _assert_same_columns(actual: SampleSelectionColumns, expected: SampleSelectionColumns) -> None:
    for field in fields(SampleSelectionColumns):
        actual_values = getattr(actual, field.name)
        expected_values = getattr(expected, field.name)
        assert actual_values.dtype == expected_values.dtype
        np.testing.assert_array_equal(actual_values, expected_values)


@pytest.mark.parametrize(
    ("extra_row", "corrupt"),
    [
        pytest.param(None, False, id="well-formed"),
        pytest.param(_row(6, t_s=3), False, id="integer-time"),
        pytest.param(_row(6, top_peaks='[{"hz":"56","amp":0.9}]'), False, id="text-peak-number"),
        pytest.param(_row(6, vibration_strength_db="loud"), True, id="text-strength"),
        pytest.param(_row(6, top_peaks="[oops"), True, id="invalid-peak-json"),
    ],
)
def test_selection_columns_from_rows_matches_one_row_at_a_time(
    extra_row: tuple[object, ...] | None, corrupt: bool
) -> None:
    rows = _selection_rows([*_CANONICAL_ROWS, *([extra_row] if extra_row else [])])

    columns, skipped = selection_columns_from_rows(rows)

    assert skipped == int(corrupt)
    _assert_same_columns(columns, _selection_one_row_at_a_time(rows))
