from __future__ import annotations

from test_support.post_analysis_artifacts import (
    RecordingPostAnalysisDB,
)
from test_support.post_analysis_artifacts import (
    analysis_payload as _analysis_payload,
)
from test_support.post_analysis_artifacts import (
    artifact as _artifact,
)
from test_support.post_analysis_artifacts import (
    context_bundle as _context_bundle,
)
from test_support.post_analysis_artifacts import (
    execute_artifact_persistence as _execute_artifact_persistence,
)
from test_support.post_analysis_artifacts import (
    manifest as _manifest,
)
from test_support.post_analysis_artifacts import (
    order_trace_bundle as _order_trace_bundle,
)
from test_support.post_analysis_artifacts import (
    samples as _samples,
)
from test_support.post_analysis_artifacts import (
    spatial_samples as _spatial_samples,
)
from test_support.post_analysis_artifacts import (
    window_policy as _window_policy,
)

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunContextInterval,
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
)
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import (
    SpatialEvidenceSummary,
    SpatialLocationSummary,
)
from vibesensor.use_cases.diagnostics.whole_run_context import (
    WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
)
from vibesensor.use_cases.diagnostics.whole_run_spatial_coherence import (
    WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY,
    WholeRunSpatialCoherenceArtifactBundle,
)


def test_execute_post_analysis_stores_whole_run_artifacts_and_appends_metadata() -> None:
    run_id = "run-whole-run"
    policy = _window_policy()
    spectral_manifest = _manifest(
        run_id,
        (
            _artifact(
                "spectral-grid:sensor-a",
                "spectra/sensor-a/freq.f32.npy",
                file_format="npy-f32-vector",
                record_count=10,
                sensor_id="sensor-a",
            ),
            _artifact(
                "spectral-summary:sensor-a",
                "spectra/sensor-a/windows.jsonl",
                record_count=3,
                sensor_id="sensor-a",
            ),
        ),
        total_window_count=3,
        policy=policy,
        algorithm_versions={"whole_run_spectra": 1},
        configuration={"spectrum_storage_format": "npy-f32"},
    )
    db = RecordingPostAnalysisDB()

    _execute_artifact_persistence(
        run_id=run_id,
        db=db,
        policy=policy,
        spectral_manifest=spectral_manifest,
        spectral_contents={"spectral-summary:sensor-a": b"{}\n"},
        context_builder=lambda **_kwargs: None,
    )

    analysis_metadata = db.stored["analysis"]["analysis_metadata"]
    assert db.stored["whole_run_run_id"] == run_id
    assert db.stored["whole_run_manifest"] == spectral_manifest
    assert db.stored["analysis_run_id"] == run_id
    assert analysis_metadata["whole_run_artifacts_available"] is True
    assert analysis_metadata["whole_run_window_count"] == 3
    assert analysis_metadata["whole_run_sensor_count"] == 1
    assert analysis_metadata["whole_run_artifact_count"] == 2
    assert analysis_metadata["whole_run_artifact_manifest_path"] == (
        "whole-run-artifacts/run-whole-run/manifest.json"
    )
    assert analysis_metadata["whole_run_artifacts_status"] == "available"
    assert analysis_metadata["whole_run_algorithm_versions"] == {"whole_run_spectra": 1}
    assert analysis_metadata["whole_run_artifact_configuration"] == {
        "spectrum_storage_format": "npy-f32",
    }
    assert analysis_metadata["whole_run_artifact_paths"]["spectral-grid:sensor-a"] == (
        "spectra/sensor-a/freq.f32.npy"
    )
    assert analysis_metadata["whole_run_artifact_warnings"] == []


def test_execute_post_analysis_persists_whole_run_context_summary_and_sidecar() -> None:
    run_id = "run-context"
    policy = _window_policy()
    spectral_manifest = _manifest(
        run_id,
        (
            _artifact(
                "spectral-summary:sensor-a",
                "spectra/sensor-a/windows.jsonl",
                record_count=3,
                sensor_id="sensor-a",
            ),
        ),
        total_window_count=3,
        policy=policy,
    )
    context_bundle = _context_bundle(
        run_id,
        policy=policy,
        window_count=3,
        intervals=(
            WholeRunContextInterval(
                segment_index=0,
                phase=DrivingPhase.CRUISE,
                load_state="steady",
                start_window_index=0,
                end_window_index=2,
                start_t_s=0.0,
                end_t_s=0.75,
                speed_min_kmh=60.0,
                speed_max_kmh=62.0,
                speed_band="60-80 km/h",
                full_context_window_count=3,
                partial_context_window_count=0,
                missing_context_window_count=0,
            ),
        ),
    )
    db = RecordingPostAnalysisDB()

    _execute_artifact_persistence(
        run_id=run_id,
        db=db,
        policy=policy,
        spectral_manifest=spectral_manifest,
        spectral_contents={"spectral-summary:sensor-a": b"{}\n"},
        context_builder=lambda **_kwargs: context_bundle,
        order_trace_builder=lambda **_kwargs: None,
    )

    merged_manifest = db.stored["whole_run_manifest"]
    analysis = db.stored["analysis"]
    analysis_metadata = analysis["analysis_metadata"]
    assert merged_manifest.artifact(WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY) is not None
    assert merged_manifest.artifact("spectral-summary:sensor-a") is not None
    assert analysis["whole_run_context_intervals"][0]["speed_band"] == "60-80 km/h"
    assert analysis_metadata["whole_run_context_available"] is True
    assert analysis_metadata["whole_run_context_window_count"] == 3
    assert analysis_metadata["whole_run_context_interval_count"] == 1
    assert analysis_metadata["whole_run_context_full_window_count"] == 3
    assert analysis_metadata["whole_run_context_missing_speed_window_count"] == 0
    assert (
        analysis_metadata["whole_run_context_labels_artifact_key"]
        == WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY
    )
    assert analysis_metadata["whole_run_artifact_count"] == 2


def test_execute_post_analysis_persists_whole_run_order_trace_sidecar_and_metadata() -> None:
    run_id = "run-order-traces"
    policy = _window_policy()
    spectral_manifest = _manifest(
        run_id,
        (
            _artifact(
                "spectral-summary:sensor-a",
                "spectra/sensor-a/windows.jsonl",
                record_count=2,
                sensor_id="sensor-a",
            ),
        ),
        total_window_count=2,
        policy=policy,
    )
    order_trace_bundle = _order_trace_bundle(
        run_id,
        policy=policy,
        total_window_count=2,
        artifact_contents=b'{"hypothesis_key":"wheel_1x","harmonic":1,"window_index":0}\n',
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
                matched_hz=5.1,
                relative_error=0.02,
                peak_intensity_db=30.0,
                vibration_strength_db=24.0,
                ref_source="speed+tire",
                strongest_location="Front Left",
            ),
            OrderTracePoint(
                hypothesis_key="wheel_1x",
                suspected_source="wheel/tire",
                order_family="wheel",
                harmonic=1,
                order_label="1x wheel",
                window_index=1,
                eligible=True,
                matched=False,
                predicted_hz=6.0,
                ref_source="speed+tire",
            ),
        ),
    )
    db = RecordingPostAnalysisDB()

    _execute_artifact_persistence(
        run_id=run_id,
        db=db,
        policy=policy,
        spectral_manifest=spectral_manifest,
        spectral_contents={"spectral-summary:sensor-a": b"{}\n{}\n"},
        context_builder=lambda **_kwargs: _context_bundle(
            run_id,
            policy=policy,
            window_count=2,
        ),
        order_trace_builder=lambda **_kwargs: order_trace_bundle,
        spatial_coherence_builder=lambda **_kwargs: None,
    )

    merged_manifest = db.stored["whole_run_manifest"]
    analysis = db.stored["analysis"]
    metadata = analysis["analysis_metadata"]
    assert merged_manifest.artifact(WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY) is not None
    assert merged_manifest.artifact(WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY) is not None
    assert merged_manifest.artifact(WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY) is not None
    assert metadata["whole_run_order_traces_available"] is True
    assert metadata["whole_run_order_trace_point_count"] == 2
    assert metadata["whole_run_order_trace_candidate_count"] == 1
    assert metadata["whole_run_order_trace_summary_count"] == 1
    assert metadata["whole_run_order_family_summary_count"] == 1
    assert len(analysis["whole_run_order_summaries"]) == 1
    order_summary = analysis["whole_run_order_summaries"][0]
    assert order_summary["hypothesis_key"] == "wheel"
    assert order_summary["matched_window_count"] == 1
    assert order_summary["support_intervals"][0]["phase"] == "cruise"
    assert order_summary["stable_frequency_min_hz"] == 5.1
    assert order_summary["ref_sources"] == ["speed+tire"]
    assert metadata["whole_run_artifact_count"] == 5


def test_execute_post_analysis_persists_whole_run_spatial_coherence_sidecar_and_metadata() -> None:
    run_id = "run-spatial-coherence"
    policy = _window_policy()
    spectral_manifest = _manifest(
        run_id,
        (
            _artifact(
                "spectral-summary:sensor-front",
                "spectra/sensor-front/windows.jsonl",
                record_count=2,
                sensor_id="sensor-front",
            ),
            _artifact(
                "spectral-summary:sensor-rear",
                "spectra/sensor-rear/windows.jsonl",
                record_count=2,
                sensor_id="sensor-rear",
            ),
        ),
        total_window_count=2,
        policy=policy,
    )
    order_trace_bundle = _order_trace_bundle(
        run_id,
        policy=policy,
        total_window_count=2,
        artifact_contents=b"",
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
    db = RecordingPostAnalysisDB()

    _execute_artifact_persistence(
        run_id=run_id,
        db=db,
        policy=policy,
        spectral_manifest=spectral_manifest,
        spectral_contents={
            "spectral-summary:sensor-front": (
                b'{"window_index":0,"coverage_state":"full",'
                b'"returned_sample_start":0,"returned_sample_count":256,'
                b'"top_peaks":[{"hz":5.0,"amp":0.2,"vibration_strength_db":31.0}]}\n'
                b'{"window_index":1,"coverage_state":"full",'
                b'"returned_sample_start":200,"returned_sample_count":256,'
                b'"top_peaks":[{"hz":6.0,"amp":0.2,"vibration_strength_db":31.0}]}\n'
            ),
            "spectral-summary:sensor-rear": (
                b'{"window_index":0,"coverage_state":"full",'
                b'"returned_sample_start":0,"returned_sample_count":256,'
                b'"top_peaks":[{"hz":5.05,"amp":0.15,"vibration_strength_db":29.0}]}\n'
                b'{"window_index":1,"coverage_state":"full",'
                b'"returned_sample_start":200,"returned_sample_count":256,'
                b'"top_peaks":[{"hz":6.05,"amp":0.15,"vibration_strength_db":29.0}]}\n'
            ),
        },
        context_builder=lambda **_kwargs: _context_bundle(
            run_id,
            policy=policy,
            window_count=2,
        ),
        order_trace_builder=lambda **_kwargs: order_trace_bundle,
        order_trace_summary_builder=lambda **_kwargs: None,
        order_family_summary_builder=lambda **_kwargs: None,
        samples_payload=_spatial_samples(),
        total_summary_row_count=2,
    )

    merged_manifest = db.stored["whole_run_manifest"]
    analysis = db.stored["analysis"]
    metadata = analysis["analysis_metadata"]
    spatial_summaries = analysis["whole_run_spatial_summaries"]
    assert merged_manifest.artifact(WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY) is not None
    assert WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY in db.stored["whole_run_artifact_contents"]
    assert metadata["whole_run_spatial_coherence_available"] is True
    assert metadata["whole_run_spatial_coherence_window_count"] == 4
    assert metadata["whole_run_spatial_coherence_candidate_count"] == 1
    assert metadata["whole_run_spatial_coherence_summary_count"] == 1
    assert len(spatial_summaries) == 1
    assert spatial_summaries[0]["candidate_key"] == "wheel_1x"
    assert spatial_summaries[0]["proof_basis"] == "supporting_windows_raw_backed"
    assert spatial_summaries[0]["dominant_location"] == "front-left"
    assert len(spatial_summaries[0]["location_summaries"]) == 2


def test_execute_post_analysis_persists_whole_run_diagnosis_summaries() -> None:
    run_id = "run-diagnosis-ranking"
    policy = _window_policy()
    spectral_manifest = _manifest(
        run_id,
        (
            _artifact(
                "spectral-summary:sensor-a",
                "spectra/sensor-a/windows.jsonl",
                record_count=4,
                sensor_id="sensor-a",
            ),
        ),
        total_window_count=4,
        policy=policy,
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
    spatial_bundle = WholeRunSpatialCoherenceArtifactBundle(
        manifest=_manifest(
            run_id,
            (
                _artifact(
                    WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY,
                    "spatial/coherence-windows.jsonl",
                ),
            ),
            total_window_count=4,
            policy=policy,
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
    db = RecordingPostAnalysisDB()

    _execute_artifact_persistence(
        run_id=run_id,
        db=db,
        policy=policy,
        spectral_manifest=spectral_manifest,
        spectral_contents={"spectral-summary:sensor-a": b"{}\n"},
        context_builder=lambda **_kwargs: _context_bundle(
            run_id,
            policy=policy,
            window_count=4,
        ),
        order_trace_builder=lambda **_kwargs: _order_trace_bundle(
            run_id,
            policy=policy,
            total_window_count=4,
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
        ),
        order_trace_summary_builder=lambda **_kwargs: WholeRunOrderTraceSummaryArtifactBundle(
            manifest=_manifest(
                run_id,
                (
                    _artifact(
                        WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY,
                        "orders/trace-summaries.jsonl",
                    ),
                ),
                total_window_count=4,
                policy=policy,
            ),
            artifact_contents={WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY: b"{}\n"},
            summaries=order_summaries,
        ),
        order_family_summary_builder=lambda **_kwargs: WholeRunOrderFamilySummaryArtifactBundle(
            manifest=_manifest(
                run_id,
                (
                    _artifact(
                        WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY,
                        "orders/family-summaries.jsonl",
                    ),
                ),
                total_window_count=4,
                policy=policy,
            ),
            artifact_contents={WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY: b"{}\n"},
            summaries=order_summaries,
        ),
        spatial_coherence_builder=lambda **_kwargs: spatial_bundle,
        context_samples=_samples(),
        analysis=_analysis_payload(
            raw_backed_sample_count=48,
            raw_capture_mode="raw_backed",
        ),
    )

    analysis = db.stored["analysis"]
    metadata = analysis["analysis_metadata"]
    diagnosis_summaries = analysis["whole_run_diagnosis_summaries"]
    assert metadata["whole_run_diagnosis_summaries_available"] is True
    assert metadata["whole_run_diagnosis_summary_count"] == 1
    assert diagnosis_summaries[0]["diagnosis_key"] == "wheel_1x"
    assert diagnosis_summaries[0]["rank"] == 1
    assert diagnosis_summaries[0]["location_proof_basis"] == "supporting_windows_raw_backed"
    assert diagnosis_summaries[0]["support_factors"][0]["factor_key"] == "raw_backed"
