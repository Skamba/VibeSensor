from __future__ import annotations

import pytest

from vibesensor.domain import AnalysisSettingsSnapshot, DrivingPhase
from vibesensor.shared.boundaries.sensor_frames.mapping import sensor_frames_from_mappings
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.diagnostics.whole_run_context import (
    normalize_whole_run_context_labels,
)
from vibesensor.use_cases.diagnostics.whole_run_windows import plan_whole_run_windows


def _metadata() -> RunMetadata:
    return RunMetadata.create(
        run_id="run-1",
        start_time_utc="2025-01-01T00:00:00Z",
        sensor_model="fixture-sensor",
        raw_sample_rate_hz=800,
        feature_interval_s=0.25,
        fft_window_size_samples=2048,
        accel_scale_g_per_lsb=0.001,
        analysis_settings=AnalysisSettingsSnapshot(**AnalysisSettingsSnapshot.DEFAULTS),
    )


def test_normalize_whole_run_context_labels_aligns_to_centers_and_groups_rows() -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=2448)
    samples = sensor_frames_from_mappings(
        [
            {
                "t_s": 1.28,
                "client_id": "sensor-a",
                "speed_kmh": 12.0,
                "speed_source": "gps",
                "engine_rpm": 1100.0,
                "engine_rpm_source": "obd2",
            },
            {
                "t_s": 1.53,
                "client_id": "sensor-a",
                "speed_kmh": 45.0,
                "speed_source": "manual",
                "gear": 0.64,
                "final_drive_ratio": 3.08,
            },
            {
                "t_s": 1.78,
                "client_id": "sensor-a",
                "speed_source": "none",
            },
            {
                "t_s": 1.78,
                "client_id": "sensor-b",
                "speed_kmh": 65.0,
                "speed_source": "gps",
                "gear": 0.64,
                "final_drive_ratio": 3.08,
            },
        ]
    )

    labels = normalize_whole_run_context_labels(
        metadata=metadata,
        samples=samples,
        window_plan=window_plan,
    )

    assert [label.window_index for label in labels] == [0, 1, 2]

    assert labels[0].context_coverage == "full"
    assert labels[0].speed_validity == "measured"
    assert labels[0].rpm_validity == "measured"
    assert labels[0].speed_source == "gps"
    assert labels[0].engine_rpm_source == "obd2"
    assert labels[0].speed_is_stale is False
    assert labels[0].rpm_is_stale is False
    assert labels[0].speed_context_reasons == ("speed_low",)
    assert labels[0].phase == DrivingPhase.SPEED_UNKNOWN

    assert labels[1].context_coverage == "full"
    assert labels[1].speed_validity == "assumed"
    assert labels[1].rpm_validity == "estimated"
    assert labels[1].speed_source == "manual"
    assert labels[1].engine_rpm_source == "estimated_from_speed_and_ratios"
    assert labels[1].speed_band == "40-50 km/h"
    assert labels[1].speed_context_reasons == ("speed_assumed",)

    assert labels[2].context_coverage == "full"
    assert labels[2].speed_validity == "measured"
    assert labels[2].rpm_validity == "estimated"
    assert labels[2].speed_source == "gps"
    assert labels[2].engine_rpm_source == "estimated_from_speed_and_ratios"


def _gps(t_s: float, speed_kmh: float) -> dict[str, object]:
    return {"t_s": t_s, "client_id": "sensor-a", "speed_kmh": speed_kmh, "speed_source": "gps"}


def _geared(t_s: float, speed_source: str) -> dict[str, object]:
    return {
        "t_s": t_s,
        "client_id": "sensor-a",
        "speed_kmh": 30.0,
        "speed_source": speed_source,
        "gear": 0.64,
        "final_drive_ratio": 3.08,
    }


_STALE_ASSUMED = {
    "context_coverage": "partial",
    "speed_validity": "assumed",
    "rpm_validity": "estimated",
    "speed_is_stale": True,
    "rpm_is_stale": True,
    "speed_context_reasons": ("speed_assumed", "speed_stale"),
    "phase": DrivingPhase.SPEED_UNKNOWN,
    "load_state": "unknown",
}


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        pytest.param([_geared(0.50, "manual")], _STALE_ASSUMED, id="stale-manual-context"),
        pytest.param(
            [_geared(1.28, "fallback_manual")],
            {**_STALE_ASSUMED, "speed_source": "fallback_manual", "speed_band": None},
            id="fallback-manual-is-stale-provenance",
        ),
        pytest.param(
            [],
            {
                "context_coverage": "missing",
                "speed_validity": "missing",
                "rpm_validity": "missing",
                "speed_source": None,
                "engine_rpm_source": None,
                "speed_is_stale": False,
                "rpm_is_stale": False,
                "speed_context_reasons": ("speed_unavailable",),
                "phase": DrivingPhase.SPEED_UNKNOWN,
            },
            id="missing-window-stays-explicit",
        ),
        pytest.param(
            [_gps(1.20, 30.0), _gps(1.35, 70.0)],
            {
                "speed_validity": "measured",
                "speed_is_stale": False,
                "speed_context_reasons": ("speed_unstable",),
            },
            id="unstable-speed-window",
        ),
        pytest.param(
            [_gps(1.28, 0.0)],
            {"phase": DrivingPhase.IDLE, "load_state": "idle"},
            id="fresh-zero-speed-is-idle",
        ),
    ],
)
def test_normalize_whole_run_context_labels_first_window(
    rows: list[dict[str, object]],
    expected: dict[str, object],
) -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=2048)

    label = normalize_whole_run_context_labels(
        metadata=metadata,
        samples=sensor_frames_from_mappings(rows),
        window_plan=window_plan,
    )[0]

    assert {name: getattr(label, name) for name in expected} == expected
