from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.run.post_analysis_input import build_post_analysis_input
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_summary import build_post_analysis_summary


def _stub_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-processing-profile"),
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.diagnostics.run_analysis.RunAnalysis",
        FakeRunAnalysis,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
        lambda _result: {},
    )


def _run_metadata(run_id: str) -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "fft_window_size_samples": 64,
            "accel_scale_g_per_lsb": 0.001,
            "language": "en",
        }
    )


def _run_input(run_id: str):
    return build_post_analysis_input(
        LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=_run_metadata(run_id),
            language="en",
            samples=sensor_frames_from_mappings([{"t_s": 1.0, "vibration_strength_db": 10.0}]),
            raw_capture=None,
            total_summary_row_count=1,
            stride=1,
        ),
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


def _raw_capture(run_id: str, *, chunk_sample_count: int = 160) -> RawRunCapture:
    run_start_monotonic_us = 1_000_000
    time_axis = np.arange(chunk_sample_count, dtype=np.float64) / 800.0
    wave = np.round(1000.0 * np.sin(2.0 * np.pi * 32.0 * time_axis)).astype(np.int16)
    samples_i16 = np.column_stack(
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
            t0_us=run_start_monotonic_us + 100_000,
            byte_offset=0,
        ),
    )
    sensor_manifest = RawCaptureSensorManifest(
        client_id="sensor-a",
        sample_rate_hz=800,
        data_file="sensor-a.raw.i16le",
        index_file="sensor-a.index.jsonl",
        sample_count=int(samples_i16.shape[0]),
        chunk_count=1,
        bytes_written=int(samples_i16.nbytes),
        first_t0_us=chunk_rows[0].t0_us,
        last_t0_us=chunk_rows[-1].t0_us,
        clock_sync=_verified_clock_sync(),
    )
    manifest = RawCaptureManifest(
        run_id=run_id,
        relative_dir=f"raw-runs/{run_id}",
        sensors=(sensor_manifest,),
        total_samples=int(samples_i16.shape[0]),
        total_bytes=int(samples_i16.nbytes),
        created_at="2025-01-01T00:00:01Z",
        run_start_monotonic_us=run_start_monotonic_us,
    )
    return RawRunCapture(
        manifest=manifest,
        sensors=(
            RawCaptureSensorData(
                manifest=sensor_manifest,
                samples_i16=samples_i16,
                chunks=chunk_rows,
            ),
        ),
    )


def test_summary_only_analysis_records_filtered_processing_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_analysis(monkeypatch)

    summary = build_post_analysis_summary(_run_input("run-summary-profile"))
    analysis_metadata = summary["analysis_metadata"]

    assert analysis_metadata["processing_profile_version"] == "processing-profiles-v1"
    assert analysis_metadata["processing_profile"] == "diagnostic_filtered"
    assert analysis_metadata["raw_diagnostic_evidence_preserved"] is False
    assert analysis_metadata["diagnostic_filter_chain"] == ["median_3_sample_time_domain"]
    assert analysis_metadata["live_display_filter_chain"] == ["median_3_sample_time_domain"]
    assert analysis_metadata["median_filter_window_samples"] == 3
    assert analysis_metadata["processing_profiles"] == [
        {
            "processing_profile": "live_display",
            "applies_to": "live_metrics",
            "filter_chain": ["median_3_sample_time_domain"],
            "enabled": True,
            "raw_evidence_preserved": False,
        },
        {
            "processing_profile": "diagnostic_raw",
            "applies_to": "raw_replay_strength_metrics",
            "filter_chain": [],
            "enabled": False,
            "raw_evidence_preserved": False,
        },
        {
            "processing_profile": "diagnostic_filtered",
            "applies_to": "summary_fallback_or_optional_comparison",
            "filter_chain": ["median_3_sample_time_domain"],
            "enabled": True,
            "raw_evidence_preserved": False,
        },
    ]


def test_raw_backed_analysis_records_raw_processing_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_analysis(monkeypatch)
    run = build_post_analysis_input(
        LoadedPostAnalysisRun(
            run_id="run-processing-profile",
            metadata=_run_metadata("run-processing-profile"),
            language="en",
            samples=sensor_frames_from_mappings(
                [
                    {
                        "client_id": "sensor-a",
                        "t_s": 0.18,
                        "sample_rate_hz": 800,
                        "vibration_strength_db": 0.0,
                        "dominant_freq_hz": 0.0,
                    }
                ]
            ),
            raw_capture=_raw_capture("run-processing-profile"),
            total_summary_row_count=1,
            stride=1,
        )
    )

    summary = build_post_analysis_summary(run)
    analysis_metadata = summary["analysis_metadata"]

    assert analysis_metadata["processing_profile"] == "diagnostic_raw"
    assert analysis_metadata["raw_diagnostic_evidence_preserved"] is True
    assert analysis_metadata["diagnostic_filter_chain"] == []
    assert analysis_metadata["live_display_filter_chain"] == ["median_3_sample_time_domain"]
    profile_rows = analysis_metadata["processing_profiles"]
    assert isinstance(profile_rows, list)
    assert profile_rows[0]["processing_profile"] == "live_display"
    assert profile_rows[1] == {
        "processing_profile": "diagnostic_raw",
        "applies_to": "raw_replay_strength_metrics",
        "filter_chain": [],
        "enabled": True,
        "raw_evidence_preserved": True,
    }


def test_raw_backed_samples_drive_sensor_intensity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-raw-intensity"),
                prepared=SimpleNamespace(per_sample_phases=["cruise"]),
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.diagnostics.run_analysis.RunAnalysis",
        FakeRunAnalysis,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
        lambda _result: {},
    )
    run = build_post_analysis_input(
        LoadedPostAnalysisRun(
            run_id="run-raw-intensity",
            metadata=_run_metadata("run-raw-intensity"),
            language="en",
            samples=sensor_frames_from_mappings(
                [
                    {
                        "client_id": "sensor-a",
                        "location": "front_left",
                        "t_s": 0.18,
                        "sample_rate_hz": 800,
                        "vibration_strength_db": 0.0,
                        "strength_bucket": "l0",
                        "dominant_freq_hz": 0.0,
                    }
                ]
            ),
            raw_capture=_raw_capture("run-raw-intensity"),
            total_summary_row_count=1,
            stride=1,
        )
    )

    raw_backed_strength = run.samples[0].vibration_strength_db
    assert raw_backed_strength is not None and raw_backed_strength > 0.0

    summary = build_post_analysis_summary(run)
    intensity_rows = summary["sensor_intensity_by_location"]

    assert len(intensity_rows) == 1
    assert intensity_rows[0]["p95_intensity_db"] == pytest.approx(raw_backed_strength)
    assert intensity_rows[0]["strength_bucket_distribution"]["total"] == 1
    assert intensity_rows[0]["strength_bucket_distribution"]["counts"]["l0"] == 0
