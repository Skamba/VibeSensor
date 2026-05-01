from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS,
    WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
)
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawCaptureSensorLossStats,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.run.post_analysis_input import (
    PostAnalysisRunInput,
    build_post_analysis_input,
)
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_summary import build_post_analysis_summary


def _run_metadata(
    run_id: str,
    *,
    language: str = "en",
    raw_sample_rate_hz: int = 800,
    feature_interval_s: float | None = 1.0,
    extra_metadata: dict[str, object] | None = None,
) -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2025-01-01T00:00:00Z",
        "sensor_model": "fixture-sensor",
        "raw_sample_rate_hz": raw_sample_rate_hz,
        "sample_rate_hz": raw_sample_rate_hz,
        "fft_window_size_samples": 64,
        "accel_scale_g_per_lsb": 0.001,
        "language": language,
    }
    if feature_interval_s is not None:
        payload["feature_interval_s"] = feature_interval_s
    if extra_metadata is not None:
        payload.update(extra_metadata)
    return run_metadata_from_mapping(payload)


def _run_input(
    run_id: str,
    *,
    language: str = "en",
    raw_sample_rate_hz: int = 800,
    total_summary_row_count: int = 1,
    summary_duration_s: float | None = None,
    feature_interval_s: float | None = 1.0,
    stride: int = 1,
    sampling_method: str = "full",
    evenly_spaced_sample_count: int = 0,
    event_sample_count: int = 0,
    extra_metadata: dict[str, object] | None = None,
) -> PostAnalysisRunInput:
    return build_post_analysis_input(
        LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=_run_metadata(
                run_id,
                language=language,
                raw_sample_rate_hz=raw_sample_rate_hz,
                feature_interval_s=feature_interval_s,
                extra_metadata=extra_metadata,
            ),
            language=language,
            samples=sensor_frames_from_mappings([{"t_s": 1.0, "vibration_strength_db": 10.0}]),
            raw_capture=None,
            total_summary_row_count=total_summary_row_count,
            stride=stride,
            summary_duration_s=(
                float(total_summary_row_count) if summary_duration_s is None else summary_duration_s
            ),
            sampling_method=sampling_method,
            evenly_spaced_sample_count=evenly_spaced_sample_count,
            event_sample_count=event_sample_count,
        ),
    )


def test_build_post_analysis_summary_surfaces_calibration_metadata_for_debugging() -> None:
    summary = build_post_analysis_summary(
        _run_input(
            "run-calibration",
            extra_metadata={
                "strength_algorithm_version": "strength-db-scalar-v1",
                "peak_detector_version": "peak-band-rms-v1",
                "calibration_profile_id": "noise-floor-p20-v1",
                "vehicle_baseline_profile_id": "car-profile-1",
                "sensor_snapshots": [
                    {
                        "sensor_id": "sensor-a",
                        "display_name": "Front Left",
                        "location_code": "front_left_wheel",
                        "mount_orientation": "radial",
                    }
                ],
            },
        )
    )

    analysis_metadata = summary["analysis_metadata"]

    assert analysis_metadata["strength_algorithm_version"] == "strength-db-scalar-v1"
    assert analysis_metadata["peak_detector_version"] == "peak-band-rms-v1"
    assert analysis_metadata["calibration_profile_id"] == "noise-floor-p20-v1"
    assert analysis_metadata["vehicle_baseline_profile_id"] == "car-profile-1"
    assert analysis_metadata["sensor_mount_profiles"] == [
        {
            "sensor_id": "sensor-a",
            "mount_location": "front_left_wheel",
            "mount_orientation": "radial",
        }
    ]


def _wave(freq_hz: float, sample_count: int, *, sample_rate_hz: int = 800) -> np.ndarray:
    time_axis = np.arange(sample_count, dtype=np.float64) / float(sample_rate_hz)
    wave = np.round(1000.0 * np.sin(2.0 * np.pi * freq_hz * time_axis)).astype(np.int16)
    return np.column_stack(
        [
            wave,
            np.zeros(sample_count, dtype=np.int16),
            np.zeros(sample_count, dtype=np.int16),
        ]
    )


def _gap_raw_capture(run_id: str) -> RawRunCapture:
    run_start_monotonic_us = 1_000_000
    first_chunk = _wave(32.0, 64)
    second_chunk = _wave(72.0, 64)
    chunk_rows = (
        RawCaptureChunkIndex(
            sample_start=0,
            sample_count=64,
            t0_us=run_start_monotonic_us + 100_000,
            byte_offset=0,
        ),
        RawCaptureChunkIndex(
            sample_start=64,
            sample_count=64,
            t0_us=run_start_monotonic_us + 220_000,
            byte_offset=int(first_chunk.nbytes),
        ),
    )
    samples_i16 = np.vstack([first_chunk, second_chunk])
    sensor_manifest = RawCaptureSensorManifest(
        client_id="sensor-a",
        sample_rate_hz=800,
        data_file="sensor-a.raw.i16le",
        index_file="sensor-a.index.jsonl",
        sample_count=int(samples_i16.shape[0]),
        chunk_count=2,
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


def _full_raw_capture(
    run_id: str,
    *,
    chunk_sample_count: int = 160,
    losses: RawCaptureLossStats | None = None,
    clock_sync: RawCaptureSensorClockSync | None = None,
) -> RawRunCapture:
    run_start_monotonic_us = 1_000_000
    chunk = _wave(32.0, chunk_sample_count)
    chunk_rows = (
        RawCaptureChunkIndex(
            sample_start=0,
            sample_count=160,
            t0_us=run_start_monotonic_us + 100_000,
            byte_offset=0,
        ),
    )
    sensor_manifest = RawCaptureSensorManifest(
        client_id="sensor-a",
        sample_rate_hz=800,
        data_file="sensor-a.raw.i16le",
        index_file="sensor-a.index.jsonl",
        sample_count=int(chunk.shape[0]),
        chunk_count=1,
        bytes_written=int(chunk.nbytes),
        first_t0_us=chunk_rows[0].t0_us,
        last_t0_us=chunk_rows[-1].t0_us,
        clock_sync=clock_sync or _verified_clock_sync(),
    )
    manifest = RawCaptureManifest(
        run_id=run_id,
        relative_dir=f"raw-runs/{run_id}",
        sensors=(sensor_manifest,),
        total_samples=int(chunk.shape[0]),
        total_bytes=int(chunk.nbytes),
        created_at="2025-01-01T00:00:01Z",
        run_start_monotonic_us=run_start_monotonic_us,
    )
    return RawRunCapture(
        manifest=(
            replace(
                manifest,
                sensor_losses=(
                    ()
                    if losses is None or losses.total_loss_event_count <= 0
                    else (RawCaptureSensorLossStats(client_id="sensor-a", losses=losses),)
                ),
                losses=losses or RawCaptureLossStats(),
            )
        ),
        sensors=(
            RawCaptureSensorData(
                manifest=sensor_manifest,
                samples_i16=chunk,
                chunks=chunk_rows,
            ),
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


def test_build_post_analysis_summary_adds_analysis_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeRunAnalysis:
        def __init__(self, diagnostics_run, *, lang, file_name, include_samples):
            captured["context"] = diagnostics_run.context
            captured["samples"] = diagnostics_run.samples
            captured["lang"] = lang
            captured["file_name"] = file_name
            captured["include_samples"] = include_samples

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-1"),
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.diagnostics.run_analysis.RunAnalysis",
        FakeRunAnalysis,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
        lambda _result: {"run_suitability": []},
    )

    summary = build_post_analysis_summary(
        _run_input("run-ok", language="nl", raw_sample_rate_hz=1, total_summary_row_count=3),
    )

    assert captured["lang"] == "nl"
    assert captured["file_name"] == "run-ok"
    assert captured["include_samples"] is False
    assert summary["case_id"] == "case-1"
    assert summary["analysis_metadata"] == {
        "analyzed_sample_count": 1,
        "analyzed_summary_row_count": 1,
        "total_sample_count": 3,
        "total_summary_row_count": 3,
        "sampling_method": "full",
        "summary_duration_s": 3.0,
        "vehicle_context_unaligned_speed_sample_count": 0,
        "vehicle_context_unaligned_rpm_sample_count": 0,
        "raw_capture_available": False,
        "raw_backed_sample_count": 0,
        "raw_backed_summary_row_count": 0,
        "raw_capture_mode": "summary_only",
        "raw_replay_window_count": 1,
        "raw_replay_complete_window_count": 0,
        "raw_replay_partial_window_count": 0,
        "raw_replay_missing_window_count": 1,
        "raw_replay_gap_count": 0,
        "raw_replay_overlap_count": 0,
        "raw_replay_dropped_chunk_count": 0,
        "raw_replay_late_packet_chunk_count": 0,
        "raw_replay_udp_ingest_queue_drop_count": 0,
        "raw_replay_queue_overflow_chunk_count": 0,
        "raw_replay_invalid_chunk_count": 0,
        "raw_replay_write_error_chunk_count": 0,
        "raw_replay_timing_fallback_count": 0,
        "raw_replay_sample_rate_mismatch_count": 0,
        "raw_replay_fft_unusable_window_count": 0,
        "raw_replay_sample_rate_unverified_sensor_count": 0,
        "raw_replay_unanchored_sensor_count": 0,
        "raw_replay_legacy_sensor_count": 0,
        "raw_replay_sync_unverified_sensor_count": 0,
        "raw_replay_stale_sync_sensor_count": 0,
        "raw_replay_high_rtt_sensor_count": 0,
        "raw_replay_confidence": "unavailable",
        "raw_capture_loss_policy_severity": "ok",
        "raw_capture_loss_policy_reason": "raw_capture_loss_ok",
        "raw_capture_loss_policy_gate_whole_run": False,
        "raw_capture_loss_policy_max_sensor_drop_ratio": 0.0,
        "raw_capture_loss_policy_max_events_per_minute": 0.0,
        "fallback_reasons": ["raw_capture_not_configured", "legacy_summary_only"],
    }


def test_build_post_analysis_summary_adds_stride_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-2"),
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.diagnostics.run_analysis.RunAnalysis",
        FakeRunAnalysis,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
        lambda _result: {},
    )
    monkeypatch.setattr(
        "vibesensor.report_i18n.tr",
        lambda _language, _key, *, stride: f"stride={stride}",
    )

    summary = build_post_analysis_summary(
        _run_input(
            "run-stride",
            raw_sample_rate_hz=1,
            total_summary_row_count=5,
            stride=3,
            sampling_method="event_preserving",
            evenly_spaced_sample_count=2,
            event_sample_count=1,
        ),
    )

    assert summary["analysis_metadata"]["sampling_method"] == "event_preserving"
    assert summary["analysis_metadata"]["sampling_base_stride"] == 3
    assert summary["analysis_metadata"]["sampling_evenly_spaced_sample_count"] == 2
    assert summary["analysis_metadata"]["sampling_event_sample_count"] == 1
    run_suitability = summary["run_suitability"]
    assert isinstance(run_suitability, list)
    assert run_suitability == [
        {
            "check_key": "SUITABILITY_CHECK_ANALYSIS_SAMPLING",
            "state": "warn",
            "explanation": "stride=3",
        }
    ]


def test_build_post_analysis_summary_propagates_dropped_chunk_metadata_and_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-drops"),
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.diagnostics.run_analysis.RunAnalysis",
        FakeRunAnalysis,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
        lambda _result: {},
    )

    summary = build_post_analysis_summary(
        build_post_analysis_input(
            LoadedPostAnalysisRun(
                run_id="run-drops",
                metadata=_run_metadata("run-drops"),
                language="en",
                samples=sensor_frames_from_mappings(
                    [
                        {
                            "client_id": "sensor-a",
                            "t_s": 0.08,
                            "sample_rate_hz": 800,
                            "vibration_strength_db": 0.0,
                            "dominant_freq_hz": 0.0,
                        }
                    ]
                ),
                raw_capture=_full_raw_capture(
                    "run-drops",
                    losses=RawCaptureLossStats(
                        late_packet_chunk_count=1,
                        udp_ingest_queue_drop_count=1,
                        queue_overflow_chunk_count=2,
                        write_error_chunk_count=1,
                    ),
                ),
                total_summary_row_count=1,
                stride=1,
            )
        )
    )

    assert summary["analysis_metadata"]["raw_replay_dropped_chunk_count"] == 4
    assert summary["analysis_metadata"]["raw_replay_late_packet_chunk_count"] == 1
    assert summary["analysis_metadata"]["raw_replay_udp_ingest_queue_drop_count"] == 1
    assert summary["analysis_metadata"]["raw_replay_queue_overflow_chunk_count"] == 2
    assert summary["analysis_metadata"]["raw_replay_invalid_chunk_count"] == 0
    assert summary["analysis_metadata"]["raw_replay_write_error_chunk_count"] == 1
    assert summary["analysis_metadata"]["raw_capture_loss_policy_severity"] == "fatal"
    assert (
        summary["analysis_metadata"]["raw_capture_loss_policy_reason"]
        == "raw_capture_queue_overflow_fatal"
    )
    assert summary["analysis_metadata"]["raw_capture_loss_policy_gate_whole_run"] is True
    assert summary["analysis_metadata"]["fallback_reasons"] == [
        "raw_capture_loss_exceeded",
        "legacy_summary_only",
    ]
    assert WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS in [
        warning["code"] for warning in summary["warnings"]
    ]


def test_build_post_analysis_summary_uses_raw_backed_samples_for_sensor_intensity(
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
            raw_capture=_full_raw_capture("run-raw-intensity"),
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


def test_build_post_analysis_summary_enriches_missing_strength_db_from_peak_and_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeRunAnalysis:
        def __init__(self, diagnostics_run, **_kwargs):
            captured["sample"] = diagnostics_run.samples[0]

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-4"),
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.diagnostics.run_analysis.RunAnalysis",
        FakeRunAnalysis,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
        lambda _result: {"run_suitability": []},
    )

    run = build_post_analysis_input(
        LoadedPostAnalysisRun(
            run_id="run-derived-strength",
            metadata=_run_metadata("run-derived-strength"),
            language="en",
            samples=sensor_frames_from_mappings(
                [
                    {
                        "t_s": 1.0,
                        "top_peaks": [{"hz": 14.0, "amp": 0.12}],
                        "strength_peak_amp_g": 0.12,
                        "strength_floor_amp_g": 0.003,
                    }
                ]
            ),
            raw_capture=None,
            total_summary_row_count=1,
            stride=1,
        )
    )

    build_post_analysis_summary(run)

    sample = captured["sample"]
    assert sample.vibration_strength_db is not None
    assert sample.strength_bucket


def test_build_post_analysis_summary_persists_raw_replay_warning_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-raw-gap"),
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
            run_id="run-raw-gap",
            metadata=_run_metadata("run-raw-gap"),
            language="en",
            samples=sensor_frames_from_mappings(
                [
                    {
                        "client_id": "sensor-a",
                        "t_s": 0.18,
                        "sample_rate_hz": 800,
                        "vibration_strength_db": 0.0,
                        "dominant_freq_hz": 0.0,
                    },
                    {
                        "client_id": "sensor-a",
                        "t_s": 0.24,
                        "sample_rate_hz": 800,
                        "vibration_strength_db": 12.0,
                        "dominant_freq_hz": 14.0,
                    },
                ]
            ),
            raw_capture=_gap_raw_capture("run-raw-gap"),
            total_summary_row_count=2,
            stride=1,
        )
    )

    summary = build_post_analysis_summary(run)

    assert summary["analysis_metadata"]["raw_capture_mode"] == "partial_raw_backed"
    assert summary["analysis_metadata"]["raw_replay_partial_window_count"] == 1
    assert summary["analysis_metadata"]["raw_replay_gap_count"] == 1
    assert [warning["code"] for warning in summary["warnings"]] == [
        WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
        WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    ]


def test_build_post_analysis_summary_persists_timing_fallback_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-legacy-sample-time"),
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
            run_id="run-legacy-sample-time",
            metadata=_run_metadata("run-legacy-sample-time"),
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
            raw_capture=_full_raw_capture("run-legacy-sample-time"),
            total_summary_row_count=1,
            stride=1,
        )
    )

    summary = build_post_analysis_summary(run)

    assert summary["analysis_metadata"]["raw_replay_timing_fallback_count"] == 1
    assert [warning["code"] for warning in summary["warnings"]] == [
        WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
        WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    ]
