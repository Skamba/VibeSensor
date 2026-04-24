from __future__ import annotations

from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.domain import DrivingPhase
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.raw_capture import RawCaptureManifest, RawRunCapture
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextInterval,
    WholeRunContextWindowLabel,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import (
    OrderTracePoint,
    OrderTraceSummary,
    OrderTraceSupportInterval,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_family_summaries import (
    WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY,
    WholeRunOrderFamilySummaryArtifactBundle,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_scoring import (
    WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY,
    WholeRunOrderTraceSummaryArtifactBundle,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
    WholeRunOrderTraceArtifactBundle,
)
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import (
    SpatialEvidenceSummary,
    SpatialLocationSummary,
)
from vibesensor.use_cases.diagnostics.whole_run_context import (
    WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
    WholeRunContextArtifactBundle,
)
from vibesensor.use_cases.diagnostics.whole_run_spatial_coherence import (
    WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY,
    WholeRunSpatialCoherenceArtifactBundle,
)
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunSpectralBuildResult,
    WholeRunSpectralCoverageSummary,
)
from vibesensor.use_cases.run.post_analysis_executor import execute_post_analysis
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


def test_execute_post_analysis_persists_whole_run_diagnosis_summaries() -> None:
    stored: dict[str, object] = {}
    raw_capture_manifest = RawCaptureManifest(
        run_id="run-diagnosis-ranking",
        relative_dir="raw-runs/run-diagnosis-ranking",
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
        run_id="run-diagnosis-ranking",
        relative_dir="whole-run-artifacts/run-diagnosis-ranking",
        window_policy=window_policy,
        total_window_count=4,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-a",
                relative_path="spectra/sensor-a/windows.jsonl",
                file_format="jsonl",
                record_count=4,
                sensor_id="sensor-a",
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )
    context_bundle = WholeRunContextArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-diagnosis-ranking",
            relative_dir="whole-run-artifacts/run-diagnosis-ranking",
            window_policy=window_policy,
            total_window_count=4,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
                    relative_path="context/window-labels.jsonl",
                    file_format="jsonl",
                    record_count=4,
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
                speed_kmh=60.0,
                speed_band="60-80 km/h",
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
                speed_kmh=64.0,
                speed_band="60-80 km/h",
                speed_source="gps",
                engine_rpm=1240.0,
                engine_rpm_source="obd2",
            ),
            WholeRunContextWindowLabel(
                window_index=2,
                segment_index=0,
                phase=DrivingPhase.CRUISE,
                context_coverage="full",
                speed_validity="measured",
                rpm_validity="measured",
                load_state="steady",
                speed_kmh=68.0,
                speed_band="60-80 km/h",
                speed_source="gps",
                engine_rpm=1280.0,
                engine_rpm_source="obd2",
            ),
            WholeRunContextWindowLabel(
                window_index=3,
                segment_index=0,
                phase=DrivingPhase.CRUISE,
                context_coverage="full",
                speed_validity="measured",
                rpm_validity="measured",
                load_state="steady",
                speed_kmh=70.0,
                speed_band="60-80 km/h",
                speed_source="gps",
                engine_rpm=1300.0,
                engine_rpm_source="obd2",
            ),
        ),
        intervals=(
            WholeRunContextInterval(
                segment_index=0,
                phase=DrivingPhase.CRUISE,
                load_state="steady",
                start_window_index=0,
                end_window_index=3,
                start_t_s=0.0,
                end_t_s=2.0,
                speed_min_kmh=60.0,
                speed_max_kmh=70.0,
                speed_band="60-80 km/h",
                full_context_window_count=4,
            ),
        ),
    )
    order_trace_bundle = WholeRunOrderTraceArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-diagnosis-ranking",
            relative_dir="whole-run-artifacts/run-diagnosis-ranking",
            window_policy=window_policy,
            total_window_count=4,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
                    relative_path="orders/traces.jsonl",
                    file_format="jsonl",
                    record_count=1,
                ),
            ),
            created_at="2025-01-01T00:00:00Z",
        ),
        artifact_contents={WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY: b"{}\n"},
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
                predicted_hz=13.0,
                matched_hz=13.1,
                relative_error=0.03,
                peak_intensity_db=18.0,
                vibration_strength_db=10.0,
                ref_source="speed+tire",
                strongest_location="front-left",
            ),
        ),
    )
    order_summaries = (
        OrderTraceSummary(
            hypothesis_key="wheel_1x",
            suspected_source="wheel/tire",
            order_family="wheel",
            order_label="1x wheel",
            total_window_count=4,
            eligible_window_count=4,
            matched_window_count=3,
            support_ratio=0.75,
            reference_coverage_ratio=0.9,
            longest_contiguous_support_window_count=3,
            contiguous_support_ratio=0.75,
            support_intervals=(
                OrderTraceSupportInterval(
                    interval_index=0,
                    start_window_index=0,
                    end_window_index=2,
                    matched_window_count=3,
                    support_ratio=1.0,
                    start_t_s=0.0,
                    end_t_s=1.5,
                    phase="cruise",
                    speed_band="60-80 km/h",
                    mean_relative_error=0.03,
                ),
            ),
            stable_frequency_min_hz=13.1,
            stable_frequency_max_hz=13.4,
            exemplar_interval_index=0,
            dominant_phase="cruise",
            dominant_speed_band="60-80 km/h",
            strongest_location="front-left",
            mean_relative_error=0.03,
            drift_score=0.1,
            lock_score=0.8,
            peak_intensity_db=18.0,
            mean_vibration_strength_db=10.0,
            ref_sources=("speed+tire",),
        ),
    )
    order_trace_summary_bundle = WholeRunOrderTraceSummaryArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-diagnosis-ranking",
            relative_dir="whole-run-artifacts/run-diagnosis-ranking",
            window_policy=window_policy,
            total_window_count=4,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY,
                    relative_path="orders/trace-summaries.jsonl",
                    file_format="jsonl",
                    record_count=1,
                ),
            ),
            created_at="2025-01-01T00:00:00Z",
        ),
        artifact_contents={WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY: b"{}\n"},
        summaries=order_summaries,
    )
    order_family_bundle = WholeRunOrderFamilySummaryArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-diagnosis-ranking",
            relative_dir="whole-run-artifacts/run-diagnosis-ranking",
            window_policy=window_policy,
            total_window_count=4,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY,
                    relative_path="orders/family-summaries.jsonl",
                    file_format="jsonl",
                    record_count=1,
                ),
            ),
            created_at="2025-01-01T00:00:00Z",
        ),
        artifact_contents={WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY: b"{}\n"},
        summaries=order_summaries,
    )
    spatial_bundle = WholeRunSpatialCoherenceArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-diagnosis-ranking",
            relative_dir="whole-run-artifacts/run-diagnosis-ranking",
            window_policy=window_policy,
            total_window_count=4,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY,
                    relative_path="spatial/coherence-windows.jsonl",
                    file_format="jsonl",
                    record_count=1,
                ),
            ),
            created_at="2025-01-01T00:00:00Z",
        ),
        artifact_contents={WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY: b"{}\n"},
        windows=(),
        summaries=(
            SpatialEvidenceSummary(
                candidate_key="wheel_1x",
                suspected_source="wheel/tire",
                proof_basis="supporting_windows_raw_backed",
                total_window_count=4,
                supporting_window_count=3,
                supporting_sensor_count=2,
                coherent_window_count=3,
                coherence_ratio=1.0,
                dominant_location="front-left",
                runner_up_location="rear-left",
                location_separation_db=3.2,
                dominance_ratio=1.6,
                location_summaries=(
                    SpatialLocationSummary(
                        location="front-left",
                        sensor_ids=("front",),
                        supporting_window_count=3,
                        support_ratio=1.0,
                        coherent_window_count=3,
                        coherence_ratio=1.0,
                    ),
                ),
            ),
        ),
    )

    result = execute_post_analysis(
        run_id="run-diagnosis-ranking",
        db=type(
            "DB",
            (),
            {
                "astore_whole_run_artifacts": lambda _self, _run_id, manifest, artifact_contents: (
                    stored.setdefault("whole_run_manifest", manifest),
                    stored.setdefault("whole_run_artifact_contents", artifact_contents),
                    manifest,
                )[2],
                "astore_analysis": lambda _self, _run_id, summary: stored.setdefault(
                    "analysis", summary.to_json_object()
                ),
            },
        )(),
        load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
            run_id="run-diagnosis-ranking",
            metadata=_run_metadata("run-diagnosis-ranking"),
            language="en",
            samples=_samples(),
            total_sample_count=1,
            stride=1,
            context_samples=_samples(),
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
        whole_run_order_trace_builder=lambda **_kwargs: order_trace_bundle,
        whole_run_order_trace_summary_builder=lambda **_kwargs: order_trace_summary_bundle,
        whole_run_order_family_summary_builder=lambda **_kwargs: order_family_bundle,
        whole_run_spatial_coherence_builder=lambda **_kwargs: spatial_bundle,
        analysis_runner=lambda _run: make_persisted_analysis(
            {
                "analysis_metadata": {
                    "analyzed_sample_count": 1,
                    "total_sample_count": 1,
                    "sampling_method": "full",
                    "raw_backed_sample_count": 48,
                    "raw_capture_mode": "raw_backed",
                },
                "run_suitability": [],
            }
        ),
    )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    analysis_metadata = stored["analysis"]["analysis_metadata"]
    diagnosis_summaries = stored["analysis"]["whole_run_diagnosis_summaries"]
    assert analysis_metadata["whole_run_diagnosis_summaries_available"] is True
    assert analysis_metadata["whole_run_diagnosis_summary_count"] == 1
    assert diagnosis_summaries[0]["diagnosis_key"] == "wheel_1x"
    assert diagnosis_summaries[0]["rank"] == 1
    assert diagnosis_summaries[0]["location_proof_basis"] == "supporting_windows_raw_backed"
    assert diagnosis_summaries[0]["support_factors"][0]["factor_key"] == "raw_backed"
