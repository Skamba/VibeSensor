from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vibesensor.runlog import (
    RUN_METADATA_TYPE,
    RUN_SAMPLE_TYPE,
    append_jsonl_records,
    as_float_or_none,
    as_int_or_none,
    create_run_end_record,
    create_run_metadata,
    normalize_sample_record,
    parse_iso8601,
    read_jsonl_run,
    utc_now_iso,
)

# -- Helpers -------------------------------------------------------------------


def _make_run_metadata(*, run_id: str = "r1", **overrides) -> dict:
    """Build a ``create_run_metadata`` dict with sensible test defaults."""
    defaults = dict(
        run_id=run_id,
        start_time_utc="2025-01-01T00:00:00Z",
        sensor_model="ADXL345",
        raw_sample_rate_hz=200,
        feature_interval_s=0.5,
        fft_window_size_samples=256,
        fft_window_type="hann",
        peak_picker_method="max_peak_amp_across_axes",
        accel_scale_g_per_lsb=1.0 / 256.0,
    )
    defaults.update(overrides)
    return create_run_metadata(**defaults)


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


# -- as_float_or_none ---------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
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
    ],
)
def test_as_float_or_none(value: object, expected: float | None) -> None:
    assert as_float_or_none(value) is expected or as_float_or_none(value) == expected


# -- as_int_or_none ------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (3.7, 4),
        (3.2, 3),
        (5, 5),
        (None, None),
        ("abc", None),
        (float("nan"), None),
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
    assert result["record_type"] == RUN_SAMPLE_TYPE
    assert result["t_s"] == 1.5
    assert result["speed_kmh"] == 80.0


def test_normalize_sample_record_handles_nan_values() -> None:
    record = {"t_s": float("nan"), "speed_kmh": None}
    result = normalize_sample_record(record)
    assert result["t_s"] is None
    assert result["speed_kmh"] is None


def test_normalize_sample_record_filters_invalid_peaks() -> None:
    record = {
        "top_peaks": [
            {"hz": 10.0, "amp": 0.5},
            {"hz": -1.0, "amp": 0.1},  # invalid hz
            {"hz": 20.0, "amp": None},  # invalid amp
            "not_a_dict",  # not a dict
        ]
    }
    result = normalize_sample_record(record)
    assert len(result["top_peaks"]) == 1
    assert result["top_peaks"][0]["hz"] == 10.0


def test_normalize_sample_record_limits_peaks_to_10() -> None:
    peaks = [{"hz": float(i + 1), "amp": 0.1} for i in range(15)]
    record = {"top_peaks": peaks}
    result = normalize_sample_record(record)
    assert len(result["top_peaks"]) == 10


def test_normalize_sample_record_preserves_optional_peak_metadata() -> None:
    record = {
        "top_peaks": [
            {
                "hz": 18.0,
                "amp": 0.22,
                "vibration_strength_db": 27.5,
                "strength_bucket": "l4",
            }
        ]
    }
    result = normalize_sample_record(record)
    assert result["top_peaks"][0]["vibration_strength_db"] == 27.5
    assert result["top_peaks"][0]["strength_bucket"] == "l4"


def test_normalize_sample_record_preserves_strength_amplitude_fields() -> None:
    record = {
        "strength_peak_amp_g": 0.18,
        "strength_floor_amp_g": 0.004,
    }
    result = normalize_sample_record(record)
    assert result["strength_peak_amp_g"] == 0.18
    assert result["strength_floor_amp_g"] == 0.004


def test_normalize_sample_record_strength_amplitudes_default_to_none_for_old_runs() -> None:
    record = {"t_s": 1.0}
    result = normalize_sample_record(record)
    assert result["strength_peak_amp_g"] is None
    assert result["strength_floor_amp_g"] is None


# -- append_jsonl_records / read_jsonl_run ------------------------------------


def test_append_and_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "test_run.jsonl"
    metadata = _make_run_metadata(run_id="test-123")
    sample = {
        "record_type": "sample",
        "t_s": 0.5,
        "speed_kmh": 80.0,
        "accel_x_g": 0.01,
        "accel_y_g": 0.02,
        "accel_z_g": 0.03,
    }
    end = create_run_end_record("test-123", "2025-01-01T00:10:00Z")
    append_jsonl_records(path, [metadata, sample, end])

    run_data = read_jsonl_run(path)
    assert run_data.metadata["run_id"] == "test-123"
    assert len(run_data.samples) == 1
    assert run_data.samples[0]["t_s"] == 0.5
    assert run_data.metadata["end_time_utc"] == "2025-01-01T00:10:00Z"


def test_read_jsonl_run_missing_metadata_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"record_type": "sample", "t_s": 1.0}\n')
    with pytest.raises(ValueError):
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
    assert run_data.metadata["run_id"] == "r1"
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
    assert run_data.metadata["run_id"] == "r2"
    assert len(run_data.samples) == 2
    assert run_data.samples[0]["t_s"] == 1.0
    assert run_data.samples[1]["t_s"] == 2.0


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
    assert run_data.metadata["run_id"] == "r3"
    assert len(run_data.samples) == 2
    assert run_data.samples[-1]["t_s"] == 2.0


def test_read_jsonl_run_logs_warning_for_corrupt_lines(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
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

    with caplog.at_level(logging.WARNING, logger="vibesensor.runlog"):
        run_data = read_jsonl_run(path)
    assert len(run_data.samples) == 1
    assert "Skipping corrupt JSONL line 2" in caplog.text


# -- create_run_metadata -------------------------------------------------------


def test_create_run_metadata_units_g_when_scale_provided() -> None:
    meta = _make_run_metadata()
    assert meta["units"]["accel_x_g"] == "g"
    assert meta["record_type"] == RUN_METADATA_TYPE


def test_create_run_metadata_units_raw_when_no_scale() -> None:
    meta = _make_run_metadata(sensor_model="unknown", accel_scale_g_per_lsb=None)
    assert meta["units"]["accel_x_g"] == "raw_lsb"


def test_create_run_metadata_includes_firmware_version_when_provided() -> None:
    meta = _make_run_metadata(firmware_version="esp-fw-1.2.3")
    assert meta["firmware_version"] == "esp-fw-1.2.3"


def test_create_run_metadata_includes_phase_metadata_defaults() -> None:
    meta = _make_run_metadata()
    phase_meta = meta.get("phase_metadata")
    assert isinstance(phase_meta, dict)
    assert phase_meta["version"] == "v1"
    assert phase_meta["idle_speed_kmh_max"] == 3.0
    assert phase_meta["labels"] == ["idle", "acceleration", "cruise", "deceleration", "coast_down"]


def test_append_jsonl_records_preserves_unicode_text(tmp_path: Path) -> None:
    path = tmp_path / "unicode.jsonl"
    append_jsonl_records(path, [{"sensor_name": "Voorwiel links", "finding": "trilling én geluid"}])
    text = path.read_text(encoding="utf-8")
    assert "Voorwiel links" in text
    assert "\\u00e9" not in text


def test_append_jsonl_records_durable_fsync_cadence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "durable.jsonl"
    fsync_calls: list[int] = []
    original_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: fsync_calls.append(fd))
    try:
        append_jsonl_records(
            path,
            [{"i": i} for i in range(5)],
            durable=True,
            durable_every_records=2,
        )
    finally:
        monkeypatch.setattr(os, "fsync", original_fsync)
    # At records 2 and 4, plus final flush.
    assert len(fsync_calls) == 3
