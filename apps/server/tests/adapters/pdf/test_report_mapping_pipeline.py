from __future__ import annotations

import pytest
from test_support.findings import make_finding_payload

import vibesensor.shared.boundaries.reporting as shared_reporting
from vibesensor.shared.boundaries.persisted_analysis_codec import (
    persisted_analysis_from_json_object,
)
from vibesensor.shared.boundaries.reporting import (
    PreparedReportInput,
    prepare_persisted_report_input,
    prepare_report_input,
)
from vibesensor.shared.boundaries.reporting import document as shared_report_document
from vibesensor.shared.boundaries.reporting import projection as shared_report_projection
from vibesensor.use_cases.history import report_document


def _prepared_report_input() -> PreparedReportInput:
    finding = make_finding_payload(finding_id="F001")
    prepared = prepare_report_input(
        {
            "run_id": "prepared-contract",
            "file_name": "prepared-contract.csv",
            "rows": 32,
            "duration_s": 12.5,
            "sensor_count_used": 2,
            "lang": "en",
            "metadata": {},
            "report_date": "",
            "record_length": "",
            "start_time_utc": "",
            "end_time_utc": "",
            "warnings": [],
            "sensor_locations": [],
            "sensor_locations_connected_throughout": [],
            "sensor_intensity_by_location": [],
            "most_likely_origin": {},
            "run_suitability": [],
            "plots": {},
            "test_plan": [],
            "findings": [finding],
            "top_causes": [finding],
        }
    )
    assert prepared.domain_test_run is not None
    assert prepared.report_facts is not None
    return prepared


def test_prepare_report_input_returns_mapping_ready_boundary_types() -> None:
    prepared = _prepared_report_input()
    composition = report_document.compose_report_document(
        aggregate=prepared.domain_test_run,
        report_facts=prepared.report_facts,
        lang=prepared.language,
    )

    assert isinstance(prepared, shared_reporting.PreparedReportInput)
    assert isinstance(prepared.report_facts, shared_reporting.PreparedReportFacts)
    assert isinstance(
        prepared.report_facts.primary_candidate_facts,
        shared_report_projection.PrimaryReportFacts,
    )
    assert isinstance(composition, report_document.ReportDocumentComposition)
    assert not hasattr(prepared, "renderer_payload")
    assert not hasattr(prepared, "presentation")


def test_prepare_report_input_exposes_canonical_summary_boundary() -> None:
    prepared = _prepared_report_input()

    assert prepared.summary.run_id == "prepared-contract"
    assert prepared.summary.sample_count == 32
    assert prepared.summary.sensor_count == 2


def test_prepare_report_input_rejects_non_projectable_payload() -> None:
    with pytest.raises(ValueError, match="findings or top_causes"):
        prepare_report_input(
            {
                "run_id": "non-projectable",
                "lang": "en",
                "metadata": {},
                "report_date": "",
                "record_length": "",
                "start_time_utc": "",
                "end_time_utc": "",
            }
        )


def test_prepare_persisted_report_input_rejects_non_projectable_payload() -> None:
    analysis = persisted_analysis_from_json_object(
        {
            "run_id": "persisted-non-projectable",
            "lang": "en",
            "metadata": {},
            "report_date": "",
            "record_length": "",
            "start_time_utc": "",
            "end_time_utc": "",
        }
    )

    with pytest.raises(ValueError, match="findings or top_causes"):
        prepare_persisted_report_input(analysis)


def test_report_document_reexports_boundary_types() -> None:
    assert report_document.PreparedReportInput is shared_reporting.PreparedReportInput
    assert report_document.Report is shared_report_document.Report
