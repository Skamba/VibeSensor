from __future__ import annotations

from vibesensor.shared.boundaries.reporting.summary import report_summary_from_mapping


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
