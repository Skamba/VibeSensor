from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_support.persisted_analysis import make_persisted_analysis
from test_support.tracing import configured_trace_output, read_trace_output

from vibesensor.domain import DrivingPhase
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.raw_capture import RawCaptureManifest, RawRunCapture
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextInterval,
    WholeRunContextWindowLabel,
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
from vibesensor.use_cases.run.post_analysis_executor import execute_post_analysis
from vibesensor.use_cases.run.post_analysis_input import PostAnalysisRunInput
from vibesensor.use_cases.run.post_analysis_loader import (
    EmptyPostAnalysisSamples,
    LoadedPostAnalysisRun,
    MissingPostAnalysisMetadata,
)
from vibesensor.use_cases.run.post_analysis_outcomes import (
    PostAnalysisExecutionMissingMetadata,
    PostAnalysisExecutionNoSamples,
    PostAnalysisExecutionPersistenceFailure,
    PostAnalysisExecutionRetryableFailure,
    PostAnalysisExecutionSuccess,
)


def _run_metadata(run_id: str, *, language: str = "en") -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "feature_interval_s": 1.0,
            "language": language,
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


def _empty_raw_capture(manifest: RawCaptureManifest) -> RawRunCapture:
    return RawRunCapture(manifest=manifest, sensors=())


def test_execute_post_analysis_success_stores_summary() -> None:
    stored: dict[str, object] = {}

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            stored["run_id"] = run_id
            stored["analysis"] = analysis

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    result = execute_post_analysis(
        run_id="run-ok",
        db=FakeDB(),
        load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=_run_metadata(run_id, language="nl"),
            language="nl",
            samples=_samples(),
            total_summary_row_count=1,
            stride=1,
        ),
        analysis_runner=lambda run: make_persisted_analysis(
            {
                "lang": run.language,
                "row_count": len(run.samples),
                "analysis_metadata": {
                    "analyzed_sample_count": len(run.samples),
                    "total_sample_count": run.total_summary_row_count,
                    "sampling_method": "full",
                },
                "run_suitability": [],
            }
        ),
    )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    assert stored["run_id"] == "run-ok"
    assert stored["analysis"]["lang"] == "nl"


def test_execute_post_analysis_exports_trace_span(tmp_path: Path) -> None:
    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            return None

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    with configured_trace_output(tmp_path) as trace_path:
        result = execute_post_analysis(
            run_id="run-trace",
            db=FakeDB(),
            load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                run_id=run_id,
                metadata=_run_metadata(run_id),
                language="en",
                samples=_samples(),
                total_summary_row_count=1,
                stride=1,
            ),
            analysis_runner=lambda _run: make_persisted_analysis({"run_suitability": []}),
        )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    span = next(
        item
        for item in read_trace_output(trace_path)
        if item["name"] == "run.post_analysis.execute"
    )
    assert span["attributes"]["vibesensor.run_id"] == "run-trace"
    assert span["attributes"]["vibesensor.sample_count"] == 1


def test_execute_post_analysis_handles_missing_metadata() -> None:
    stored_errors: list[tuple[str, str]] = []

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise AssertionError(f"unexpected store_analysis({run_id}, {analysis})")

        async def astore_analysis_error(self, run_id, error):
            stored_errors.append((run_id, error))

    result = execute_post_analysis(
        run_id="run-missing",
        db=FakeDB(),
        load_run=lambda *, run_id, db: MissingPostAnalysisMetadata(
            run_id=run_id,
            error_message="Metadata not found or corrupt; cannot analyse",
        ),
        analysis_runner=lambda _run: make_persisted_analysis({}),
    )

    assert isinstance(result, PostAnalysisExecutionMissingMetadata)
    assert result.completed_error == "Metadata not found or corrupt; cannot analyse"
    assert stored_errors == [("run-missing", "Metadata not found or corrupt; cannot analyse")]


def test_execute_post_analysis_handles_no_samples() -> None:
    stored_errors: list[tuple[str, str]] = []

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise AssertionError(f"unexpected store_analysis({run_id}, {analysis})")

        async def astore_analysis_error(self, run_id, error):
            stored_errors.append((run_id, error))

    result = execute_post_analysis(
        run_id="run-empty",
        db=FakeDB(),
        load_run=lambda *, run_id, db: EmptyPostAnalysisSamples(
            run_id=run_id,
            error_message="No samples collected during run",
        ),
        analysis_runner=lambda _run: make_persisted_analysis({}),
    )

    assert isinstance(result, PostAnalysisExecutionNoSamples)
    assert result.completed_error == "No samples collected during run"
    assert stored_errors == [("run-empty", "No samples collected during run")]


def test_execute_post_analysis_propagates_unexpected_analysis_failure() -> None:
    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise AssertionError(f"unexpected store_analysis({run_id}, {analysis})")

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    with pytest.raises(RuntimeError, match="boom"):
        execute_post_analysis(
            run_id="run-fail",
            db=FakeDB(),
            load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                run_id=run_id,
                metadata=_run_metadata(run_id),
                language="en",
                samples=_samples(),
                total_summary_row_count=1,
                stride=1,
            ),
            analysis_runner=lambda _run: (_ for _ in ()).throw(RuntimeError("boom")),
        )


def test_execute_post_analysis_reports_persistence_failure() -> None:
    stored_errors: list[tuple[str, str]] = []

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise sqlite3.Error("db write failed")

        async def astore_analysis_error(self, run_id, error):
            stored_errors.append((run_id, error))

    result = execute_post_analysis(
        run_id="run-store-fail",
        db=FakeDB(),
        load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=_run_metadata(run_id),
            language="en",
            samples=_samples(),
            total_summary_row_count=1,
            stride=1,
        ),
        analysis_runner=lambda _run: make_persisted_analysis({"run_suitability": []}),
    )

    assert isinstance(result, PostAnalysisExecutionPersistenceFailure)
    assert result.completed_error == "db write failed"
    assert result.callback_errors == (
        "post-analysis failed for run run-store-fail: db write failed",
    )
    assert stored_errors == [("run-store-fail", "db write failed")]


def test_execute_post_analysis_defers_retryable_persistence_failure() -> None:
    stored_errors: list[tuple[str, str]] = []

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise sqlite3.OperationalError("db locked")

        async def astore_analysis_error(self, run_id, error):
            stored_errors.append((run_id, error))

    result = execute_post_analysis(
        run_id="run-retry",
        db=FakeDB(),
        load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=_run_metadata(run_id),
            language="en",
            samples=_samples(),
            total_summary_row_count=1,
            stride=1,
        ),
        analysis_runner=lambda _run: make_persisted_analysis({"run_suitability": []}),
        defer_retryable_error_storage=True,
    )

    assert isinstance(result, PostAnalysisExecutionRetryableFailure)
    assert result.error_message == "db locked"
    assert result.callback_errors == ("post-analysis failed for run run-retry: db locked",)
    assert stored_errors == []


def test_execute_post_analysis_defers_retryable_load_failure() -> None:
    stored_errors: list[tuple[str, str]] = []

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise AssertionError(f"unexpected store_analysis({run_id}, {analysis})")

        async def astore_analysis_error(self, run_id, error):
            stored_errors.append((run_id, error))

    result = execute_post_analysis(
        run_id="run-load-retry",
        db=FakeDB(),
        load_run=lambda *, run_id, db: (_ for _ in ()).throw(sqlite3.OperationalError("db busy")),
        analysis_runner=lambda _run: make_persisted_analysis({}),
        defer_retryable_error_storage=True,
    )

    assert isinstance(result, PostAnalysisExecutionRetryableFailure)
    assert result.error_message == "db busy"
    assert stored_errors == []


def test_execute_post_analysis_passes_canonical_typed_input_to_runner() -> None:
    captured: dict[str, object] = {}

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            captured["stored_run_id"] = run_id
            captured["stored_analysis"] = analysis

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    result = execute_post_analysis(
        run_id="run-input",
        db=FakeDB(),
        load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=_run_metadata(run_id, language="nl"),
            language="nl",
            samples=_samples(),
            total_summary_row_count=1,
            stride=1,
        ),
        analysis_runner=lambda run: _capture_run_input(captured, run),
    )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    assert captured["run_input_type"] is PostAnalysisRunInput
    assert captured["context_run_id"] == "run-input"
    assert captured["sample_type"] == "SensorFrame"


def test_execute_post_analysis_stores_whole_run_artifacts_and_appends_metadata() -> None:
    stored: dict[str, object] = {}
    raw_capture_manifest = RawCaptureManifest(
        run_id="run-whole-run",
        relative_dir="raw-runs/run-whole-run",
        sensors=(),
        total_samples=0,
        total_bytes=0,
        created_at="2025-01-01T00:00:00Z",
    )
    whole_run_manifest = WholeRunArtifactManifest(
        run_id="run-whole-run",
        relative_dir="whole-run-artifacts/run-whole-run",
        window_policy=WholeRunWindowPolicy(
            sample_rate_hz=800,
            window_size_samples=2048,
            stride_samples=200,
            overlap_samples=1848,
            feature_interval_s=0.25,
        ),
        total_window_count=3,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="spectral-grid:sensor-a",
                relative_path="spectra/sensor-a/freq.f32.npy",
                file_format="npy-f32-vector",
                record_count=10,
                sensor_id="sensor-a",
            ),
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-a",
                relative_path="spectra/sensor-a/windows.jsonl",
                file_format="jsonl",
                record_count=3,
                sensor_id="sensor-a",
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )

    class FakeDB:
        async def astore_whole_run_artifacts(self, run_id, manifest, *, artifact_contents):
            stored["whole_run_run_id"] = run_id
            stored["whole_run_manifest"] = manifest
            stored["whole_run_artifact_contents"] = artifact_contents
            return manifest

        async def astore_analysis(self, run_id, analysis):
            stored["analysis_run_id"] = run_id
            stored["analysis"] = analysis

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    result = execute_post_analysis(
        run_id="run-whole-run",
        db=FakeDB(),
        load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=_run_metadata(run_id),
            language="en",
            samples=_samples(),
            total_summary_row_count=1,
            stride=1,
            raw_capture=_empty_raw_capture(raw_capture_manifest),
            raw_capture_manifest=raw_capture_manifest,
        ),
        whole_run_artifact_builder=lambda **_kwargs: _spectral_result(
            type(
                "Bundle",
                (),
                {
                    "manifest": whole_run_manifest,
                    "artifact_contents": {"spectral-summary:sensor-a": b"{}\n"},
                },
            )()
        ),
        analysis_runner=lambda _run: make_persisted_analysis(
            {
                "analysis_metadata": {
                    "analyzed_sample_count": 1,
                    "total_sample_count": 1,
                    "sampling_method": "full",
                },
                "run_suitability": [],
            }
        ),
        whole_run_context_builder=lambda **_kwargs: None,
    )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    assert stored["whole_run_run_id"] == "run-whole-run"
    assert stored["whole_run_manifest"] == whole_run_manifest
    assert stored["analysis_run_id"] == "run-whole-run"
    assert stored["analysis"]["analysis_metadata"]["whole_run_artifacts_available"] is True
    assert stored["analysis"]["analysis_metadata"]["whole_run_window_count"] == 3
    assert stored["analysis"]["analysis_metadata"]["whole_run_sensor_count"] == 1
    assert stored["analysis"]["analysis_metadata"]["whole_run_artifact_count"] == 2


def test_execute_post_analysis_persists_whole_run_context_summary_and_sidecar() -> None:
    stored: dict[str, object] = {}
    raw_capture_manifest = RawCaptureManifest(
        run_id="run-context",
        relative_dir="raw-runs/run-context",
        sensors=(),
        total_samples=0,
        total_bytes=0,
        created_at="2025-01-01T00:00:00Z",
    )
    window_policy = WholeRunWindowPolicy(
        sample_rate_hz=800,
        window_size_samples=2048,
        stride_samples=200,
        overlap_samples=1848,
        feature_interval_s=0.25,
    )
    spectral_manifest = WholeRunArtifactManifest(
        run_id="run-context",
        relative_dir="whole-run-artifacts/run-context",
        window_policy=window_policy,
        total_window_count=3,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-a",
                relative_path="spectra/sensor-a/windows.jsonl",
                file_format="jsonl",
                record_count=3,
                sensor_id="sensor-a",
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )
    context_bundle = WholeRunContextArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-context",
            relative_dir="whole-run-artifacts/run-context",
            window_policy=window_policy,
            total_window_count=3,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
                    relative_path="context/window-labels.jsonl",
                    file_format="jsonl",
                    record_count=3,
                ),
            ),
            created_at="2025-01-01T00:00:00Z",
        ),
        artifact_contents={
            WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY: b'{"window_index":0}\n',
        },
        labels=(
            WholeRunContextWindowLabel(
                window_index=0,
                segment_index=0,
                phase=DrivingPhase.IDLE,
                context_coverage="full",
                speed_validity="measured",
                rpm_validity="measured",
                load_state="idle",
                speed_kmh=0.0,
                speed_source="gps",
                engine_rpm=800.0,
                engine_rpm_source="obd2",
            ),
            WholeRunContextWindowLabel(
                window_index=1,
                segment_index=0,
                phase=DrivingPhase.IDLE,
                context_coverage="full",
                speed_validity="measured",
                rpm_validity="measured",
                load_state="idle",
                speed_kmh=0.0,
                speed_source="gps",
                engine_rpm=800.0,
                engine_rpm_source="obd2",
            ),
            WholeRunContextWindowLabel(
                window_index=2,
                segment_index=0,
                phase=DrivingPhase.IDLE,
                context_coverage="full",
                speed_validity="measured",
                rpm_validity="measured",
                load_state="idle",
                speed_kmh=0.0,
                speed_source="gps",
                engine_rpm=800.0,
                engine_rpm_source="obd2",
            ),
        ),
        intervals=(
            WholeRunContextInterval(
                segment_index=0,
                phase=DrivingPhase.IDLE,
                load_state="idle",
                start_window_index=0,
                end_window_index=2,
                start_t_s=0.0,
                end_t_s=0.75,
                speed_min_kmh=0.0,
                speed_max_kmh=0.0,
                speed_band="0-10",
                full_context_window_count=3,
                partial_context_window_count=0,
                missing_context_window_count=0,
            ),
        ),
    )

    class FakeDB:
        async def astore_whole_run_artifacts(self, run_id, manifest, *, artifact_contents):
            stored["whole_run_run_id"] = run_id
            stored["whole_run_manifest"] = manifest
            stored["whole_run_artifact_contents"] = artifact_contents
            return manifest

        async def astore_analysis(self, run_id, analysis):
            stored["analysis_run_id"] = run_id
            stored["analysis"] = analysis

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    result = execute_post_analysis(
        run_id="run-context",
        db=FakeDB(),
        load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=_run_metadata(run_id),
            language="en",
            samples=_samples(),
            total_summary_row_count=1,
            stride=1,
            raw_capture=_empty_raw_capture(raw_capture_manifest),
            raw_capture_manifest=raw_capture_manifest,
        ),
        whole_run_artifact_builder=lambda **_kwargs: _spectral_result(
            type(
                "Bundle",
                (),
                {
                    "manifest": spectral_manifest,
                    "artifact_contents": {"spectral-summary:sensor-a": b"{}\n"},
                },
            )()
        ),
        whole_run_context_builder=lambda **_kwargs: context_bundle,
        whole_run_order_trace_builder=lambda **_kwargs: None,
        analysis_runner=lambda _run: make_persisted_analysis(
            {
                "analysis_metadata": {
                    "analyzed_sample_count": 1,
                    "total_sample_count": 1,
                    "sampling_method": "full",
                },
                "run_suitability": [],
            }
        ),
    )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    merged_manifest = stored["whole_run_manifest"]
    assert isinstance(merged_manifest, WholeRunArtifactManifest)
    assert merged_manifest.artifact(WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY) is not None
    assert merged_manifest.artifact("spectral-summary:sensor-a") is not None
    assert stored["analysis"]["whole_run_context_intervals"] == [
        {
            "segment_index": 0,
            "phase": "idle",
            "load_state": "idle",
            "start_window_index": 0,
            "end_window_index": 2,
            "start_t_s": 0.0,
            "end_t_s": 0.75,
            "speed_min_kmh": 0.0,
            "speed_max_kmh": 0.0,
            "speed_band": "0-10",
            "full_context_window_count": 3,
            "partial_context_window_count": 0,
            "missing_context_window_count": 0,
        }
    ]
    assert stored["analysis"]["analysis_metadata"]["whole_run_context_available"] is True
    assert stored["analysis"]["analysis_metadata"]["whole_run_context_window_count"] == 3
    assert stored["analysis"]["analysis_metadata"]["whole_run_context_interval_count"] == 1
    assert stored["analysis"]["analysis_metadata"]["whole_run_context_full_window_count"] == 3
    assert stored["analysis"]["analysis_metadata"]["whole_run_context_partial_window_count"] == 0
    assert stored["analysis"]["analysis_metadata"]["whole_run_context_missing_window_count"] == 0
    assert (
        stored["analysis"]["analysis_metadata"]["whole_run_context_missing_speed_window_count"] == 0
    )
    assert (
        stored["analysis"]["analysis_metadata"]["whole_run_context_missing_rpm_window_count"] == 0
    )
    assert (
        stored["analysis"]["analysis_metadata"]["whole_run_context_stale_speed_window_count"] == 0
    )
    assert stored["analysis"]["analysis_metadata"]["whole_run_context_stale_rpm_window_count"] == 0
    assert (
        stored["analysis"]["analysis_metadata"]["whole_run_context_labels_artifact_key"]
        == WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY
    )
    assert stored["analysis"]["analysis_metadata"]["whole_run_artifact_count"] == 2


def _capture_run_input(captured: dict[str, object], run: PostAnalysisRunInput):
    captured["run_input_type"] = type(run)
    captured["context_run_id"] = run.context.run_id
    captured["sample_type"] = type(run.samples[0]).__name__
    return make_persisted_analysis({"run_suitability": []})
