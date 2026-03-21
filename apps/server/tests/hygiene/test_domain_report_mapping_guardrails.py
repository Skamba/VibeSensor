"""Guardrails for report mapping staying on domain-owned report inputs."""

from __future__ import annotations


def test_report_mapping_context_has_domain_aggregate() -> None:
    """``prepare_report_mapping_context`` must build a domain aggregate."""
    from test_support.findings import make_finding_payload

    from vibesensor.adapters.pdf.mapping import prepare_report_mapping_context
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
    context = prepare_report_mapping_context(summary)
    assert context.domain_aggregate is not None
    assert isinstance(context.domain_aggregate, TestRun)
    assert len(context.domain_aggregate.findings) == 1


def test_build_system_cards_uses_domain_findings() -> None:
    """build_system_cards must read confidence tone from domain, not dict."""
    from vibesensor.adapters.pdf.mapping import (
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

    from vibesensor.adapters.pdf.mapping import map_summary

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
    template = map_summary(summary)
    assert template.run_id == "test-map"


def test_report_mapping_business_functions_use_domain_objects() -> None:
    """Key business-decision functions derive values from the domain aggregate.

    When ``prepare_report_mapping_context`` produces a domain aggregate,
    ``resolve_primary_report_candidate`` must derive primary source,
    strength, and reference-gap status from domain objects — not from
    raw payload dict traversal.
    """
    from test_support.findings import make_finding_payload

    from vibesensor.adapters.pdf.mapping import (
        prepare_report_mapping_context,
        resolve_primary_report_candidate,
    )
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

    context = prepare_report_mapping_context(summary)
    assert context.domain_aggregate is not None
    assert isinstance(context.domain_aggregate, TestRun)

    primary = resolve_primary_report_candidate(
        context=context,
        sensor_intensity=[],
        tr=lambda key, **kw: tr(lang, key, **kw),
        lang=lang,
    )

    # primary_source must be a VibrationSource enum (domain-first derivation)
    assert isinstance(primary.primary_source, VibrationSource), (
        "primary_source must be a VibrationSource enum when domain aggregate is present"
    )


def test_next_steps_domain_path_is_primary() -> None:
    """``build_next_steps_from_summary`` must use domain aggregate only.

    The function must check ``aggregate.recommended_actions`` as its
    sole source for next steps.  No payload fallback loop should exist.
    Prevents regression of T12.
    """
    from tests._paths import SERVER_ROOT

    sections_path = SERVER_ROOT / "vibesensor" / "adapters" / "pdf" / "report_sections.py"
    source = sections_path.read_text()

    # Find the function body
    func_start = source.find("def build_next_steps_from_summary(")
    assert func_start != -1, "build_next_steps_from_summary not found in report_sections.py"

    # Find end of function (next top-level def or end of file)
    next_def = source.find("\ndef ", func_start + 1)
    func_body = source[func_start : next_def if next_def != -1 else len(source)]

    # The domain aggregate if-guard must exist
    domain_guard = func_body.find("if aggregate is not None and aggregate.recommended_actions")
    assert domain_guard != -1, (
        "build_next_steps_from_summary must check aggregate.recommended_actions"
    )
    # No payload fallback loop should remain
    payload_loop = func_body.find("for step in summary_steps")
    assert payload_loop == -1, (
        "build_next_steps_from_summary must not have a payload fallback loop — domain-only"
    )
