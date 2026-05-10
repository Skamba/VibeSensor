from __future__ import annotations

from vibesensor.shared.boundaries.reporting.analysis_metadata import (
    REPORT_ANALYSIS_METADATA_STABLE_KEYS,
    report_analysis_metadata_from_payload,
)


def test_report_analysis_metadata_decodes_stable_persisted_keys() -> None:
    metadata = report_analysis_metadata_from_payload(
        {
            "analysis_metadata": {
                "raw_backed_sample_count": "12",
                "raw_capture_available": False,
                "raw_capture_finalize_status": "timeout",
                "raw_capture_mode": "partial_raw_backed",
                "whole_run_context_available": True,
                "whole_run_context_window_count": 8,
                "whole_run_context_missing_speed_window_count": 2,
                "whole_run_order_family_summaries_available": True,
                "whole_run_order_family_summary_count": 3,
            }
        }
    )

    assert metadata.present is True
    assert metadata.raw_backed_sample_count == 12
    assert metadata.raw_capture_available is False
    assert metadata.raw_capture_finalize_status == "timeout"
    assert metadata.data_basis == "partial_raw_backed"
    assert metadata.whole_run_context_available is True
    assert metadata.whole_run_context.window_count == 8
    assert metadata.whole_run_context.missing_speed_window_count == 2
    assert metadata.whole_run_order_family_summary_count == 3


def test_report_analysis_metadata_documents_external_stable_keys() -> None:
    assert "raw_capture_mode" in REPORT_ANALYSIS_METADATA_STABLE_KEYS
    assert "raw_backed_sample_count" in REPORT_ANALYSIS_METADATA_STABLE_KEYS
    assert "whole_run_context_available" in REPORT_ANALYSIS_METADATA_STABLE_KEYS
    assert "whole_run_order_family_summaries_available" in REPORT_ANALYSIS_METADATA_STABLE_KEYS
