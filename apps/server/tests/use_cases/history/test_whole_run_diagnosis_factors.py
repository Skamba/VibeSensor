from __future__ import annotations

import pytest

from vibesensor.shared.boundaries.reporting.confidence_facts import (
    ReportConfidenceScoringInputs,
    apply_report_confidence_fallback,
    project_whole_run_diagnosis_factors,
    score_report_confidence_inputs,
)


def test_project_whole_run_diagnosis_factors_maps_support_signals_to_stable_rows() -> None:
    support_factors, counter_factors = project_whole_run_diagnosis_factors(
        score_report_confidence_inputs(
            ReportConfidenceScoringInputs(
                base_confidence=1.0,
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
                weak_spatial=False,
                context_traceable=True,
                context_source="whole_run",
                speed_gap_window_count=0,
                rpm_gap_window_count=0,
            )
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
        apply_report_confidence_fallback(
            score_report_confidence_inputs(
                ReportConfidenceScoringInputs(
                    base_confidence=0.12,
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
                    weak_spatial=True,
                    context_traceable=True,
                    context_source="whole_run",
                    speed_gap_window_count=3,
                    rpm_gap_window_count=2,
                )
            ),
            fallback_reason="legacy_summary_only",
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
    assert counter_factors[0]["details"]["fallback_reason"] == "legacy_summary_only"
    assert counter_factors[1]["details"]["speed_gap_window_count"] == 3
    assert counter_factors[5]["details"]["frequency_span_hz"] == pytest.approx(2.2)
    assert counter_factors[10]["details"]["alternative_source"] == "driveshaft"
