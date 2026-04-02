"""Shared report-display text and candidate helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.domain import Finding, LocationIntensitySummary, TestRun, VibrationSource
from vibesensor.report_i18n import (
    human_location,
    human_source,
    is_i18n_ref,
    location_candidates,
    resolve_i18n,
)
from vibesensor.shared.boundaries.report_interpretation import PrimaryReportFacts
from vibesensor.shared.types.history_analysis_contracts import RunSuitabilityCheck
from vibesensor.shared.types.history_analysis_contracts import (
    SummaryWarningResponse as SummaryWarningPayload,
)

__all__ = [
    "_action_status_text",
    "_append_unique_line",
    "_candidate_signal_text",
    "_check_state",
    "_confidence_pct_text",
    "_coverage_label",
    "_coverage_notes",
    "_display_location",
    "_first_confidence_reason_clause",
    "_first_nonpass_detail",
    "_has_source_overlap",
    "_has_warning_code",
    "_is_transient_primary",
    "_location_confidence_text",
    "_nonpass_detail_lines",
    "_presented_location_confidence_key",
    "_proof_caveat_text",
    "_resolve_check_text",
    "_resolve_detail_text",
    "_runner_up_corner",
    "_source_with_confidence",
    "_uses_shared_overlap_wording",
]


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
        label = _resolve_check_text(check.get("check_key"), lang=lang, tr=tr)
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
        label = _resolve_check_text(check.get("check_key"), lang=lang, tr=tr)
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
