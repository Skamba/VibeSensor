"""Focused regressions for whole-run source-family order summaries."""

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
from vibesensor.use_cases.diagnostics.orders.whole_run_family_summaries import (
    WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY,
    build_whole_run_order_family_summary_artifact_bundle,
    summarize_whole_run_order_trace_families,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_scoring import (
    WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY,
    WholeRunOrderTraceSummaryArtifactBundle,
    summarize_whole_run_order_traces,
    whole_run_order_trace_summaries_from_jsonl_bytes,
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
        segment_index=0 if window_index < 7 else 1,
        phase=phase,
        context_coverage="full",
        speed_validity="measured",
        rpm_validity="measured",
        load_state="pulling" if phase == DrivingPhase.ACCELERATION else "steady",
        speed_kmh=55.0 if phase == DrivingPhase.CRUISE else 65.0,
        speed_band=speed_band,
        speed_source="gps",
        engine_rpm=1800.0 if phase == DrivingPhase.CRUISE else 2200.0,
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
            run_id="run-order-families",
            relative_dir="whole-run-artifacts/run-order-families",
            window_policy=_window_policy(),
            total_window_count=4,
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
    hypothesis_key: str,
    harmonic: int,
    order_label: str,
    eligible: bool = True,
    matched: bool = False,
    relative_error: float | None = None,
    peak_intensity_db: float | None = None,
    vibration_strength_db: float | None = None,
    matched_hz: float | None = None,
    strongest_location: str | None = None,
    order_family: OrderTraceFamily = "wheel",
) -> OrderTracePoint:
    return OrderTracePoint(
        hypothesis_key=hypothesis_key,
        suspected_source="wheel/tire",
        order_family=order_family,
        harmonic=harmonic,
        order_label=order_label,
        window_index=window_index,
        eligible=eligible,
        matched=matched,
        predicted_hz=12.0 if eligible else None,
        matched_hz=matched_hz if matched else None,
        relative_error=relative_error,
        peak_intensity_db=peak_intensity_db,
        vibration_strength_db=vibration_strength_db,
        ref_source="speed+tire" if eligible else None,
        strongest_location=strongest_location,
    )


def test_summarize_whole_run_order_trace_families_builds_phase_and_interval_rollups() -> None:
    labels = tuple(
        _label(
            index,
            phase=DrivingPhase.CRUISE if index < 6 else DrivingPhase.ACCELERATION,
            speed_band="50-60 km/h" if index < 6 else "60-70 km/h",
        )
        for index in range(9)
    )
    points = (
        *(
            _point(
                index,
                hypothesis_key="wheel_1x",
                harmonic=1,
                order_label="1x wheel",
                eligible=index != 6,
                matched=index in {0, 1, 2, 4, 7},
                matched_hz=11.8 + index * 0.1 if index in {0, 1, 2, 4, 7} else None,
                relative_error=0.02 if index in {0, 1, 2, 4, 7} else None,
                peak_intensity_db=18.0 if index in {0, 1, 2, 4, 7} else None,
                vibration_strength_db=12.0 if index in {0, 1, 2, 4, 7} else None,
                strongest_location="Front Left",
            )
            for index in range(9)
        ),
        *(
            _point(
                index,
                hypothesis_key="wheel_2x",
                harmonic=2,
                order_label="2x wheel",
                eligible=index != 6,
                matched=index in {1, 5},
                matched_hz=23.6 + index * 0.2 if index in {1, 5} else None,
                relative_error=0.03 if index in {1, 5} else None,
                peak_intensity_db=20.0 if index == 1 else (17.0 if index == 5 else None),
                vibration_strength_db=13.0 if index in {1, 5} else None,
                strongest_location="Front Right",
            )
            for index in range(9)
        ),
    )

    candidate_summaries = summarize_whole_run_order_traces(points=points, context_labels=labels)
    family_summaries = summarize_whole_run_order_trace_families(
        points=points,
        candidate_summaries=candidate_summaries,
        context_labels=labels,
    )

    assert len(family_summaries) == 1
    summary = family_summaries[0]
    assert summary.hypothesis_key == "wheel"
    assert summary.order_label == "wheel family"
    assert [row.harmonic for row in summary.harmonic_summaries] == [1, 2]
    assert summary.support_ratio == 0.75
    assert summary.reference_coverage_ratio == 8 / 9
    assert [
        (row.phase, row.eligible_window_count, row.matched_window_count)
        for row in summary.phase_support
    ] == [
        (DrivingPhase.ACCELERATION.value, 2, 1),
        (DrivingPhase.CRUISE.value, 6, 5),
    ]
    assert summary.phase_support[0].support_ratio == 0.5
    assert summary.phase_support[1].support_ratio == 5 / 6
    assert summary.support_intervals[0].start_window_index == 0
    assert summary.support_intervals[0].end_window_index == 5
    assert summary.support_intervals[0].matched_window_count == 5
    assert summary.support_intervals[0].support_ratio == 5 / 6
    assert summary.support_intervals[1].start_window_index == 7
    assert summary.support_intervals[1].end_window_index == 8
    assert summary.support_intervals[1].matched_window_count == 1
    assert summary.support_intervals[1].support_ratio == 0.5
    assert summary.exemplar_interval_index == 0
    assert summary.dominant_phase == DrivingPhase.CRUISE.value
    assert summary.dominant_speed_band == "50-60 km/h"
    assert summary.strongest_location == "Front Left"
    assert summary.stable_frequency_min_hz == 11.8
    assert summary.stable_frequency_max_hz == 24.6


def test_build_whole_run_order_family_summary_artifact_bundle_preserves_manifest_shape() -> None:
    labels = tuple(_label(index) for index in range(4))
    points = tuple(
        _point(
            index,
            hypothesis_key="wheel_1x",
            harmonic=1,
            order_label="1x wheel",
            matched=True,
            matched_hz=12.0 + index,
            relative_error=0.02,
            peak_intensity_db=18.0,
            vibration_strength_db=12.0,
            strongest_location="Front Left",
        )
        for index in range(4)
    )
    candidate_summaries = summarize_whole_run_order_traces(points=points, context_labels=labels)
    order_trace_bundle = _order_trace_bundle(points)
    order_trace_summary_bundle = WholeRunOrderTraceSummaryArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-order-families",
            relative_dir="whole-run-artifacts/run-order-families",
            window_policy=_window_policy(),
            total_window_count=4,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY,
                    relative_path="orders/trace-summaries.jsonl",
                    file_format="jsonl",
                    record_count=len(candidate_summaries),
                ),
            ),
            created_at="2025-01-01T00:00:00Z",
        ),
        artifact_contents={WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY: b""},
        summaries=candidate_summaries,
    )

    bundle = build_whole_run_order_family_summary_artifact_bundle(
        order_trace_bundle=order_trace_bundle,
        order_trace_summary_bundle=order_trace_summary_bundle,
        context_labels=tuple(reversed(labels)),
    )

    assert bundle.manifest.to_json_object() == {
        "schema_version": bundle.manifest.schema_version,
        "storage_type": bundle.manifest.storage_type,
        "run_id": "run-order-families",
        "relative_dir": "whole-run-artifacts/run-order-families",
        "window_policy": bundle.manifest.window_policy.to_json_object(),
        "total_window_count": 4,
        "artifacts": [
            {
                "artifact_key": WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY,
                "relative_path": "orders/family-summaries.jsonl",
                "file_format": "jsonl",
                "record_count": len(bundle.summaries),
            }
        ],
        "created_at": "2025-01-01T00:00:00Z",
    }
    assert (
        whole_run_order_trace_summaries_from_jsonl_bytes(
            bundle.artifact_contents[WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY]
        )
        == bundle.summaries
    )
