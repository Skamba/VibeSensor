"""Tests for JSONL run-log parsing, normalization, and metadata helpers."""

from __future__ import annotations

import json

import pytest

from vibesensor.common.json_utils import as_float_or_none, as_int_or_none
from vibesensor.common.time_utils import (
    coerce_utc_offset_seconds,
    format_timestamp_in_recorded_timezone,
    format_utc_timestamp,
    parse_iso8601,
    utc_now_iso,
)
from vibesensor.recording.run_metadata import run_metadata_to_json_object
from vibesensor.recording.run_metadata_builder import create_run_metadata
from vibesensor.recording.run_schema import RUN_METADATA_TYPE

# -- Helpers -------------------------------------------------------------------


def _make_run_metadata(*, run_id: str = "r1", **overrides) -> dict:
    """Build a ``create_run_metadata`` dict with sensible test defaults."""
    defaults = {
        "run_id": run_id,
        "start_time_utc": "2025-01-01T00:00:00Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 200,
        "feature_interval_s": 0.5,
        "fft_window_size_samples": 256,
        "accel_scale_g_per_lsb": 1.0 / 256.0,
    }
    defaults.update(overrides)
    return run_metadata_to_json_object(create_run_metadata(**defaults))


# -- utc_now_iso ---------------------------------------------------------------


def test_utc_now_iso_returns_valid_isoformat() -> None:
    result = utc_now_iso()
    assert isinstance(result, str)
    # Should be parseable by parse_iso8601
    parsed = parse_iso8601(result)
    assert parsed is not None
    # Should contain timezone info (UTC offset)
    assert "+" in result or "Z" in result


# -- parse_iso8601 ------------------------------------------------------------


def test_parse_iso8601_valid_utc() -> None:
    result = parse_iso8601("2025-01-15T10:30:00+00:00")
    assert result is not None
    assert result.year == 2025
    assert result.month == 1


def test_parse_iso8601_z_suffix() -> None:
    result = parse_iso8601("2025-01-15T10:30:00Z")
    assert result is not None
    assert result.tzinfo is not None


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "not-a-date", 12345, 3.14],
    ids=["none", "empty", "whitespace", "invalid-str", "int", "float"],
)
def test_parse_iso8601_returns_none_for_bad_input(value: object) -> None:
    assert parse_iso8601(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2025-01-15T10:30:00Z", "2025-01-15 10:30:00 UTC"),
        ("2025-01-15T12:30:00+02:00", "2025-01-15 10:30:00 UTC"),
        ("2025-01-15 10:30:00", "2025-01-15 10:30:00 UTC"),
        ("not-a-date", "not-a-date"),
        ("", None),
        (None, None),
    ],
)
def test_format_utc_timestamp(value: object, expected: str | None) -> None:
    assert format_utc_timestamp(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (7200, 7200),
        ("7200", 7200),
        (-19800, -19800),
        (None, None),
        ("bad", None),
        (15 * 60 * 60, None),
        (True, None),
    ],
)
def test_coerce_utc_offset_seconds(value: object, expected: int | None) -> None:
    assert coerce_utc_offset_seconds(value) == expected


def test_create_run_metadata_keeps_recorded_utc_offset_seconds() -> None:
    metadata = _make_run_metadata(recorded_utc_offset_seconds=7200)
    assert metadata["recorded_utc_offset_seconds"] == 7200


# -- as_float_or_none ---------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3.14, 3.14),
        (42, 42.0),
        ("2.5", 2.5),
        (0, 0.0),
        (None, None),
        ("", None),
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
        ("abc", None),
        (True, None),
        (False, None),
    ],
)
def test_as_float_or_none(value: object, expected: float | None) -> None:
    assert as_float_or_none(value) is expected or as_float_or_none(value) == expected


# -- as_int_or_none ------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3.7, 4),
        (3.2, 3),
        (5, 5),
        (None, None),
        ("abc", None),
        (float("nan"), None),
        (True, None),
        (False, None),
    ],
)
def test_as_int_or_none(value: object, expected: int | None) -> None:
    assert as_int_or_none(value) is expected or as_int_or_none(value) == expected


# -- normalize_sample_record ---------------------------------------------------


# -- read_jsonl_run -----------------------------------------------------------


def _sample_line(t_s: float) -> str:
    return json.dumps({"record_type": "sample", "t_s": t_s})


# -- create_run_metadata -------------------------------------------------------


def test_create_run_metadata_basic_fields() -> None:
    meta = _make_run_metadata()
    assert meta["record_type"] == RUN_METADATA_TYPE
    assert meta["run_id"] == "r1"
    assert meta["sensor_model"] == "ADXL345"


def test_create_run_metadata_includes_firmware_version_when_provided() -> None:
    meta = _make_run_metadata(firmware_version="esp-fw-1.2.3")
    assert meta["firmware_version"] == "esp-fw-1.2.3"


# ---------------------------------------------------------------------------
# Fix 3: read_jsonl_run warns on duplicate metadata records
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Fix 4: read_jsonl_run end record missing end_time_utc is not silently set to None
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "recorded_utc_offset_seconds", "expected"),
    [
        ("2025-01-15T10:30:00Z", 7200, "2025-01-15 12:30:00 UTC+02:00"),
        ("2025-01-15T10:30:00Z", -19800, "2025-01-15 05:00:00 UTC-05:30"),
        ("2025-01-15 10:30:00", 7200, "2025-01-15 12:30:00 UTC+02:00"),
        ("2025-01-15T10:30:00Z", None, "2025-01-15 10:30:00 UTC"),
        ("not-a-date", 7200, "not-a-date"),
        ("", 7200, None),
        (None, 7200, None),
    ],
)
def test_format_timestamp_in_recorded_timezone(
    value: object,
    recorded_utc_offset_seconds: object,
    expected: str | None,
) -> None:
    assert format_timestamp_in_recorded_timezone(value, recorded_utc_offset_seconds) == expected
