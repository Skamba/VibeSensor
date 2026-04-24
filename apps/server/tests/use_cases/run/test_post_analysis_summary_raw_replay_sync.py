from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_post_analysis_summary import _full_raw_capture

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    WARNING_CODE_RAW_REPLAY_SYNC_UNVERIFIED,
)
from vibesensor.shared.types.raw_capture import RawCaptureSensorClockSync
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


def test_build_post_analysis_summary_persists_sync_unverified_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-stale-sync"),
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
            run_id="run-stale-sync",
            metadata=_run_metadata("run-stale-sync"),
            language="en",
            samples=sensor_frames_from_mappings(
                [
                    {
                        "client_id": "sensor-a",
                        "t_s": 0.18,
                        "sample_rate_hz": 800,
                        "vibration_strength_db": 12.0,
                        "dominant_freq_hz": 14.0,
                    }
                ]
            ),
            raw_capture=_full_raw_capture(
                "run-stale-sync",
                clock_sync=RawCaptureSensorClockSync(
                    clock_domain="unverified",
                    proof_state="stale_sync",
                    observed_monotonic_us=2_000_000,
                    last_sync_monotonic_us=1_000_000,
                    sync_offset_us=5_000,
                    sync_rtt_us=4_000,
                    max_sync_age_us=15_000_000,
                    max_sync_rtt_us=50_000,
                ),
            ),
            total_summary_row_count=1,
            stride=1,
        )
    )

    summary = build_post_analysis_summary(run)

    assert summary["analysis_metadata"]["raw_replay_sync_unverified_sensor_count"] == 1
    assert summary["analysis_metadata"]["raw_replay_stale_sync_sensor_count"] == 1
    assert [warning["code"] for warning in summary["warnings"]] == [
        WARNING_CODE_RAW_REPLAY_SYNC_UNVERIFIED,
        WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    ]
