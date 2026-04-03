"""Top-level PDF mapping orchestration."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.adapters.pdf._candidate_resolver import resolve_primary_report_candidate
from vibesensor.adapters.pdf._card_builder import build_system_cards
from vibesensor.adapters.pdf.models import (
    NextStep,
    Report,
    ReportTemplateData,
    build_report_from_renderer_payload,
)
from vibesensor.adapters.pdf.peak_table import build_peak_rows
from vibesensor.adapters.pdf.report_context import (
    ReportMappingContext,
    observed_signature,
    prepare_report_mapping_context,
)
from vibesensor.adapters.pdf.report_sections import build_data_trust, build_next_steps
from vibesensor.adapters.pdf.template_builder import build_template_data
from vibesensor.domain import TestRun
from vibesensor.report_i18n import normalize_lang
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting.contracts import (
    PreparedReportFacts,
    PreparedReportInput,
)
from vibesensor.shared.report_presentation import display_location
from vibesensor.shared.types.json_types import JsonValue

from .measurements import _measurement_rows
from .narrative_summaries import _proof_summary_text
from .pattern_evidence import build_pattern_evidence
from .sections import (
    _build_appendix_a_data,
    _build_appendix_b_data,
    _build_appendix_c_data,
    _build_appendix_d_data,
    _build_timeline_graph_data,
    _build_verdict_page_data,
    _finding_to_presentation,
)

__all__ = ["map_summary"]


def map_summary(prepared: PreparedReportInput) -> ReportTemplateData:
    """Map a canonical prepared report input into final report template data."""
    context = prepare_report_mapping_context(prepared)
    lang = str(normalize_lang(prepared.language))
    report = build_report_from_renderer_payload(
        prepared.renderer_payload,
        language=lang,
    )

    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    return _build_report_template_data(
        prepared,
        context=context,
        report=report,
        lang=lang,
        tr=tr,
        test_run=prepared.domain_test_run,
        report_facts=prepared.report_facts,
    )


def _build_report_template_data(
    prepared: PreparedReportInput,
    *,
    context: ReportMappingContext,
    report: Report,
    lang: str,
    tr: Callable[..., str],
    test_run: TestRun,
    report_facts: PreparedReportFacts,
) -> ReportTemplateData:
    """Resolve report sections, then delegate field assignment to the builder."""
    raw_sensor_intensity = list(report_facts.active_sensor_intensity)
    primary = resolve_primary_report_candidate(
        context=context,
        facts=report_facts.primary_candidate_facts,
        tr=tr,
        lang=lang,
    )
    observed = observed_signature(primary)
    observed.strongest_location = display_location(primary.primary_location, tr=tr)
    system_cards = build_system_cards(
        context,
        primary,
        lang,
        tr,
    )
    recapture_mode = report_facts.action_status_key == "recapture_before_acting"
    data_trust = build_data_trust(
        suitability_checks=report_facts.suitability_checks,
        warnings=report_facts.warnings,
        lang=lang,
        tr=tr,
    )
    next_steps = (
        [NextStep(action=action) for action in report_facts.display.appendix_a.capture_changes]
        if recapture_mode
        else build_next_steps(
            recommended_actions=report_facts.recommended_actions,
            primary_source=primary.primary_source,
            primary_location=primary.primary_location,
            tier=primary.tier,
            cert_reason=primary.certainty_reason or tr("REPORT_CAPTURE_ISSUE_GENERIC"),
            recapture_mode=recapture_mode,
            lang=lang,
            tr=tr,
        )
    )
    pattern_evidence = build_pattern_evidence(
        context,
        primary,
        lang,
        tr,
    )
    findings = [_finding_to_presentation(f) for f in context.domain_aggregate.findings]
    top_causes = [
        _finding_to_presentation(f) for f in context.domain_aggregate.effective_top_causes()
    ]
    peak_rows = build_peak_rows(
        prepared.renderer_payload.peak_table_rows,
        findings=findings,
        lang=lang,
        tr=tr,
    )
    measurements = _measurement_rows(
        prepared,
        aggregate=context.domain_aggregate,
        tr=tr,
    )
    proof_summary = _proof_summary_text(context.domain_aggregate, primary, report_facts, tr=tr)
    timeline_graph = _build_timeline_graph_data(report_facts, duration_s=report.duration_s)
    verdict_page = _build_verdict_page_data(
        verdict=report_facts.display.verdict,
        proof_summary=proof_summary,
        timeline_graph=timeline_graph,
    )
    appendix_a = _build_appendix_a_data(
        appendix=report_facts.display.appendix_a,
        next_steps=next_steps,
    )
    appendix_b = _build_appendix_b_data(
        aggregate=context.domain_aggregate,
        appendix=report_facts.display.appendix_b,
        sensor_locations=context.sensor_locations_active,
        sensor_intensity=raw_sensor_intensity,
        tr=tr,
    )
    appendix_c = _build_appendix_c_data(
        primary=primary,
        aggregate=context.domain_aggregate,
        measurements=measurements,
        report_facts=report_facts,
        data_trust=data_trust,
        tr=tr,
    )
    appendix_d = _build_appendix_d_data(
        context=context,
        report=report,
        tr=tr,
    )

    return build_template_data(
        context=context,
        report=report,
        primary=primary,
        title=tr("REPORT_FOOTER_TITLE"),
        observed=observed,
        system_cards=system_cards,
        next_steps=next_steps,
        data_trust=data_trust,
        pattern_evidence=pattern_evidence,
        peak_rows=peak_rows,
        findings=findings,
        top_causes=top_causes,
        sensor_intensity=raw_sensor_intensity,
        hotspot_rows=list(report_facts.location_hotspot_rows),
        verdict_page=verdict_page,
        appendix_a=appendix_a,
        appendix_b=appendix_b,
        appendix_c=appendix_c,
        appendix_d=appendix_d,
    )
