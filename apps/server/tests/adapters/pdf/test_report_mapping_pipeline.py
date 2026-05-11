from __future__ import annotations

import pytest
from test_support.findings import make_finding_payload

import vibesensor.shared.boundaries.reporting as shared_reporting
from vibesensor.shared.boundaries.reporting import (
    PreparedReportInput,
    prepare_persisted_report_input,
    prepare_report_input,
)
from vibesensor.shared.boundaries.reporting import document as shared_report_document
from vibesensor.shared.boundaries.reporting import projection as shared_report_projection
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
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
    document = report_document.build_report_document(prepared)

    assert isinstance(prepared, shared_reporting.PreparedReportInput)
    assert isinstance(prepared.report_facts, shared_reporting.PreparedReportFacts)
    assert isinstance(
        prepared.report_facts.decision.primary_candidate,
        shared_report_projection.PrimaryReportFacts,
    )
    assert isinstance(document, shared_report_document.ReportDocument)


def test_prepare_report_input_exposes_canonical_report_facts() -> None:
    prepared = _prepared_report_input()

    assert prepared.report_facts.run.run_id == "prepared-contract"
    assert prepared.report_facts.run.sample_count == 32
    assert prepared.report_facts.run.sensor_count == 2
    assert len(prepared.report_facts.findings.all_findings) == 1
    assert len(prepared.report_facts.findings.top_causes) == 1


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
    analysis = PersistedAnalysis.from_json_object(
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
