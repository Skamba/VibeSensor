"""Whole-run harmonic stability and order-lock scoring over dense order traces."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import sqrt

from vibesensor.shared.json_utils import safe_json_dumps, safe_json_loads
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.json_types import is_json_object
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
)
from vibesensor.use_cases.diagnostics.orders.physics import OrderHypothesis, _order_hypotheses
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import (
    OrderHarmonicEvidenceSummary,
    OrderTracePoint,
    OrderTraceSummary,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WholeRunOrderTraceArtifactBundle,
)

WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY = "order-trace-summaries"
_WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_PATH = "orders/trace-summaries.jsonl"
_LOCK_SCORE_SUPPORT_WEIGHT = 0.35
_LOCK_SCORE_REFERENCE_WEIGHT = 0.20
_LOCK_SCORE_CONTIGUOUS_WEIGHT = 0.20
_LOCK_SCORE_ERROR_WEIGHT = 0.15
_LOCK_SCORE_DRIFT_WEIGHT = 0.10
_RELATIVE_ERROR_DENOMINATOR = 0.25
_RELATIVE_ERROR_DRIFT_TOLERANCE = 0.08

__all__ = [
    "WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY",
    "WholeRunOrderTraceSummaryArtifactBundle",
    "build_whole_run_order_trace_summary_artifact_bundle",
    "summarize_whole_run_order_traces",
    "whole_run_order_trace_summaries_from_jsonl_bytes",
    "whole_run_order_trace_summaries_to_jsonl_bytes",
]


@dataclass(frozen=True, slots=True)
class WholeRunOrderTraceSummaryArtifactBundle:
    """Compact whole-run order-trace summaries plus the summary sidecar bytes."""

    manifest: WholeRunArtifactManifest
    artifact_contents: dict[str, bytes]
    summaries: tuple[OrderTraceSummary, ...]


def build_whole_run_order_trace_summary_artifact_bundle(
    *,
    order_trace_bundle: WholeRunOrderTraceArtifactBundle,
    context_labels: Sequence[WholeRunContextWindowLabel],
    created_at: str | None = None,
) -> WholeRunOrderTraceSummaryArtifactBundle:
    """Collapse dense whole-run order traces into deterministic scored summaries."""

    ordered_labels = tuple(sorted(context_labels, key=lambda label: label.window_index))
    manifest = order_trace_bundle.manifest
    if len(ordered_labels) != manifest.total_window_count:
        raise ValueError("whole-run order scoring requires context labels for every window")
    if any(label.window_index != index for index, label in enumerate(ordered_labels)):
        raise ValueError("whole-run order scoring requires contiguous ordered context labels")
    summaries = summarize_whole_run_order_traces(
        points=order_trace_bundle.points,
        context_labels=ordered_labels,
    )
    artifact = WholeRunArtifactFile(
        artifact_key=WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY,
        relative_path=_WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_PATH,
        file_format="jsonl",
        record_count=len(summaries),
    )
    summary_manifest = WholeRunArtifactManifest(
        run_id=manifest.run_id,
        relative_dir=manifest.relative_dir,
        window_policy=manifest.window_policy,
        total_window_count=manifest.total_window_count,
        artifacts=(artifact,),
        created_at=created_at or manifest.created_at or utc_now_iso(),
        schema_version=manifest.schema_version,
        storage_type=manifest.storage_type,
    )
    return WholeRunOrderTraceSummaryArtifactBundle(
        manifest=summary_manifest,
        artifact_contents={
            WHOLE_RUN_ORDER_TRACE_SUMMARY_ARTIFACT_KEY: (
                whole_run_order_trace_summaries_to_jsonl_bytes(summaries)
            )
        },
        summaries=summaries,
    )


def summarize_whole_run_order_traces(
    *,
    points: Sequence[OrderTracePoint],
    context_labels: Sequence[WholeRunContextWindowLabel],
) -> tuple[OrderTraceSummary, ...]:
    """Score whole-run order traces into compact summary rows."""

    if not points:
        return ()
    context_by_window = {label.window_index: label for label in context_labels}
    points_by_hypothesis: dict[str, list[OrderTracePoint]] = defaultdict(list)
    for point in points:
        points_by_hypothesis[point.hypothesis_key].append(point)

    hypothesis_catalog = {hypothesis.key: hypothesis for hypothesis in _order_hypotheses()}
    ordered_keys = [
        hypothesis.key
        for hypothesis in _order_hypotheses()
        if hypothesis.key in points_by_hypothesis
    ]
    ordered_keys.extend(
        sorted(key for key in points_by_hypothesis if key not in hypothesis_catalog)
    )
    summaries: list[OrderTraceSummary] = []
    for hypothesis_key in ordered_keys:
        hypothesis_points = tuple(
            sorted(points_by_hypothesis[hypothesis_key], key=lambda point: point.window_index)
        )
        summaries.append(
            _summarize_hypothesis_trace(
                points=hypothesis_points,
                hypothesis=hypothesis_catalog.get(hypothesis_key),
                context_by_window=context_by_window,
            )
        )
    return tuple(summaries)


def whole_run_order_trace_summaries_to_jsonl_bytes(
    summaries: Sequence[OrderTraceSummary],
) -> bytes:
    """Serialize compact whole-run order-trace summaries into sidecar JSONL bytes."""

    if not summaries:
        return b""
    lines = [safe_json_dumps(summary.to_json_object()).encode("utf-8") for summary in summaries]
    return b"\n".join(lines) + b"\n"


def whole_run_order_trace_summaries_from_jsonl_bytes(
    payload: bytes,
) -> tuple[OrderTraceSummary, ...]:
    """Reconstruct compact whole-run order-trace summaries from persisted JSONL bytes."""

    if not payload:
        return ()
    summaries: list[OrderTraceSummary] = []
    for raw_line in payload.decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = safe_json_loads(line, context="whole-run order trace summaries")
        if not is_json_object(parsed):
            raise ValueError("whole-run order trace summary line must decode to a JSON object")
        summaries.append(OrderTraceSummary.from_mapping(parsed))
    return tuple(summaries)


def _summarize_hypothesis_trace(
    *,
    points: Sequence[OrderTracePoint],
    hypothesis: OrderHypothesis | None,
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
) -> OrderTraceSummary:
    first_point = points[0]
    total_window_count = len(points)
    eligible_points = [point for point in points if point.eligible]
    matched_points = [point for point in points if point.matched]
    eligible_window_count = len(eligible_points)
    matched_window_count = len(matched_points)
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
        path_compliance=hypothesis.path_compliance if hypothesis is not None else 1.0,
    )
    lock_score = _lock_score(
        support_ratio=support_ratio,
        reference_coverage_ratio=reference_coverage_ratio,
        contiguous_support_ratio=contiguous_support_ratio,
        mean_relative_error=mean_relative_error,
        drift_score=drift_score,
        path_compliance=hypothesis.path_compliance if hypothesis is not None else 1.0,
    )
    peak_intensity_db = _max_or_none(
        point.peak_intensity_db for point in matched_points if point.peak_intensity_db is not None
    )
    mean_vibration_strength_db = _mean(
        point.vibration_strength_db
        for point in matched_points
        if point.vibration_strength_db is not None
    )
    strongest_location = _dominant_value(
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
    ref_sources = tuple(
        sorted({point.ref_source for point in eligible_points if point.ref_source is not None})
    )
    harmonic_summary = OrderHarmonicEvidenceSummary(
        harmonic=first_point.harmonic,
        order_label=first_point.order_label,
        eligible_window_count=eligible_window_count,
        matched_window_count=matched_window_count,
        support_ratio=support_ratio,
        reference_coverage_ratio=reference_coverage_ratio,
        contiguous_support_ratio=contiguous_support_ratio,
        lock_score=lock_score,
        mean_relative_error=mean_relative_error,
        relative_error_stddev=relative_error_stddev,
        drift_score=drift_score,
        peak_intensity_db=peak_intensity_db,
        mean_vibration_strength_db=mean_vibration_strength_db,
    )
    return OrderTraceSummary(
        hypothesis_key=first_point.hypothesis_key,
        suspected_source=first_point.suspected_source,
        order_family=first_point.order_family,
        order_label=first_point.order_label,
        total_window_count=total_window_count,
        eligible_window_count=eligible_window_count,
        matched_window_count=matched_window_count,
        support_ratio=support_ratio,
        reference_coverage_ratio=reference_coverage_ratio,
        longest_contiguous_support_window_count=longest_contiguous_support_window_count,
        contiguous_support_ratio=contiguous_support_ratio,
        support_intervals=(),
        phase_support=(),
        harmonic_summaries=(harmonic_summary,),
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


def _lock_score(
    *,
    support_ratio: float,
    reference_coverage_ratio: float,
    contiguous_support_ratio: float,
    mean_relative_error: float | None,
    drift_score: float,
    path_compliance: float,
) -> float:
    error_score = _relative_error_score(
        mean_relative_error=mean_relative_error,
        path_compliance=path_compliance,
    )
    return max(
        0.0,
        min(
            1.0,
            (_LOCK_SCORE_SUPPORT_WEIGHT * support_ratio)
            + (_LOCK_SCORE_REFERENCE_WEIGHT * reference_coverage_ratio)
            + (_LOCK_SCORE_CONTIGUOUS_WEIGHT * contiguous_support_ratio)
            + (_LOCK_SCORE_ERROR_WEIGHT * error_score)
            + (_LOCK_SCORE_DRIFT_WEIGHT * drift_score),
        ),
    )


def _relative_error_score(*, mean_relative_error: float | None, path_compliance: float) -> float:
    if mean_relative_error is None:
        return 0.0
    denominator = max(1e-9, _RELATIVE_ERROR_DENOMINATOR * path_compliance)
    return max(0.0, 1.0 - min(1.0, mean_relative_error / denominator))


def _drift_score(*, relative_error_stddev: float | None, path_compliance: float) -> float:
    if relative_error_stddev is None:
        return 0.0
    denominator = max(1e-9, _RELATIVE_ERROR_DRIFT_TOLERANCE * path_compliance)
    return max(0.0, 1.0 - min(1.0, relative_error_stddev / denominator))


def _longest_contiguous_match_run(points: Sequence[OrderTracePoint]) -> int:
    longest = 0
    current = 0
    previous_window_index: int | None = None
    for point in points:
        if previous_window_index is None or point.window_index == previous_window_index + 1:
            current += 1
        else:
            current = 1
        previous_window_index = point.window_index
        longest = max(longest, current)
    return longest


def _dominant_context_value(
    *,
    points: Sequence[OrderTracePoint],
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
    attribute_name: str,
) -> str | None:
    ranked_values: list[tuple[str, float]] = []
    for point in points:
        label = context_by_window.get(point.window_index)
        if label is None:
            continue
        raw_value = getattr(label, attribute_name)
        value = raw_value.value if hasattr(raw_value, "value") else raw_value
        if not isinstance(value, str) or not value:
            continue
        ranked_values.append(
            (value, point.peak_intensity_db if point.peak_intensity_db is not None else 0.0)
        )
    return _dominant_value(values=ranked_values)


def _dominant_value(*, values: Iterable[tuple[str, float]]) -> str | None:
    items = tuple(values)
    if not items:
        return None
    counts = Counter(value for value, _weight in items)
    weights: dict[str, float] = defaultdict(float)
    for value, weight in items:
        weights[value] += float(weight)
    return max(
        counts,
        key=lambda value: (counts[value], weights[value], value),
    )


def _mean(values: Iterable[float]) -> float | None:
    items = tuple(values)
    if not items:
        return None
    return sum(float(value) for value in items) / len(items)


def _max_or_none(values: Iterable[float]) -> float | None:
    items = tuple(values)
    if not items:
        return None
    return max(float(value) for value in items)


def _stddev(values: Iterable[float]) -> float | None:
    items = tuple(values)
    if not items:
        return None
    mean_value = _mean(items)
    if mean_value is None:
        return None
    variance = sum((float(value) - mean_value) ** 2 for value in items) / len(items)
    return sqrt(max(0.0, variance))


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
