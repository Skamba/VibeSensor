from __future__ import annotations

from vibesensor.summary.analysis_metadata import (
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
                "raw_capture_loss_policy_severity": "fatal",
            }
        }
    )

    assert metadata.present is True
    assert metadata.raw_backed_sample_count == 12
    assert metadata.raw_capture_available is False
    assert metadata.raw_capture_finalize_status == "timeout"
    assert metadata.data_basis == "partial_raw_backed"
    assert metadata.has_fatal_raw_capture_loss is True


def test_report_analysis_metadata_documents_external_stable_keys() -> None:
    assert "raw_capture_mode" in REPORT_ANALYSIS_METADATA_STABLE_KEYS
    assert "raw_backed_sample_count" in REPORT_ANALYSIS_METADATA_STABLE_KEYS
    assert "raw_capture_loss_policy_severity" in REPORT_ANALYSIS_METADATA_STABLE_KEYS
