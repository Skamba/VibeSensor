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


def _run_metadata(
    run_id: str,
    *,
    language: str = "en",
    raw_sample_rate_hz: int = 800,
    feature_interval_s: float | None = 1.0,
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
    return run_metadata_from_mapping(payload)


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


def _full_raw_capture(run_id: str, *, chunk_sample_count: int = 160) -> RawRunCapture:
    run_start_monotonic_us = 1_000_000
    chunk = _wave(32.0, chunk_sample_count)
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
        sample_count=int(chunk.shape[0]),
        chunk_count=1,
        bytes_written=int(chunk.nbytes),
        first_t0_us=chunk_rows[0].t0_us,
        last_t0_us=chunk_rows[0].t0_us,
        clock_sync=_verified_clock_sync(),
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
        manifest=manifest,
        sensors=(
            RawCaptureSensorData(
                manifest=sensor_manifest,
                samples_i16=chunk,
                chunks=chunk_rows,
            ),
        ),
    )


def _install_fake_summary(monkeypatch: pytest.MonkeyPatch, *, case_id: str) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id=case_id),
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
        lambda _language, key, **_kwargs: key,
    )


def test_build_post_analysis_summary_adds_short_run_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_summary(monkeypatch, case_id="case-short")

    summary = build_post_analysis_summary(
        build_post_analysis_input(
            LoadedPostAnalysisRun(
                run_id="run-short",
                metadata=_run_metadata("run-short"),
                language="en",
                samples=sensor_frames_from_mappings([{"t_s": 0.25, "vibration_strength_db": 10.0}]),
                raw_capture=None,
                total_summary_row_count=1,
                summary_duration_s=0.25,
                stride=1,
            )
        )
    )

    assert summary["run_suitability"] == [
        {
            "check_key": "SUITABILITY_CHECK_RUN_DURATION",
            "state": "warn",
            "explanation": "SUITABILITY_RUN_DURATION_WARNING",
        }
    ]


def test_build_post_analysis_summary_skips_short_run_warning_when_raw_duration_is_sufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_summary(monkeypatch, case_id="case-raw-ok")

    summary = build_post_analysis_summary(
        build_post_analysis_input(
            LoadedPostAnalysisRun(
                run_id="run-raw-ok",
                metadata=_run_metadata("run-raw-ok"),
                language="en",
                samples=sensor_frames_from_mappings(
                    [
                        {
                            "client_id": "sensor-a",
                            "t_s": 0.25,
                            "sample_rate_hz": 800,
                            "vibration_strength_db": 0.0,
                            "dominant_freq_hz": 0.0,
                        }
                    ]
                ),
                raw_capture=_full_raw_capture("run-raw-ok", chunk_sample_count=1_600),
                total_summary_row_count=1,
                summary_duration_s=0.25,
                stride=1,
            )
        )
    )

    assert summary.get("run_suitability") is None


def test_build_post_analysis_summary_warns_when_raw_capture_duration_is_too_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_summary(monkeypatch, case_id="case-raw-short")

    summary = build_post_analysis_summary(
        build_post_analysis_input(
            LoadedPostAnalysisRun(
                run_id="run-raw-short",
                metadata=_run_metadata("run-raw-short"),
                language="en",
                samples=sensor_frames_from_mappings(
                    [
                        {
                            "client_id": "sensor-a",
                            "t_s": 2.0,
                            "sample_rate_hz": 800,
                            "vibration_strength_db": 0.0,
                            "dominant_freq_hz": 0.0,
                        }
                    ]
                ),
                raw_capture=_full_raw_capture("run-raw-short"),
                total_summary_row_count=1,
                summary_duration_s=2.0,
                stride=1,
            )
        )
    )

    assert summary["run_suitability"] == [
        {
            "check_key": "SUITABILITY_CHECK_RUN_DURATION",
            "state": "warn",
            "explanation": "SUITABILITY_RAW_SAMPLE_DURATION_WARNING",
        }
    ]


def test_build_post_analysis_summary_falls_back_to_summary_row_warning_when_duration_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_summary(monkeypatch, case_id="case-summary-rows")

    summary = build_post_analysis_summary(
        build_post_analysis_input(
            LoadedPostAnalysisRun(
                run_id="run-summary-rows",
                metadata=_run_metadata(
                    "run-summary-rows",
                    raw_sample_rate_hz=800,
                    feature_interval_s=None,
                ),
                language="en",
                samples=sensor_frames_from_mappings([{"vibration_strength_db": 10.0}]),
                raw_capture=None,
                total_summary_row_count=1,
                summary_duration_s=None,
                stride=1,
            )
        )
    )

    assert summary["run_suitability"] == [
        {
            "check_key": "SUITABILITY_CHECK_RUN_DURATION",
            "state": "warn",
            "explanation": "SUITABILITY_SUMMARY_ROW_COUNT_WARNING",
        }
    ]
