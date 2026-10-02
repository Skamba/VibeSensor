from __future__ import annotations

import pytest

from vibesensor.summary.order_trace_contracts import (
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


def test_order_trace_point_rejects_unsupported_order_family() -> None:
    payload = OrderTracePoint(
        hypothesis_key="wheel_1x",
        suspected_source="wheel/tire",
        order_family="wheel",
        harmonic=1,
        order_label="1x wheel",
        window_index=42,
        eligible=True,
        matched=True,
    ).to_json_object()
    payload["order_family"] = "axle"

    with pytest.raises(ValueError, match="order_family"):
        OrderTracePoint.from_mapping(payload)


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


def test_order_trace_summary_decodes_legacy_payload_without_quality_counts() -> None:
    """Sidecars written before window-quality accounting still decode with zero counts."""

    legacy_payload = {
        "hypothesis_key": "wheel_1x",
        "suspected_source": "wheel/tire",
        "order_family": "wheel",
        "order_label": "1x wheel",
        "total_window_count": 20,
        "eligible_window_count": 16,
        "matched_window_count": 12,
        "support_ratio": 0.75,
        "reference_coverage_ratio": 0.8,
        "longest_contiguous_support_window_count": 9,
        "contiguous_support_ratio": 0.5625,
        "support_intervals": [],
        "phase_support": [],
        "harmonic_summaries": [],
        "drift_score": 0.1,
        "lock_score": 0.8,
        "ref_sources": ["speed+tire"],
        "retired_field": "ignored",
    }

    restored = OrderTraceSummary.from_mapping(legacy_payload)

    assert restored.usable_window_count == 0
    assert restored.speed_context_limited_window_count == 0
    assert restored.mean_quality_score is None
    assert restored.ref_sources == ("speed+tire",)
    assert "retired_field" not in restored.to_json_object()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exemplar_interval_index", 2.5),
        ("dominant_phase", 7),
        ("mean_relative_error", "bad"),
    ],
)
def test_order_trace_summary_rejects_invalid_optional_values(field: str, value: object) -> None:
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

    with pytest.raises(ValueError, match=field):
        OrderTraceSummary.from_mapping(payload)


def test_order_trace_summary_rejects_non_mapping_nested_rows() -> None:
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

    with pytest.raises(ValueError, match="support_intervals.1"):
        OrderTraceSummary.from_mapping(payload)
