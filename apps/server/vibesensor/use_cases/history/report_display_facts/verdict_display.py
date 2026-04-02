"""Verdict-surface text and state builders for report display facts."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.domain import TestRun
from vibesensor.report_i18n import human_source
from vibesensor.shared.boundaries.report_interpretation import PrimaryReportFacts
from vibesensor.shared.types.history_analysis_contracts import RunSuitabilityCheck
from vibesensor.shared.types.history_analysis_contracts import (
    SummaryWarningResponse as SummaryWarningPayload,
)

from .models import PreparedVerdictDisplay
from .shared import (
    _action_status_text,
    _confidence_pct_text,
    _display_location,
    _first_confidence_reason_clause,
    _first_nonpass_detail,
    _location_confidence_text,
    _presented_location_confidence_key,
    _proof_caveat_text,
    _source_with_confidence,
)

__all__ = ["build_verdict_display"]


def build_verdict_display(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    duration_text: str | None,
    action_status_key: str,
    location_confidence_key: str,
    alternative_source_visible: bool,
    active_locations: Sequence[str],
    coverage_label: str,
    runner_up_corner: str | None,
    proof_caveat: str | None,
    recapture_issues: Sequence[str],
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    lang: str,
    tr: Callable[..., str],
) -> PreparedVerdictDisplay:
    recapture_before_acting = action_status_key == "recapture_before_acting"
    return PreparedVerdictDisplay(
        speed_window_label=str(primary_candidate_facts.primary_speed or "").strip() or None,
        suspected_source=(
            tr("REPORT_INCONCLUSIVE_SOURCE")
            if recapture_before_acting
            else _primary_source_text(primary_candidate_facts, tr=tr)
        ),
        inspect_first=(
            None
            if recapture_before_acting
            else _display_location(primary_candidate_facts.primary_location, tr=tr)
        ),
        action_status=_action_status_text(action_status_key, tr=tr),
        action_status_note=_action_status_note_text(
            aggregate=aggregate,
            primary_candidate_facts=primary_candidate_facts,
            action_status_key=action_status_key,
            location_confidence_key=location_confidence_key,
            alternative_source_visible=alternative_source_visible,
            suitability_checks=suitability_checks,
            warnings=warnings,
            lang=lang,
            tr=tr,
        ),
        reason_sentence=(
            recapture_issues[0]
            if recapture_before_acting and recapture_issues
            else _build_primary_reason_sentence(
                primary_candidate_facts=primary_candidate_facts,
                active_locations=active_locations,
                duration_text=duration_text,
                tr=tr,
            )
        ),
        dominant_corner=_display_location(primary_candidate_facts.primary_location, tr=tr),
        runner_up_corner=runner_up_corner,
        location_confidence=_location_confidence_display_text(
            primary_candidate_facts=primary_candidate_facts,
            action_status_key=action_status_key,
            location_confidence_key=location_confidence_key,
            alternative_source_visible=alternative_source_visible,
            dominance_ratio=primary_candidate_facts.dominance_ratio,
            suitability_checks=suitability_checks,
            warnings=warnings,
            lang=lang,
            tr=tr,
        ),
        coverage_label=coverage_label,
        also_consider=(
            _source_with_confidence(aggregate.effective_top_causes()[1], tr=tr)
            if not recapture_before_acting
            and alternative_source_visible
            and len(aggregate.effective_top_causes()) > 1
            else None
        ),
        proof_caveat=proof_caveat,
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


def _build_primary_reason_sentence(
    *,
    primary_candidate_facts: PrimaryReportFacts,
    active_locations: Sequence[str],
    duration_text: str | None,
    tr: Callable[..., str],
) -> str:
    location = _display_location(primary_candidate_facts.primary_location, tr=tr)
    duration = str(duration_text or "").strip() or tr("UNKNOWN")
    sensor_count = len(active_locations) or primary_candidate_facts.sensor_count
    speed_window = str(primary_candidate_facts.primary_speed or "").strip()
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
    primary_candidate_facts: PrimaryReportFacts,
    action_status_key: str,
    location_confidence_key: str,
    alternative_source_visible: bool,
    dominance_ratio: float | None,
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    lang: str,
    tr: Callable[..., str],
) -> str:
    presented_key = _presented_location_confidence_key(
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
    )
    if action_status_key != "action_ready_caution":
        return _location_confidence_text(presented_key, tr=tr)

    reason = _first_confidence_reason_clause(primary_candidate_facts)
    if reason:
        return reason
    if alternative_source_visible:
        return tr("REPORT_LOCATION_CONFIDENCE_CLOSE_SCORES")
    issue = _first_nonpass_detail(
        suitability_checks=suitability_checks,
        warnings=warnings,
        lang=lang,
        tr=tr,
    )
    if issue:
        return issue.rstrip(".")
    if dominance_ratio is not None:
        return tr("REPORT_LOCATION_CONFIDENCE_RATIO_REASON", ratio=f"{dominance_ratio:.1f}")
    return tr("REPORT_LOCATION_CONFIDENCE_MODERATE_DETAIL")


def _action_status_note_text(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    action_status_key: str,
    location_confidence_key: str,
    alternative_source_visible: bool,
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    lang: str,
    tr: Callable[..., str],
) -> str | None:
    if action_status_key not in {"action_ready_caution", "recapture_before_acting"}:
        return None
    issue = _first_nonpass_detail(
        suitability_checks=suitability_checks,
        warnings=warnings,
        lang=lang,
        tr=tr,
    )
    score_note: str | None = None
    if action_status_key == "action_ready_caution" and alternative_source_visible:
        ranked_candidates = list(aggregate.effective_top_causes()[:2])
        if len(ranked_candidates) > 1:
            score_note = tr(
                "REPORT_ACTION_STATUS_NOTE_GATE_CAUTION_WITH_SCORES",
                primary=human_source(ranked_candidates[0].suspected_source, tr=tr),
                primary_confidence=_confidence_pct_text(ranked_candidates[0]),
                alternative=human_source(ranked_candidates[1].suspected_source, tr=tr),
                alternative_confidence=_confidence_pct_text(ranked_candidates[1]),
            )
        else:
            score_note = tr("REPORT_ACTION_STATUS_NOTE_GATE_CAUTION")
    reason = score_note or _proof_caveat_text(
        primary_candidate_facts=primary_candidate_facts,
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
        return issue
    return issue or reason


def _primary_source_text(
    primary_candidate_facts: PrimaryReportFacts,
    *,
    tr: Callable[..., str],
) -> str:
    if primary_candidate_facts.primary_source is None:
        return tr("UNKNOWN")
    return human_source(primary_candidate_facts.primary_source, tr=tr)
