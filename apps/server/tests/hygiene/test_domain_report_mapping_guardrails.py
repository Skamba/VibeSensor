"""Guardrails for report mapping staying on domain-owned report inputs."""

from __future__ import annotations


def test_report_mapping_context_has_domain_aggregate() -> None:
    """``prepare_report_mapping_context`` must consume a prepared domain aggregate."""
    from test_support.findings import make_finding_payload

    from vibesensor.adapters.pdf.assembly import prepare_report_input
    from vibesensor.adapters.pdf.report_context import prepare_report_mapping_context
    from vibesensor.domain import TestRun

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
    assert prepared.domain_test_run is not None
    assert prepared.report_facts is not None
    context = prepare_report_mapping_context(prepared)
    assert context.domain_aggregate is not None
    assert isinstance(context.domain_aggregate, TestRun)
    assert len(context.domain_aggregate.findings) == 1


def test_build_system_cards_uses_domain_findings() -> None:
    """build_system_cards must read confidence tone from domain, not dict."""
    from vibesensor.adapters.pdf.assembly import (
        PrimaryCandidateContext,
        ReportMappingContext,
        build_system_cards,
    )
    from vibesensor.domain import Finding, RunCapture, TestRun
    from vibesensor.report_i18n import tr

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
    # Build a context with the aggregate (payloads no longer stored on context)
    context = ReportMappingContext(
        car_name=None,
        car_type=None,
        date_str="",
        origin={},
        origin_location="",
        sensor_locations_active=[],
        duration_text=None,
        start_time_utc=None,
        end_time_utc=None,
        sample_rate_hz=None,
        tire_spec_text=None,
        sample_count=0,
        sensor_model=None,
        firmware_version=None,
        domain_aggregate=aggregate,
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
    cards = build_system_cards(context, primary, lang, lambda key, **kw: tr(lang, key, **kw))
    assert len(cards) == 1
    # The tone should come from domain Finding, not the payload's "WRONG_TONE"
    assert cards[0].tone != "WRONG_TONE"
    assert cards[0].tone == "success"  # HIGH confidence → success


def test_map_summary_produces_report_with_domain_findings() -> None:
    """map_summary must produce report data using domain-first pipeline."""
    from test_support.findings import make_finding_payload

    from vibesensor.adapters.pdf.assembly import map_summary, prepare_report_input

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
    template = map_summary(prepare_report_input(summary))
    assert template.run_id == "test-map"


def test_report_mapping_business_functions_use_domain_objects() -> None:
    """Key business-decision functions derive values from the domain aggregate.

    When ``prepare_report_mapping_context`` produces a domain aggregate,
    ``resolve_primary_report_candidate`` must derive primary source,
    strength, and reference-gap status from domain objects — not from
    raw payload dict traversal.
    """
    from test_support.findings import make_finding_payload

    from vibesensor.adapters.pdf.assembly import (
        prepare_report_input,
        resolve_primary_report_candidate,
    )
    from vibesensor.adapters.pdf.report_context import prepare_report_mapping_context
    from vibesensor.domain import TestRun, VibrationSource
    from vibesensor.report_i18n import tr

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
    assert prepared.domain_test_run is not None
    assert prepared.report_facts is not None
    context = prepare_report_mapping_context(prepared)
    assert context.domain_aggregate is not None
    assert isinstance(context.domain_aggregate, TestRun)

    primary = resolve_primary_report_candidate(
        context=context,
        facts=prepared.report_facts.primary_candidate_facts,
        tr=lambda key, **kw: tr(lang, key, **kw),
        lang=lang,
    )

    # primary_source must be a VibrationSource enum (domain-first derivation)
    assert isinstance(primary.primary_source, VibrationSource), (
        "primary_source must be a VibrationSource enum when domain aggregate is present"
    )


def test_prepared_report_input_no_longer_exposes_summary_payload() -> None:
    """Prepared report inputs must expose explicit fields instead of a raw summary dict."""
    from test_support.findings import make_finding_payload

    from vibesensor.adapters.pdf.assembly import prepare_report_input

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

    assert not hasattr(prepared, "analysis_summary")
    assert prepared.renderer_payload.run_id == "guardrails"


def test_next_steps_consume_prepared_actions() -> None:
    """``build_next_steps`` must accept prepared actions, not summary dicts."""
    from inspect import signature

    from vibesensor.adapters.pdf.report_sections import build_next_steps

    params = signature(build_next_steps).parameters
    assert "recommended_actions" in params
    assert "summary" not in params
    assert "aggregate" not in params


def test_mapping_module_no_longer_reexports_raw_summary_report_builder() -> None:
    import vibesensor.adapters.pdf.assembly as mapping

    assert not hasattr(mapping, "build_report_from_summary")


def test_mapping_section_builders_consume_prepared_display_facts() -> None:
    from inspect import signature

    import vibesensor.adapters.pdf.assembly as mapping

    verdict_params = signature(mapping._build_verdict_page_data).parameters
    assert "verdict" in verdict_params
    assert "aggregate" not in verdict_params
    assert "primary" not in verdict_params
    assert "report_facts" not in verdict_params

    appendix_a_params = signature(mapping._build_appendix_a_data).parameters
    assert "appendix" in appendix_a_params
    assert "report_facts" not in appendix_a_params

    appendix_b_params = signature(mapping._build_appendix_b_data).parameters
    assert "appendix" in appendix_b_params
    assert "report_facts" not in appendix_b_params
