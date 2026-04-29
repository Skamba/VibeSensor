"""Whole-run source-family summaries over scored harmonic order traces."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
)
from vibesensor.use_cases.diagnostics._artifact_bundles import (
    build_single_artifact_bundle_parts,
)
from vibesensor.use_cases.diagnostics._ranking_utils import dominant_weighted_value
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import (
    OrderTracePhaseSupport,
    OrderTracePoint,
    OrderTraceSummary,
    OrderTraceSupportInterval,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_scoring import (
    WholeRunOrderTraceSummaryArtifactBundle,
    _dominant_context_value,
    _drift_score,
    _lock_score,
    _longest_contiguous_match_run,
    _max_or_none,
    _mean,
    _min_or_none,
    _ratio,
    _stddev,
    whole_run_order_trace_summaries_to_jsonl_bytes,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WholeRunOrderTraceArtifactBundle,
)

WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY = "order-family-summaries"
_WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_PATH = "orders/family-summaries.jsonl"
_FAMILY_ORDER = ("wheel", "driveshaft", "engine")

__all__ = [
    "WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY",
    "WholeRunOrderFamilySummaryArtifactBundle",
    "build_whole_run_order_family_summary_artifact_bundle",
    "summarize_whole_run_order_trace_families",
]


@dataclass(frozen=True, slots=True)
class WholeRunOrderFamilySummaryArtifactBundle:
    """Compact source-family order summaries plus persisted sidecar bytes."""

    manifest: WholeRunArtifactManifest
    artifact_contents: dict[str, bytes]
    summaries: tuple[OrderTraceSummary, ...]


def build_whole_run_order_family_summary_artifact_bundle(
    *,
    order_trace_bundle: WholeRunOrderTraceArtifactBundle,
    order_trace_summary_bundle: WholeRunOrderTraceSummaryArtifactBundle,
    context_labels: Sequence[WholeRunContextWindowLabel],
    created_at: str | None = None,
) -> WholeRunOrderFamilySummaryArtifactBundle:
    """Build compact source-family summaries over dense whole-run order traces."""

    ordered_labels = tuple(sorted(context_labels, key=lambda label: label.window_index))
    manifest = order_trace_bundle.manifest
    if len(ordered_labels) != manifest.total_window_count:
        raise ValueError("whole-run order family summaries require context labels for every window")
    if any(label.window_index != index for index, label in enumerate(ordered_labels)):
        raise ValueError(
            "whole-run order family summaries require contiguous ordered context labels"
        )
    summaries = summarize_whole_run_order_trace_families(
        points=order_trace_bundle.points,
        candidate_summaries=order_trace_summary_bundle.summaries,
        context_labels=ordered_labels,
    )
    parts = build_single_artifact_bundle_parts(
        artifact_key=WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_KEY,
        relative_path=_WHOLE_RUN_ORDER_FAMILY_SUMMARY_ARTIFACT_PATH,
        file_format="jsonl",
        record_count=len(summaries),
        source_manifest=manifest,
        created_at=created_at or manifest.created_at or utc_now_iso(),
        content_bytes=whole_run_order_trace_summaries_to_jsonl_bytes(summaries),
    )
    return WholeRunOrderFamilySummaryArtifactBundle(
        manifest=parts.manifest,
        artifact_contents=parts.artifact_contents,
        summaries=summaries,
    )


def summarize_whole_run_order_trace_families(
    *,
    points: Sequence[OrderTracePoint],
    candidate_summaries: Sequence[OrderTraceSummary],
    context_labels: Sequence[WholeRunContextWindowLabel],
) -> tuple[OrderTraceSummary, ...]:
    """Collapse scored harmonic traces into compact source-family summaries."""

    if not points or not candidate_summaries:
        return ()
    context_by_window = {label.window_index: label for label in context_labels}
    summaries_by_family: dict[str, list[OrderTraceSummary]] = defaultdict(list)
    points_by_family: dict[str, list[OrderTracePoint]] = defaultdict(list)
    for summary in candidate_summaries:
        summaries_by_family[summary.order_family].append(summary)
    for point in points:
        points_by_family[point.order_family].append(point)

    ordered_families = [
        family
        for family in _FAMILY_ORDER
        if family in summaries_by_family and family in points_by_family
    ]
    ordered_families.extend(
        sorted(
            family
            for family in summaries_by_family
            if family not in ordered_families and family in points_by_family
        )
    )
    family_summaries: list[OrderTraceSummary] = []
    total_window_count = len(context_labels)
    for family in ordered_families:
        family_summaries.append(
            _family_summary(
                family=family,
                total_window_count=total_window_count,
                candidate_summaries=tuple(summaries_by_family[family]),
                points=tuple(points_by_family[family]),
                context_by_window=context_by_window,
            )
        )
    return tuple(family_summaries)


def _family_summary(
    *,
    family: str,
    total_window_count: int,
    candidate_summaries: Sequence[OrderTraceSummary],
    points: Sequence[OrderTracePoint],
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
) -> OrderTraceSummary:
    ordered_candidate_summaries = tuple(
        sorted(candidate_summaries, key=lambda summary: _summary_sort_key(summary))
    )
    primary_summary = ordered_candidate_summaries[0]
    selected_matches_by_window = _selected_family_matches_by_window(
        points=points,
        candidate_summaries=ordered_candidate_summaries,
    )
    matched_points = [
        selected_matches_by_window[index] for index in sorted(selected_matches_by_window)
    ]
    eligible_windows = sorted({point.window_index for point in points if point.eligible})
    matched_window_count = len(matched_points)
    eligible_window_count = len(eligible_windows)
    support_ratio = _ratio(matched_window_count, eligible_window_count)
    reference_coverage_ratio = _ratio(eligible_window_count, total_window_count)
    longest_contiguous_support_window_count = _longest_contiguous_match_run(matched_points)
    contiguous_support_ratio = _ratio(
        longest_contiguous_support_window_count,
        eligible_window_count,
    )
    relative_errors = [
        point.relative_error for point in matched_points if point.relative_error is not None
    ]
    mean_relative_error = _mean(relative_errors)
    relative_error_stddev = _stddev(relative_errors)
    drift_score = _drift_score(
        relative_error_stddev=relative_error_stddev,
        path_compliance=1.0,
    )
    lock_score = _lock_score(
        support_ratio=support_ratio,
        reference_coverage_ratio=reference_coverage_ratio,
        contiguous_support_ratio=contiguous_support_ratio,
        mean_relative_error=mean_relative_error,
        drift_score=drift_score,
        path_compliance=1.0,
    )
    support_intervals, exemplar_interval_index = _support_intervals(
        eligible_windows=eligible_windows,
        selected_matches_by_window=selected_matches_by_window,
        context_by_window=context_by_window,
    )
    phase_support = _phase_support_rows(
        eligible_windows=eligible_windows,
        selected_matches_by_window=selected_matches_by_window,
        context_by_window=context_by_window,
    )
    stable_frequency_min_hz = _min_or_none(
        point.matched_hz for point in matched_points if point.matched_hz is not None
    )
    stable_frequency_max_hz = _max_or_none(
        point.matched_hz for point in matched_points if point.matched_hz is not None
    )
    peak_intensity_db = _max_or_none(
        point.peak_intensity_db for point in matched_points if point.peak_intensity_db is not None
    )
    mean_vibration_strength_db = _mean(
        point.vibration_strength_db
        for point in matched_points
        if point.vibration_strength_db is not None
    )
    strongest_location = dominant_weighted_value(
        values=(
            (
                point.strongest_location,
                point.peak_intensity_db if point.peak_intensity_db is not None else 0.0,
            )
            for point in matched_points
            if point.strongest_location
        )
    )
    dominant_phase = _dominant_context_value(
        points=matched_points,
        context_by_window=context_by_window,
        attribute_name="phase",
    )
    dominant_speed_band = _dominant_context_value(
        points=matched_points,
        context_by_window=context_by_window,
        attribute_name="speed_band",
    )
    ref_sources = tuple(sorted({point.ref_source for point in points if point.ref_source}))
    harmonic_summaries = tuple(
        summary.harmonic_summaries[0]
        for summary in ordered_candidate_summaries
        if summary.harmonic_summaries
    )
    return OrderTraceSummary(
        hypothesis_key=family,
        suspected_source=primary_summary.suspected_source,
        order_family=primary_summary.order_family,
        order_label=f"{family} family",
        total_window_count=total_window_count,
        eligible_window_count=eligible_window_count,
        matched_window_count=matched_window_count,
        support_ratio=support_ratio,
        reference_coverage_ratio=reference_coverage_ratio,
        longest_contiguous_support_window_count=longest_contiguous_support_window_count,
        contiguous_support_ratio=contiguous_support_ratio,
        support_intervals=support_intervals,
        phase_support=phase_support,
        harmonic_summaries=harmonic_summaries,
        stable_frequency_min_hz=stable_frequency_min_hz,
        stable_frequency_max_hz=stable_frequency_max_hz,
        exemplar_interval_index=exemplar_interval_index,
        dominant_phase=dominant_phase,
        dominant_speed_band=dominant_speed_band,
        strongest_location=strongest_location,
        mean_relative_error=mean_relative_error,
        relative_error_stddev=relative_error_stddev,
        drift_score=drift_score,
        lock_score=lock_score,
        peak_intensity_db=peak_intensity_db,
        mean_vibration_strength_db=mean_vibration_strength_db,
        ref_sources=ref_sources,
    )


def _selected_family_matches_by_window(
    *,
    points: Sequence[OrderTracePoint],
    candidate_summaries: Sequence[OrderTraceSummary],
) -> dict[int, OrderTracePoint]:
    summary_by_key = {summary.hypothesis_key: summary for summary in candidate_summaries}
    matched_candidates_by_window: dict[int, list[OrderTracePoint]] = defaultdict(list)
    for point in points:
        if point.matched:
            matched_candidates_by_window[point.window_index].append(point)
    selected: dict[int, OrderTracePoint] = {}
    for window_index, window_points in matched_candidates_by_window.items():
        selected[window_index] = sorted(
            window_points,
            key=lambda point: _point_rank(point, summary_by_key),
            reverse=True,
        )[0]
    return selected


def _support_intervals(
    *,
    eligible_windows: Sequence[int],
    selected_matches_by_window: Mapping[int, OrderTracePoint],
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
) -> tuple[tuple[OrderTraceSupportInterval, ...], int | None]:
    intervals: list[OrderTraceSupportInterval] = []
    interval_ranks: list[tuple[int, float, float, float, int]] = []
    current_start: int | None = None
    current_windows: list[int] = []
    matched_points: list[OrderTracePoint] = []
    previous_window: int | None = None
    for window_index in eligible_windows:
        if previous_window is None or window_index == previous_window + 1:
            if current_start is None:
                current_start = window_index
            current_windows.append(window_index)
            point = selected_matches_by_window.get(window_index)
            if point is not None:
                matched_points.append(point)
        else:
            _append_interval(
                intervals=intervals,
                interval_ranks=interval_ranks,
                interval_index=len(intervals),
                start_window=current_start,
                eligible_windows=current_windows,
                matched_points=matched_points,
                context_by_window=context_by_window,
            )
            current_start = window_index
            current_windows = [window_index]
            matched_points = []
            point = selected_matches_by_window.get(window_index)
            if point is not None:
                matched_points.append(point)
        previous_window = window_index
    _append_interval(
        intervals=intervals,
        interval_ranks=interval_ranks,
        interval_index=len(intervals),
        start_window=current_start,
        eligible_windows=current_windows,
        matched_points=matched_points,
        context_by_window=context_by_window,
    )
    exemplar_interval_index: int | None = None
    if interval_ranks:
        exemplar_interval_index = max(interval_ranks)[-1]
    return tuple(intervals), exemplar_interval_index


def _append_interval(
    *,
    intervals: list[OrderTraceSupportInterval],
    interval_ranks: list[tuple[int, float, float, float, int]],
    interval_index: int,
    start_window: int | None,
    eligible_windows: Sequence[int],
    matched_points: Sequence[OrderTracePoint],
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
) -> None:
    if start_window is None or not eligible_windows or not matched_points:
        return
    end_window = eligible_windows[-1]
    support_ratio = _ratio(len(matched_points), len(eligible_windows))
    mean_relative_error = _mean(
        point.relative_error for point in matched_points if point.relative_error is not None
    )
    interval = OrderTraceSupportInterval(
        interval_index=interval_index,
        start_window_index=start_window,
        end_window_index=end_window,
        matched_window_count=len(matched_points),
        support_ratio=support_ratio,
        phase=_dominant_context_value(
            points=matched_points,
            context_by_window=context_by_window,
            attribute_name="phase",
        ),
        load_state=_dominant_load_state(matched_points, context_by_window),
        speed_band=_dominant_context_value(
            points=matched_points,
            context_by_window=context_by_window,
            attribute_name="speed_band",
        ),
        mean_relative_error=mean_relative_error,
    )
    intervals.append(interval)
    interval_ranks.append(
        (
            len(matched_points),
            support_ratio,
            _max_or_none(
                point.peak_intensity_db
                for point in matched_points
                if point.peak_intensity_db is not None
            )
            or 0.0,
            -(mean_relative_error or 1.0),
            -interval_index,
        )
    )


def _phase_support_rows(
    *,
    eligible_windows: Sequence[int],
    selected_matches_by_window: Mapping[int, OrderTracePoint],
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
) -> tuple[OrderTracePhaseSupport, ...]:
    eligible_by_phase: dict[str, int] = defaultdict(int)
    matched_by_phase: dict[str, int] = defaultdict(int)
    for window_index in eligible_windows:
        label = context_by_window.get(window_index)
        if label is None:
            continue
        phase = label.phase.value
        eligible_by_phase[phase] += 1
        if window_index in selected_matches_by_window:
            matched_by_phase[phase] += 1
    ordered_phases = sorted(eligible_by_phase)
    return tuple(
        OrderTracePhaseSupport(
            phase=phase,
            eligible_window_count=eligible_by_phase[phase],
            matched_window_count=matched_by_phase.get(phase, 0),
            support_ratio=_ratio(matched_by_phase.get(phase, 0), eligible_by_phase[phase]),
        )
        for phase in ordered_phases
    )


def _dominant_load_state(
    points: Sequence[OrderTracePoint],
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
) -> str | None:
    ranked_values: list[tuple[str, float]] = []
    for point in points:
        label = context_by_window.get(point.window_index)
        if label is None or not label.load_state:
            continue
        ranked_values.append(
            (
                label.load_state,
                point.peak_intensity_db if point.peak_intensity_db is not None else 0.0,
            )
        )
    return dominant_weighted_value(values=ranked_values)


def _point_rank(
    point: OrderTracePoint,
    summary_by_key: Mapping[str, OrderTraceSummary],
) -> tuple[float, float, float, int, str]:
    summary = summary_by_key.get(point.hypothesis_key)
    lock_score = summary.lock_score if summary is not None else 0.0
    return (
        lock_score,
        point.peak_intensity_db if point.peak_intensity_db is not None else 0.0,
        -(point.relative_error if point.relative_error is not None else 1.0),
        -point.harmonic,
        point.hypothesis_key,
    )


def _summary_sort_key(summary: OrderTraceSummary) -> tuple[int, float, float, str]:
    harmonic = summary.harmonic_summaries[0].harmonic if summary.harmonic_summaries else 99
    return (harmonic, -summary.lock_score, -summary.support_ratio, summary.hypothesis_key)
