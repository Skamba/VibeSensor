from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from test_support.persisted_analysis import make_persisted_analysis
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
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTracePoint
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
    WholeRunOrderTraceArtifactBundle,
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
    PostAnalysisExecutionConfig,
    PostAnalysisWholeRunBuilderConfig,
    execute_post_analysis,
)
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_outcomes import PostAnalysisExecutionSuccess


def run_metadata(run_id: str) -> RunMetadata:
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


def samples() -> list:
    return sensor_frames_from_mappings([{"t_s": 1.0, "vibration_strength_db": 10.0}])


def spatial_samples() -> list:
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


def raw_manifest(run_id: str) -> RawCaptureManifest:
    return RawCaptureManifest(
        run_id=run_id,
        relative_dir=f"raw-runs/{run_id}",
        sensors=(),
        total_samples=0,
        total_bytes=0,
        created_at="2025-01-01T00:00:00Z",
    )


def window_policy() -> WholeRunWindowPolicy:
    return WholeRunWindowPolicy(
        sample_rate_hz=800,
        window_size_samples=2048,
        stride_samples=200,
        overlap_samples=1848,
        feature_interval_s=0.25,
    )


def artifact(
    key: str,
    path: str,
    *,
    record_count: int = 1,
    file_format: str = "jsonl",
    sensor_id: str | None = None,
) -> WholeRunArtifactFile:
    return WholeRunArtifactFile(
        artifact_key=key,
        relative_path=path,
        file_format=file_format,
        record_count=record_count,
        sensor_id=sensor_id,
    )


def manifest(
    run_id: str,
    artifacts: Sequence[WholeRunArtifactFile],
    *,
    total_window_count: int,
    policy: WholeRunWindowPolicy,
    algorithm_versions: Mapping[str, int] | None = None,
    configuration: Mapping[str, object] | None = None,
) -> WholeRunArtifactManifest:
    return WholeRunArtifactManifest(
        run_id=run_id,
        relative_dir=f"whole-run-artifacts/{run_id}",
        window_policy=policy,
        total_window_count=total_window_count,
        algorithm_versions=dict(algorithm_versions or {}),
        configuration=dict(configuration or {}),
        artifacts=tuple(artifacts),
        created_at="2025-01-01T00:00:00Z",
    )


def spectral_result(
    manifest: WholeRunArtifactManifest,
    artifact_contents: Mapping[str, bytes],
) -> WholeRunSpectralBuildResult:
    bundle = type(
        "Bundle",
        (),
        {"manifest": manifest, "artifact_contents": dict(artifact_contents)},
    )()
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


def raw_capture(manifest: RawCaptureManifest) -> RawRunCapture:
    return RawRunCapture(manifest=manifest, sensors=())


def context_labels(window_count: int) -> tuple[WholeRunContextWindowLabel, ...]:
    return tuple(
        WholeRunContextWindowLabel(
            window_index=index,
            segment_index=0,
            phase=DrivingPhase.CRUISE,
            context_coverage="full",
            speed_validity="measured",
            rpm_validity="measured",
            load_state="steady",
            speed_kmh=60.0 + index,
            speed_band="60-80 km/h",
            speed_source="gps",
            engine_rpm=1200.0 + index * 20.0,
            engine_rpm_source="obd2",
        )
        for index in range(window_count)
    )


def context_bundle(
    run_id: str,
    *,
    policy: WholeRunWindowPolicy,
    window_count: int,
    labels: tuple[WholeRunContextWindowLabel, ...] | None = None,
    intervals: tuple[WholeRunContextInterval, ...] = (),
) -> WholeRunContextArtifactBundle:
    return WholeRunContextArtifactBundle(
        manifest=manifest(
            run_id,
            (
                artifact(
                    WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY,
                    "context/window-labels.jsonl",
                    record_count=window_count,
                ),
            ),
            total_window_count=window_count,
            policy=policy,
        ),
        artifact_contents={
            WHOLE_RUN_CONTEXT_LABEL_ARTIFACT_KEY: b'{"window_index":0}\n' * window_count,
        },
        labels=labels or context_labels(window_count),
        intervals=intervals,
    )


def order_trace_bundle(
    run_id: str,
    *,
    policy: WholeRunWindowPolicy,
    total_window_count: int,
    points: tuple[OrderTracePoint, ...],
    artifact_contents: bytes = b"{}\n",
) -> WholeRunOrderTraceArtifactBundle:
    return WholeRunOrderTraceArtifactBundle(
        manifest=manifest(
            run_id,
            (
                artifact(
                    WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
                    "orders/trace-points.jsonl",
                    record_count=len(points),
                ),
            ),
            total_window_count=total_window_count,
            policy=policy,
        ),
        artifact_contents={WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY: artifact_contents},
        points=points,
    )


def analysis_payload(**metadata: object) -> object:
    base: dict[str, object] = {
        "analyzed_sample_count": 1,
        "total_sample_count": 1,
        "sampling_method": "full",
    }
    base.update(metadata)
    return make_persisted_analysis(
        {
            "analysis_metadata": base,
            "run_suitability": [],
        }
    )


class RecordingPostAnalysisDB:
    def __init__(self) -> None:
        self.stored: dict[str, Any] = {}

    async def astore_whole_run_artifacts(
        self,
        run_id: str,
        manifest: WholeRunArtifactManifest,
        *,
        artifact_contents: Mapping[str, bytes],
    ) -> WholeRunArtifactManifest:
        self.stored["whole_run_run_id"] = run_id
        self.stored["whole_run_manifest"] = manifest
        self.stored["whole_run_artifact_contents"] = dict(artifact_contents)
        return manifest

    async def astore_analysis(self, run_id: str, analysis: object) -> None:
        self.stored["analysis_run_id"] = run_id
        self.stored["analysis"] = (
            analysis.to_json_object() if hasattr(analysis, "to_json_object") else analysis
        )

    async def astore_analysis_error(self, run_id: str, error: str) -> None:
        raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")


def execute_artifact_persistence(
    *,
    run_id: str,
    db: RecordingPostAnalysisDB,
    policy: WholeRunWindowPolicy | None = None,
    spectral_manifest: WholeRunArtifactManifest,
    spectral_contents: Mapping[str, bytes],
    context_builder=None,
    order_trace_builder=None,
    order_trace_summary_builder=None,
    order_family_summary_builder=None,
    spatial_coherence_builder=None,
    samples_payload: list | None = None,
    context_samples: list | None = None,
    total_summary_row_count: int = 1,
    analysis: object | None = None,
) -> PostAnalysisExecutionSuccess:
    _ = policy
    raw_capture_manifest = raw_manifest(run_id)
    result = execute_post_analysis(
        run_id=run_id,
        db=db,
        config=PostAnalysisExecutionConfig(
            load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                run_id=run_id,
                metadata=run_metadata(run_id),
                language="en",
                samples=samples_payload or samples(),
                total_summary_row_count=total_summary_row_count,
                stride=1,
                context_samples=context_samples,
                raw_capture=raw_capture(raw_capture_manifest),
                raw_capture_manifest=raw_capture_manifest,
            ),
            whole_run_builders=PostAnalysisWholeRunBuilderConfig(
                artifact_builder=lambda **_kwargs: spectral_result(
                    spectral_manifest,
                    spectral_contents,
                ),
                context_builder=context_builder,
                order_trace_builder=order_trace_builder,
                order_trace_summary_builder=order_trace_summary_builder,
                order_family_summary_builder=order_family_summary_builder,
                spatial_coherence_builder=spatial_coherence_builder,
            ),
            analysis_runner=lambda _run: analysis or analysis_payload(),
        ),
    )
    assert isinstance(result, PostAnalysisExecutionSuccess)
    return result
