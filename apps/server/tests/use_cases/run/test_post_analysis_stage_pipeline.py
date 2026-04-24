from __future__ import annotations

from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.raw_capture import RawCaptureManifest
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
from vibesensor.use_cases.run.post_analysis_executor import (
    resolve_whole_run_builders,
    run_build_post_analysis_input_stage,
    run_load_run_stage,
    run_persist_analysis_summary_stage,
    run_whole_run_pipeline_stages,
)
from vibesensor.use_cases.run.post_analysis_loader import (
    LoadedPostAnalysisRun,
    MissingPostAnalysisMetadata,
)
from vibesensor.use_cases.run.post_analysis_outcomes import PostAnalysisExecutionMissingMetadata


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


def test_run_load_run_stage_returns_terminal_missing_metadata_result() -> None:
    stored_errors: list[tuple[str, str]] = []

    class FakeDB:
        async def astore_analysis_error(self, run_id, error):
            stored_errors.append((run_id, error))

    stage = run_load_run_stage(
        run_id="run-missing-stage",
        db=FakeDB(),
        load_run=lambda *, run_id, db: MissingPostAnalysisMetadata(
            run_id=run_id,
            error_message="Metadata not found or corrupt; cannot analyse",
        ),
        analysis_start=0.0,
        defer_retryable_error_storage=False,
    )

    assert stage.loaded is None
    assert isinstance(stage.terminal_result, PostAnalysisExecutionMissingMetadata)
    assert stage.stage_result.stage_name == "LoadRunStage"
    assert stage.stage_result.status == "failed"
    assert stored_errors == [("run-missing-stage", "Metadata not found or corrupt; cannot analyse")]


def test_run_whole_run_pipeline_stages_reports_degraded_context_fallback() -> None:
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
        async def astore_whole_run_artifacts(self, run_id, manifest, *, artifact_contents):
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
    run_input = run_build_post_analysis_input_stage(loaded).run_input
    builders = resolve_whole_run_builders(
        whole_run_artifact_builder=lambda **_kwargs: _spectral_result(None),
        whole_run_context_builder=lambda **_kwargs: context_bundle,
        whole_run_order_trace_builder=lambda **_kwargs: None,
        whole_run_order_trace_summary_builder=lambda **_kwargs: None,
        whole_run_order_family_summary_builder=lambda **_kwargs: None,
        whole_run_spatial_coherence_builder=lambda **_kwargs: None,
        whole_run_diagnosis_summary_builder=lambda **_kwargs: (),
    )

    result = run_whole_run_pipeline_stages(
        db=FakeDB(),
        loaded=loaded,
        run_input=run_input,
        builders=builders,
    )

    statuses = {stage.stage_name: stage.status for stage in result.stage_results}
    assert statuses["BuildWholeRunSpectraStage"] == "skipped"
    assert statuses["BuildWholeRunContextStage"] == "degraded"
    assert statuses["BuildOrderTraceStage"] == "skipped"
    assert statuses["PersistArtifactsStage"] == "ok"
    assert stored["run_id"] == "run-stage-pipeline"
    assert result.stored_artifact_manifest is not None


def test_run_persist_analysis_summary_stage_stores_summary() -> None:
    stored: list[tuple[str, object]] = []

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            stored.append((run_id, analysis))

    summary = make_persisted_analysis({"run_suitability": []})
    stage = run_persist_analysis_summary_stage(
        db=FakeDB(),
        run_id="run-persist-stage",
        summary=summary,
    )

    assert stage.stage_name == "PersistAnalysisSummaryStage"
    assert stage.status == "ok"
    assert stored == [("run-persist-stage", summary)]
