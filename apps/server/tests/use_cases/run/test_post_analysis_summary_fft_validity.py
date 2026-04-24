from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.run_context_warning import WARNING_CODE_RAW_REPLAY_FFT_UNUSABLE
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
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
            "raw_sample_rate_hz": 8,
            "sample_rate_hz": 8,
            "feature_interval_s": 1.0,
            "fft_window_size_samples": 64,
            "accel_scale_g_per_lsb": 0.001,
            "language": "en",
        }
    )


def _verified_clock_sync() -> RawCaptureSensorClockSync:
    return RawCaptureSensorClockSync(
        clock_domain="server_monotonic",
        proof_state="verified",
        observed_monotonic_us=1_010_000,
        last_sync_monotonic_us=1_009_000,
        sync_offset_us=5_000,
        sync_rtt_us=4_000,
        max_sync_age_us=15_000_000,
        max_sync_rtt_us=50_000,
    )


def _low_rate_raw_capture(run_id: str) -> RawRunCapture:
    run_start_monotonic_us = 1_000_000
    sample_rate_hz = 8
    chunk_sample_count = 64
    time_axis = np.arange(chunk_sample_count, dtype=np.float64) / float(sample_rate_hz)
    wave = np.round(1000.0 * np.sin(2.0 * np.pi * 2.0 * time_axis)).astype(np.int16)
    chunk = np.column_stack(
        [
            wave,
            np.zeros(chunk_sample_count, dtype=np.int16),
            np.zeros(chunk_sample_count, dtype=np.int16),
        ]
    )
    chunk_rows = (
        RawCaptureChunkIndex(
            sample_start=0,
            sample_count=chunk_sample_count,
            t0_us=run_start_monotonic_us,
            byte_offset=0,
        ),
    )
    sensor_manifest = RawCaptureSensorManifest(
        client_id="sensor-a",
        sample_rate_hz=sample_rate_hz,
        data_file="sensor-a.raw.i16le",
        index_file="sensor-a.index.jsonl",
        sample_count=chunk_sample_count,
        chunk_count=1,
        bytes_written=int(chunk.nbytes),
        first_t0_us=chunk_rows[0].t0_us,
        last_t0_us=chunk_rows[0].t0_us,
        clock_sync=_verified_clock_sync(),
        sample_rate_proof_state="observed_consistent",
    )
    manifest = RawCaptureManifest(
        run_id=run_id,
        relative_dir=f"raw-runs/{run_id}",
        sensors=(sensor_manifest,),
        total_samples=chunk_sample_count,
        total_bytes=int(chunk.nbytes),
        created_at="2025-01-01T00:00:01Z",
        run_start_monotonic_us=run_start_monotonic_us,
    )
    return RawRunCapture(
        manifest=manifest,
        sensors=(
            RawCaptureSensorData(
                manifest=sensor_manifest,
                samples_i16=chunk,
                chunks=chunk_rows,
            ),
        ),
    )


def test_build_post_analysis_summary_persists_fft_unusable_warning_and_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-fft-unusable"),
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
            run_id="run-fft-unusable",
            metadata=_run_metadata("run-fft-unusable"),
            language="en",
            samples=sensor_frames_from_mappings(
                [
                    {
                        "client_id": "sensor-a",
                        "t_s": 8.0,
                        "sample_rate_hz": 8,
                        "vibration_strength_db": 0.0,
                        "dominant_freq_hz": 0.0,
                    }
                ]
            ),
            raw_capture=_low_rate_raw_capture("run-fft-unusable"),
            total_summary_row_count=1,
            stride=1,
        )
    )

    summary = build_post_analysis_summary(run)

    assert summary["analysis_metadata"]["raw_replay_complete_window_count"] == 1
    assert summary["analysis_metadata"]["raw_replay_fft_unusable_window_count"] == 1
    assert summary["analysis_metadata"]["raw_capture_mode"] == "summary_only"
    assert [warning["code"] for warning in summary["warnings"]] == [
        WARNING_CODE_RAW_REPLAY_FFT_UNUSABLE,
    ]
