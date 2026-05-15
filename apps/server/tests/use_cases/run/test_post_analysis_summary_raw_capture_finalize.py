from __future__ import annotations

from types import SimpleNamespace

import pytest

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.run_context_warning import WARNING_CODE_RAW_CAPTURE_FINALIZE_DEGRADED
from vibesensor.use_cases.run.post_analysis_input import build_post_analysis_input
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_summary import build_post_analysis_summary


def _run_input(run_id: str):
    return build_post_analysis_input(
        LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=run_metadata_from_mapping(
                {
                    "run_id": run_id,
                    "start_time_utc": "2025-01-01T00:00:00Z",
                    "sensor_model": "fixture-sensor",
                    "raw_sample_rate_hz": 800,
                    "sample_rate_hz": 800,
                    "fft_window_size_samples": 64,
                    "accel_scale_g_per_lsb": 0.001,
                    "language": "en",
                    "raw_capture_finalize": {
                        "status": "timeout",
                        "queue_depth": 3,
                        "error_summary": "raw capture finalize timed out",
                    },
                }
            ),
            language="en",
            samples=sensor_frames_from_mappings([{"t_s": 1.0, "vibration_strength_db": 10.0}]),
            raw_capture=None,
            total_summary_row_count=1,
            stride=1,
            summary_duration_s=1.0,
            sampling_method="full",
            evenly_spaced_sample_count=0,
            event_sample_count=0,
        )
    )


def test_build_post_analysis_summary_persists_raw_capture_finalize_state_and_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-raw-finalize"),
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.diagnostics.run_analysis.RunAnalysis",
        FakeRunAnalysis,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
        lambda _result: {"warnings": []},
    )

    summary = build_post_analysis_summary(_run_input("run-degraded-finalize"))

    assert summary["analysis_metadata"]["raw_capture_finalize_status"] == "timeout"
    assert summary["analysis_metadata"]["raw_capture_finalize_queue_depth"] == 3
    assert (
        summary["analysis_metadata"]["raw_capture_finalize_error_summary"]
        == "raw capture finalize timed out"
    )
    warnings = summary["warnings"]
    assert [warning["code"] for warning in warnings] == [WARNING_CODE_RAW_CAPTURE_FINALIZE_DEGRADED]
