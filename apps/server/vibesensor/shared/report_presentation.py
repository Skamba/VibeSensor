"""Canonical report presentation helpers shared by history prep and PDF mapping."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.domain import Finding, LocationIntensitySummary, TestRun, VibrationSource
from vibesensor.report_i18n import human_location, human_source, location_candidates
from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts

__all__ = [
    "action_status_text",
    "append_unique_line",
    "candidate_signal_text",
    "confidence_pct_text",
    "coverage_label",
    "coverage_notes",
    "display_location",
    "first_confidence_reason_clause",
    "has_source_overlap",
    "is_transient_primary",
    "location_confidence_text",
    "presented_location_confidence_key",
    "proof_caveat_text",
    "runner_up_corner",
    "source_with_confidence",
    "uses_shared_overlap_wording",
]


def action_status_text(action_status_key: str, *, tr: Callable[..., str]) -> str:
    keys = {
        "action_ready": "REPORT_ACTION_STATUS_READY",
        "action_ready_caution": "REPORT_ACTION_STATUS_READY_CAUTION",
        "recapture_before_acting": "REPORT_ACTION_STATUS_RECAPTURE",
    }
    return tr(keys.get(action_status_key, "REPORT_ACTION_STATUS_RECAPTURE"))


def location_confidence_text(location_confidence_key: str, *, tr: Callable[..., str]) -> str:
    keys = {
        "strong": "REPORT_LOCATION_CONFIDENCE_STRONG",
        "limited": "REPORT_LOCATION_CONFIDENCE_LIMITED",
        "mixed": "REPORT_LOCATION_CONFIDENCE_MIXED",
        "weak": "REPORT_LOCATION_CONFIDENCE_WEAK",
    }
    return tr(keys.get(location_confidence_key, "REPORT_LOCATION_CONFIDENCE_MIXED"))


def presented_location_confidence_key(
    *,
    action_status_key: str,
    location_confidence_key: str,
) -> str:
    if action_status_key == "action_ready_caution" and location_confidence_key != "weak":
        return "limited"
    return location_confidence_key


def first_confidence_reason_clause(primary_candidate_facts: PrimaryReportFacts) -> str | None:
    finding = primary_candidate_facts.domain_primary
    if finding is None or finding.confidence_assessment is None:
        return None
    for clause in str(finding.confidence_assessment.reason or "").split(";"):
        text = clause.strip().rstrip(".")
        if text:
            return text
    return None


def display_location(value: object, *, short: bool = True, tr: Callable[..., str]) -> str:
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


def coverage_label(
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


def coverage_notes(
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
                    display_location(location, short=False, tr=tr) for location in missing_locations
                ),
            ),
        )
    if partial_locations:
        notes.append(
            tr(
                "REPORT_COVERAGE_NOTE_PARTIAL",
                locations=", ".join(
                    display_location(location, short=False, tr=tr) for location in partial_locations
                ),
            ),
        )
    if not notes:
        notes.append(tr("REPORT_COVERAGE_NOTE_COMPLETE"))
    return tuple(notes)


def confidence_pct_text(finding: Finding) -> str:
    if finding.confidence_assessment is not None:
        return finding.confidence_assessment.pct_text
    return finding.confidence_pct_text


def source_with_confidence(finding: Finding, *, tr: Callable[..., str]) -> str:
    return tr(
        "REPORT_SOURCE_WITH_CONFIDENCE",
        source=human_source(finding.suspected_source, tr=tr),
        confidence=confidence_pct_text(finding),
    )


def runner_up_corner(
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
    return display_location(ranked_rows[1].location, tr=tr)


def proof_caveat_text(
    *,
    primary_candidate_facts: PrimaryReportFacts,
    action_status_key: str,
    location_confidence_key: str,
    tr: Callable[..., str],
) -> str | None:
    if action_status_key == "action_ready_caution":
        return None
    reason = (
        first_confidence_reason_clause(primary_candidate_facts)
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


def append_unique_line(lines: list[str], text: object) -> None:
    value = str(text or "").strip()
    if not value:
        return
    normalized = value.rstrip(".").casefold()
    if any(existing.rstrip(".").casefold() == normalized for existing in lines):
        return
    lines.append(value)


def candidate_signal_text(finding: Finding, *, tr: Callable[..., str]) -> str:
    if finding.signature_labels:
        return ", ".join(finding.signature_labels[:2])
    if finding.order:
        return finding.order
    if finding.frequency_hz is not None:
        return f"{finding.frequency_hz:.1f} Hz"
    return tr("REPORT_SIGNAL_FALLBACK")


def uses_shared_overlap_wording(
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
        display_location(primary_location, short=False, tr=tr).strip().lower()
        == display_location(alternative_location, short=False, tr=tr).strip().lower()
    )


def has_source_overlap(aggregate: TestRun, *, tr: Callable[..., str]) -> bool:
    ranked = list(aggregate.effective_top_causes()[:2])
    if len(ranked) < 2:
        return False
    return uses_shared_overlap_wording(ranked[0], ranked[1], tr=tr)


def is_transient_primary(primary_candidate_facts: PrimaryReportFacts) -> bool:
    finding = primary_candidate_facts.domain_primary
    if finding is None:
        return False
    source = str(finding.suspected_source or "").strip().lower()
    classification = str(finding.peak_classification or "").strip().lower()
    return source == "transient_impact" or classification == "transient"
