from __future__ import annotations

from test_support.sample_scenarios import make_analysis_sample, make_sample

from vibesensor.domain import StrengthPeak
from vibesensor.shared.boundaries.sensor_frame_codec import (
    normalize_sensor_frames,
    sensor_frames_to_json_objects,
)


def test_sensor_frame_boundary_normalization_types_top_peaks() -> None:
    raw = make_sample(
        t_s=1.5,
        speed_kmh=72.0,
        client_name="FL",
        top_peaks=[{"hz": 31.0, "amp": 0.11}],
        location="FL",
        dominant_freq_hz=31.0,
    )

    sample = normalize_sensor_frames([raw])[0]

    assert sample.t_s == 1.5
    assert sample.speed_kmh == 72.0
    assert sample.location == "FL"
    assert sample.top_peaks == (StrengthPeak(hz=31.0, amp=0.11),)


def test_normalize_sensor_frames_returns_typed_rows_and_explicit_json_projection() -> None:
    raw = make_sample(
        t_s=0.0,
        speed_kmh=60.0,
        client_name="RR",
        top_peaks=[{"hz": 25.0, "amp": 0.08}],
    )
    typed = make_analysis_sample(
        t_s=2.0,
        speed_kmh=65.0,
        client_name="RL",
        top_peaks=[{"hz": 27.0, "amp": 0.09}],
    )

    typed_rows = normalize_sensor_frames([raw, typed])
    raw_rows = sensor_frames_to_json_objects(typed_rows)

    assert raw_rows[0]["client_name"] == raw["client_name"]
    assert raw_rows[0]["speed_kmh"] == raw["speed_kmh"]
    assert raw_rows[0]["top_peaks"] == raw["top_peaks"]
    assert raw_rows[1]["client_name"] == "RL"
    assert raw_rows[1]["top_peaks"] == [
        {
            "hz": 27.0,
            "amp": 0.09,
        },
    ]
    assert [sample.client_name for sample in typed_rows] == ["RR", "RL"]
