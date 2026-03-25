from __future__ import annotations

from dataclasses import replace

import pytest
from test_support.findings import make_finding_payload

from vibesensor.adapters.pdf import mapping as pdf_mapping
from vibesensor.adapters.pdf.report_context import prepare_report_mapping_context
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


def test_validate_prepared_report_input_rejects_missing_mapping_context() -> None:
    prepared = replace(_prepared_report_input(), mapping_context=None)

    with pytest.raises(ValueError, match="mapping_context"):
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
    assert prepared.mapping_context is not None
    assert validated.mapping_context is prepared.mapping_context


def test_prepare_report_mapping_context_returns_precomputed_context() -> None:
    prepared = _prepared_report_input()

    assert prepared.mapping_context is not None
    assert prepare_report_mapping_context(prepared) is prepared.mapping_context


def test_prepare_report_mapping_context_rejects_invalid_input() -> None:
    prepared = replace(_prepared_report_input(), domain_test_run=None)

    with pytest.raises(ValueError, match="domain_test_run"):
        prepare_report_mapping_context(prepared)


def test_map_summary_fails_before_pdf_mapping_for_invalid_prepared_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = replace(_prepared_report_input(), report_facts=None)

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("map_summary should validate the prepared handoff before mapping")

    monkeypatch.setattr(pdf_mapping, "_build_report_template_data", _explode)

    with pytest.raises(ValueError, match="report_facts"):
        pdf_mapping.map_summary(prepared)


def test_map_summary_fails_before_pdf_mapping_for_missing_mapping_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = replace(_prepared_report_input(), mapping_context=None)

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("map_summary should validate the prepared handoff before mapping")

    monkeypatch.setattr(pdf_mapping, "_build_report_template_data", _explode)

    with pytest.raises(ValueError, match="mapping_context"):
        pdf_mapping.map_summary(prepared)


def test_report_preparation_imports_primary_report_facts_from_shared_boundaries() -> None:
    assert PrimaryReportFacts is shared_report_interpretation.PrimaryReportFacts


def test_report_preparation_imports_renderer_payload_from_shared_boundaries() -> None:
    assert (
        PreparedReportRendererPayload
        is shared_report_renderer_payload.PreparedReportRendererPayload
    )


# ---------------------------------------------------------------------------
# Cross-object consistency validation
# ---------------------------------------------------------------------------


def test_validate_rejects_mismatched_domain_aggregate() -> None:
    """mapping_context.domain_aggregate must be the same TestRun as domain_test_run."""
    prepared = _prepared_report_input()
    assert prepared.mapping_context is not None
    # Build a second, distinct TestRun from the same payload
    second_run = prepare_report_input(
        {
            "run_id": "other-run",
            "findings": [make_finding_payload(finding_id="F002")],
            "top_causes": [make_finding_payload(finding_id="F002")],
            "lang": "en",
            "metadata": {},
            "report_date": "",
            "record_length": "",
            "start_time_utc": "",
            "end_time_utc": "",
            "sensor_locations": [],
            "sensor_locations_connected_throughout": [],
            "most_likely_origin": {},
            "run_suitability": [],
        }
    )
    assert second_run.domain_test_run is not None
    # Replace mapping_context with one pointing at a different domain_aggregate
    mismatched_context = replace(
        prepared.mapping_context, domain_aggregate=second_run.domain_test_run
    )
    bad = replace(prepared, mapping_context=mismatched_context)

    with pytest.raises(ValueError, match="domain_aggregate"):
        validate_prepared_report_input(bad)


def test_validate_rejects_mismatched_origin() -> None:
    """mapping_context.origin must match report_facts.origin."""
    from vibesensor.domain import VibrationOrigin, VibrationSource

    prepared = _prepared_report_input()
    assert prepared.mapping_context is not None
    different_origin = VibrationOrigin(
        suspected_source=VibrationSource.ENGINE,
        speed_band="60-80",
        dominance_ratio=0.9,
    )
    mismatched_context = replace(prepared.mapping_context, origin=different_origin)
    bad = replace(prepared, mapping_context=mismatched_context)

    with pytest.raises(ValueError, match="origin"):
        validate_prepared_report_input(bad)


def test_validate_rejects_mismatched_sensor_locations() -> None:
    """mapping_context.sensor_locations_active must match report_facts."""
    prepared = _prepared_report_input()
    assert prepared.mapping_context is not None
    mismatched_context = replace(
        prepared.mapping_context,
        sensor_locations_active=["front_left", "rear_right"],
    )
    bad = replace(prepared, mapping_context=mismatched_context)

    with pytest.raises(ValueError, match="sensor_locations_active"):
        validate_prepared_report_input(bad)


def test_validate_rejects_mismatched_renderer_car_name() -> None:
    """mapping_context.car_name must match renderer_payload.car_name."""
    prepared = _prepared_report_input()
    assert prepared.mapping_context is not None
    mismatched_context = replace(prepared.mapping_context, car_name="Different Car")
    bad = replace(prepared, mapping_context=mismatched_context)

    with pytest.raises(ValueError, match="car_name"):
        validate_prepared_report_input(bad)


def test_validate_rejects_mismatched_renderer_car_type() -> None:
    """mapping_context.car_type must match renderer_payload.car_type."""
    prepared = _prepared_report_input()
    assert prepared.mapping_context is not None
    mismatched_context = replace(prepared.mapping_context, car_type="SUV")
    bad = replace(prepared, mapping_context=mismatched_context)

    with pytest.raises(ValueError, match="car_type"):
        validate_prepared_report_input(bad)
