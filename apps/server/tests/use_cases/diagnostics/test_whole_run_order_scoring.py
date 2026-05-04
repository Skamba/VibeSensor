"""Focused regressions for whole-run order-lock scoring and stability summaries."""

from __future__ import annotations

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import (
    OrderTraceFamily,
    OrderTracePoint,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_scoring import (
    WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY,
    build_whole_run_order_trace_summary_artifact_bundle,
    summarize_whole_run_order_traces,
    whole_run_order_trace_summaries_from_jsonl_bytes,
    whole_run_order_trace_summaries_to_jsonl_bytes,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
    WholeRunOrderTraceArtifactBundle,
)


def _label(
    window_index: int,
    *,
    phase: DrivingPhase = DrivingPhase.CRUISE,
    speed_band: str = "50-60 km/h",
) -> WholeRunContextWindowLabel:
    return WholeRunContextWindowLabel(
        window_index=window_index,
        segment_index=0,
        phase=phase,
        context_coverage="full",
        speed_validity="measured",
        rpm_validity="measured",
        load_state="steady",
        speed_kmh=55.0,
        speed_band=speed_band,
        speed_source="obd2",
        engine_rpm=1800.0,
        engine_rpm_source="obd2",
    )


def _window_policy() -> WholeRunWindowPolicy:
    return WholeRunWindowPolicy(
        sample_rate_hz=200,
        window_size_samples=256,
        stride_samples=100,
        overlap_samples=156,
        feature_interval_s=0.5,
    )


def _order_trace_bundle(points: tuple[OrderTracePoint, ...]) -> WholeRunOrderTraceArtifactBundle:
    return WholeRunOrderTraceArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-order-scoring",
            relative_dir="whole-run-artifacts/run-order-scoring",
            window_policy=_window_policy(),
            total_window_count=2,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
                    relative_path="orders/traces.jsonl",
                    file_format="jsonl",
                    record_count=len(points),
                ),
            ),
            created_at="2025-01-01T00:00:00Z",
        ),
        artifact_contents={WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY: b""},
        points=points,
    )


def _point(
    window_index: int,
    *,
    hypothesis_key: str = "wheel_1x",
    suspected_source: str = "wheel/tire",
    order_family: OrderTraceFamily = "wheel",
    harmonic: int = 1,
    order_label: str = "1x wheel",
    eligible: bool = True,
    matched: bool = False,
    relative_error: float | None = None,
    peak_intensity_db: float | None = None,
    vibration_strength_db: float | None = None,
    strongest_location: str | None = None,
    ref_source: str | None = "speed+tire",
) -> OrderTracePoint:
    return OrderTracePoint(
        hypothesis_key=hypothesis_key,
        suspected_source=suspected_source,
        order_family=order_family,
        harmonic=harmonic,
        order_label=order_label,
        window_index=window_index,
        eligible=eligible,
        matched=matched,
        predicted_hz=12.0 if eligible else None,
        matched_hz=12.0 if matched else None,
        relative_error=relative_error,
        peak_intensity_db=peak_intensity_db,
        vibration_strength_db=vibration_strength_db,
        ref_source=ref_source if eligible else None,
        strongest_location=strongest_location,
    )


def test_summarize_whole_run_order_traces_distinguishes_strong_and_weak_lock() -> None:
    labels = tuple(
        _label(
            index,
            phase=DrivingPhase.CRUISE if index < 4 else DrivingPhase.ACCELERATION,
            speed_band="50-60 km/h" if index < 4 else "60-70 km/h",
        )
        for index in range(8)
    )
    points = (
        *(
            _point(
                index,
                matched=index in {0, 1, 2, 3, 4, 5},
                relative_error=0.01,
                peak_intensity_db=18.0,
                vibration_strength_db=12.0,
                strongest_location="Front Left",
            )
            for index in range(8)
        ),
        *(
            _point(
                index,
                hypothesis_key="engine_2x",
                suspected_source="engine",
                order_family="engine",
                harmonic=2,
                order_label="2x engine",
                matched=index in {0, 3, 7},
                relative_error={0: 0.02, 3: 0.11, 7: 0.20}.get(index),
                peak_intensity_db={0: 12.0, 3: 10.0, 7: 9.0}.get(index),
                vibration_strength_db={0: 8.0, 3: 7.0, 7: 6.0}.get(index),
                strongest_location="Rear Right" if index in {0, 7} else "Front Right",
                ref_source="obd2",
            )
            for index in range(8)
        ),
    )

    summaries = summarize_whole_run_order_traces(points=points, context_labels=labels)

    strong = summaries[0]
    weak = summaries[1]
    assert strong.hypothesis_key == "wheel_1x"
    assert weak.hypothesis_key == "engine_2x"
    assert strong.lock_score > weak.lock_score
    assert strong.drift_score > weak.drift_score
    assert strong.longest_contiguous_support_window_count == 6
    assert strong.contiguous_support_ratio == 0.75
    assert strong.reference_coverage_ratio == 1.0
    assert strong.stable_frequency_min_hz == 12.0
    assert strong.stable_frequency_max_hz == 12.0
    assert strong.exemplar_interval_index is None
    assert strong.dominant_phase == DrivingPhase.CRUISE.value
    assert strong.dominant_speed_band == "50-60 km/h"
    assert strong.strongest_location == "Front Left"
    assert strong.harmonic_summaries[0].lock_score == strong.lock_score
    assert weak.harmonic_summaries[0].relative_error_stddev is not None


def test_whole_run_order_trace_summaries_jsonl_round_trip() -> None:
    labels = tuple(_label(index) for index in range(2))
    points = tuple(
        _point(
            index,
            matched=True,
            relative_error=0.01,
            peak_intensity_db=18.0,
            vibration_strength_db=12.0,
            strongest_location="Front Left",
        )
        for index in range(2)
    )

    summaries = summarize_whole_run_order_traces(points=points, context_labels=labels)
    payload = whole_run_order_trace_summaries_to_jsonl_bytes(summaries)

    assert whole_run_order_trace_summaries_from_jsonl_bytes(payload) == summaries


def test_build_whole_run_order_trace_summary_artifact_bundle_preserves_manifest_shape() -> None:
    labels = tuple(_label(index) for index in range(2))
    points = tuple(
        _point(
            index,
            matched=True,
            relative_error=0.01,
            peak_intensity_db=18.0,
            vibration_strength_db=12.0,
            strongest_location="Front Left",
        )
        for index in range(2)
    )

    bundle = build_whole_run_order_trace_summary_artifact_bundle(
        order_trace_bundle=_order_trace_bundle(points),
        context_labels=tuple(reversed(labels)),
    )

    assert bundle.manifest.to_json_object() == {
        "schema_version": bundle.manifest.schema_version,
        "storage_type": bundle.manifest.storage_type,
        "run_id": "run-order-scoring",
        "relative_dir": "whole-run-artifacts/run-order-scoring",
        "window_policy": bundle.manifest.window_policy.to_json_object(),
        "total_window_count": 2,
        "artifacts": [
            {
                "artifact_key": WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY,
                "relative_path": "orders/trace-summaries.jsonl",
                "file_format": "jsonl",
                "record_count": len(bundle.summaries),
            }
        ],
        "created_at": "2025-01-01T00:00:00Z",
        "generated_artifact_paths": {
            WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY: "orders/trace-summaries.jsonl",
        },
        "algorithm_versions": {},
        "configuration": {},
        "source_raw_manifests": [],
    }
    assert (
        whole_run_order_trace_summaries_from_jsonl_bytes(
            bundle.artifact_contents[WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY]
        )
        == bundle.summaries
    )


def test_summarize_whole_run_order_traces_degrades_partial_reference_explicitly() -> None:
    labels = tuple(_label(index) for index in range(8))
    full_points = tuple(
        _point(
            index,
            eligible=index < 4,
            matched=index in {0, 1},
            relative_error=0.02 if index in {0, 1} else None,
            peak_intensity_db=16.0 if index in {0, 1} else None,
            vibration_strength_db=10.0 if index in {0, 1} else None,
            strongest_location="Front Left",
        )
        for index in range(8)
    )
    partial_points = tuple(
        _point(
            index,
            hypothesis_key="wheel_2x",
            order_label="2x wheel",
            harmonic=2,
            eligible=index < 2,
            matched=index == 0,
            relative_error=0.02 if index == 0 else None,
            peak_intensity_db=16.0 if index == 0 else None,
            vibration_strength_db=10.0 if index == 0 else None,
            strongest_location="Front Left",
        )
        for index in range(8)
    )

    summaries = summarize_whole_run_order_traces(
        points=(*full_points, *partial_points),
        context_labels=labels,
    )

    full_reference = summaries[0]
    partial_reference = summaries[1]
    assert full_reference.support_ratio == 0.5
    assert partial_reference.support_ratio == 0.5
    assert full_reference.contiguous_support_ratio == 0.5
    assert partial_reference.contiguous_support_ratio == 0.5
    assert full_reference.reference_coverage_ratio == 0.5
    assert partial_reference.reference_coverage_ratio == 0.25
    assert full_reference.lock_score > partial_reference.lock_score


def test_summarize_whole_run_order_traces_is_deterministic() -> None:
    labels = tuple(_label(index) for index in range(4))
    points = tuple(
        _point(
            index,
            matched=index in {0, 1},
            relative_error=0.02 if index in {0, 1} else None,
            peak_intensity_db=14.0 if index in {0, 1} else None,
            vibration_strength_db=9.0 if index in {0, 1} else None,
            strongest_location="Front Left",
        )
        for index in range(4)
    )

    forward = summarize_whole_run_order_traces(points=points, context_labels=labels)
    reversed_inputs = summarize_whole_run_order_traces(
        points=tuple(reversed(points)),
        context_labels=tuple(reversed(labels)),
    )

    assert reversed_inputs == forward
