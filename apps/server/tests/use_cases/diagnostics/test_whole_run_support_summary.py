from __future__ import annotations

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.whole_run_analysis import WholeRunContextWindowLabel
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTracePoint
from vibesensor.use_cases.diagnostics.whole_run_support_summary import (
    build_phase_support,
    build_support_intervals,
    has_speed_context_quality_reason,
    has_timing_quality_reason,
    mean_window_quality_score,
    unique_quality_reason_window_count,
    window_quality_state_counts,
)


def _label(
    window_index: int,
    *,
    phase: DrivingPhase,
    load_state: str = "steady",
    speed_band: str = "medium",
) -> WholeRunContextWindowLabel:
    return WholeRunContextWindowLabel(
        window_index=window_index,
        segment_index=0,
        phase=phase,
        context_coverage="full",
        speed_validity="measured",
        rpm_validity="measured",
        load_state=load_state,
        speed_band=speed_band,
    )


def _point(
    window_index: int,
    *,
    matched: bool = True,
    peak_intensity_db: float = 20.0,
    window_quality_score: float = 1.0,
    window_quality_state: str = "usable",
    window_quality_reasons: tuple[str, ...] = (),
) -> OrderTracePoint:
    return OrderTracePoint(
        hypothesis_key="wheel_1x",
        suspected_source="wheel/tire",
        order_family="wheel",
        harmonic=1,
        order_label="1x wheel",
        window_index=window_index,
        eligible=True,
        matched=matched,
        predicted_hz=10.0,
        matched_hz=10.05 if matched else None,
        relative_error=0.01 if matched else None,
        peak_intensity_db=peak_intensity_db if matched else None,
        vibration_strength_db=peak_intensity_db - 4.0 if matched else None,
        ref_source="speed+tire",
        window_quality_score=window_quality_score,
        window_quality_state=window_quality_state,
        window_quality_reasons=window_quality_reasons,
    )


def test_support_intervals_keep_eligible_gaps_and_rank_real_exemplar_index() -> None:
    context_by_window = {
        0: _label(0, phase=DrivingPhase.CRUISE, load_state="steady"),
        1: _label(1, phase=DrivingPhase.CRUISE, load_state="steady"),
        2: _label(2, phase=DrivingPhase.ACCELERATION, load_state="accel"),
        4: _label(4, phase=DrivingPhase.CRUISE, load_state="steady"),
        5: _label(5, phase=DrivingPhase.CRUISE, load_state="steady"),
    }
    matched_points_by_window = {
        0: _point(0, peak_intensity_db=15.0),
        2: _point(2, peak_intensity_db=30.0),
        4: _point(4, peak_intensity_db=18.0),
        5: _point(5, peak_intensity_db=18.0),
    }

    summary = build_support_intervals(
        eligible_windows=(0, 1, 2, 4, 5),
        matched_points_by_window=matched_points_by_window,
        context_by_window=context_by_window,
        context_rank_mode="weighted",
        include_peak_intensity_in_rank=True,
        missing_mean_error_rank=1.0,
    )

    assert [(row.start_window_index, row.end_window_index) for row in summary.intervals] == [
        (0, 2),
        (4, 5),
    ]
    assert summary.intervals[0].support_ratio == 2 / 3
    assert summary.intervals[0].phase == "acceleration"
    assert summary.exemplar_interval_index == 1


def test_phase_support_counts_eligible_and_matched_windows_by_phase() -> None:
    context_by_window = {
        0: _label(0, phase=DrivingPhase.CRUISE),
        1: _label(1, phase=DrivingPhase.CRUISE),
        2: _label(2, phase=DrivingPhase.ACCELERATION),
    }

    rows = build_phase_support(
        eligible_windows=(0, 1, 2),
        matched_windows=(0, 2),
        context_by_window=context_by_window,
    )

    assert [(row.phase, row.eligible_window_count, row.matched_window_count) for row in rows] == [
        ("acceleration", 1, 1),
        ("cruise", 2, 1),
    ]
    assert rows[1].support_ratio == 0.5


def test_quality_summary_helpers_count_states_and_reason_windows_once() -> None:
    points = (
        _point(0, window_quality_score=1.0, window_quality_state="usable"),
        _point(
            1,
            window_quality_score=0.5,
            window_quality_state="limited",
            window_quality_reasons=("timing_gap", "server_queue_drop"),
        ),
        _point(
            1,
            window_quality_score=0.25,
            window_quality_state="excluded",
            window_quality_reasons=("timing_gap",),
        ),
        _point(
            2,
            matched=False,
            window_quality_score=0.0,
            window_quality_state="excluded",
            window_quality_reasons=("speed_stale",),
        ),
    )

    counts = window_quality_state_counts(points)

    assert counts.usable_window_count == 1
    assert counts.limited_window_count == 1
    assert counts.excluded_window_count == 2
    assert mean_window_quality_score(points) == 0.4375
    assert unique_quality_reason_window_count(points, "timing_gap") == 1
    assert has_timing_quality_reason(points[1])
    assert has_speed_context_quality_reason(points[3])
