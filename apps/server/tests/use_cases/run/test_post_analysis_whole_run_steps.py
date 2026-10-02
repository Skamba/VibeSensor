from __future__ import annotations

import logging

import pytest

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames.mapping import sensor_frames_from_mappings
from vibesensor.shared.types.raw_capture import (
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorManifest,
    RawCaptureSensorRange,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.whole_run_context import (
    WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
    WholeRunContextArtifactBundle,
)
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunSpectralBuildResult,
    WholeRunSpectralCoverageSummary,
)
from vibesensor.use_cases.run import post_analysis_executor
from vibesensor.use_cases.run.post_analysis_executor import build_whole_run_artifacts
from vibesensor.use_cases.run.post_analysis_input import build_post_analysis_input
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun


def _run_metadata(run_id: str) -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "feature_interval_s": 1.0,
            "language": "en",
        }
    )


def _samples() -> list:
    return sensor_frames_from_mappings([{"t_s": 1.0, "vibration_strength_db": 10.0}])


def _spectral_result(bundle) -> WholeRunSpectralBuildResult:
    return WholeRunSpectralBuildResult(
        bundle=bundle,
        coverage_summary=WholeRunSpectralCoverageSummary(
            total_sensor_window_count=0,
            full_sensor_window_count=0,
            partial_sensor_window_count=0,
            missing_sensor_window_count=0,
            empty_sensor_window_count=0,
            gap_count=0,
            overlap_count=0,
            dropped_chunk_count=0,
            late_packet_chunk_count=0,
            queue_overflow_chunk_count=0,
            invalid_chunk_count=0,
            write_error_chunk_count=0,
            sample_rate_mismatch_sensor_count=0,
            sample_rate_unverified_sensor_count=0,
            unanchored_sensor_count=0,
            legacy_sensor_count=0,
            sync_unverified_sensor_count=0,
            stale_sync_sensor_count=0,
            high_rtt_sensor_count=0,
            coverage_confidence="unavailable",
        ),
    )


def _raw_capture_manifest_with_sensor(run_id: str) -> RawCaptureManifest:
    return RawCaptureManifest(
        run_id=run_id,
        relative_dir=f"raw-runs/{run_id}",
        sensors=(
            RawCaptureSensorManifest(
                client_id="sensor-a",
                sample_rate_hz=800,
                data_file="sensor-a.raw.i16le",
                index_file="sensor-a.index.jsonl",
                sample_count=2048,
                chunk_count=1,
                bytes_written=2048 * 3 * 2,
                first_t0_us=1_000_000,
                last_t0_us=1_000_000,
                clock_sync=RawCaptureSensorClockSync(
                    clock_domain="server_monotonic",
                    proof_state="verified",
                ),
                declared_sample_rate_hz=800,
                sample_rate_proof_state="observed_consistent",
            ),
        ),
        total_samples=2048,
        total_bytes=2048 * 3 * 2,
        created_at="2025-01-01T00:00:00Z",
        run_start_monotonic_us=1_000_000,
    )


def _step_statuses(caplog: pytest.LogCaptureFixture) -> dict[str, str]:
    return {
        record.step: record.step_status
        for record in caplog.records
        if getattr(record, "event", None) == "post_analysis_step"
    }


def test_whole_run_artifacts_fall_back_to_sample_count_context(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stored: dict[str, object] = {}
    raw_capture_manifest = RawCaptureManifest(
        run_id="run-stage-pipeline",
        relative_dir="raw-runs/run-stage-pipeline",
        sensors=(),
        total_samples=0,
        total_bytes=0,
        created_at="2025-01-01T00:00:00Z",
    )
    context_bundle = WholeRunContextArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-stage-pipeline",
            relative_dir="whole-run-artifacts/run-stage-pipeline",
            window_policy=WholeRunWindowPolicy(
                sample_rate_hz=800,
                window_size_samples=2048,
                stride_samples=200,
                overlap_samples=1848,
                feature_interval_s=0.25,
            ),
            total_window_count=1,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
                    relative_path="context/window-labels.jsonl",
                    file_format="jsonl",
                    record_count=1,
                ),
            ),
            created_at="2025-01-01T00:00:00Z",
        ),
        artifact_contents={WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY: b'{"window_index":0}\n'},
        labels=(),
        intervals=(),
    )

    class FakeDB:
        def store_whole_run_artifacts(self, run_id, manifest, *, artifact_contents):
            stored["run_id"] = run_id
            stored["manifest"] = manifest
            stored["artifact_contents"] = artifact_contents
            return manifest

    loaded = LoadedPostAnalysisRun(
        run_id="run-stage-pipeline",
        metadata=_run_metadata("run-stage-pipeline"),
        language="en",
        samples=_samples(),
        total_summary_row_count=1,
        stride=1,
        raw_capture_manifest=raw_capture_manifest,
    )
    run_input = build_post_analysis_input(loaded)
    monkeypatch.setattr(
        post_analysis_executor,
        "build_whole_run_spectral_artifact_bundle_from_ranges",
        lambda **_kwargs: _spectral_result(None),
    )
    monkeypatch.setattr(
        post_analysis_executor,
        "build_whole_run_context_artifact_bundle",
        lambda **_kwargs: context_bundle,
    )

    with caplog.at_level(logging.INFO, logger=post_analysis_executor.__name__):
        result = build_whole_run_artifacts(db=FakeDB(), loaded=loaded, run_input=run_input)

    assert _step_statuses(caplog) == {
        "whole_run_spectra": "ok",
        "whole_run_context": "degraded",
        "order_traces": "skipped",
        "order_trace_summary": "skipped",
        "order_family_summary": "skipped",
        "spatial_summary": "skipped",
        "persist_whole_run_artifacts": "ok",
    }
    assert result.context_bundle is context_bundle
    assert result.order_trace_bundle is None
    assert stored["run_id"] == "run-stage-pipeline"
    assert result.stored_manifest is not None


def test_whole_run_spectra_use_manifest_and_bounded_range_reader(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_capture_manifest = _raw_capture_manifest_with_sensor("run-range-pipeline")
    captured: dict[str, object] = {}

    class FakeDB:
        def load_raw_capture(self, _run_id):  # pragma: no cover - regression guard
            raise AssertionError("whole-run spectra must not load full raw capture")

        def load_raw_capture_sensor_range(
            self,
            run_id,
            client_id,
            *,
            sample_start,
            sample_count,
        ):
            captured["range_read"] = (run_id, client_id, sample_start, sample_count)
            return RawCaptureSensorRange.missing(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
            )

    def artifact_builder(**kwargs):
        captured["artifact_kwargs"] = kwargs
        range_reader = kwargs["raw_range_reader"]
        range_reader("sensor-a", sample_start=4, sample_count=8)
        return _spectral_result(None)

    loaded = LoadedPostAnalysisRun(
        run_id="run-range-pipeline",
        metadata=_run_metadata("run-range-pipeline"),
        language="en",
        samples=_samples(),
        total_summary_row_count=1,
        stride=1,
        raw_capture=None,
        raw_capture_manifest=raw_capture_manifest,
    )
    run_input = build_post_analysis_input(loaded)
    monkeypatch.setattr(
        post_analysis_executor,
        "build_whole_run_spectral_artifact_bundle_from_ranges",
        artifact_builder,
    )
    monkeypatch.setattr(
        post_analysis_executor,
        "build_whole_run_context_artifact_bundle",
        lambda **_kwargs: None,
    )

    with caplog.at_level(logging.INFO, logger=post_analysis_executor.__name__):
        result = build_whole_run_artifacts(db=FakeDB(), loaded=loaded, run_input=run_input)

    assert _step_statuses(caplog)["whole_run_spectra"] == "ok"
    assert result.spectral_result is not None
    artifact_kwargs = captured["artifact_kwargs"]
    assert artifact_kwargs["raw_capture_manifest"] == raw_capture_manifest
    assert "raw_capture" not in artifact_kwargs
    assert captured["range_read"] == ("run-range-pipeline", "sensor-a", 4, 8)
