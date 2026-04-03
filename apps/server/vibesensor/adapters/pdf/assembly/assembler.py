"""Top-level PDF mapping orchestration."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.adapters.pdf._candidate_resolver import (
    PrimaryCandidateContext,
    resolve_primary_report_candidate,
)
from vibesensor.adapters.pdf._card_builder import build_system_cards
from vibesensor.adapters.pdf.models import (
    NextStep,
    PatternEvidence,
    Report,
    ReportTemplateData,
    build_report_from_summary,
)
from vibesensor.adapters.pdf.peak_table import build_peak_rows
from vibesensor.adapters.pdf.report_sections import build_data_trust, build_next_steps
from vibesensor.adapters.pdf.template_builder import build_template_data
from vibesensor.report_i18n import normalize_lang
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting.contracts import PreparedReportInput
from vibesensor.shared.report_presentation import display_location
from vibesensor.shared.time_utils import (
    format_timestamp_in_recorded_timezone,
    format_utc_timestamp,
    utc_now_iso,
)
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
    lang = str(normalize_lang(prepared.language))
    report = build_report_from_summary(
        prepared.summary,
        language=lang,
    )

    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    return _build_report_template_data(
        prepared,
        report=report,
        lang=lang,
        tr=tr,
    )


def _build_report_template_data(
    prepared: PreparedReportInput,
    *,
    report: Report,
    lang: str,
    tr: Callable[..., str],
) -> ReportTemplateData:
    """Resolve report sections, then delegate field assignment to the builder."""
    test_run = prepared.domain_test_run
    report_facts = prepared.report_facts
    report_date_text = _report_date_text(prepared)
    report_start_time_utc = format_utc_timestamp(report_facts.start_time_utc)
    report_end_time_utc = format_utc_timestamp(report_facts.end_time_utc)
    raw_sensor_intensity = list(report_facts.active_sensor_intensity)

    primary = resolve_primary_report_candidate(
        aggregate=test_run,
        facts=report_facts.primary_candidate_facts,
        tr=tr,
        lang=lang,
    )
    observed = _observed_signature(primary)
    observed.strongest_location = display_location(primary.primary_location, tr=tr)
    system_cards = build_system_cards(
        test_run,
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
        aggregate=test_run,
        origin=report_facts.origin,
        primary=primary,
        lang=lang,
        tr=tr,
    )
    findings = [_finding_to_presentation(f) for f in test_run.findings]
    top_causes = [_finding_to_presentation(f) for f in test_run.effective_top_causes()]
    peak_rows = build_peak_rows(
        prepared.summary.peak_table_rows,
        findings=findings,
        lang=lang,
        tr=tr,
    )
    measurements = _measurement_rows(
        prepared.summary,
        aggregate=test_run,
        tr=tr,
    )
    proof_summary = _proof_summary_text(test_run, primary, report_facts, tr=tr)
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
        aggregate=test_run,
        appendix=report_facts.display.appendix_b,
        sensor_locations=list(report_facts.sensor_locations_active),
        sensor_intensity=raw_sensor_intensity,
        tr=tr,
    )
    appendix_c = _build_appendix_c_data(
        primary=primary,
        aggregate=test_run,
        measurements=measurements,
        report_facts=report_facts,
        data_trust=data_trust,
        tr=tr,
    )
    appendix_d = _build_appendix_d_data(
        date_str=report_date_text,
        run_id=report.run_id,
        tire_spec_text=report_facts.tire_spec_text,
        sensor_model=report_facts.sensor_model,
        firmware_version=report_facts.firmware_version,
        sample_count=report_facts.sample_count,
        sample_rate_hz=report_facts.sample_rate_hz,
        tr=tr,
    )

    return build_template_data(
        prepared=prepared,
        report=report,
        report_date_text=report_date_text,
        report_start_time_utc=report_start_time_utc,
        report_end_time_utc=report_end_time_utc,
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


def _observed_signature(primary: PrimaryCandidateContext) -> PatternEvidence:
    return PatternEvidence(
        primary_system=primary.primary_system,
        strongest_location=primary.primary_location,
        speed_band=primary.primary_speed,
        strength_label=primary.strength_text,
        strength_peak_db=primary.strength_db,
        certainty_label=primary.certainty_label_text,
        certainty_pct=primary.certainty_pct,
        certainty_reason=primary.certainty_reason,
    )


def _report_date_text(prepared: PreparedReportInput) -> str:
    report_date = prepared.summary.report_date or utc_now_iso()
    recorded_offset_seconds = (
        prepared.summary.metadata.recorded_utc_offset_seconds
        if prepared.summary.metadata is not None
        else None
    )
    return format_timestamp_in_recorded_timezone(
        report_date,
        recorded_offset_seconds,
    ) or str(report_date)
