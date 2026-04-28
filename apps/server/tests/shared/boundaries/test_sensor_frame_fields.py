from __future__ import annotations

import pytest
from test_support.sample_scenarios import make_sample

from vibesensor.shared.boundaries.sensor_frames import SensorFrameDecodeError
from vibesensor.shared.boundaries.sensor_frames.fields import (
    SENSOR_FRAME_FIELD_NAMES,
    sensor_frame_from_mapping_payload,
    sensor_frame_from_row_payload,
    sensor_frame_to_mapping_payload,
    sensor_frame_to_row_payload,
)


def test_sensor_frame_field_codecs_keep_mapping_and_row_paths_aligned() -> None:
    payload = make_sample(
        t_s=1.5,
        speed_kmh=72.0,
        client_name="FL",
        top_peaks=[{"hz": 31.0, "amp": 0.11}],
        vibration_strength_db=18.0,
        strength_floor_amp_g=0.01,
        strength_peak_amp_g=0.11,
        dominant_freq_hz=31.0,
        engine_rpm=2100.0,
        location="front_left",
    )

    frame = sensor_frame_from_mapping_payload(payload)
    row = sensor_frame_to_row_payload(frame)

    assert len(row) == len(SENSOR_FRAME_FIELD_NAMES)
    assert sensor_frame_from_row_payload(row) == frame
    assert sensor_frame_to_mapping_payload(frame)["top_peaks"] == payload["top_peaks"]


def test_sensor_frame_mapping_payload_keeps_strict_and_lenient_scalar_decode_modes() -> None:
    payload = make_sample(
        t_s=1.5,
        speed_kmh=72.0,
        client_name="FL",
        top_peaks=[{"hz": 31.0, "amp": 0.11}],
    )
    payload["sample_rate_hz"] = "fast"

    assert sensor_frame_from_mapping_payload(payload, strict=False).sample_rate_hz is None

    with pytest.raises(SensorFrameDecodeError, match="sample_rate_hz"):
        sensor_frame_from_mapping_payload(payload, strict=True)


def test_sensor_frame_row_payload_reports_invalid_scalar_field_names() -> None:
    frame = sensor_frame_from_mapping_payload(
        make_sample(
            t_s=1.5,
            speed_kmh=72.0,
            client_name="FL",
            top_peaks=[{"hz": 31.0, "amp": 0.11}],
        )
    )
    row = list(sensor_frame_to_row_payload(frame))
    row[SENSOR_FRAME_FIELD_NAMES.index("sample_rate_hz")] = "fast"

    with pytest.raises(SensorFrameDecodeError, match="sample_rate_hz"):
        sensor_frame_from_row_payload(tuple(row))
