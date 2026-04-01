"""Prepared report display facts assembled on the history side."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vibesensor.domain import Finding, LocationIntensitySummary, TestRun, VibrationSource
from vibesensor.report_i18n import (
    human_location,
    human_source,
    is_i18n_ref,
    location_candidates,
    resolve_i18n,
)
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.report_interpretation import PrimaryReportFacts
from vibesensor.shared.types.history_analysis_contracts import (
    RunSuitabilityCheck,
)
from vibesensor.shared.types.history_analysis_contracts import (
    SummaryWarningResponse as SummaryWarningPayload,
)
from vibesensor.shared.types.json_types import JsonValue


@dataclass(frozen=True, slots=True)
class PreparedRankedCandidateDisplay:
    source_name: str
    confidence_pct: str | None
    inspect_first: str | None
    path_role: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class PreparedVerdictDisplay:
    speed_window_label: str | None
    suspected_source: str | None
    inspect_first: str | None
    action_status: str
    action_status_note: str | None
    reason_sentence: str | None
    dominant_corner: str | None
    runner_up_corner: str | None
    location_confidence: str
    coverage_label: str
    also_consider: str | None
    proof_caveat: str | None
    proof_panel_title: str
    footer_routes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedAppendixADisplay:
    mode: str
    primary_source: str | None
    alternative_source: str | None
    why_primary_first: str | None
    why_alternative_next: str | None
    next_if_clean: str | None
    ranked_candidates: tuple[PreparedRankedCandidateDisplay, ...]
    capture_issues: tuple[str, ...]
    capture_changes: tuple[str, ...]
    capture_conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedAppendixBSummaryDisplay:
    dominant_corner: str | None
    runner_up_corner: str | None
    dominance_ratio_text: str
    location_confidence: str
    coverage_label: str
    coverage_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedReportDisplayFacts:
    verdict: PreparedVerdictDisplay
    appendix_a: PreparedAppendixADisplay
    appendix_b: PreparedAppendixBSummaryDisplay


def _action_status_text(action_status_key: str, *, tr: Callable[..., str]) -> str:
    keys = {
        "action_ready": "REPORT_ACTION_STATUS_READY",
        "action_ready_caution": "REPORT_ACTION_STATUS_READY_CAUTION",
        "recapture_before_acting": "REPORT_ACTION_STATUS_RECAPTURE",
    }
    return tr(keys.get(action_status_key, "REPORT_ACTION_STATUS_RECAPTURE"))


def _location_confidence_text(location_confidence_key: str, *, tr: Callable[..., str]) -> str:
    keys = {
        "strong": "REPORT_LOCATION_CONFIDENCE_STRONG",
        "limited": "REPORT_LOCATION_CONFIDENCE_LIMITED",
        "mixed": "REPORT_LOCATION_CONFIDENCE_MIXED",
        "weak": "REPORT_LOCATION_CONFIDENCE_WEAK",
    }
    return tr(keys.get(location_confidence_key, "REPORT_LOCATION_CONFIDENCE_MIXED"))


def _presented_location_confidence_key(
    *,
    action_status_key: str,
    location_confidence_key: str,
) -> str:
    if action_status_key == "action_ready_caution" and location_confidence_key != "weak":
        return "limited"
    return location_confidence_key


def _first_confidence_reason_clause(primary_candidate_facts: PrimaryReportFacts) -> str | None:
    finding = primary_candidate_facts.domain_primary
    if finding is None or finding.confidence_assessment is None:
        return None
    for clause in str(finding.confidence_assessment.reason or "").split(";"):
        text = clause.strip().rstrip(".")
        if text:
            return text
    return None


def _display_location(value: object, *, short: bool = True, tr: Callable[..., str]) -> str:
    text = str(value or "").strip()
    if not text:
        return tr("UNKNOWN")
    candidates = location_candidates(text)
    if len(candidates) == 2:
        return tr(
            "REPORT_LOCATION_MIXED_SIGNAL_BETWEEN",
            first_location=human_location(candidates[0], short=short),
            second_location=human_location(candidates[1], short=short),
        )
    if len(candidates) > 2:
        return tr(
            "REPORT_LOCATION_MIXED_SIGNAL_LIST",
            locations=", ".join(human_location(candidate, short=short) for candidate in candidates),
        )
    return human_location(text, short=short)


def _coverage_label(
    *,
    expected_locations: Sequence[str],
    active_locations: Sequence[str],
    missing_locations: Sequence[str],
    partial_locations: Sequence[str],
    tr: Callable[..., str],
) -> str:
    expected = len(expected_locations) or len(active_locations)
    active = len(active_locations)
    if expected <= 0:
        return tr("REPORT_COVERAGE_UNKNOWN")
    if not missing_locations and not partial_locations:
        return tr("REPORT_COVERAGE_ALL_SEEN", active=active, expected=expected)
    if partial_locations:
        return tr("REPORT_COVERAGE_PARTIAL", active=active, expected=expected)
    return tr("REPORT_COVERAGE_ACTIVE_OF_EXPECTED", active=active, expected=expected)


def _coverage_notes(
    *,
    missing_locations: Sequence[str],
    partial_locations: Sequence[str],
    tr: Callable[..., str],
) -> tuple[str, ...]:
    notes: list[str] = []
    if missing_locations:
        notes.append(
            tr(
                "REPORT_COVERAGE_NOTE_MISSING",
                locations=", ".join(
                    _display_location(location, short=False, tr=tr)
                    for location in missing_locations
                ),
            ),
        )
    if partial_locations:
        notes.append(
            tr(
                "REPORT_COVERAGE_NOTE_PARTIAL",
                locations=", ".join(
                    _display_location(location, short=False, tr=tr)
                    for location in partial_locations
                ),
            ),
        )
    if not notes:
        notes.append(tr("REPORT_COVERAGE_NOTE_COMPLETE"))
    return tuple(notes)


def _resolve_check_text(value: object, *, lang: str, tr: Callable[..., str]) -> str:
    if is_i18n_ref(value):
        return resolve_i18n(lang, value, tr=tr)
    if isinstance(value, str) and value.startswith("SUITABILITY_CHECK_"):
        return str(tr(value))
    return str(value or "")


def _resolve_detail_text(value: object, *, lang: str, tr: Callable[..., str]) -> str | None:
    if is_i18n_ref(value) or isinstance(value, list):
        resolved = resolve_i18n(lang, value, tr=tr).strip()
    else:
        resolved = str(value or "").strip()
    return resolved or None


def _first_nonpass_detail(
    *,
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    lang: str,
    tr: Callable[..., str],
) -> str | None:
    for check in suitability_checks:
        if str(check.get("state") or "").strip().lower() == "pass":
            continue
        detail = _resolve_detail_text(check.get("explanation"), lang=lang, tr=tr)
        if detail:
            return detail
        label = _resolve_check_text(check.get("check_key") or check.get("check"), lang=lang, tr=tr)
        if label:
            return label
    for warning in warnings:
        detail = _resolve_detail_text(
            warning.get("detail") or warning.get("message"),
            lang=lang,
            tr=tr,
        )
        if detail:
            return detail
        title = _resolve_detail_text(warning.get("title"), lang=lang, tr=tr)
        if title:
            return title
    return None


def _nonpass_detail_lines(
    *,
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    lang: str,
    tr: Callable[..., str],
) -> tuple[str, ...]:
    lines: list[str] = []
    for check in suitability_checks:
        if str(check.get("state") or "").strip().lower() == "pass":
            continue
        detail = _resolve_detail_text(check.get("explanation"), lang=lang, tr=tr)
        label = _resolve_check_text(check.get("check_key") or check.get("check"), lang=lang, tr=tr)
        text = detail or label
        if text:
            lines.append(text)
    for warning in warnings:
        detail = _resolve_detail_text(
            warning.get("detail") or warning.get("message"),
            lang=lang,
            tr=tr,
        )
        title = _resolve_detail_text(warning.get("title"), lang=lang, tr=tr)
        warning_text: str | None = detail or title
        if warning_text:
            lines.append(warning_text)
    return tuple(lines)


def _confidence_pct_text(finding: Finding) -> str:
    if finding.confidence_assessment is not None:
        return finding.confidence_assessment.pct_text
    return finding.confidence_pct_text


def _source_with_confidence(finding: Finding, *, tr: Callable[..., str]) -> str:
    return tr(
        "REPORT_SOURCE_WITH_CONFIDENCE",
        source=human_source(finding.suspected_source, tr=tr),
        confidence=_confidence_pct_text(finding),
    )


def _runner_up_corner(
    active_sensor_intensity: Sequence[LocationIntensitySummary],
    *,
    tr: Callable[..., str],
) -> str | None:
    ranked_rows = sorted(
        active_sensor_intensity,
        key=lambda row: (
            row.p95_intensity_db if row.p95_intensity_db is not None else float("-inf"),
            row.mean_intensity_db if row.mean_intensity_db is not None else float("-inf"),
        ),
        reverse=True,
    )
    if len(ranked_rows) < 2:
        return None
    return _display_location(ranked_rows[1].location, tr=tr)


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


def _proof_caveat_text(
    *,
    primary_candidate_facts: PrimaryReportFacts,
    action_status_key: str,
    location_confidence_key: str,
    tr: Callable[..., str],
) -> str | None:
    if action_status_key == "action_ready_caution":
        return None
    reason = (
        _first_confidence_reason_clause(primary_candidate_facts)
        if action_status_key != "action_ready"
        else None
    )
    if reason:
        return reason
    if location_confidence_key == "weak":
        return tr("REPORT_PROOF_CAVEAT_WEAK")
    if location_confidence_key == "mixed":
        return tr("REPORT_PROOF_CAVEAT_MIXED")
    return None


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


def _uses_shared_overlap_wording(
    primary_finding: Finding,
    alternative_finding: Finding,
    *,
    tr: Callable[..., str],
) -> bool:
    sources = {
        primary_finding.source_normalized,
        alternative_finding.source_normalized,
    }
    if sources != {VibrationSource.WHEEL_TIRE, VibrationSource.DRIVELINE}:
        return False
    primary_location = str(primary_finding.strongest_location or "").strip()
    alternative_location = str(alternative_finding.strongest_location or "").strip()
    if not primary_location or not alternative_location:
        return False
    return (
        _display_location(primary_location, short=False, tr=tr).strip().lower()
        == _display_location(alternative_location, short=False, tr=tr).strip().lower()
    )


def _has_source_overlap(aggregate: TestRun, *, tr: Callable[..., str]) -> bool:
    ranked = list(aggregate.effective_top_causes()[:2])
    if len(ranked) < 2:
        return False
    return _uses_shared_overlap_wording(ranked[0], ranked[1], tr=tr)


def _is_transient_primary(primary_candidate_facts: PrimaryReportFacts) -> bool:
    finding = primary_candidate_facts.domain_primary
    if finding is None:
        return False
    source = str(finding.suspected_source or "").strip().lower()
    classification = str(finding.peak_classification or "").strip().lower()
    return source == "transient_impact" or classification == "transient"


def _check_state(
    suitability_checks: Sequence[RunSuitabilityCheck],
    check_key: str,
) -> str:
    target = check_key.strip().upper()
    for check in suitability_checks:
        key = str(check.get("check_key") or "").strip().upper()
        if key == target:
            return str(check.get("state") or "").strip().lower()
    return ""


def _has_warning_code(warnings: Sequence[SummaryWarningPayload], code: str) -> bool:
    target = code.strip().lower()
    return any(str(warning.get("code") or "").strip().lower() == target for warning in warnings)


def _append_unique_line(lines: list[str], text: object) -> None:
    value = str(text or "").strip()
    if not value:
        return
    normalized = value.rstrip(".").casefold()
    if any(existing.rstrip(".").casefold() == normalized for existing in lines):
        return
    lines.append(value)


def _candidate_signal_text(finding: Finding, *, tr: Callable[..., str]) -> str:
    if finding.signature_labels:
        return ", ".join(finding.signature_labels[:2])
    if finding.order:
        return finding.order
    if finding.frequency_hz is not None:
        return f"{finding.frequency_hz:.1f} Hz"
    return tr("REPORT_SIGNAL_FALLBACK")


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


def _recapture_issue_lines(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    location_confidence_key: str,
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    lang: str,
    tr: Callable[..., str],
) -> tuple[str, ...]:
    issues: list[str] = []
    if _has_source_overlap(aggregate, tr=tr):
        ranked = list(aggregate.effective_top_causes()[:2])
        if len(ranked) > 1:
            _append_unique_line(
                issues,
                tr(
                    "REPORT_RECAPTURE_ISSUE_SOURCE_OVERLAP",
                    primary=human_source(ranked[0].suspected_source, tr=tr),
                    alternative=human_source(ranked[1].suspected_source, tr=tr),
                ),
            )
    if location_confidence_key == "weak":
        _append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_WEAK_LOCATION"))
    elif location_confidence_key == "mixed":
        _append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_MIXED_LOCATION"))
    if _is_transient_primary(primary_candidate_facts):
        _append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_TRANSIENT"))
    for detail in _nonpass_detail_lines(
        suitability_checks=suitability_checks,
        warnings=warnings,
        lang=lang,
        tr=tr,
    ):
        _append_unique_line(issues, detail)
    if not issues:
        note = _proof_caveat_text(
            primary_candidate_facts=primary_candidate_facts,
            action_status_key="recapture_before_acting",
            location_confidence_key=location_confidence_key,
            tr=tr,
        )
        _append_unique_line(issues, note or tr("REPORT_CAPTURE_ISSUE_GENERIC"))
    return tuple(issues[:4])


def _recapture_actions(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    location_confidence_key: str,
    expected_locations: Sequence[str],
    active_locations: Sequence[str],
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    tr: Callable[..., str],
) -> tuple[str, ...]:
    expected = len(expected_locations) or len(active_locations)
    actions: list[str] = []
    if _has_source_overlap(aggregate, tr=tr):
        _append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_COMPARE_PATHS"))
    if _check_state(suitability_checks, "SUITABILITY_CHECK_SPEED_VARIATION") != "pass":
        _append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_STEADY_HOLD"))
    if _is_transient_primary(primary_candidate_facts):
        _append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_REPEAT_EVENT"))
    if (
        location_confidence_key in {"weak", "mixed"}
        or _check_state(suitability_checks, "SUITABILITY_CHECK_SENSOR_COVERAGE") != "pass"
    ):
        _append_unique_line(actions, tr("TIER_A_CAPTURE_MORE_SENSORS"))
    if (
        primary_candidate_facts.has_reference_gaps
        or _check_state(suitability_checks, "SUITABILITY_CHECK_REFERENCE_COMPLETENESS") != "pass"
        or _has_warning_code(warnings, "reference_context_incomplete")
    ):
        _append_unique_line(actions, tr("TIER_A_CAPTURE_REFERENCE_DATA"))
    if not actions:
        _append_unique_line(actions, tr("TIER_A_CAPTURE_WIDER_SPEED"))
        _append_unique_line(
            actions,
            tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected),
        )
    return tuple(actions[:4])


def _recapture_condition_lines(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    location_confidence_key: str,
    expected_locations: Sequence[str],
    active_locations: Sequence[str],
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    tr: Callable[..., str],
) -> tuple[str, ...]:
    expected = len(expected_locations) or len(active_locations)
    lines: list[str] = []
    if _check_state(suitability_checks, "SUITABILITY_CHECK_SPEED_VARIATION") != "pass":
        _append_unique_line(lines, tr("REPORT_RECAPTURE_CONDITION_STEADY_HOLD"))
    if _has_source_overlap(aggregate, tr=tr):
        _append_unique_line(lines, tr("REPORT_RECAPTURE_CONDITION_COMPARE_PATHS"))
    if _is_transient_primary(primary_candidate_facts):
        _append_unique_line(lines, tr("REPORT_RECAPTURE_CONDITION_REPEAT_EVENT"))
    if (
        location_confidence_key in {"weak", "mixed"}
        or _check_state(suitability_checks, "SUITABILITY_CHECK_SENSOR_COVERAGE") != "pass"
    ):
        _append_unique_line(
            lines,
            tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected),
        )
    if (
        primary_candidate_facts.has_reference_gaps
        or _check_state(suitability_checks, "SUITABILITY_CHECK_REFERENCE_COMPLETENESS") != "pass"
        or _has_warning_code(warnings, "reference_context_incomplete")
    ):
        _append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_REFERENCE"))
    if not lines:
        _append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_STEADY"))
        _append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected))
        _append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_REFERENCE"))
    return tuple(lines[:4])


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
