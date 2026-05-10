from __future__ import annotations

from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.domain import DrivingPhase
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.raw_capture import RawCaptureManifest, RawRunCapture
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTracePoint
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
    WholeRunOrderTraceArtifactBundle,
)
from vibesensor.use_cases.diagnostics.whole_run_context import (
    WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
    WholeRunContextArtifactBundle,
)
from vibesensor.use_cases.diagnostics.whole_run_spatial_coherence import (
    WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY,
)
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunSpectralBuildResult,
    WholeRunSpectralCoverageSummary,
)
from vibesensor.use_cases.run.post_analysis_executor import (
    PostAnalysisExecutionConfig,
    PostAnalysisWholeRunBuilderConfig,
    execute_post_analysis,
)
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_outcomes import PostAnalysisExecutionSuccess


def _run_metadata(run_id: str):
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


def _samples():
    return sensor_frames_from_mappings(
        [
            {
                "t_s": 0.0,
                "client_id": "sensor-front",
                "location": "front-left",
                "vibration_strength_db": 10.0,
            },
            {
                "t_s": 0.0,
                "client_id": "sensor-rear",
                "location": "rear-left",
                "vibration_strength_db": 9.0,
            },
        ]
    )


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


def _empty_raw_capture(manifest: RawCaptureManifest) -> RawRunCapture:
    return RawRunCapture(manifest=manifest, sensors=())


def test_execute_post_analysis_persists_whole_run_spatial_coherence_sidecar_and_metadata() -> None:
    stored: dict[str, object] = {}
    raw_capture_manifest = RawCaptureManifest(
        run_id="run-spatial-coherence",
        relative_dir="raw-runs/run-spatial-coherence",
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
        run_id="run-spatial-coherence",
        relative_dir="whole-run-artifacts/run-spatial-coherence",
        window_policy=window_policy,
        total_window_count=2,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-front",
                relative_path="spectra/sensor-front/windows.jsonl",
                file_format="jsonl",
                record_count=2,
                sensor_id="sensor-front",
            ),
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-rear",
                relative_path="spectra/sensor-rear/windows.jsonl",
                file_format="jsonl",
                record_count=2,
                sensor_id="sensor-rear",
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )
    context_bundle = WholeRunContextArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-spatial-coherence",
            relative_dir="whole-run-artifacts/run-spatial-coherence",
            window_policy=window_policy,
            total_window_count=2,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
                    relative_path="context/window-labels.jsonl",
                    file_format="jsonl",
                    record_count=2,
                ),
            ),
            created_at="2025-01-01T00:00:00Z",
        ),
        artifact_contents={
            WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY: b'{"window_index":0}\n{"window_index":1}\n',
        },
        labels=(
            WholeRunContextWindowLabel(
                window_index=0,
                segment_index=0,
                phase=DrivingPhase.CRUISE,
                context_coverage="full",
                speed_validity="measured",
                rpm_validity="measured",
                load_state="steady",
                speed_kmh=40.0,
                speed_source="gps",
                engine_rpm=1200.0,
                engine_rpm_source="obd2",
            ),
            WholeRunContextWindowLabel(
                window_index=1,
                segment_index=0,
                phase=DrivingPhase.CRUISE,
                context_coverage="full",
                speed_validity="measured",
                rpm_validity="measured",
                load_state="steady",
                speed_kmh=50.0,
                speed_source="gps",
                engine_rpm=1500.0,
                engine_rpm_source="obd2",
            ),
        ),
        intervals=(),
    )
    order_trace_bundle = WholeRunOrderTraceArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-spatial-coherence",
            relative_dir="whole-run-artifacts/run-spatial-coherence",
            window_policy=window_policy,
            total_window_count=2,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
                    relative_path="orders/trace-points.jsonl",
                    file_format="jsonl",
                    record_count=2,
                ),
            ),
            created_at="2025-01-01T00:00:00Z",
        ),
        artifact_contents={WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY: b""},
        points=(
            OrderTracePoint(
                hypothesis_key="wheel_1x",
                suspected_source="wheel/tire",
                order_family="wheel",
                harmonic=1,
                order_label="1x wheel",
                window_index=0,
                eligible=True,
                matched=True,
                predicted_hz=5.0,
            ),
            OrderTracePoint(
                hypothesis_key="wheel_1x",
                suspected_source="wheel/tire",
                order_family="wheel",
                harmonic=1,
                order_label="1x wheel",
                window_index=1,
                eligible=True,
                matched=True,
                predicted_hz=6.0,
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
        run_id="run-spatial-coherence",
        db=FakeDB(),
        config=PostAnalysisExecutionConfig(
            load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                run_id=run_id,
                metadata=_run_metadata(run_id),
                language="en",
                samples=_samples(),
                total_summary_row_count=2,
                stride=1,
                raw_capture=_empty_raw_capture(raw_capture_manifest),
                raw_capture_manifest=raw_capture_manifest,
            ),
            whole_run_builders=PostAnalysisWholeRunBuilderConfig(
                artifact_builder=lambda **_kwargs: _spectral_result(
                    type(
                        "Bundle",
                        (),
                        {
                            "manifest": spectral_manifest,
                            "artifact_contents": {
                                "spectral-summary:sensor-front": (
                                    b'{"window_index":0,"coverage_state":"full",'
                                    b'"returned_sample_start":0,"returned_sample_count":256,'
                                    b'"top_peaks":[{"hz":5.0,"amp":0.2,'
                                    b'"vibration_strength_db":31.0}]}\n'
                                    b'{"window_index":1,"coverage_state":"full",'
                                    b'"returned_sample_start":200,"returned_sample_count":256,'
                                    b'"top_peaks":[{"hz":6.0,"amp":0.2,'
                                    b'"vibration_strength_db":31.0}]}\n'
                                ),
                                "spectral-summary:sensor-rear": (
                                    b'{"window_index":0,"coverage_state":"full",'
                                    b'"returned_sample_start":0,"returned_sample_count":256,'
                                    b'"top_peaks":[{"hz":5.05,"amp":0.15,'
                                    b'"vibration_strength_db":29.0}]}\n'
                                    b'{"window_index":1,"coverage_state":"full",'
                                    b'"returned_sample_start":200,"returned_sample_count":256,'
                                    b'"top_peaks":[{"hz":6.05,"amp":0.15,'
                                    b'"vibration_strength_db":29.0}]}\n'
                                ),
                            },
                        },
                    )()
                ),
                context_builder=lambda **_kwargs: context_bundle,
                order_trace_builder=lambda **_kwargs: order_trace_bundle,
                order_trace_summary_builder=lambda **_kwargs: None,
                order_family_summary_builder=lambda **_kwargs: None,
            ),
            analysis_runner=lambda _run: make_persisted_analysis(
                {
                    "analysis_metadata": {
                        "analyzed_sample_count": 2,
                        "total_sample_count": 2,
                        "sampling_method": "full",
                    },
                    "run_suitability": [],
                }
            ),
        ),
    )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    merged_manifest = stored["whole_run_manifest"]
    assert isinstance(merged_manifest, WholeRunArtifactManifest)
    assert merged_manifest.artifact(WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY) is not None
    artifact_contents = stored["whole_run_artifact_contents"]
    assert WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY in artifact_contents
    analysis_metadata = stored["analysis"]["analysis_metadata"]
    spatial_summaries = stored["analysis"]["whole_run_spatial_summaries"]
    assert analysis_metadata["whole_run_spatial_coherence_available"] is True
    assert analysis_metadata["whole_run_spatial_coherence_window_count"] == 4
    assert analysis_metadata["whole_run_spatial_coherence_candidate_count"] == 1
    assert analysis_metadata["whole_run_spatial_coherence_summary_count"] == 1
    assert (
        analysis_metadata["whole_run_spatial_coherence_artifact_key"]
        == WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY
    )
    assert len(spatial_summaries) == 1
    assert spatial_summaries[0]["candidate_key"] == "wheel_1x"
    assert spatial_summaries[0]["proof_basis"] == "supporting_windows_raw_backed"
    assert spatial_summaries[0]["dominant_location"] == "front-left"
    assert spatial_summaries[0]["supporting_window_count"] == 2
    assert spatial_summaries[0]["coherent_window_count"] == 2
    assert len(spatial_summaries[0]["location_summaries"]) == 2
