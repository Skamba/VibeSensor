"""Resolved report sections and section-assembly orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary
from vibesensor.shared.boundaries.reporting import (
    PreparedReportFacts,
    PreparedReportInput,
    PreparedReportPresentation,
)
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    AppendixDData,
    DataTrustItem,
    FindingPresentation,
    NextStep,
    PatternEvidence,
    PeakRow,
    Report,
    SystemFindingCard,
    VerdictPageData,
)
from vibesensor.shared.report_presentation import display_location
from vibesensor.shared.time_utils import (
    format_timestamp_in_recorded_timezone,
    format_utc_timestamp,
    utc_now_iso,
)
from vibesensor.use_cases.history.report_document._candidate_resolver import (
    PrimaryCandidateContext,
    resolve_primary_report_candidate,
)
from vibesensor.use_cases.history.report_document._card_builder import build_system_cards
from vibesensor.use_cases.history.report_document.peak_table import build_peak_rows
from vibesensor.use_cases.history.report_document.report_sections import (
    build_data_trust,
    build_next_steps,
)

from .measurements import _measurement_rows
from .narrative_summaries import _proof_summary_text
from .pattern_evidence import build_pattern_evidence
from .sections import (
    _build_appendix_c_data,
    _build_appendix_d_data,
    _build_timeline_graph_data,
    _finding_to_presentation,
)

__all__ = ["ResolvedReportDocumentSections", "resolve_report_document_sections"]


@dataclass(frozen=True, slots=True)
class ResolvedReportDocumentSections:
    """Canonical resolved report sections prior to document field mapping."""

    report_date_text: str
    report_start_time_utc: str | None
    report_end_time_utc: str | None
    title: str
    primary: PrimaryCandidateContext
    observed: PatternEvidence
    system_cards: tuple[SystemFindingCard, ...]
    next_steps: tuple[NextStep, ...]
    data_trust: tuple[DataTrustItem, ...]
    pattern_evidence: PatternEvidence
    peak_rows: tuple[PeakRow, ...]
    findings: tuple[FindingPresentation, ...]
    top_causes: tuple[FindingPresentation, ...]
    sensor_intensity: tuple[LocationIntensitySummary, ...]
    hotspot_rows: tuple[LocationHotspotRow, ...]
    verdict_page: VerdictPageData
    appendix_a: AppendixAData
    appendix_b: AppendixBData
    appendix_c: AppendixCData
    appendix_d: AppendixDData


def resolve_report_document_sections(
    prepared: PreparedReportInput,
    *,
    report: Report,
    lang: str,
    tr: Callable[..., str],
) -> ResolvedReportDocumentSections:
    """Resolve report-facing sections before mapping them into ``ReportDocument``."""

    test_run = prepared.domain_test_run
    report_facts = prepared.report_facts
    presentation = prepared.presentation
    report_date_text = _report_date_text(prepared)
    primary = resolve_primary_report_candidate(
        aggregate=test_run,
        facts=report_facts.primary_candidate_facts,
        tr=tr,
        lang=lang,
    )
    observed = _observed_signature(primary)
    observed.strongest_location = display_location(primary.primary_location, tr=tr)
    system_cards = tuple(
        build_system_cards(
            test_run,
            primary,
            lang,
            tr,
        )
    )
    recapture_mode = report_facts.action_status_key == "recapture_before_acting"
    data_trust = tuple(
        build_data_trust(
            suitability_checks=report_facts.suitability_checks,
            warnings=report_facts.warnings,
            lang=lang,
            tr=tr,
        )
    )
    next_steps = _resolve_next_steps(
        primary=primary,
        report_facts=report_facts,
        presentation=presentation,
        recapture_mode=recapture_mode,
        lang=lang,
        tr=tr,
    )
    pattern_evidence = build_pattern_evidence(
        aggregate=test_run,
        origin=report_facts.origin,
        primary=primary,
        lang=lang,
        tr=tr,
    )
    findings = tuple(_finding_to_presentation(finding) for finding in test_run.findings)
    top_causes = tuple(
        _finding_to_presentation(finding) for finding in test_run.effective_top_causes()
    )
    peak_rows = tuple(
        build_peak_rows(
            prepared.summary.peak_table_rows,
            findings=list(findings),
            lang=lang,
            tr=tr,
        )
    )
    measurements = _measurement_rows(
        prepared.summary,
        aggregate=test_run,
        tr=tr,
    )
    proof_summary = _proof_summary_text(
        test_run,
        primary,
        report_facts,
        presentation,
        tr=tr,
    )
    timeline_graph = _build_timeline_graph_data(report_facts, duration_s=report.duration_s)
    sensor_intensity = tuple(report_facts.active_sensor_intensity)
    return ResolvedReportDocumentSections(
        report_date_text=report_date_text,
        report_start_time_utc=format_utc_timestamp(report_facts.start_time_utc),
        report_end_time_utc=format_utc_timestamp(report_facts.end_time_utc),
        title=tr("REPORT_FOOTER_TITLE"),
        primary=primary,
        observed=observed,
        system_cards=system_cards,
        next_steps=next_steps,
        data_trust=data_trust,
        pattern_evidence=pattern_evidence,
        peak_rows=peak_rows,
        findings=findings,
        top_causes=top_causes,
        sensor_intensity=sensor_intensity,
        hotspot_rows=tuple(report_facts.location_hotspot_rows),
        verdict_page=replace(
            presentation.verdict_page,
            proof_summary=proof_summary,
            timeline_graph=timeline_graph,
        ),
        appendix_a=presentation.appendix_a,
        appendix_b=presentation.appendix_b,
        appendix_c=_build_appendix_c_data(
            primary=primary,
            aggregate=test_run,
            measurements=measurements,
            report_facts=report_facts,
            presentation=presentation,
            data_trust=list(data_trust),
            tr=tr,
        ),
        appendix_d=_build_appendix_d_data(
            date_str=report_date_text,
            run_id=report.run_id,
            tire_spec_text=report_facts.tire_spec_text,
            sensor_model=report_facts.sensor_model,
            firmware_version=report_facts.firmware_version,
            sample_count=report_facts.sample_count,
            sample_rate_hz=report_facts.sample_rate_hz,
            tr=tr,
        ),
    )


def _resolve_next_steps(
    *,
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    presentation: PreparedReportPresentation,
    recapture_mode: bool,
    lang: str,
    tr: Callable[..., str],
) -> tuple[NextStep, ...]:
    if recapture_mode:
        return tuple(NextStep(action=action) for action in presentation.appendix_a.capture_changes)
    return tuple(
        build_next_steps(
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
