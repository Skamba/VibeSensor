"""Compose canonical pre-render report state from prepared report input."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary, TestRun
from vibesensor.report_i18n import normalize_lang
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting import PreparedReportFacts, PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    DataTrustItem,
    NextStep,
    PatternEvidence,
    PeakRow,
    ReportLabelValueRow,
    SystemFindingCard,
    VerdictPageData,
)
from vibesensor.shared.boundaries.reporting.facts import ReportRunFacts
from vibesensor.shared.boundaries.reporting.findings import FindingPresentation
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
from .section_context import ReportSectionContext
from .sections import _build_appendix_c_data, _build_timeline_graph_data, _build_traceability_rows
from .verdict_page import build_observed_signature, build_verdict_page_data
from .workflow_appendix import (
    build_appendix_a_data,
    build_ranked_candidates,
    build_recapture_assessment,
)

__all__ = ["ReportDocumentContext", "compose_report_document_context"]


@dataclass(frozen=True, slots=True)
class _ReportDocumentSections:
    """Document-facing sections composed before final report assembly."""

    section_context: ReportSectionContext
    verdict_page: VerdictPageData
    appendix_a: AppendixAData
    appendix_b: AppendixBData


@dataclass(frozen=True, slots=True)
class ReportDocumentContext:
    """Canonical pre-render report state composed before PDF document mapping."""

    title: str
    run_datetime: str
    run_id: str
    duration_text: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sample_rate_hz: str | None
    tire_spec_text: str | None
    sample_count: int
    sensor_count: int
    sensor_locations: tuple[str, ...]
    sensor_model: str | None
    firmware_version: str | None
    car_name: str | None
    car_type: str | None
    observed: PatternEvidence
    system_cards: tuple[SystemFindingCard, ...]
    next_steps: tuple[NextStep, ...]
    data_trust: tuple[DataTrustItem, ...]
    pattern_evidence: PatternEvidence
    peak_rows: tuple[PeakRow, ...]
    lang: str
    certainty_tier_key: str
    findings: tuple[FindingPresentation, ...]
    top_causes: tuple[FindingPresentation, ...]
    sensor_intensity_by_location: tuple[LocationIntensitySummary, ...]
    location_hotspot_rows: tuple[LocationHotspotRow, ...]
    verdict_page: VerdictPageData
    appendix_a: AppendixAData
    appendix_b: AppendixBData
    appendix_c: AppendixCData
    traceability_rows: tuple[ReportLabelValueRow, ...]


def compose_report_document_context(prepared: PreparedReportInput) -> ReportDocumentContext:
    """Compose the canonical pre-render report context from prepared report input."""

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
        runner_up_corner=sections.section_context.runner_up_corner,
        tr=tr,
    )
    run_datetime = _report_date_text(run_facts)
    findings = tuple(prepared_findings.all_findings)
    verdict_page = replace(
        sections.verdict_page,
        proof_summary=proof_summary,
        timeline_graph=_build_timeline_graph_data(
            report_facts,
            duration_s=run_facts.duration_s,
        ),
    )
    return ReportDocumentContext(
        title=tr("REPORT_FOOTER_TITLE"),
        run_datetime=run_datetime,
        run_id=run_facts.run_id,
        duration_text=run_facts.duration_text,
        start_time_utc=format_utc_timestamp(run_facts.start_time_utc),
        end_time_utc=format_utc_timestamp(run_facts.end_time_utc),
        sample_rate_hz=run_facts.sample_rate_hz,
        tire_spec_text=run_facts.tire_spec_text,
        sample_count=run_facts.sample_count,
        sensor_count=primary.sensor_count,
        sensor_locations=tuple(sensor_facts.active_locations),
        sensor_model=run_facts.sensor_model,
        firmware_version=run_facts.firmware_version,
        car_name=run_facts.car_name,
        car_type=run_facts.car_type,
        observed=build_observed_signature(primary, tr=tr),
        system_cards=tuple(
            build_system_cards(
                test_run,
                primary,
                lang,
                tr,
            )
        ),
        next_steps=_resolve_next_steps(
            primary=primary,
            report_facts=report_facts,
            appendix_a=sections.appendix_a,
            lang=lang,
            tr=tr,
        ),
        data_trust=data_trust,
        pattern_evidence=build_pattern_evidence(
            aggregate=test_run,
            origin=run_facts.origin,
            primary=primary,
            lang=lang,
            tr=tr,
        ),
        peak_rows=tuple(
            build_peak_rows(
                run_facts.peak_table_rows,
                findings=list(findings),
                lang=lang,
                tr=tr,
            )
        ),
        lang=lang,
        certainty_tier_key=primary.tier,
        findings=findings,
        top_causes=tuple(prepared_findings.top_causes),
        sensor_intensity_by_location=tuple(sensor_facts.active_intensity),
        location_hotspot_rows=tuple(sensor_facts.location_hotspot_rows),
        verdict_page=verdict_page,
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
            section_context=sections.section_context,
            data_trust=list(data_trust),
            tr=tr,
        ),
        traceability_rows=tuple(
            _build_traceability_rows(
                date_str=run_datetime,
                run_id=run_facts.run_id,
                tire_spec_text=run_facts.tire_spec_text,
                sensor_model=run_facts.sensor_model,
                firmware_version=run_facts.firmware_version,
                sample_count=run_facts.sample_count,
                sample_rate_hz=run_facts.sample_rate_hz,
                tr=tr,
            )
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
    section_context = _build_report_section_context(
        aggregate=aggregate,
        report_facts=report_facts,
        lang=lang,
        tr=tr,
    )
    return _ReportDocumentSections(
        section_context=section_context,
        verdict_page=build_verdict_page_data(
            aggregate=aggregate,
            primary_candidate_facts=decision_facts.primary_candidate,
            duration_text=run_facts.duration_text,
            section_context=section_context,
            suitability_checks=decision_facts.suitability_checks,
            warnings=decision_facts.warnings,
            lang=lang,
            tr=tr,
        ),
        appendix_a=build_appendix_a_data(
            aggregate=aggregate,
            section_context=section_context,
            tr=tr,
        ),
        appendix_b=build_appendix_b_data(
            aggregate=aggregate,
            primary_candidate_facts=decision_facts.primary_candidate,
            active_sensor_intensity=sensor_facts.active_intensity,
            section_context=section_context,
            tr=tr,
        ),
    )


def _build_report_section_context(
    *,
    aggregate: TestRun,
    report_facts: PreparedReportFacts,
    lang: str,
    tr: Callable[..., str],
) -> ReportSectionContext:
    sensor_facts = report_facts.sensor
    decision_facts = report_facts.decision
    coverage = sensor_facts.coverage
    return ReportSectionContext(
        action_status_key=decision_facts.action_status_key,
        location_confidence_key=decision_facts.location_confidence_key,
        alternative_source_visible=decision_facts.alternative_source_visible,
        active_locations=tuple(coverage.active_locations),
        coverage_label=coverage_label(
            expected_locations=coverage.expected_locations,
            active_locations=coverage.active_locations,
            missing_locations=coverage.missing_locations,
            partial_locations=coverage.partial_locations,
            tr=tr,
        ),
        coverage_notes=tuple(
            coverage_notes(
                missing_locations=coverage.missing_locations,
                partial_locations=coverage.partial_locations,
                tr=tr,
            )
        ),
        proof_caveat=proof_caveat_text(
            primary_candidate_facts=decision_facts.primary_candidate,
            action_status_key=decision_facts.action_status_key,
            location_confidence_key=decision_facts.location_confidence_key,
            tr=tr,
        ),
        runner_up_corner=runner_up_corner(sensor_facts.active_intensity, tr=tr),
        speed_window_label=str(decision_facts.primary_candidate.primary_speed or "").strip()
        or None,
        ranked_candidates=build_ranked_candidates(aggregate, tr=tr),
        recapture=build_recapture_assessment(
            aggregate=aggregate,
            primary_candidate_facts=decision_facts.primary_candidate,
            location_confidence_key=decision_facts.location_confidence_key,
            expected_locations=coverage.expected_locations,
            active_locations=coverage.active_locations,
            suitability_checks=decision_facts.suitability_checks,
            warnings=decision_facts.warnings,
            lang=lang,
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
