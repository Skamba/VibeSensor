from __future__ import annotations

from dataclasses import replace

import pytest
from test_support.findings import make_finding_payload

from vibesensor.adapters.pdf import mapping as pdf_mapping
from vibesensor.adapters.pdf.report_context import (
    ReportMappingContext,
    prepare_report_mapping_context,
)
from vibesensor.shared.boundaries import report_interpretation as shared_report_interpretation
from vibesensor.shared.boundaries import report_renderer_payload as shared_report_renderer_payload
from vibesensor.use_cases.history.report_preparation import (
    PreparedReportInput,
    PreparedReportRendererPayload,
    PrimaryReportFacts,
    ValidatedPreparedReportInput,
    prepare_report_input,
    validate_prepared_report_input,
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


def test_validate_prepared_report_input_rejects_missing_domain_test_run() -> None:
    prepared = replace(_prepared_report_input(), domain_test_run=None)

    with pytest.raises(ValueError, match="domain_test_run"):
        validate_prepared_report_input(prepared)


def test_validate_prepared_report_input_rejects_missing_report_facts() -> None:
    prepared = replace(_prepared_report_input(), report_facts=None)

    with pytest.raises(ValueError, match="report_facts"):
        validate_prepared_report_input(prepared)


def test_validate_prepared_report_input_is_idempotent() -> None:
    prepared = _prepared_report_input()
    validated = validate_prepared_report_input(prepared)
    revalidated = validate_prepared_report_input(validated)

    assert revalidated is validated


def test_validate_prepared_report_input_returns_mapping_ready_handoff() -> None:
    prepared = _prepared_report_input()
    validated = validate_prepared_report_input(prepared)

    assert isinstance(validated, ValidatedPreparedReportInput)
    assert validated.domain_test_run is not None
    assert validated.report_facts is not None
    assert not hasattr(prepared, "mapping_context")
    assert not hasattr(validated, "mapping_context")


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


def test_prepare_report_mapping_context_accepts_validated_input() -> None:
    validated = validate_prepared_report_input(_prepared_report_input())
    context = prepare_report_mapping_context(validated)

    assert context.domain_aggregate is validated.domain_test_run
    assert context.origin is validated.report_facts.origin


def test_prepare_report_mapping_context_rejects_invalid_input() -> None:
    prepared = replace(_prepared_report_input(), domain_test_run=None)

    with pytest.raises(ValueError, match="domain_test_run"):
        prepare_report_mapping_context(prepared)


def test_prepare_report_input_keeps_non_projectable_payload_unprepared() -> None:
    prepared = prepare_report_input(
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

    assert prepared.domain_test_run is None
    assert prepared.report_facts is None
    assert not hasattr(prepared, "mapping_context")


def test_map_summary_fails_before_pdf_mapping_for_invalid_prepared_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = replace(_prepared_report_input(), report_facts=None)

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("map_summary should validate the prepared handoff before mapping")

    monkeypatch.setattr(pdf_mapping, "_build_report_template_data", _explode)

    with pytest.raises(ValueError, match="report_facts"):
        pdf_mapping.map_summary(prepared)


def test_report_preparation_imports_primary_report_facts_from_shared_boundaries() -> None:
    assert PrimaryReportFacts is shared_report_interpretation.PrimaryReportFacts


def test_report_preparation_imports_renderer_payload_from_shared_boundaries() -> None:
    assert (
        PreparedReportRendererPayload
        is shared_report_renderer_payload.PreparedReportRendererPayload
    )
