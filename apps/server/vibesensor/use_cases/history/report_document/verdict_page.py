"""Verdict-page and observed-signature builders for report document composition."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from vibesensor.domain import SuitabilityCheck, TestRun
from vibesensor.shared.boundaries.reporting.confidence_facts import ReportConfidenceFacts
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    PatternEvidence,
    VerdictPageData,
)
from vibesensor.shared.report_diagnostics import first_nonpass_detail
from vibesensor.shared.report_presentation import (
    action_status_text,
    display_location,
    human_source,
    location_confidence_text,
    presented_location_confidence_key,
    proof_caveat_text,
)
from vibesensor.shared.run_context_warning import RunContextWarning

from ._candidate_resolver import PrimaryCandidateContext
from .evidence_snapshot import build_evidence_snapshot_rows
from .narrative_summaries import _proof_summary_text
from .section_context import VerdictPageContext
from .timeline_graph import build_timeline_graph_data

if TYPE_CHECKING:
    from vibesensor.shared.boundaries.reporting.summary import ReportWholeRunDiagnosisSummary

    from .document_context import ReportDocumentContext

__all__ = ["build_observed_signature", "build_verdict_page", "build_verdict_page_data"]


def build_observed_signature(
    primary: PrimaryCandidateContext,
    *,
    tr: Callable[..., str],
) -> PatternEvidence:
    return PatternEvidence(
        primary_system=primary.primary_system,
        strongest_location=display_location(primary.primary_location, tr=tr),
        speed_band=primary.primary_speed,
        strength_label=primary.strength_text,
        strength_peak_db=primary.strength_db,
        certainty_label=primary.certainty_label_text,
        certainty_pct=primary.certainty_pct,
        certainty_reason=primary.certainty_reason,
    )


def build_verdict_page_data(
    *,
    aggregate: TestRun,
    primary: PrimaryCandidateContext,
    report_confidence: ReportConfidenceFacts,
    diagnosis_summaries: Sequence[ReportWholeRunDiagnosisSummary],
    duration_text: str | None,
    verdict_context: VerdictPageContext,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> VerdictPageData:
    recapture_before_acting = verdict_context.action_status_key == "recapture_before_acting"
    return VerdictPageData(
        speed_window_label=verdict_context.speed_window_label,
        suspected_source=(
            tr("REPORT_INCONCLUSIVE_SOURCE") if recapture_before_acting else primary.primary_system
        ),
        inspect_first=(
            None if recapture_before_acting else display_location(primary.primary_location, tr=tr)
        ),
        action_status=action_status_text(verdict_context.action_status_key, tr=tr),
        action_status_note=_action_status_note_text(
            aggregate=aggregate,
            primary=primary,
            report_confidence=report_confidence,
            action_status_key=verdict_context.action_status_key,
            location_confidence_key=verdict_context.location_confidence_key,
            alternative_source_visible=verdict_context.alternative_source_visible,
            suitability_checks=suitability_checks,
            warnings=warnings,
            lang=lang,
            tr=tr,
        ),
        reason_sentence=(
            verdict_context.recapture.issues[0]
            if recapture_before_acting and verdict_context.recapture.issues
            else _build_primary_reason_sentence(
                primary=primary,
                active_locations=verdict_context.active_locations,
                duration_text=duration_text,
                tr=tr,
            )
        ),
        dominant_corner=display_location(primary.primary_location, tr=tr),
        runner_up_corner=verdict_context.runner_up_corner,
        dominance_ratio_label=_dominance_ratio_label(primary.dominance_ratio, tr=tr),
        location_confidence=_location_confidence_display_text(
            primary=primary,
            action_status_key=verdict_context.action_status_key,
            location_confidence_key=verdict_context.location_confidence_key,
            alternative_source_visible=verdict_context.alternative_source_visible,
            dominance_ratio=primary.dominance_ratio,
            suitability_checks=suitability_checks,
            warnings=warnings,
            lang=lang,
            tr=tr,
        ),
        coverage_label=verdict_context.coverage_label,
        also_consider=(
            (
                human_source(diagnosis_summaries[1].suspected_source, tr=tr)
                if len(diagnosis_summaries) > 1
                else human_source(aggregate.effective_top_causes()[1].suspected_source, tr=tr)
                if len(aggregate.effective_top_causes()) > 1
                else None
            )
            if not recapture_before_acting and verdict_context.alternative_source_visible
            else None
        ),
        proof_caveat=verdict_context.proof_caveat,
        proof_panel_title=(
            tr("REPORT_PROOF_PANEL_TITLE_INCONCLUSIVE")
            if recapture_before_acting
            else tr("REPORT_PROOF_PANEL_TITLE")
        ),
        footer_routes=(
            (tr("REPORT_ROUTE_APPENDIX_A"),)
            if recapture_before_acting
            else (
                tr("REPORT_ROUTE_APPENDIX_A"),
                tr("REPORT_ROUTE_APPENDIX_B"),
                tr("REPORT_ROUTE_APPENDIX_C"),
                tr("REPORT_ROUTE_APPENDIX_D"),
            )
        ),
    )


def build_verdict_page(
    *,
    context: ReportDocumentContext,
    appendix_a: AppendixAData,
) -> VerdictPageData:
    """Build the fully assembled verdict page from shared document context."""

    verdict_page = build_verdict_page_data(
        aggregate=context.test_run,
        primary=context.primary,
        report_confidence=context.report_facts.confidence,
        diagnosis_summaries=context.report_facts.report_surface_diagnosis_summaries,
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
        reason_sentence=_page1_reason_sentence(verdict_page.reason_sentence, proof_summary),
        proof_summary=proof_summary,
        fallback_path=_page1_fallback_path(verdict_page, appendix_a=appendix_a, tr=context.tr),
        proof_snapshot_rows=build_evidence_snapshot_rows(
            context.report_facts,
            compact=True,
            tr=context.tr,
        ),
        timeline_graph=build_timeline_graph_data(
            context.report_facts,
            duration_s=context.run_facts.duration_s,
        ),
    )


def _page1_reason_sentence(current: str | None, proof_summary: str | None) -> str | None:
    summary = str(proof_summary or "").strip()
    if "No single corner" in summary or "Geen enkele hoek" in summary:
        return summary
    return current


def _dominance_ratio_label(
    dominance_ratio: float | None,
    *,
    tr: Callable[..., str],
) -> str | None:
    if dominance_ratio is None or dominance_ratio <= 0:
        return None
    return tr("REPORT_DOMINANCE_RATIO_VALUE", ratio=f"{dominance_ratio:.1f}")


def _page1_fallback_path(
    verdict_page: VerdictPageData,
    *,
    appendix_a: AppendixAData,
    tr: Callable[..., str],
) -> str | None:
    alternative = str(verdict_page.also_consider or appendix_a.alternative_source or "").strip()
    if not alternative:
        return None
    return tr("REPORT_PAGE1_FALLBACK_ALTERNATIVE", source=alternative)


def _build_primary_reason_sentence(
    *,
    primary: PrimaryCandidateContext,
    active_locations: Sequence[str],
    duration_text: str | None,
    tr: Callable[..., str],
) -> str:
    location = display_location(primary.primary_location, tr=tr)
    duration = str(duration_text or "").strip() or tr("UNKNOWN")
    sensor_count = len(active_locations) or primary.sensor_count
    speed_window = str(primary.primary_speed or "").strip()
    if speed_window and speed_window != tr("UNKNOWN"):
        return tr(
            "REPORT_REASON_RUN_SUMMARY",
            duration=duration,
            location=location,
            speed=speed_window,
            sensors=sensor_count,
        )
    return tr(
        "REPORT_REASON_RUN_SUMMARY_NO_SPEED",
        duration=duration,
        location=location,
        sensors=sensor_count,
    )


def _location_confidence_display_text(
    *,
    primary: PrimaryCandidateContext,
    action_status_key: str,
    location_confidence_key: str,
    alternative_source_visible: bool,
    dominance_ratio: float | None,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> str:
    presented_key = presented_location_confidence_key(
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
    )
    return location_confidence_text(presented_key, tr=tr)


def _action_status_note_text(
    *,
    aggregate: TestRun,
    primary: PrimaryCandidateContext,
    report_confidence: ReportConfidenceFacts,
    action_status_key: str,
    location_confidence_key: str,
    alternative_source_visible: bool,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> str | None:
    if action_status_key not in {"action_ready_caution", "recapture_before_acting"}:
        return None
    issue = first_nonpass_detail(
        suitability_checks=suitability_checks,
        warnings=warnings,
        lang=lang,
        tr=tr,
    )
    if action_status_key == "action_ready_caution" and alternative_source_visible:
        return tr("REPORT_PAGE1_CAVEAT_ALTERNATIVE")
    reason = proof_caveat_text(
        confidence_facts=report_confidence,
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
        tr=tr,
    )
    if issue and reason:
        issue_norm = issue.rstrip(".")
        reason_norm = reason.rstrip(".")
        if reason_norm.casefold() not in issue_norm.casefold():
            return tr(
                "REPORT_ACTION_STATUS_NOTE_COMBINED",
                issue=issue_norm,
                reason=reason_norm,
            )
        return _brief_page1_note(issue, tr=tr)
    return _brief_page1_note(issue or reason, tr=tr)


def _brief_page1_note(note: str | None, *, tr: Callable[..., str]) -> str | None:
    text = str(note or "").strip()
    if not text:
        return None
    first_sentence = text.split(". ", 1)[0].rstrip(".")
    if len(first_sentence) <= 96:
        return first_sentence
    return tr("REPORT_PAGE1_CAVEAT_LIMITED_RUN")
