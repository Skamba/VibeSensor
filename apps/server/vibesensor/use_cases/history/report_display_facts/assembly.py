"""Verdict and appendix assembly for prepared report display facts."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.domain import Finding, LocationIntensitySummary, TestRun
from vibesensor.report_i18n import human_source
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.report_interpretation import PrimaryReportFacts
from vibesensor.shared.types.history_analysis_contracts import RunSuitabilityCheck
from vibesensor.shared.types.history_analysis_contracts import (
    SummaryWarningResponse as SummaryWarningPayload,
)
from vibesensor.shared.types.json_types import JsonValue

from .models import (
    PreparedAppendixADisplay,
    PreparedAppendixBSummaryDisplay,
    PreparedRankedCandidateDisplay,
    PreparedReportDisplayFacts,
    PreparedVerdictDisplay,
)
from .recapture import (
    _recapture_actions,
    _recapture_condition_lines,
    _recapture_issue_lines,
)
from .shared import (
    _action_status_text,
    _candidate_signal_text,
    _confidence_pct_text,
    _coverage_label,
    _coverage_notes,
    _display_location,
    _first_confidence_reason_clause,
    _first_nonpass_detail,
    _location_confidence_text,
    _presented_location_confidence_key,
    _proof_caveat_text,
    _runner_up_corner,
    _source_with_confidence,
    _uses_shared_overlap_wording,
)

__all__ = ["prepare_report_display_facts"]


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


def _candidate_reason_text(
    finding: Finding,
    *,
    tr: Callable[..., str],
    use_shared_overlap_wording: bool = False,
) -> str:
    speed_window = (
        str(
            finding.evidence.focused_speed_band
            if finding.evidence and finding.evidence.focused_speed_band
            else ""
        ).strip()
        or str(finding.strongest_speed_band or "").strip()
    )
    location = _display_location(finding.strongest_location, tr=tr)
    signal = _candidate_signal_text(finding, tr=tr)
    if use_shared_overlap_wording:
        return tr(
            "REPORT_CANDIDATE_REASON_OVERLAP",
            signal=signal,
            speed=speed_window or tr("UNKNOWN"),
        )
    if finding.weak_spatial_separation:
        return tr(
            "REPORT_CANDIDATE_REASON_WEAK",
            signal=signal,
            speed=speed_window or tr("UNKNOWN"),
        )
    return tr(
        "REPORT_CANDIDATE_REASON_STRONG",
        signal=signal,
        location=location,
        speed=speed_window or tr("UNKNOWN"),
    )


def _path_role_text(index: int, *, tr: Callable[..., str]) -> str:
    if index == 0:
        return tr("REPORT_PATH_ROLE_PRIMARY")
    if index == 1:
        return tr("REPORT_PATH_ROLE_ALTERNATIVE")
    return tr("REPORT_PATH_ROLE_LOW_CONFIDENCE")


def _ranked_candidates(
    aggregate: TestRun,
    *,
    tr: Callable[..., str],
) -> tuple[PreparedRankedCandidateDisplay, ...]:
    candidates = list(aggregate.effective_top_causes()[:3])
    rows: list[PreparedRankedCandidateDisplay] = []
    primary_finding = candidates[0] if candidates else None
    for index, finding in enumerate(candidates):
        use_shared_overlap_wording = (
            index > 0
            and primary_finding is not None
            and _uses_shared_overlap_wording(primary_finding, finding, tr=tr)
        )
        rows.append(
            PreparedRankedCandidateDisplay(
                source_name=human_source(finding.suspected_source, tr=tr),
                confidence_pct=_confidence_pct_text(finding),
                inspect_first=_display_location(finding.strongest_location, tr=tr),
                path_role=f"{index + 1}. {_path_role_text(index, tr=tr)}",
                reason=_candidate_reason_text(
                    finding,
                    tr=tr,
                    use_shared_overlap_wording=use_shared_overlap_wording,
                ),
            ),
        )
    return tuple(rows)


def _next_if_primary_clean(
    aggregate: TestRun,
    *,
    tr: Callable[..., str],
) -> str | None:
    candidates = list(aggregate.effective_top_causes()[:2])
    if len(candidates) < 2:
        return None
    alternative = candidates[1]
    use_shared_overlap_wording = _uses_shared_overlap_wording(candidates[0], alternative, tr=tr)
    return _candidate_reason_text(
        alternative,
        tr=tr,
        use_shared_overlap_wording=use_shared_overlap_wording,
    )


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


def prepare_report_display_facts(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    active_sensor_intensity: Sequence[LocationIntensitySummary],
    duration_text: str | None,
    action_status_key: str,
    location_confidence_key: str,
    alternative_source_visible: bool,
    expected_locations: Sequence[str],
    active_locations: Sequence[str],
    missing_locations: Sequence[str],
    partial_locations: Sequence[str],
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    lang: str,
) -> PreparedReportDisplayFacts:
    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    coverage_label = _coverage_label(
        expected_locations=expected_locations,
        active_locations=active_locations,
        missing_locations=missing_locations,
        partial_locations=partial_locations,
        tr=tr,
    )
    coverage_notes = _coverage_notes(
        missing_locations=missing_locations,
        partial_locations=partial_locations,
        tr=tr,
    )
    runner_up_corner = _runner_up_corner(active_sensor_intensity, tr=tr)
    proof_caveat = _proof_caveat_text(
        primary_candidate_facts=primary_candidate_facts,
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
        tr=tr,
    )
    ranked_candidates = _ranked_candidates(aggregate, tr=tr)
    recapture_before_acting = action_status_key == "recapture_before_acting"
    recapture_issues = _recapture_issue_lines(
        aggregate=aggregate,
        primary_candidate_facts=primary_candidate_facts,
        location_confidence_key=location_confidence_key,
        suitability_checks=suitability_checks,
        warnings=warnings,
        lang=lang,
        tr=tr,
    )
    recapture_actions = _recapture_actions(
        aggregate=aggregate,
        primary_candidate_facts=primary_candidate_facts,
        location_confidence_key=location_confidence_key,
        expected_locations=expected_locations,
        active_locations=active_locations,
        suitability_checks=suitability_checks,
        warnings=warnings,
        tr=tr,
    )
    recapture_conditions = _recapture_condition_lines(
        aggregate=aggregate,
        primary_candidate_facts=primary_candidate_facts,
        location_confidence_key=location_confidence_key,
        expected_locations=expected_locations,
        active_locations=active_locations,
        suitability_checks=suitability_checks,
        warnings=warnings,
        tr=tr,
    )
    verdict = PreparedVerdictDisplay(
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
    if recapture_before_acting:
        appendix_a = PreparedAppendixADisplay(
            mode="recapture",
            primary_source=None,
            alternative_source=None,
            why_primary_first=None,
            why_alternative_next=None,
            next_if_clean=None,
            ranked_candidates=(),
            capture_issues=recapture_issues,
            capture_changes=recapture_actions,
            capture_conditions=recapture_conditions,
        )
    else:
        primary_source = (
            tr(
                "REPORT_SOURCE_WITH_CONFIDENCE",
                source=ranked_candidates[0].source_name,
                confidence=ranked_candidates[0].confidence_pct,
            )
            if ranked_candidates and ranked_candidates[0].confidence_pct
            else ranked_candidates[0].source_name
            if ranked_candidates
            else None
        )
        alternative_source = (
            tr(
                "REPORT_SOURCE_WITH_CONFIDENCE",
                source=ranked_candidates[1].source_name,
                confidence=ranked_candidates[1].confidence_pct,
            )
            if alternative_source_visible
            and len(ranked_candidates) > 1
            and ranked_candidates[1].confidence_pct
            else ranked_candidates[1].source_name
            if alternative_source_visible and len(ranked_candidates) > 1
            else None
        )
        appendix_a = PreparedAppendixADisplay(
            mode="workflow",
            primary_source=primary_source,
            alternative_source=alternative_source,
            why_primary_first=ranked_candidates[0].reason if ranked_candidates else None,
            why_alternative_next=(
                ranked_candidates[1].reason
                if alternative_source_visible and len(ranked_candidates) > 1
                else None
            ),
            next_if_clean=_next_if_primary_clean(aggregate, tr=tr),
            ranked_candidates=ranked_candidates,
            capture_issues=(),
            capture_changes=(),
            capture_conditions=(),
        )
    dominance_ratio_text = (
        tr(
            "REPORT_DOMINANCE_RATIO_TEXT",
            ratio=f"{primary_candidate_facts.dominance_ratio:.2f}",
        )
        if primary_candidate_facts.dominance_ratio is not None
        else tr("REPORT_DOMINANCE_RATIO_UNKNOWN")
    )
    appendix_b = PreparedAppendixBSummaryDisplay(
        dominant_corner=_display_location(primary_candidate_facts.primary_location, tr=tr),
        runner_up_corner=runner_up_corner,
        dominance_ratio_text=dominance_ratio_text,
        location_confidence=_location_confidence_text(
            _presented_location_confidence_key(
                action_status_key=action_status_key,
                location_confidence_key=location_confidence_key,
            ),
            tr=tr,
        ),
        coverage_label=coverage_label,
        coverage_notes=coverage_notes,
    )
    return PreparedReportDisplayFacts(
        verdict=verdict,
        appendix_a=appendix_a,
        appendix_b=appendix_b,
    )
