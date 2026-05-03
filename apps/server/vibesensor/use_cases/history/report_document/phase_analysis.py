"""Phase and temporal relationship helpers for PDF report mapping."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.domain import Finding, TestRun, speed_band_sort_key
from vibesensor.report_i18n import is_composite_location
from vibesensor.shared.boundaries.reporting import PreparedReportFacts
from vibesensor.shared.constants.phases import PHASE_I18N_KEYS
from vibesensor.shared.report_presentation import display_location

__all__ = [
    "_finding_phase_index",
    "_finding_phase_keys",
    "_finding_phase_label",
    "_finding_speed_window",
    "_normalized_phase_key",
    "_ordered_temporal_pair",
    "_ordered_timeline_phase_keys",
    "_phase_label_text",
    "_same_display_location",
    "_same_source_temporal_pair",
]


def _normalized_phase_key(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _ordered_timeline_phase_keys(
    report_facts: PreparedReportFacts,
    *,
    fault_only: bool = False,
) -> tuple[str, ...]:
    phase_keys: list[str] = []
    ordered_intervals = sorted(
        report_facts.run.timeline_intervals,
        key=lambda interval: (
            interval.start_t_s is None,
            interval.start_t_s or 0.0,
            interval.end_t_s or 0.0,
        ),
    )
    for interval in ordered_intervals:
        if fault_only and not interval.has_fault_evidence:
            continue
        phase_key = _normalized_phase_key(interval.phase)
        if phase_key and phase_key not in phase_keys:
            phase_keys.append(phase_key)
    return tuple(phase_keys)


def _phase_label_text(
    phase_key: str | None,
    *,
    tr: Callable[..., str],
) -> str | None:
    normalized = _normalized_phase_key(phase_key)
    if not normalized:
        return None
    i18n_key = PHASE_I18N_KEYS.get(normalized)
    return tr(i18n_key) if i18n_key is not None else normalized.replace("_", " ").title()


def _finding_phase_keys(finding: Finding) -> tuple[str, ...]:
    phases: list[str] = []
    for raw_phase in (finding.dominant_phase, *finding.phases_detected):
        phase_key = _normalized_phase_key(raw_phase)
        if phase_key and phase_key not in phases:
            phases.append(phase_key)
    if phases:
        return tuple(phases)
    for point in finding.matched_points:
        phase_key = _normalized_phase_key(getattr(point, "phase", None))
        if phase_key and phase_key not in phases:
            phases.append(phase_key)
    return tuple(phases)


def _finding_phase_index(
    finding: Finding,
    report_facts: PreparedReportFacts,
) -> int | None:
    ordered_phase_keys = _ordered_timeline_phase_keys(report_facts)
    if not ordered_phase_keys:
        return None
    indexes = [
        ordered_phase_keys.index(phase)
        for phase in _finding_phase_keys(finding)
        if phase in ordered_phase_keys
    ]
    return min(indexes) if indexes else None


def _finding_phase_label(
    finding: Finding,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str | None:
    ordered_phase_keys = _ordered_timeline_phase_keys(report_facts)
    finding_phase_keys = _finding_phase_keys(finding)
    for phase_key in ordered_phase_keys:
        if phase_key in finding_phase_keys:
            return _phase_label_text(phase_key, tr=tr)
    if finding_phase_keys:
        return _phase_label_text(finding_phase_keys[0], tr=tr)
    return None


def _finding_speed_window(finding: Finding) -> str | None:
    return (
        str(
            finding.evidence.focused_speed_band
            if finding.evidence is not None and finding.evidence.focused_speed_band
            else finding.strongest_speed_band or ""
        ).strip()
        or None
    )


def _same_display_location(
    lhs: object,
    rhs: object,
    *,
    tr: Callable[..., str],
) -> bool:
    return (
        display_location(lhs, short=False, tr=tr).strip().lower()
        == display_location(rhs, short=False, tr=tr).strip().lower()
    )


def _ordered_temporal_pair(
    first: Finding,
    second: Finding,
    report_facts: PreparedReportFacts,
) -> tuple[Finding, Finding]:
    first_index = _finding_phase_index(first, report_facts)
    second_index = _finding_phase_index(second, report_facts)
    if first_index is not None and second_index is not None and first_index != second_index:
        return (first, second) if first_index < second_index else (second, first)
    first_speed = _finding_speed_window(first)
    second_speed = _finding_speed_window(second)
    if first_speed and second_speed and first_speed != second_speed:
        return (
            (first, second)
            if speed_band_sort_key(first_speed) <= speed_band_sort_key(second_speed)
            else (second, first)
        )
    return first, second


def _same_source_temporal_pair(
    aggregate: TestRun,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> tuple[Finding, Finding] | None:
    candidates = [
        finding
        for finding in aggregate.effective_top_causes()[:3]
        if str(finding.strongest_location or "").strip()
        and not is_composite_location(finding.strongest_location)
    ]
    if len(candidates) < 2:
        return None
    primary_finding = candidates[0]
    for alternative_finding in candidates[1:]:
        if primary_finding.source_normalized != alternative_finding.source_normalized:
            continue
        if _same_display_location(
            primary_finding.strongest_location,
            alternative_finding.strongest_location,
            tr=tr,
        ):
            continue
        if not _has_same_source_temporal_shift(
            primary_finding,
            alternative_finding,
            report_facts,
        ):
            continue
        return _ordered_temporal_pair(primary_finding, alternative_finding, report_facts)
    return None


def _has_same_source_temporal_shift(
    primary_finding: Finding,
    alternative_finding: Finding,
    report_facts: PreparedReportFacts,
) -> bool:
    primary_index = _finding_phase_index(primary_finding, report_facts)
    alternative_index = _finding_phase_index(alternative_finding, report_facts)
    if (
        primary_index is not None
        and alternative_index is not None
        and primary_index != alternative_index
    ):
        return True
    primary_phases = set(_finding_phase_keys(primary_finding))
    alternative_phases = set(_finding_phase_keys(alternative_finding))
    if primary_phases and alternative_phases and primary_phases != alternative_phases:
        return True
    primary_speed = _finding_speed_window(primary_finding)
    alternative_speed = _finding_speed_window(alternative_finding)
    if primary_speed and alternative_speed and primary_speed != alternative_speed:
        return True
    return len(_ordered_timeline_phase_keys(report_facts, fault_only=True)) >= 2
