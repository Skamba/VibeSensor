"""Shared compact support-summary helpers for whole-run diagnostics."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from vibesensor.shared.types.whole_run_analysis import WholeRunContextWindowLabel
from vibesensor.use_cases.diagnostics._ranking_utils import dominant_weighted_value
from vibesensor.use_cases.diagnostics.math_utils import (
    _mean_or_none as _mean,
)
from vibesensor.use_cases.diagnostics.math_utils import (
    _ratio_or_zero as _ratio,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import (
    OrderTracePhaseSupport,
    OrderTraceSupportInterval,
)

TIMING_QUALITY_REASONS = frozenset(
    {"timing_gap", "late_packet_loss", "server_queue_drop", "sensor_reset"}
)
SPEED_CONTEXT_QUALITY_REASONS = frozenset(
    {
        "speed_unavailable",
        "speed_low",
        "speed_stale",
        "speed_unstable",
        "speed_assumed",
    }
)

type ContextRankMode = Literal["count", "weighted"]


class WholeRunSupportPoint(Protocol):
    @property
    def window_index(self) -> int: ...

    @property
    def matched(self) -> bool: ...

    @property
    def relative_error(self) -> float | None: ...

    @property
    def peak_intensity_db(self) -> float | None: ...

    @property
    def window_quality_score(self) -> float | None: ...

    @property
    def window_quality_state(self) -> str | None: ...

    @property
    def window_quality_reasons(self) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class WindowQualityStateCounts:
    usable_window_count: int
    limited_window_count: int
    excluded_window_count: int


@dataclass(frozen=True, slots=True)
class SupportIntervalSummary:
    intervals: tuple[OrderTraceSupportInterval, ...]
    exemplar_interval_index: int | None


def mean_window_quality_score(points: Iterable[WholeRunSupportPoint]) -> float | None:
    return _mean(
        point.window_quality_score for point in points if point.window_quality_score is not None
    )


def window_quality_state_counts(
    points: Iterable[WholeRunSupportPoint],
    *,
    excluded_window_count: int | None = None,
) -> WindowQualityStateCounts:
    usable_window_count = 0
    limited_window_count = 0
    computed_excluded_window_count = 0
    for point in points:
        if point.window_quality_state == "usable":
            usable_window_count += 1
        elif point.window_quality_state == "limited":
            limited_window_count += 1
        elif point.window_quality_state == "excluded":
            computed_excluded_window_count += 1
    return WindowQualityStateCounts(
        usable_window_count=usable_window_count,
        limited_window_count=limited_window_count,
        excluded_window_count=(
            computed_excluded_window_count
            if excluded_window_count is None
            else excluded_window_count
        ),
    )


def unique_quality_reason_window_count(
    points: Iterable[WholeRunSupportPoint],
    reason: str,
) -> int:
    return len({point.window_index for point in points if reason in point.window_quality_reasons})


def has_timing_quality_reason(point: WholeRunSupportPoint) -> bool:
    return has_any_quality_reason(point, TIMING_QUALITY_REASONS)


def has_speed_context_quality_reason(point: WholeRunSupportPoint) -> bool:
    return has_any_quality_reason(point, SPEED_CONTEXT_QUALITY_REASONS)


def has_any_quality_reason(
    point: WholeRunSupportPoint,
    reasons: frozenset[str],
) -> bool:
    return any(reason in reasons for reason in point.window_quality_reasons)


def build_support_intervals(
    *,
    eligible_windows: Sequence[int],
    matched_points_by_window: Mapping[int, WholeRunSupportPoint],
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
    context_rank_mode: ContextRankMode,
    include_peak_intensity_in_rank: bool = False,
    missing_mean_error_rank: float = 0.0,
) -> SupportIntervalSummary:
    intervals: list[OrderTraceSupportInterval] = []
    interval_ranks: list[tuple[tuple[float, ...], int]] = []
    current_start: int | None = None
    current_windows: list[int] = []
    matched_points: list[WholeRunSupportPoint] = []
    previous_window: int | None = None
    for window_index in sorted(eligible_windows):
        if previous_window is None or window_index == previous_window + 1:
            if current_start is None:
                current_start = window_index
            current_windows.append(window_index)
            point = matched_points_by_window.get(window_index)
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
                context_rank_mode=context_rank_mode,
                include_peak_intensity_in_rank=include_peak_intensity_in_rank,
                missing_mean_error_rank=missing_mean_error_rank,
            )
            current_start = window_index
            current_windows = [window_index]
            matched_points = []
            point = matched_points_by_window.get(window_index)
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
        context_rank_mode=context_rank_mode,
        include_peak_intensity_in_rank=include_peak_intensity_in_rank,
        missing_mean_error_rank=missing_mean_error_rank,
    )
    return SupportIntervalSummary(
        intervals=tuple(intervals),
        exemplar_interval_index=max(interval_ranks)[1] if interval_ranks else None,
    )


def build_phase_support(
    *,
    eligible_windows: Sequence[int],
    matched_windows: Iterable[int],
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
) -> tuple[OrderTracePhaseSupport, ...]:
    matched_window_set = set(matched_windows)
    eligible_by_phase: dict[str, int] = defaultdict(int)
    matched_by_phase: dict[str, int] = defaultdict(int)
    for window_index in sorted(eligible_windows):
        label = context_by_window.get(window_index)
        if label is None:
            continue
        phase = label.phase.value
        eligible_by_phase[phase] += 1
        if window_index in matched_window_set:
            matched_by_phase[phase] += 1
    return tuple(
        OrderTracePhaseSupport(
            phase=phase,
            eligible_window_count=eligible_by_phase[phase],
            matched_window_count=matched_by_phase.get(phase, 0),
            support_ratio=_ratio(matched_by_phase.get(phase, 0), eligible_by_phase[phase]),
        )
        for phase in sorted(eligible_by_phase)
    )


def dominant_context_value(
    *,
    points: Sequence[WholeRunSupportPoint],
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
    attribute_name: str,
) -> str | None:
    ranked_values: list[tuple[str, float]] = []
    for point in points:
        value = _context_value(
            point=point,
            context_by_window=context_by_window,
            attribute_name=attribute_name,
        )
        if value is None:
            continue
        ranked_values.append(
            (value, point.peak_intensity_db if point.peak_intensity_db is not None else 0.0)
        )
    return dominant_weighted_value(values=ranked_values)


def _append_interval(
    *,
    intervals: list[OrderTraceSupportInterval],
    interval_ranks: list[tuple[tuple[float, ...], int]],
    interval_index: int,
    start_window: int | None,
    eligible_windows: Sequence[int],
    matched_points: Sequence[WholeRunSupportPoint],
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
    context_rank_mode: ContextRankMode,
    include_peak_intensity_in_rank: bool,
    missing_mean_error_rank: float,
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
        phase=_interval_context_value(
            points=matched_points,
            context_by_window=context_by_window,
            attribute_name="phase",
            rank_mode=context_rank_mode,
        ),
        load_state=_interval_context_value(
            points=matched_points,
            context_by_window=context_by_window,
            attribute_name="load_state",
            rank_mode=context_rank_mode,
        ),
        speed_band=_interval_context_value(
            points=matched_points,
            context_by_window=context_by_window,
            attribute_name="speed_band",
            rank_mode=context_rank_mode,
        ),
        mean_relative_error=mean_relative_error,
    )
    intervals.append(interval)
    rank: tuple[float, ...]
    if include_peak_intensity_in_rank:
        rank = (
            float(len(matched_points)),
            support_ratio,
            _max_peak_intensity(matched_points),
            -(mean_relative_error or missing_mean_error_rank),
            float(-interval_index),
        )
    else:
        rank = (
            float(len(matched_points)),
            support_ratio,
            -(mean_relative_error or missing_mean_error_rank),
            float(-interval_index),
        )
    interval_ranks.append((rank, interval_index))


def _interval_context_value(
    *,
    points: Sequence[WholeRunSupportPoint],
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
    attribute_name: str,
    rank_mode: ContextRankMode,
) -> str | None:
    if rank_mode == "weighted":
        return dominant_context_value(
            points=points,
            context_by_window=context_by_window,
            attribute_name=attribute_name,
        )
    counts: dict[str, int] = {}
    for point in points:
        value = _context_value(
            point=point,
            context_by_window=context_by_window,
            attribute_name=attribute_name,
        )
        if value is None:
            continue
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def _context_value(
    *,
    point: WholeRunSupportPoint,
    context_by_window: Mapping[int, WholeRunContextWindowLabel],
    attribute_name: str,
) -> str | None:
    label = context_by_window.get(point.window_index)
    if label is None:
        return None
    raw_value = getattr(label, attribute_name)
    value = raw_value.value if hasattr(raw_value, "value") else raw_value
    return value if isinstance(value, str) and value else None


def _max_peak_intensity(points: Sequence[WholeRunSupportPoint]) -> float:
    values = [point.peak_intensity_db for point in points if point.peak_intensity_db is not None]
    return max(values) if values else 0.0
