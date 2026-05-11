"""Derived shared context for report-document composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.report_i18n import normalize_lang
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting import PreparedReportFacts, PreparedReportInput
from vibesensor.shared.boundaries.reporting.facts import ReportRunFacts
from vibesensor.shared.boundaries.reporting.findings import FindingPresentation
from vibesensor.shared.report_confidence_presentation import proof_caveat_text
from vibesensor.shared.report_presentation import (
    coverage_label,
    coverage_notes,
    display_location,
    display_speed_band,
    runner_up_corner,
)
from vibesensor.shared.time_utils import (
    format_timestamp_in_recorded_timezone,
    utc_now_iso,
)
from vibesensor.shared.types.json_types import JsonValue

from ._candidate_resolver import PrimaryCandidateContext, resolve_primary_report_candidate
from .section_context import (
    AppendixAContext,
    AppendixBContext,
    AppendixCContext,
    VerdictPageContext,
)
from .workflow_appendix import build_ranked_candidates, build_recapture_assessment

if TYPE_CHECKING:
    from vibesensor.domain import TestRun
    from vibesensor.shared.boundaries.reporting.decision_facts import ReportDecisionFacts
    from vibesensor.shared.boundaries.reporting.sensor_facts import ReportSensorFacts

__all__ = ["ReportDocumentContext", "build_report_document_context"]


@dataclass(frozen=True, slots=True)
class ReportDocumentContext:
    """Shared derived context used across report-document builders."""

    lang: str
    tr: Callable[..., str]
    test_run: TestRun
    report_facts: PreparedReportFacts
    run_facts: ReportRunFacts
    sensor_facts: ReportSensorFacts
    decision_facts: ReportDecisionFacts
    findings: tuple[FindingPresentation, ...]
    top_causes: tuple[FindingPresentation, ...]
    primary: PrimaryCandidateContext
    run_datetime: str
    verdict_page_context: VerdictPageContext
    appendix_a_context: AppendixAContext
    appendix_b_context: AppendixBContext
    appendix_c_context: AppendixCContext


def build_report_document_context(prepared: PreparedReportInput) -> ReportDocumentContext:
    """Resolve shared narrative and section context before document assembly."""

    lang = str(normalize_lang(prepared.language))

    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    test_run = prepared.domain_test_run
    report_facts = prepared.report_facts
    run_facts = report_facts.run
    sensor_facts = report_facts.sensor
    decision_facts = report_facts.decision
    prepared_findings = report_facts.findings
    coverage = sensor_facts.coverage
    active_locations = tuple(coverage.active_locations)
    coverage_label_text = coverage_label(
        expected_locations=coverage.expected_locations,
        active_locations=coverage.active_locations,
        missing_locations=coverage.missing_locations,
        partial_locations=coverage.partial_locations,
        tr=tr,
    )
    coverage_notes_items = tuple(
        coverage_notes(
            missing_locations=coverage.missing_locations,
            partial_locations=coverage.partial_locations,
            tr=tr,
        )
    )
    proof_caveat = proof_caveat_text(
        confidence_facts=report_facts.confidence,
        action_status_key=decision_facts.action_status_key,
        location_confidence_key=decision_facts.location_confidence_key,
        tr=tr,
    )
    primary_diagnosis = report_facts.primary_diagnosis
    primary_location_for_display = (
        primary_diagnosis.dominant_location
        if primary_diagnosis is not None and primary_diagnosis.dominant_location
        else decision_facts.primary_candidate.primary_location
    )
    primary_location_text = display_location(primary_location_for_display, tr=tr)
    runner_up_candidate = (
        display_location(primary_diagnosis.runner_up_location, tr=tr)
        if primary_diagnosis is not None and primary_diagnosis.runner_up_location
        else runner_up_corner(sensor_facts.proof_intensity, tr=tr)
    )
    runner_up = (
        runner_up_candidate
        if runner_up_candidate and runner_up_candidate != primary_location_text
        else None
    )
    speed_window_label = (
        display_speed_band(
            str(primary_diagnosis.dominant_speed_band or "").strip()
            if primary_diagnosis is not None
            else str(decision_facts.primary_candidate.primary_speed or "").strip(),
            tr=tr,
        )
        or None
    )
    recapture = build_recapture_assessment(
        aggregate=test_run,
        primary_candidate_facts=decision_facts.primary_candidate,
        confidence_facts=report_facts.confidence,
        location_confidence_key=decision_facts.location_confidence_key,
        expected_locations=coverage.expected_locations,
        active_locations=coverage.active_locations,
        suitability_checks=decision_facts.suitability_checks,
        warnings=decision_facts.warnings,
        lang=lang,
        tr=tr,
    )
    primary = resolve_primary_report_candidate(
        aggregate=test_run,
        facts=decision_facts.primary_candidate,
        confidence_facts=report_facts.confidence,
        diagnosis_summary=primary_diagnosis,
        tr=tr,
        lang=lang,
    )
    return ReportDocumentContext(
        lang=lang,
        tr=tr,
        test_run=test_run,
        report_facts=report_facts,
        run_facts=run_facts,
        sensor_facts=sensor_facts,
        decision_facts=decision_facts,
        findings=prepared_findings.all_findings,
        top_causes=prepared_findings.top_causes,
        primary=primary,
        run_datetime=_report_date_text(run_facts),
        verdict_page_context=VerdictPageContext(
            action_status_key=decision_facts.action_status_key,
            location_confidence_key=decision_facts.location_confidence_key,
            alternative_source_visible=decision_facts.alternative_source_visible,
            active_locations=active_locations,
            coverage_label=coverage_label_text,
            proof_caveat=proof_caveat,
            runner_up_corner=runner_up,
            speed_window_label=speed_window_label,
            recapture=recapture,
        ),
        appendix_a_context=AppendixAContext(
            action_status_key=decision_facts.action_status_key,
            alternative_source_visible=decision_facts.alternative_source_visible,
            ranked_candidates=build_ranked_candidates(
                test_run,
                diagnosis_summaries=report_facts.report_surface_diagnosis_summaries,
                tr=tr,
            ),
            recapture=recapture,
        ),
        appendix_b_context=AppendixBContext(
            action_status_key=decision_facts.action_status_key,
            location_confidence_key=decision_facts.location_confidence_key,
            active_locations=active_locations,
            coverage_label=coverage_label_text,
            coverage_notes=coverage_notes_items,
            runner_up_corner=runner_up,
        ),
        appendix_c_context=AppendixCContext(
            speed_window_label=speed_window_label,
            proof_caveat=proof_caveat,
        ),
    )


def _report_date_text(run_facts: ReportRunFacts) -> str:
    report_date = run_facts.report_date or utc_now_iso()
    return format_timestamp_in_recorded_timezone(
        report_date,
        run_facts.recorded_utc_offset_seconds,
    ) or str(report_date)
