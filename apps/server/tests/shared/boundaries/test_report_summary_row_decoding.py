from __future__ import annotations

from vibesensor.shared.boundaries.reporting.summary import report_summary_from_mapping
from vibesensor.shared.types.order_trace_contracts import OrderTraceSummary
from vibesensor.shared.types.whole_run_diagnosis_contracts import WholeRunDiagnosisSummary


def test_report_summary_from_mapping_drops_rows_missing_required_identity_fields() -> None:
    summary = report_summary_from_mapping(
        {
            "whole_run_order_summaries": [
                {
                    "suspected_source": "wheel/tire",
                    "order_family": "wheel",
                    "order_label": "wheel family",
                },
                {
                    "hypothesis_key": "wheel",
                    "suspected_source": "wheel/tire",
                    "order_family": "wheel",
                    "order_label": "wheel family",
                },
            ],
            "whole_run_spatial_summaries": [
                {
                    "candidate_key": "wheel-invalid",
                    "suspected_source": "wheel/tire",
                    "proof_basis": "unsupported",
                },
                {
                    "candidate_key": "wheel-valid",
                    "suspected_source": "wheel/tire",
                    "proof_basis": "whole_run_summary",
                },
            ],
        }
    )

    assert [item.hypothesis_key for item in summary.whole_run_order_summaries] == ["wheel"]
    assert [item.candidate_key for item in summary.whole_run_spatial_summaries] == ["wheel-valid"]


def test_report_summary_from_mapping_keeps_diagnosis_factor_with_non_mapping_details() -> None:
    summary = report_summary_from_mapping(
        {
            "whole_run_diagnosis_summaries": [
                {
                    "diagnosis_key": "wheel_1x",
                    "suspected_source": "wheel/tire",
                    "rank": 1,
                    "data_basis": "summary_only",
                    "support_factors": [
                        {
                            "factor_key": "summary_only",
                            "polarity": "support",
                            "severity": "low",
                            "details": "not-a-mapping",
                        }
                    ],
                }
            ]
        }
    )

    factor = summary.whole_run_diagnosis_summaries[0].support_factors[0]

    assert factor.factor_key == "summary_only"
    assert factor.details.raw_backed_sample_count is None
    assert factor.details.fallback_reason is None


def test_report_summary_from_mapping_decodes_diagnosis_data_quality_summary() -> None:
    summary = report_summary_from_mapping(
        {
            "whole_run_diagnosis_summaries": [
                {
                    "diagnosis_key": "wheel_1x",
                    "suspected_source": "wheel/tire",
                    "rank": 1,
                    "data_basis": "raw_backed",
                    "data_quality_summary": {
                        "usable_window_count": 7,
                        "limited_window_count": 2,
                        "excluded_window_count": 1,
                        "mean_quality_score": 0.81,
                        "speed_context_limited_window_count": 1,
                        "sensor_timing_integrity_window_count": 2,
                        "sensor_mounting_artifact_window_count": 0,
                        "sensor_clipping_window_count": 1,
                        "shock_transient_window_count": 0,
                        "limitation_keys": [
                            "speed_context",
                            "sensor_timing",
                            "bad-value",
                            "speed_context",
                        ],
                    },
                }
            ]
        }
    )

    quality = summary.whole_run_diagnosis_summaries[0].data_quality_summary

    assert quality.usable_window_count == 7
    assert quality.limited_window_count == 2
    assert quality.excluded_window_count == 1
    assert quality.mean_quality_score == 0.81
    assert quality.speed_context_limited_window_count == 1
    assert quality.sensor_timing_integrity_window_count == 2
    assert quality.sensor_clipping_window_count == 1
    assert quality.limitation_keys == ("speed_context", "sensor_timing")


def test_report_summary_from_mapping_decodes_canonical_summary_types() -> None:
    summary = report_summary_from_mapping(
        {
            "whole_run_diagnosis_summaries": [
                {
                    "diagnosis_key": "wheel_1x",
                    "suspected_source": "wheel/tire",
                    "rank": 1,
                    "data_basis": "raw_backed",
                }
            ],
            "whole_run_order_summaries": [
                {
                    "hypothesis_key": "wheel",
                    "suspected_source": "wheel/tire",
                    "order_family": "wheel",
                    "order_label": "wheel family",
                }
            ],
        }
    )

    assert isinstance(summary.whole_run_diagnosis_summaries[0], WholeRunDiagnosisSummary)
    assert isinstance(summary.whole_run_order_summaries[0], OrderTraceSummary)


def test_report_summary_from_mapping_keeps_vehicle_data_factors() -> None:
    summary = report_summary_from_mapping(
        {
            "whole_run_diagnosis_summaries": [
                {
                    "diagnosis_key": "wheel_1x",
                    "suspected_source": "wheel/tire",
                    "rank": 1,
                    "data_basis": "raw_backed",
                    "support_factors": [
                        {
                            "factor_key": "user_confirmed_vehicle_data",
                            "polarity": "support",
                            "severity": "low",
                            "weight": 0.1,
                        },
                        {
                            "factor_key": "raw_backed",
                            "polarity": "support",
                            "severity": "high",
                            "weight": 0.4,
                        },
                    ],
                }
            ]
        }
    )

    factors = summary.whole_run_diagnosis_summaries[0].support_factors
    assert [factor.factor_key for factor in factors] == [
        "user_confirmed_vehicle_data",
        "raw_backed",
    ]
