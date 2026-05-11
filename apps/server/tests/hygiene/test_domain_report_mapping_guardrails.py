"""Guardrails for report mapping staying on domain-owned report inputs."""

from __future__ import annotations


def test_prepared_report_input_has_domain_aggregate() -> None:
    """Prepared report inputs must carry the reconstructed domain aggregate."""
    from test_support.findings import make_finding_payload

    from vibesensor.domain import TestRun
    from vibesensor.shared.boundaries.reporting import prepare_report_input

    summary = {
        "run_id": "test-context",
        "findings": [make_finding_payload(finding_id="F001")],
        "top_causes": [make_finding_payload(finding_id="F001")],
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
    prepared = prepare_report_input(summary)
    assert isinstance(prepared.domain_test_run, TestRun)
    assert len(prepared.domain_test_run.findings) == 1


def test_build_system_cards_uses_domain_findings() -> None:
    """build_system_cards must read confidence tone from domain, not dict."""
    from vibesensor.domain import Finding, RunCapture, TestRun
    from vibesensor.report_i18n import tr
    from vibesensor.use_cases.history.report_document import (
        PrimaryCandidateContext,
        build_system_cards,
    )

    lang = "en"
    domain_f = Finding(
        finding_id="F001",
        confidence=0.80,
        suspected_source="wheel/tire",
        strongest_location="Left Front",
    )
    aggregate = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(domain_f,),
        top_causes=(domain_f,),
    )
    primary = PrimaryCandidateContext(
        primary_candidate=domain_f,
        primary_source="wheel/tire",
        primary_system="Wheel/Tire",
        primary_location="Left Front",
        primary_speed="80-90 km/h",
        confidence=0.80,
        sensor_count=2,
        weak_spatial=False,
        has_reference_gaps=False,
        strength_db=12.0,
        strength_text="Moderate (12.0 dB)",
        strength_band_key="moderate",
        certainty_key="high",
        certainty_label_text="High",
        certainty_pct="80%",
        certainty_reason="Consistent order-tracking match",
        tier="C",
    )
    cards = build_system_cards(aggregate, primary, lang, lambda key, **kw: tr(lang, key, **kw))
    assert len(cards) == 1
    assert cards[0].tone != "WRONG_TONE"
    assert cards[0].tone == "success"


def test_build_report_document_produces_report_with_domain_findings() -> None:
    """build_report_document must produce report data using domain-first pipeline."""
    from test_support.findings import make_finding_payload

    from vibesensor.shared.boundaries.reporting import prepare_report_input
    from vibesensor.use_cases.history.report_document import build_report_document

    summary = {
        "run_id": "test-map",
        "file_name": "test.csv",
        "rows": 100,
        "duration_s": 60.0,
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
        "findings": [make_finding_payload(finding_id="F001", confidence=0.80)],
        "top_causes": [make_finding_payload(finding_id="F001", confidence=0.80)],
        "sensor_count_used": 2,
    }
    template = build_report_document(prepare_report_input(summary))
    assert template.run_id == "test-map"


def test_report_mapping_business_functions_use_domain_objects() -> None:
    """Primary-candidate resolution must derive values from the domain aggregate."""
    from test_support.findings import make_finding_payload

    from vibesensor.domain import VibrationSource
    from vibesensor.report_i18n import tr
    from vibesensor.shared.boundaries.reporting import prepare_report_input
    from vibesensor.use_cases.history.report_document import (
        resolve_primary_report_candidate,
    )

    lang = "en"
    finding = make_finding_payload(
        finding_id="F001",
        confidence=0.80,
        suspected_source="wheel_tire",
    )
    summary = {
        "run_id": "guard-biz",
        "findings": [finding],
        "top_causes": [finding],
        "lang": lang,
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

    prepared = prepare_report_input(summary)
    primary = resolve_primary_report_candidate(
        aggregate=prepared.domain_test_run,
        facts=prepared.report_facts.decision.primary_candidate,
        tr=lambda key, **kw: tr(lang, key, **kw),
        lang=lang,
    )

    assert isinstance(primary.primary_source, VibrationSource), (
        "primary_source must be a VibrationSource enum when domain aggregate is present"
    )


def test_prepared_report_input_exposes_canonical_summary_boundary() -> None:
    """Prepared report inputs must expose explicit typed fields instead of raw dict state."""
    from test_support.findings import make_finding_payload

    from vibesensor.shared.boundaries.reporting import prepare_report_input

    prepared = prepare_report_input(
        {
            "run_id": "guardrails",
            "findings": [make_finding_payload(finding_id="F001")],
            "top_causes": [make_finding_payload(finding_id="F001")],
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
            "plots": {},
        }
    )

    assert prepared.report_facts.run.run_id == "guardrails"


def test_next_steps_consume_prepared_actions() -> None:
    """``build_next_steps`` must accept prepared actions, not summary dicts."""
    from inspect import signature

    from vibesensor.use_cases.history.report_document.report_sections import build_next_steps

    params = signature(build_next_steps).parameters
    assert "recommended_actions" in params
    assert "summary" not in params
    assert "aggregate" not in params


def test_reporting_document_boundary_exposes_document_models_only() -> None:
    from vibesensor.shared.boundaries.reporting import FindingPresentation
    from vibesensor.shared.boundaries.reporting import document as document_boundary

    assert not hasattr(document_boundary, "build_report_from_summary")
    assert not hasattr(document_boundary, "FindingPresentation")
    assert FindingPresentation is not None


def test_report_facts_hold_canonical_document_sections_without_builder_shims() -> None:
    from dataclasses import fields

    from vibesensor.shared.boundaries.reporting import (
        PreparedReportFacts,
        PreparedReportInput,
    )
    from vibesensor.shared.boundaries.reporting.document import ReportDocument

    fact_fields = {field.name for field in fields(PreparedReportFacts)}
    assert "verdict_page" not in fact_fields
    assert "appendix_a" not in fact_fields
    assert "appendix_b" not in fact_fields
    assert "presentation" not in fact_fields

    input_fields = {field.name for field in fields(PreparedReportInput)}
    assert "summary" not in input_fields
    assert "presentation" not in input_fields

    document_fields = {field.name for field in fields(ReportDocument)}
    assert {
        "verdict_page",
        "appendix_a",
        "appendix_b",
        "appendix_c",
        "traceability_rows",
    } <= document_fields
