"""Canonical report-document composition from prepared report facts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from vibesensor.domain import TestRun
from vibesensor.report_i18n import normalize_lang
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting import PreparedReportFacts, PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixBData,
    NextStep,
    ReportDocument,
    VerdictPageData,
)
from vibesensor.shared.boundaries.reporting.facts import ReportRunFacts
from vibesensor.shared.report_presentation import (
    coverage_label,
    coverage_notes,
    proof_caveat_text,
    runner_up_corner,
)
from vibesensor.shared.time_utils import (
    format_timestamp_in_recorded_timezone,
    format_utc_timestamp,
    utc_now_iso,
)
from vibesensor.shared.types.json_types import JsonValue

from ._candidate_resolver import PrimaryCandidateContext, resolve_primary_report_candidate
from ._card_builder import build_system_cards
from .location_appendix import build_appendix_b_data
from .measurements import _measurement_rows
from .narrative_summaries import _proof_summary_text
from .pattern_evidence import build_pattern_evidence
from .peak_table import build_peak_rows
from .report_sections import build_data_trust, build_next_steps
from .sections import _build_appendix_c_data, _build_timeline_graph_data, _build_traceability_rows
from .verdict_page import build_observed_signature, build_verdict_page_data
from .workflow_appendix import (
    build_appendix_a_data,
    build_ranked_candidates,
)
from .workflow_appendix import (
    recapture_actions as build_recapture_actions,
)
from .workflow_appendix import (
    recapture_condition_lines as build_recapture_condition_lines,
)
from .workflow_appendix import (
    recapture_issue_lines as build_recapture_issue_lines,
)

__all__ = ["build_report_document"]


@dataclass(frozen=True, slots=True)
class _ReportDocumentSections:
    """Document-facing sections composed before final report assembly."""

    verdict_page: VerdictPageData
    appendix_a: AppendixAData
    appendix_b: AppendixBData


def build_report_document(prepared: PreparedReportInput) -> ReportDocument:
    """Compose the canonical report document directly from prepared report input."""

    lang = str(normalize_lang(prepared.language))

    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    test_run = prepared.domain_test_run
    report_facts = prepared.report_facts
    run_facts = report_facts.run
    sensor_facts = report_facts.sensor
    decision_facts = report_facts.decision
    prepared_findings = report_facts.findings
    sections = _compose_report_document_sections(
        aggregate=test_run,
        report_facts=report_facts,
        lang=lang,
    )
    primary = resolve_primary_report_candidate(
        aggregate=test_run,
        facts=decision_facts.primary_candidate,
        tr=tr,
        lang=lang,
    )
    data_trust = tuple(
        build_data_trust(
            suitability_checks=decision_facts.suitability_checks,
            warnings=decision_facts.warnings,
            lang=lang,
            tr=tr,
        )
    )
    proof_summary = _proof_summary_text(
        test_run,
        primary,
        report_facts,
        runner_up_corner=sections.appendix_b.runner_up_corner,
        tr=tr,
    )
    return ReportDocument(
        title=tr("REPORT_FOOTER_TITLE"),
        run_datetime=_report_date_text(run_facts),
        run_id=run_facts.run_id,
        duration_text=run_facts.duration_text,
        start_time_utc=format_utc_timestamp(run_facts.start_time_utc),
        end_time_utc=format_utc_timestamp(run_facts.end_time_utc),
        sample_rate_hz=run_facts.sample_rate_hz,
        tire_spec_text=run_facts.tire_spec_text,
        sample_count=run_facts.sample_count,
        sensor_count=primary.sensor_count,
        sensor_locations=list(sensor_facts.active_locations),
        sensor_model=run_facts.sensor_model,
        firmware_version=run_facts.firmware_version,
        car_name=run_facts.car_name,
        car_type=run_facts.car_type,
        observed=build_observed_signature(primary, tr=tr),
        system_cards=list(
            build_system_cards(
                test_run,
                primary,
                lang,
                tr,
            )
        ),
        next_steps=list(
            _resolve_next_steps(
                primary=primary,
                report_facts=report_facts,
                appendix_a=sections.appendix_a,
                lang=lang,
                tr=tr,
            )
        ),
        data_trust=list(data_trust),
        pattern_evidence=build_pattern_evidence(
            aggregate=test_run,
            origin=run_facts.origin,
            primary=primary,
            lang=lang,
            tr=tr,
        ),
        peak_rows=list(
            build_peak_rows(
                run_facts.peak_table_rows,
                findings=list(prepared_findings.all_findings),
                lang=lang,
                tr=tr,
            )
        ),
        lang=lang,
        certainty_tier_key=primary.tier,
        findings=list(prepared_findings.all_findings),
        top_causes=list(prepared_findings.top_causes),
        sensor_intensity_by_location=list(sensor_facts.active_intensity),
        location_hotspot_rows=list(sensor_facts.location_hotspot_rows),
        verdict_page=replace(
            sections.verdict_page,
            proof_summary=proof_summary,
            timeline_graph=_build_timeline_graph_data(
                report_facts,
                duration_s=run_facts.duration_s,
            ),
        ),
        appendix_a=sections.appendix_a,
        appendix_b=sections.appendix_b,
        appendix_c=_build_appendix_c_data(
            primary=primary,
            aggregate=test_run,
            measurements=_measurement_rows(
                run_facts,
                aggregate=test_run,
                tr=tr,
            ),
            report_facts=report_facts,
            speed_window_label=sections.verdict_page.speed_window_label,
            proof_caveat=sections.verdict_page.proof_caveat,
            data_trust=list(data_trust),
            tr=tr,
        ),
        traceability_rows=_build_traceability_rows(
            date_str=_report_date_text(run_facts),
            run_id=run_facts.run_id,
            tire_spec_text=run_facts.tire_spec_text,
            sensor_model=run_facts.sensor_model,
            firmware_version=run_facts.firmware_version,
            sample_count=run_facts.sample_count,
            sample_rate_hz=run_facts.sample_rate_hz,
            tr=tr,
        ),
    )


def _compose_report_document_sections(
    *,
    aggregate: TestRun,
    report_facts: PreparedReportFacts,
    lang: str,
) -> _ReportDocumentSections:
    """Build presentation-specific report sections from prepared semantic facts."""

    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    run_facts = report_facts.run
    sensor_facts = report_facts.sensor
    decision_facts = report_facts.decision
    coverage = sensor_facts.coverage
    resolved_coverage_label = coverage_label(
        expected_locations=coverage.expected_locations,
        active_locations=coverage.active_locations,
        missing_locations=coverage.missing_locations,
        partial_locations=coverage.partial_locations,
        tr=tr,
    )
    resolved_coverage_notes = coverage_notes(
        missing_locations=coverage.missing_locations,
        partial_locations=coverage.partial_locations,
        tr=tr,
    )
    resolved_runner_up_corner = runner_up_corner(
        sensor_facts.active_intensity,
        tr=tr,
    )
    proof_caveat = proof_caveat_text(
        primary_candidate_facts=decision_facts.primary_candidate,
        action_status_key=decision_facts.action_status_key,
        location_confidence_key=decision_facts.location_confidence_key,
        tr=tr,
    )
    ranked_candidates = build_ranked_candidates(aggregate, tr=tr)
    recapture_issues = build_recapture_issue_lines(
        aggregate=aggregate,
        primary_candidate_facts=decision_facts.primary_candidate,
        location_confidence_key=decision_facts.location_confidence_key,
        suitability_checks=decision_facts.suitability_checks,
        warnings=decision_facts.warnings,
        lang=lang,
        tr=tr,
    )
    recapture_actions = build_recapture_actions(
        aggregate=aggregate,
        primary_candidate_facts=decision_facts.primary_candidate,
        location_confidence_key=decision_facts.location_confidence_key,
        expected_locations=coverage.expected_locations,
        active_locations=coverage.active_locations,
        suitability_checks=decision_facts.suitability_checks,
        warnings=decision_facts.warnings,
        tr=tr,
    )
    recapture_conditions = build_recapture_condition_lines(
        aggregate=aggregate,
        primary_candidate_facts=decision_facts.primary_candidate,
        location_confidence_key=decision_facts.location_confidence_key,
        expected_locations=coverage.expected_locations,
        active_locations=coverage.active_locations,
        suitability_checks=decision_facts.suitability_checks,
        warnings=decision_facts.warnings,
        tr=tr,
    )
    return _ReportDocumentSections(
        verdict_page=build_verdict_page_data(
            aggregate=aggregate,
            primary_candidate_facts=decision_facts.primary_candidate,
            duration_text=run_facts.duration_text,
            action_status_key=decision_facts.action_status_key,
            location_confidence_key=decision_facts.location_confidence_key,
            alternative_source_visible=decision_facts.alternative_source_visible,
            active_locations=coverage.active_locations,
            coverage_label=resolved_coverage_label,
            runner_up_corner=resolved_runner_up_corner,
            proof_caveat=proof_caveat,
            recapture_issues=recapture_issues,
            suitability_checks=decision_facts.suitability_checks,
            warnings=decision_facts.warnings,
            lang=lang,
            tr=tr,
        ),
        appendix_a=build_appendix_a_data(
            aggregate=aggregate,
            action_status_key=decision_facts.action_status_key,
            alternative_source_visible=decision_facts.alternative_source_visible,
            ranked_candidates=ranked_candidates,
            recapture_issues=recapture_issues,
            recapture_actions=recapture_actions,
            recapture_conditions=recapture_conditions,
            tr=tr,
        ),
        appendix_b=build_appendix_b_data(
            aggregate=aggregate,
            primary_candidate_facts=decision_facts.primary_candidate,
            active_sensor_intensity=sensor_facts.active_intensity,
            action_status_key=decision_facts.action_status_key,
            location_confidence_key=decision_facts.location_confidence_key,
            active_locations=coverage.active_locations,
            runner_up_corner=resolved_runner_up_corner,
            coverage_label=resolved_coverage_label,
            coverage_notes=resolved_coverage_notes,
            tr=tr,
        ),
    )


def _resolve_next_steps(
    *,
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    appendix_a: AppendixAData,
    lang: str,
    tr: Callable[..., str],
) -> tuple[NextStep, ...]:
    recapture_mode = report_facts.decision.action_status_key == "recapture_before_acting"
    if recapture_mode:
        return tuple(NextStep(action=action) for action in appendix_a.capture_changes)
    return tuple(
        build_next_steps(
            recommended_actions=report_facts.decision.recommended_actions,
            primary_source=primary.primary_source,
            primary_location=primary.primary_location,
            tier=primary.tier,
            cert_reason=primary.certainty_reason or tr("REPORT_CAPTURE_ISSUE_GENERIC"),
            recapture_mode=recapture_mode,
            lang=lang,
            tr=tr,
        )
    )


def _report_date_text(run_facts: ReportRunFacts) -> str:
    report_date = run_facts.report_date or utc_now_iso()
    return format_timestamp_in_recorded_timezone(
        report_date,
        run_facts.recorded_utc_offset_seconds,
    ) or str(report_date)
