"""Tests for JSONL run-log parsing, normalization, and metadata helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibesensor.shared.boundaries.runs.log import (
    RUN_METADATA_TYPE,
    normalize_sample_record,
    read_jsonl_run,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_to_json_object
from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none
from vibesensor.shared.sampling import bounded_sample
from vibesensor.shared.time_utils import (
    coerce_utc_offset_seconds,
    format_timestamp_in_recorded_timezone,
    format_utc_timestamp,
    parse_iso8601,
    utc_now_iso,
)
from vibesensor.use_cases.run.run_metadata_builder import create_run_metadata

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


def test_normalize_sample_record_basic() -> None:
    record = {
        "t_s": "1.5",
        "speed_kmh": 80,
        "accel_x_g": 0.01,
        "accel_y_g": 0.02,
        "accel_z_g": 0.03,
    }
    result = normalize_sample_record(record)
    assert result.t_s == 1.5
    assert result.speed_kmh == 80.0


def test_normalize_sample_record_handles_nan_values() -> None:
    record = {"t_s": float("nan"), "speed_kmh": None}
    result = normalize_sample_record(record)
    assert result.t_s is None
    assert result.speed_kmh is None


def test_normalize_sample_record_filters_invalid_peaks() -> None:
    record = {
        "top_peaks": [
            {"hz": 10.0, "amp": 0.5},
            {"hz": -1.0, "amp": 0.1},  # invalid hz
            {"hz": 20.0, "amp": None},  # invalid amp
            "not_a_dict",  # not a dict
        ],
    }
    result = normalize_sample_record(record)
    assert len(result.top_peaks) == 1
    assert result.top_peaks[0].hz == 10.0


def test_normalize_sample_record_limits_peaks_to_10() -> None:
    peaks = [{"hz": float(i + 1), "amp": 0.1} for i in range(15)]
    record = {"top_peaks": peaks}
    result = normalize_sample_record(record)
    assert len(result.top_peaks) == 10


def test_normalize_sample_record_preserves_optional_peak_metadata() -> None:
    record = {
        "top_peaks": [
            {
                "hz": 18.0,
                "amp": 0.22,
                "vibration_strength_db": 27.5,
                "strength_bucket": "l4",
            },
        ],
    }
    result = normalize_sample_record(record)
    assert result.top_peaks[0].vibration_strength_db == 27.5
    assert result.top_peaks[0].strength_bucket == "l4"


def test_normalize_sample_record_preserves_strength_amplitude_fields() -> None:
    record = {
        "strength_peak_amp_g": 0.18,
        "strength_floor_amp_g": 0.004,
    }
    result = normalize_sample_record(record)
    assert result.strength_peak_amp_g == 0.18
    assert result.strength_floor_amp_g == 0.004


def test_normalize_sample_record_strength_amplitudes_default_to_none_for_old_runs() -> None:
    record = {"t_s": 1.0}
    result = normalize_sample_record(record)
    assert result.strength_peak_amp_g is None
    assert result.strength_floor_amp_g is None


# -- read_jsonl_run -----------------------------------------------------------


def test_read_jsonl_run_missing_metadata_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"record_type": "sample", "t_s": 1.0}\n')
    with pytest.raises(ValueError, match="Run metadata missing"):
        read_jsonl_run(path)


def test_read_jsonl_run_file_not_found(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.jsonl"
    with pytest.raises(FileNotFoundError):
        read_jsonl_run(path)


def test_read_jsonl_run_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "blanks.jsonl"
    metadata = _make_run_metadata(run_id="r1")
    lines = [json.dumps(metadata), "", "  ", json.dumps({"record_type": "sample", "t_s": 1.0})]
    path.write_text("\n".join(lines) + "\n")
    run_data = read_jsonl_run(path)
    assert run_data.metadata.run_id == "r1"
    assert len(run_data.samples) == 1


def test_read_jsonl_run_skips_corrupt_line_mid_file(tmp_path: Path) -> None:
    """A corrupt JSON line mid-file is skipped; surrounding samples are kept."""
    path = tmp_path / "corrupt_mid.jsonl"
    metadata = _make_run_metadata(run_id="r2")
    lines = [
        json.dumps(metadata),
        json.dumps({"record_type": "sample", "t_s": 1.0}),
        '{CORRUPT LINE "not valid json',  # corrupt
        json.dumps({"record_type": "sample", "t_s": 2.0}),
    ]
    path.write_text("\n".join(lines) + "\n")
    run_data = read_jsonl_run(path)
    assert run_data.metadata.run_id == "r2"
    assert len(run_data.samples) == 2
    assert run_data.samples[0].t_s == 1.0
    assert run_data.samples[1].t_s == 2.0


def test_read_jsonl_run_truncated_last_line(tmp_path: Path) -> None:
    """A truncated final line (simulating power loss) doesn't crash the reader."""
    path = tmp_path / "truncated.jsonl"
    metadata = _make_run_metadata(run_id="r3")
    lines = [
        json.dumps(metadata),
        json.dumps({"record_type": "sample", "t_s": 1.0}),
        json.dumps({"record_type": "sample", "t_s": 2.0}),
        '{"record_type": "sample", "t_s": 3.0, "accel_x',  # truncated
    ]
    path.write_text("\n".join(lines) + "\n")
    run_data = read_jsonl_run(path)
    assert run_data.metadata.run_id == "r3"
    assert len(run_data.samples) == 2
    assert run_data.samples[-1].t_s == 2.0


def test_read_jsonl_run_logs_warning_for_corrupt_lines(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warnings are logged for each corrupt line, including line numbers."""
    path = tmp_path / "warn.jsonl"
    metadata = _make_run_metadata(run_id="r4")
    lines = [
        json.dumps(metadata),
        "NOT_JSON_AT_ALL",
        json.dumps({"record_type": "sample", "t_s": 1.0}),
    ]
    path.write_text("\n".join(lines) + "\n")
    import logging

    with caplog.at_level(logging.WARNING, logger="vibesensor.shared.boundaries.runs.log"):
        run_data = read_jsonl_run(path)
    assert len(run_data.samples) == 1
    assert "Skipping corrupt JSONL line 2" in caplog.text


def test_read_jsonl_run_skips_malformed_sample_line(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "malformed_sample.jsonl"
    metadata = _make_run_metadata(run_id="r5")
    lines = [
        json.dumps(metadata),
        json.dumps({"record_type": "sample", "t_s": 1.0, "sample_rate_hz": "fast"}),
        json.dumps({"record_type": "sample", "t_s": 2.0}),
    ]
    path.write_text("\n".join(lines) + "\n")
    import logging

    with caplog.at_level(logging.WARNING, logger="vibesensor.shared.boundaries.runs.log"):
        run_data = read_jsonl_run(path)

    assert [sample.t_s for sample in run_data.samples] == [2.0]
    assert "Skipping malformed sample at line 2" in caplog.text
    assert "sample_rate_hz" in caplog.text


# -- create_run_metadata -------------------------------------------------------


def test_create_run_metadata_basic_fields() -> None:
    meta = _make_run_metadata()
    assert meta["record_type"] == RUN_METADATA_TYPE
    assert meta["run_id"] == "r1"
    assert meta["sensor_model"] == "ADXL345"


def test_create_run_metadata_includes_firmware_version_when_provided() -> None:
    meta = _make_run_metadata(firmware_version="esp-fw-1.2.3")
    assert meta["firmware_version"] == "esp-fw-1.2.3"


def test_bounded_sample_zero_max_items_raises() -> None:
    """max_items=0 must raise ValueError (not ZeroDivisionError)."""
    with pytest.raises(ValueError, match="max_items"):
        bounded_sample(iter([{"x": 1}]), max_items=0)


def test_bounded_sample_negative_max_items_raises() -> None:
    """Negative max_items must raise ValueError."""
    with pytest.raises(ValueError, match="max_items"):
        bounded_sample(iter([{"x": 1}]), max_items=-5)


def test_bounded_sample_zero_max_items_with_hint_raises() -> None:
    """max_items=0 with a total_hint must raise before the ZeroDivisionError."""
    with pytest.raises(ValueError, match="max_items"):
        bounded_sample(iter([{"x": 1}]), max_items=0, total_hint=100)


# ---------------------------------------------------------------------------
# Fix 3: read_jsonl_run warns on duplicate metadata records
# ---------------------------------------------------------------------------


def test_read_jsonl_run_warns_on_duplicate_metadata(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Second metadata record in the same file logs a warning; first is used."""
    path = tmp_path / "dup_meta.jsonl"
    meta1 = _make_run_metadata(run_id="dup-run")
    meta2 = dict(meta1)
    meta2["run_id"] = "should-not-be-used"

    with path.open("w") as f:
        f.write(json.dumps(meta1) + "\n")
        f.write(json.dumps({"record_type": "sample", "t_s": 1.0}) + "\n")
        f.write(json.dumps(meta2) + "\n")

    import logging

    with caplog.at_level(logging.WARNING, logger="vibesensor.shared.boundaries.runs.log"):
        run_data = read_jsonl_run(path)

    # First metadata wins
    assert run_data.metadata.run_id == "dup-run"
    # Warning was emitted
    assert "Duplicate metadata" in caplog.text


# ---------------------------------------------------------------------------
# Fix 4: read_jsonl_run end record missing end_time_utc is not silently set to None
# ---------------------------------------------------------------------------


def test_read_jsonl_run_end_record_without_end_time_utc_leaves_metadata_unchanged(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the end record has no end_time_utc, metadata is not overwritten with None."""
    path = tmp_path / "no_end_time.jsonl"
    meta = _make_run_metadata(run_id="no-end-run")
    end_record = {"record_type": "run_end", "run_id": "no-end-run"}  # no end_time_utc

    with path.open("w") as f:
        f.write(json.dumps(meta) + "\n")
        f.write(json.dumps(end_record) + "\n")

    import logging

    with caplog.at_level(logging.WARNING, logger="vibesensor.shared.boundaries.runs.log"):
        run_data = read_jsonl_run(path)

    # end_time_utc must NOT be set to None
    assert run_data.metadata.end_time_utc in (None, "")
    # Warning was emitted
    assert "end_time_utc" in caplog.text
    assert "no end_time_utc" in caplog.text.lower() or "not updated" in caplog.text.lower()


def test_read_jsonl_run_end_record_with_valid_end_time_utc_is_applied(
    tmp_path: Path,
) -> None:
    """When the end record has a valid end_time_utc and metadata lacks one, it is propagated."""
    path = tmp_path / "valid_end.jsonl"
    meta = _make_run_metadata(run_id="end-run")
    end_record = {
        "record_type": "run_end",
        "schema_version": "v2-jsonl",
        "run_id": "end-run",
        "end_time_utc": "2025-01-01T00:10:00Z",
    }

    with path.open("w") as f:
        f.write(json.dumps(meta) + "\n")
        f.write(json.dumps(end_record) + "\n")

    run_data = read_jsonl_run(path)
    assert run_data.metadata.end_time_utc == "2025-01-01T00:10:00Z"
