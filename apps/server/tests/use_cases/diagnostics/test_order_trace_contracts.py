from __future__ import annotations

import pytest

from vibesensor.shared.types.history_analysis_contracts import (
    OrderHarmonicEvidenceSummaryResponse,
    OrderTracePhaseSupportResponse,
    OrderTraceSummaryResponse,
    OrderTraceSupportIntervalResponse,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import (
    OrderHarmonicEvidenceSummary,
    OrderTracePhaseSupport,
    OrderTracePoint,
    OrderTraceSummary,
    OrderTraceSupportInterval,
)


def test_order_trace_point_round_trips_json_shape() -> None:
    point = OrderTracePoint(
        hypothesis_key="wheel_1x",
        suspected_source="wheel/tire",
        order_family="wheel",
        harmonic=1,
        order_label="1x wheel",
        window_index=42,
        eligible=True,
        matched=True,
        predicted_hz=14.8,
        matched_hz=14.9,
        relative_error=0.0067,
        peak_intensity_db=18.2,
        vibration_strength_db=11.5,
        ref_source="speed+tire",
        strongest_location="Front Left",
    )

    assert OrderTracePoint.from_mapping(point.to_json_object()) == point


def test_order_trace_summary_round_trips_nested_compact_contracts() -> None:
    summary = OrderTraceSummary(
        hypothesis_key="engine_2x",
        suspected_source="engine",
        order_family="engine",
        order_label="2x engine",
        total_window_count=128,
        eligible_window_count=96,
        matched_window_count=52,
        support_ratio=52 / 96,
        reference_coverage_ratio=96 / 128,
        longest_contiguous_support_window_count=12,
        contiguous_support_ratio=12 / 96,
        support_intervals=(
            OrderTraceSupportInterval(
                interval_index=0,
                start_window_index=8,
                end_window_index=19,
                matched_window_count=12,
                support_ratio=1.0,
                start_t_s=4.0,
                end_t_s=10.0,
                phase="cruise",
                load_state="pulling",
                speed_band="70-90 km/h",
                mean_relative_error=0.03,
            ),
        ),
        phase_support=(
            OrderTracePhaseSupport(
                phase="cruise",
                eligible_window_count=48,
                matched_window_count=30,
                support_ratio=30 / 48,
            ),
        ),
        harmonic_summaries=(
            OrderHarmonicEvidenceSummary(
                harmonic=2,
                order_label="2x engine",
                eligible_window_count=96,
                matched_window_count=52,
                support_ratio=52 / 96,
                reference_coverage_ratio=96 / 128,
                contiguous_support_ratio=12 / 96,
                lock_score=0.71,
                mean_relative_error=0.04,
                relative_error_stddev=0.01,
                drift_score=0.87,
                peak_intensity_db=19.7,
                mean_vibration_strength_db=12.4,
            ),
        ),
        stable_frequency_min_hz=24.5,
        stable_frequency_max_hz=27.0,
        exemplar_interval_index=0,
        dominant_phase="cruise",
        dominant_speed_band="70-90 km/h",
        strongest_location="Front Right",
        mean_relative_error=0.04,
        relative_error_stddev=0.01,
        drift_score=0.87,
        lock_score=0.71,
        peak_intensity_db=19.7,
        mean_vibration_strength_db=12.4,
        ref_sources=("obd2",),
    )

    assert OrderTraceSummary.from_mapping(summary.to_json_object()) == summary


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exemplar_interval_index", 2.5),
        ("dominant_phase", 7),
        ("mean_relative_error", "bad"),
    ],
)
def test_order_trace_summary_drops_invalid_optional_values(field: str, value: object) -> None:
    payload = OrderTraceSummary(
        hypothesis_key="engine_2x",
        suspected_source="engine",
        order_family="engine",
        order_label="2x engine",
        total_window_count=128,
        eligible_window_count=96,
        matched_window_count=52,
        support_ratio=52 / 96,
        reference_coverage_ratio=96 / 128,
        longest_contiguous_support_window_count=12,
        contiguous_support_ratio=12 / 96,
    ).to_json_object()
    payload[field] = value

    restored = OrderTraceSummary.from_mapping(payload)

    assert getattr(restored, field) is None


def test_order_trace_summary_skips_non_mapping_nested_rows() -> None:
    payload = OrderTraceSummary(
        hypothesis_key="engine_2x",
        suspected_source="engine",
        order_family="engine",
        order_label="2x engine",
        total_window_count=8,
        eligible_window_count=6,
        matched_window_count=3,
        support_ratio=0.5,
        reference_coverage_ratio=0.75,
        longest_contiguous_support_window_count=2,
        contiguous_support_ratio=2 / 6,
    ).to_json_object()
    payload["support_intervals"] = [
        {
            "interval_index": 0,
            "start_window_index": 1,
            "end_window_index": 2,
            "matched_window_count": 2,
            "support_ratio": 1.0,
        },
        "skip-me",
    ]
    payload["phase_support"] = [
        {
            "phase": "cruise",
            "eligible_window_count": 4,
            "matched_window_count": 2,
            "support_ratio": 0.5,
        },
        7,
    ]
    payload["harmonic_summaries"] = [
        {
            "harmonic": 2,
            "order_label": "2x engine",
            "eligible_window_count": 6,
            "matched_window_count": 3,
            "support_ratio": 0.5,
            "reference_coverage_ratio": 0.75,
            "contiguous_support_ratio": 2 / 6,
            "lock_score": 0.6,
            "drift_score": 0.4,
        },
        [],
    ]

    restored = OrderTraceSummary.from_mapping(payload)

    assert [interval.interval_index for interval in restored.support_intervals] == [0]
    assert [row.phase for row in restored.phase_support] == ["cruise"]
    assert [summary.harmonic for summary in restored.harmonic_summaries] == [2]


def test_history_order_trace_response_contracts_expose_named_summary_fields() -> None:
    assert set(OrderTraceSupportIntervalResponse.__annotations__) == {
        "interval_index",
        "start_window_index",
        "end_window_index",
        "matched_window_count",
        "support_ratio",
        "start_t_s",
        "end_t_s",
        "phase",
        "load_state",
        "speed_band",
        "mean_relative_error",
    }
    assert set(OrderTracePhaseSupportResponse.__annotations__) == {
        "phase",
        "eligible_window_count",
        "matched_window_count",
        "support_ratio",
    }
    assert set(OrderHarmonicEvidenceSummaryResponse.__annotations__) == {
        "harmonic",
        "order_label",
        "eligible_window_count",
        "matched_window_count",
        "support_ratio",
        "reference_coverage_ratio",
        "contiguous_support_ratio",
        "lock_score",
        "mean_relative_error",
        "relative_error_stddev",
        "drift_score",
        "peak_intensity_db",
        "mean_vibration_strength_db",
    }
    assert set(OrderTraceSummaryResponse.__annotations__) == {
        "hypothesis_key",
        "suspected_source",
        "order_family",
        "order_label",
        "total_window_count",
        "eligible_window_count",
        "matched_window_count",
        "support_ratio",
        "reference_coverage_ratio",
        "longest_contiguous_support_window_count",
        "contiguous_support_ratio",
        "support_intervals",
        "phase_support",
        "harmonic_summaries",
        "stable_frequency_min_hz",
        "stable_frequency_max_hz",
        "exemplar_interval_index",
        "dominant_phase",
        "dominant_speed_band",
        "strongest_location",
        "mean_relative_error",
        "relative_error_stddev",
        "drift_score",
        "lock_score",
        "peak_intensity_db",
        "mean_vibration_strength_db",
        "ref_sources",
    }
