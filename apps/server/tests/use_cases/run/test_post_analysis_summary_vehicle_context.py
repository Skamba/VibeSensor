from __future__ import annotations

from types import SimpleNamespace

import pytest

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_VEHICLE_CONTEXT_ALIGNMENT_INCOMPLETE,
)
from vibesensor.use_cases.run.post_analysis_input import build_post_analysis_input
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_summary import build_post_analysis_summary


def _run_metadata(run_id: str):
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "feature_interval_s": 1.0,
            "fft_window_size_samples": 64,
            "accel_scale_g_per_lsb": 0.001,
            "language": "en",
        }
    )


def test_build_post_analysis_summary_warns_when_vehicle_context_is_unaligned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-vehicle-context"),
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.diagnostics.run_analysis.RunAnalysis",
        FakeRunAnalysis,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
        lambda _result: {"warnings": [], "run_suitability": []},
    )

    run = build_post_analysis_input(
        LoadedPostAnalysisRun(
            run_id="run-vehicle-context",
            metadata=_run_metadata("run-vehicle-context"),
            language="en",
            samples=sensor_frames_from_mappings(
                [
                    {
                        "t_s": 1.0,
                        "speed_source": "gps_unaligned",
                        "engine_rpm_source": "context_unaligned",
                    }
                ]
            ),
            raw_capture=None,
            total_summary_row_count=1,
            stride=1,
            sampling_method="full",
            evenly_spaced_sample_count=0,
            event_sample_count=0,
        )
    )

    summary = build_post_analysis_summary(run)

    assert summary["analysis_metadata"]["vehicle_context_unaligned_speed_sample_count"] == 1
    assert summary["analysis_metadata"]["vehicle_context_unaligned_rpm_sample_count"] == 1
    assert [warning["code"] for warning in summary["warnings"]] == [
        WARNING_CODE_VEHICLE_CONTEXT_ALIGNMENT_INCOMPLETE,
    ]
