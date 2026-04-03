from __future__ import annotations

import pytest
from test_support.findings import make_finding_payload

from vibesensor.adapters.pdf import mapping as pdf_mapping
from vibesensor.adapters.pdf.report_context import (
    ReportMappingContext,
    prepare_report_mapping_context,
)
from vibesensor.shared.boundaries import report_prepared_input as shared_report_prepared_input
from vibesensor.shared.boundaries import report_projection as shared_report_projection
from vibesensor.shared.boundaries.persisted_analysis_codec import (
    persisted_analysis_from_json_object,
)
from vibesensor.shared.boundaries.report_prepared_input import PreparedReportInput
from vibesensor.use_cases.history.report_preparation import (
    prepare_persisted_report_input,
    prepare_report_input,
)


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

    assert isinstance(prepared, shared_report_prepared_input.PreparedReportInput)
    assert isinstance(prepared.report_facts, shared_report_prepared_input.PreparedReportFacts)
    assert isinstance(
        prepared.report_facts.primary_candidate_facts,
        shared_report_projection.PrimaryReportFacts,
    )
    assert not hasattr(prepared, "mapping_context")


def test_prepare_report_mapping_context_builds_adapter_owned_context() -> None:
    prepared = _prepared_report_input()
    context = prepare_report_mapping_context(prepared)

    assert isinstance(context, ReportMappingContext)
    assert context.domain_aggregate is prepared.domain_test_run
    assert context.origin is prepared.report_facts.origin
    assert context.origin_location == prepared.report_facts.origin_location
    assert context.sensor_locations_active == list(prepared.report_facts.sensor_locations_active)
    assert context.car_name == prepared.renderer_payload.car_name
    assert context.car_type == prepared.renderer_payload.car_type


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


def test_pdf_mapping_reexports_boundary_prepared_input() -> None:
    assert pdf_mapping.PreparedReportInput is shared_report_prepared_input.PreparedReportInput


def test_prepare_report_context_consumes_prepared_input_directly() -> None:
    prepared = _prepared_report_input()
    context = prepare_report_mapping_context(prepared)

    assert isinstance(context, ReportMappingContext)
