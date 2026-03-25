from __future__ import annotations

from dataclasses import replace

import pytest
from test_support.findings import make_finding_payload

from vibesensor.adapters.pdf import mapping as pdf_mapping
from vibesensor.use_cases.history.report_preparation import (
    PreparedReportInput,
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


def test_validate_prepared_report_input_returns_mapping_ready_handoff() -> None:
    validated = validate_prepared_report_input(_prepared_report_input())

    assert isinstance(validated, ValidatedPreparedReportInput)
    assert validated.domain_test_run is not None
    assert validated.report_facts is not None


def test_map_summary_fails_before_pdf_mapping_for_invalid_prepared_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = replace(_prepared_report_input(), report_facts=None)

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("map_summary should validate the prepared handoff before mapping")

    monkeypatch.setattr(pdf_mapping, "_build_report_template_data", _explode)

    with pytest.raises(ValueError, match="report_facts"):
        pdf_mapping.map_summary(prepared)
