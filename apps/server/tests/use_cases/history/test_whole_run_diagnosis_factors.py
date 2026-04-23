from __future__ import annotations

import pytest

from vibesensor.shared.boundaries.reporting.confidence_facts import (
    ReportConfidenceFacts,
    project_whole_run_diagnosis_factors,
)


def test_project_whole_run_diagnosis_factors_maps_support_signals_to_stable_rows() -> None:
    support_factors, counter_factors = project_whole_run_diagnosis_factors(
        ReportConfidenceFacts(
            score_0_to_1=0.9,
            label_key="CONFIDENCE_HIGH",
            pct_text="90%",
            tier="C",
            data_basis="raw_backed",
            raw_backed_sample_count=48,
            supporting_window_count=6,
            supporting_duration_s=3.0,
            stable_frequency_min_hz=13.1,
            stable_frequency_max_hz=13.4,
            supporting_location_count=1,
            top_support_location="front-left",
            top_support_share=0.9,
            mean_relative_error=0.03,
            snr_db=8.5,
            alternative_source=None,
            has_reference_gap=False,
            speed_gap_window_count=0,
            rpm_gap_window_count=0,
            uses_summary_fallback=False,
            fallback_reason=None,
            signal_keys=(
                "raw_backed",
                "repeated_support",
                "sustained_support",
                "stable_frequency",
                "tight_order_lock",
                "localized_support",
                "clean_signal",
            ),
            caveat_keys=(),
        )
    )

    assert counter_factors == ()
    assert [factor["factor_key"] for factor in support_factors] == [
        "raw_backed",
        "repeated_support",
        "sustained_support",
        "stable_frequency",
        "tight_order_lock",
        "localized_support",
        "clean_signal",
    ]
    assert support_factors[0]["weight"] == 0.10
    assert support_factors[0]["details"]["raw_backed_sample_count"] == 48
    assert support_factors[3]["details"]["frequency_span_hz"] == pytest.approx(0.3)
    assert support_factors[5]["details"]["top_support_location"] == "front-left"


def test_project_whole_run_diagnosis_factors_maps_counterevidence_signals_to_stable_rows() -> None:
    support_factors, counter_factors = project_whole_run_diagnosis_factors(
        ReportConfidenceFacts(
            score_0_to_1=0.3,
            label_key="CONFIDENCE_LOW",
            pct_text="30%",
            tier="A",
            data_basis="summary_only",
            raw_backed_sample_count=0,
            supporting_window_count=1,
            supporting_duration_s=0.2,
            stable_frequency_min_hz=12.0,
            stable_frequency_max_hz=14.2,
            supporting_location_count=2,
            top_support_location="front-left",
            top_support_share=0.5,
            mean_relative_error=0.22,
            snr_db=2.5,
            alternative_source="driveshaft",
            has_reference_gap=True,
            speed_gap_window_count=3,
            rpm_gap_window_count=2,
            uses_summary_fallback=True,
            fallback_reason="summary-only legacy confidence",
            signal_keys=(),
            caveat_keys=(
                "summary_only",
                "speed_context_gaps",
                "rpm_context_gaps",
                "sparse_support",
                "brief_support",
                "drifting_frequency",
                "loose_order_lock",
                "mixed_support_locations",
                "noisy_signal",
                "weak_spatial",
                "close_alternative",
                "incomplete_reference",
            ),
        )
    )

    assert support_factors == ()
    assert [factor["factor_key"] for factor in counter_factors] == [
        "summary_only",
        "speed_context_gaps",
        "rpm_context_gaps",
        "sparse_support",
        "brief_support",
        "drifting_frequency",
        "loose_order_lock",
        "mixed_support_locations",
        "noisy_signal",
        "weak_spatial",
        "close_alternative",
        "incomplete_reference",
    ]
    assert counter_factors[0]["details"]["fallback_reason"] == "summary-only legacy confidence"
    assert counter_factors[1]["details"]["speed_gap_window_count"] == 3
    assert counter_factors[5]["details"]["frequency_span_hz"] == pytest.approx(2.2)
    assert counter_factors[10]["details"]["alternative_source"] == "driveshaft"
