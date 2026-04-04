"""Compose the canonical report document from prepared report input."""

from __future__ import annotations

from dataclasses import replace

from vibesensor.shared.boundaries.reporting import PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    NextStep,
    ReportDocument,
    VerdictPageData,
)
from vibesensor.shared.time_utils import format_utc_timestamp

from ._card_builder import build_system_cards
from .appendix_c import build_appendix_c_data
from .document_context import ReportDocumentContext, build_report_document_context
from .location_appendix import build_appendix_b_data
from .measurements import _measurement_rows
from .narrative_summaries import _proof_summary_text
from .pattern_evidence import build_pattern_evidence
from .peak_table import build_peak_rows
from .report_sections import build_data_trust, build_next_steps
from .timeline_graph import build_timeline_graph_data
from .traceability import build_traceability_rows
from .verdict_page import build_observed_signature, build_verdict_page_data
from .workflow_appendix import build_appendix_a_data

__all__ = ["compose_report_document"]


def compose_report_document(prepared: PreparedReportInput) -> ReportDocument:
    """Compose the canonical report document from prepared report input."""

    context = build_report_document_context(prepared)
    appendix_a = build_appendix_a_data(
        aggregate=context.test_run,
        appendix_context=context.appendix_a_context,
        tr=context.tr,
    )
    appendix_b = build_appendix_b_data(
        aggregate=context.test_run,
        primary_candidate_facts=context.decision_facts.primary_candidate,
        active_sensor_intensity=context.sensor_facts.active_intensity,
        appendix_context=context.appendix_b_context,
        tr=context.tr,
    )
    data_trust = build_data_trust(
        suitability_checks=context.decision_facts.suitability_checks,
        warnings=context.decision_facts.warnings,
        lang=context.lang,
        tr=context.tr,
    )
    verdict_page = _build_verdict_page(context=context)
    return ReportDocument(
        title=context.tr("REPORT_FOOTER_TITLE"),
        run_datetime=context.run_datetime,
        run_id=context.run_facts.run_id,
        duration_text=context.run_facts.duration_text,
        start_time_utc=format_utc_timestamp(context.run_facts.start_time_utc),
        end_time_utc=format_utc_timestamp(context.run_facts.end_time_utc),
        sample_rate_hz=context.run_facts.sample_rate_hz,
        tire_spec_text=context.run_facts.tire_spec_text,
        sample_count=context.run_facts.sample_count,
        sensor_count=context.primary.sensor_count,
        sensor_locations=list(context.sensor_facts.active_locations),
        sensor_model=context.run_facts.sensor_model,
        firmware_version=context.run_facts.firmware_version,
        car_name=context.run_facts.car_name,
        car_type=context.run_facts.car_type,
        observed=build_observed_signature(context.primary, tr=context.tr),
        system_cards=build_system_cards(
            context.test_run,
            context.primary,
            context.lang,
            context.tr,
        ),
        next_steps=list(
            _resolve_next_steps(
                context=context,
                appendix_a=appendix_a,
            )
        ),
        data_trust=data_trust,
        pattern_evidence=build_pattern_evidence(
            aggregate=context.test_run,
            origin=context.run_facts.origin,
            primary=context.primary,
            lang=context.lang,
            tr=context.tr,
        ),
        peak_rows=build_peak_rows(
            context.run_facts.peak_table_rows,
            findings=list(context.findings),
            lang=context.lang,
            tr=context.tr,
        ),
        lang=context.lang,
        certainty_tier_key=context.primary.tier,
        findings=list(context.findings),
        top_causes=list(context.top_causes),
        sensor_intensity_by_location=list(context.sensor_facts.active_intensity),
        location_hotspot_rows=list(context.sensor_facts.location_hotspot_rows),
        verdict_page=verdict_page,
        appendix_a=appendix_a,
        appendix_b=appendix_b,
        appendix_c=build_appendix_c_data(
            primary=context.primary,
            aggregate=context.test_run,
            measurements=_measurement_rows(
                context.run_facts,
                aggregate=context.test_run,
                tr=context.tr,
            ),
            report_facts=context.report_facts,
            appendix_context=context.appendix_c_context,
            data_trust=list(data_trust),
            tr=context.tr,
        ),
        traceability_rows=list(
            build_traceability_rows(
                date_str=context.run_datetime,
                run_id=context.run_facts.run_id,
                tire_spec_text=context.run_facts.tire_spec_text,
                sensor_model=context.run_facts.sensor_model,
                firmware_version=context.run_facts.firmware_version,
                sample_count=context.run_facts.sample_count,
                sample_rate_hz=context.run_facts.sample_rate_hz,
                tr=context.tr,
            )
        ),
    )


def _build_verdict_page(
    *,
    context: ReportDocumentContext,
) -> VerdictPageData:
    verdict_page = build_verdict_page_data(
        aggregate=context.test_run,
        primary_candidate_facts=context.decision_facts.primary_candidate,
        duration_text=context.run_facts.duration_text,
        verdict_context=context.verdict_page_context,
        suitability_checks=context.decision_facts.suitability_checks,
        warnings=context.decision_facts.warnings,
        lang=context.lang,
        tr=context.tr,
    )
    proof_summary = _proof_summary_text(
        context.test_run,
        context.primary,
        context.report_facts,
        runner_up_corner=context.verdict_page_context.runner_up_corner,
        tr=context.tr,
    )
    return replace(
        verdict_page,
        proof_summary=proof_summary,
        timeline_graph=build_timeline_graph_data(
            context.report_facts,
            duration_s=context.run_facts.duration_s,
        ),
    )


def _resolve_next_steps(
    *,
    context: ReportDocumentContext,
    appendix_a: AppendixAData,
) -> tuple[NextStep, ...]:
    recapture_mode = context.decision_facts.action_status_key == "recapture_before_acting"
    if recapture_mode:
        return tuple(NextStep(action=action) for action in appendix_a.capture_changes)
    return tuple(
        build_next_steps(
            recommended_actions=context.decision_facts.recommended_actions,
            primary_source=context.primary.primary_source,
            primary_location=context.primary.primary_location,
            tier=context.primary.tier,
            cert_reason=context.primary.certainty_reason
            or context.tr("REPORT_CAPTURE_ISSUE_GENERIC"),
            recapture_mode=recapture_mode,
            lang=context.lang,
            tr=context.tr,
        )
    )
