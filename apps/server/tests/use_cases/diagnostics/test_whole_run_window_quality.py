from __future__ import annotations

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.whole_run_analysis import WholeRunContextWindowLabel
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTracePoint
from vibesensor.use_cases.diagnostics.orders.whole_run_scoring import (
    summarize_whole_run_order_traces,
)


def _context_labels() -> tuple[WholeRunContextWindowLabel, ...]:
    return (
        WholeRunContextWindowLabel(
            window_index=0,
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
        WholeRunContextWindowLabel(
            window_index=1,
            segment_index=0,
            phase=DrivingPhase.CRUISE,
            context_coverage="full",
            speed_validity="measured",
            rpm_validity="measured",
            load_state="steady",
            speed_kmh=55.0,
            speed_source="gps",
            engine_rpm=1600.0,
            engine_rpm_source="obd2",
        ),
    )


def _point(window_index: int, *, quality_score: float, quality_state: str) -> OrderTracePoint:
    return OrderTracePoint(
        hypothesis_key="wheel_1x",
        suspected_source="wheel/tire",
        order_family="wheel",
        harmonic=1,
        order_label="1x wheel",
        window_index=window_index,
        eligible=True,
        matched=True,
        predicted_hz=8.0 + window_index,
        matched_hz=8.05 + window_index,
        relative_error=0.01,
        peak_intensity_db=24.0,
        vibration_strength_db=20.0,
        ref_source="speed+tire",
        strongest_location="Front Left",
        window_quality_score=quality_score,
        window_quality_state=quality_state,
    )


def _shock_point(window_index: int) -> OrderTracePoint:
    return OrderTracePoint(
        hypothesis_key="wheel_1x",
        suspected_source="wheel/tire",
        order_family="wheel",
        harmonic=1,
        order_label="1x wheel",
        window_index=window_index,
        eligible=True,
        matched=False,
        predicted_hz=8.0 + window_index,
        ref_source="speed+tire",
        window_quality_score=0.12,
        window_quality_state="excluded",
        window_quality_reasons=("shock_transient",),
    )


def _clipped_point(window_index: int) -> OrderTracePoint:
    return OrderTracePoint(
        hypothesis_key="wheel_1x",
        suspected_source="wheel/tire",
        order_family="wheel",
        harmonic=1,
        order_label="1x wheel",
        window_index=window_index,
        eligible=True,
        matched=False,
        predicted_hz=8.0 + window_index,
        ref_source="speed+tire",
        window_quality_score=0.10,
        window_quality_state="excluded",
        window_quality_reasons=("sensor_clipping",),
    )


def test_order_trace_scoring_records_and_downweights_limited_window_quality() -> None:
    context_labels = _context_labels()
    clean_summary = summarize_whole_run_order_traces(
        points=(
            _point(0, quality_score=1.0, quality_state="usable"),
            _point(1, quality_score=1.0, quality_state="usable"),
        ),
        context_labels=context_labels,
    )[0]
    limited_summary = summarize_whole_run_order_traces(
        points=(
            _point(0, quality_score=1.0, quality_state="usable"),
            _point(1, quality_score=0.5, quality_state="limited"),
        ),
        context_labels=context_labels,
    )[0]

    assert limited_summary.usable_window_count == 1
    assert limited_summary.limited_window_count == 1
    assert limited_summary.mean_quality_score == 0.75
    assert limited_summary.lock_score < clean_summary.lock_score


def test_order_trace_scoring_counts_unmatched_shock_windows() -> None:
    summary = summarize_whole_run_order_traces(
        points=(
            _point(0, quality_score=1.0, quality_state="usable"),
            _shock_point(1),
        ),
        context_labels=_context_labels(),
    )[0]

    assert summary.matched_window_count == 1
    assert summary.excluded_window_count == 1
    assert summary.shock_transient_window_count == 1
    assert summary.mean_quality_score == 0.56


def test_order_trace_scoring_counts_unmatched_clipped_windows() -> None:
    summary = summarize_whole_run_order_traces(
        points=(
            _point(0, quality_score=1.0, quality_state="usable"),
            _clipped_point(1),
        ),
        context_labels=_context_labels(),
    )[0]

    assert summary.matched_window_count == 1
    assert summary.excluded_window_count == 1
    assert summary.sensor_clipping_window_count == 1
    assert summary.mean_quality_score == 0.55
