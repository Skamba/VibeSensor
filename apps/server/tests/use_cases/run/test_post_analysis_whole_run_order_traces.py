from __future__ import annotations

from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.domain import DrivingPhase
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.raw_capture import RawCaptureManifest
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTracePoint
from vibesensor.use_cases.diagnostics.orders.whole_run_family_summaries import (
    WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_scoring import (
    WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
    WholeRunOrderTraceArtifactBundle,
)
from vibesensor.use_cases.diagnostics.whole_run_context import (
    WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
    WholeRunContextArtifactBundle,
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


def test_execute_post_analysis_persists_whole_run_order_trace_sidecar_and_metadata() -> None:
    stored: dict[str, object] = {}
    raw_capture_manifest = RawCaptureManifest(
        run_id="run-order-traces",
        relative_dir="raw-runs/run-order-traces",
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
        run_id="run-order-traces",
        relative_dir="whole-run-artifacts/run-order-traces",
        window_policy=window_policy,
        total_window_count=2,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-a",
                relative_path="spectra/sensor-a/windows.jsonl",
                file_format="jsonl",
                record_count=2,
                sensor_id="sensor-a",
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )
    context_bundle = WholeRunContextArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-order-traces",
            relative_dir="whole-run-artifacts/run-order-traces",
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
            run_id="run-order-traces",
            relative_dir="whole-run-artifacts/run-order-traces",
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
        artifact_contents={
            WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY: (
                b'{"hypothesis_key":"wheel_1x","harmonic":1,"window_index":0}\n'
            ),
        },
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
        run_id="run-order-traces",
        db=FakeDB(),
        load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=_run_metadata(run_id),
            language="en",
            samples=_samples(),
            total_sample_count=1,
            stride=1,
            raw_capture_manifest=raw_capture_manifest,
        ),
        whole_run_artifact_builder=lambda **_kwargs: type(
            "Bundle",
            (),
            {
                "manifest": spectral_manifest,
                "artifact_contents": {"spectral-summary:sensor-a": b"{}\n{}\n"},
            },
        )(),
        whole_run_context_builder=lambda **_kwargs: context_bundle,
        whole_run_order_trace_builder=lambda **_kwargs: order_trace_bundle,
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
    assert merged_manifest.artifact(WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY) is not None
    assert merged_manifest.artifact(WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY) is not None
    assert merged_manifest.artifact(WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY) is not None
    assert stored["analysis"]["analysis_metadata"]["whole_run_order_traces_available"] is True
    assert stored["analysis"]["analysis_metadata"]["whole_run_order_trace_point_count"] == 2
    assert stored["analysis"]["analysis_metadata"]["whole_run_order_trace_candidate_count"] == 1
    assert (
        stored["analysis"]["analysis_metadata"]["whole_run_order_trace_artifact_key"]
        == WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY
    )
    assert (
        stored["analysis"]["analysis_metadata"]["whole_run_order_trace_summaries_available"] is True
    )
    assert stored["analysis"]["analysis_metadata"]["whole_run_order_trace_summary_count"] == 1
    assert (
        stored["analysis"]["analysis_metadata"]["whole_run_order_trace_summary_artifact_key"]
        == WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY
    )
    assert (
        stored["analysis"]["analysis_metadata"]["whole_run_order_family_summaries_available"]
        is True
    )
    assert stored["analysis"]["analysis_metadata"]["whole_run_order_family_summary_count"] == 1
    assert (
        stored["analysis"]["analysis_metadata"]["whole_run_order_family_summary_artifact_key"]
        == WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY
    )
    assert len(stored["analysis"]["whole_run_order_summaries"]) == 1
    order_summary = stored["analysis"]["whole_run_order_summaries"][0]
    assert order_summary["hypothesis_key"] == "wheel"
    assert order_summary["suspected_source"] == "wheel/tire"
    assert order_summary["matched_window_count"] == 1
    assert order_summary["support_intervals"][0]["phase"] == "cruise"
    assert order_summary["phase_support"][0]["matched_window_count"] == 1
    assert order_summary["harmonic_summaries"][0]["harmonic"] == 1
    assert order_summary["stable_frequency_min_hz"] == 5.1
    assert order_summary["exemplar_interval_index"] == 0
    assert order_summary["ref_sources"] == ["speed+tire"]
    assert stored["analysis"]["analysis_metadata"]["whole_run_artifact_count"] == 5
