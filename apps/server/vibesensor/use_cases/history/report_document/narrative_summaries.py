"""Narrative summary builders for PDF report mapping."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.domain import TestRun
from vibesensor.shared.boundaries.reporting import PreparedReportFacts
from vibesensor.shared.report_presentation import (
    candidate_signal_text,
    display_location,
    display_phase_label,
    display_speed_band,
    human_source,
    uses_shared_overlap_wording,
)
from vibesensor.use_cases.history.report_document._candidate_resolver import PrimaryCandidateContext

from .phase_analysis import (
    _finding_phase_label,
    _same_source_temporal_pair,
)

__all__ = [
    "_context_summary_text",
    "_evidence_summary_text",
    "_observation_texts",
    "_phase_summary_text",
    "_proof_summary_text",
    "_run_limits_summary_text",
]


def _proof_summary_text(
    aggregate: TestRun,
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    *,
    runner_up_corner: str | None,
    tr: Callable[..., str],
) -> str:
    sequence_summary = _same_source_temporal_proof_summary(
        aggregate,
        report_facts,
        tr=tr,
    )
    if sequence_summary is not None:
        return sequence_summary
    ratio = report_facts.decision.primary_candidate.dominance_ratio
    location = display_location(primary.primary_location, tr=tr)
    runner_up = runner_up_corner
    if (
        primary.weak_spatial
        or report_facts.decision.location_confidence_key == "weak"
        or (ratio is not None and ratio <= 1.05)
    ):
        return tr("REPORT_PROOF_SUMMARY_WEAK_LOCATION")
    if ratio is not None:
        if runner_up is not None:
            return tr(
                "REPORT_PROOF_SUMMARY_RATIO_RUNNER_UP",
                location=location,
                runner_up=runner_up,
                ratio=f"{ratio:.1f}",
            )
        return tr(
            "REPORT_PROOF_SUMMARY_RATIO_NO_RUNNER_UP",
            location=location,
            ratio=f"{ratio:.1f}",
        )
    return tr("REPORT_PROOF_SUMMARY_SIMPLE_PLAIN", location=location)


def _run_limits_summary_text(
    report_facts: PreparedReportFacts,
    *,
    speed_window_label: str | None,
    proof_caveat: str | None,
    tr: Callable[..., str],
) -> str:
    speed_window = display_speed_band(speed_window_label, tr=tr) or tr("UNKNOWN")
    if (
        report_facts.decision.action_status_key == "action_ready_caution"
        and report_facts.decision.alternative_source_visible
    ):
        return tr("REPORT_RUN_LIMITS_RECAPTURE_RECIPE", speed=speed_window)
    return proof_caveat or tr("REPORT_CAPTURE_ISSUE_GENERIC")


def _evidence_summary_text(
    aggregate: TestRun,
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str:
    effective_causes = aggregate.effective_top_causes()
    matched_windows = report_facts.decision.primary_candidate.matched_evidence_window_count
    speed_window = display_speed_band(primary.primary_speed, tr=tr) or tr("UNKNOWN")
    source = primary.primary_system
    location = display_location(primary.primary_location, tr=tr)
    sequential_summary = _same_source_temporal_evidence_summary(
        aggregate,
        report_facts,
        tr=tr,
    )
    if sequential_summary is not None:
        return sequential_summary
    alternative = (
        human_source(report_facts.decision.alternative_source, tr=tr)
        if report_facts.decision.alternative_source_visible
        and report_facts.decision.alternative_source is not None
        else None
    )
    alternative_finding = (
        effective_causes[1]
        if report_facts.decision.alternative_source_visible and len(effective_causes) > 1
        else None
    )
    if alternative is not None and matched_windows is not None:
        if alternative_finding is not None:
            if uses_shared_overlap_wording(effective_causes[0], alternative_finding, tr=tr):
                return tr(
                    "REPORT_EVIDENCE_SUMMARY_ALT_OVERLAP",
                    source=source,
                    matches=matched_windows,
                    speed=speed_window,
                    location=location,
                    alternative=alternative,
                )
            alternative_signal = candidate_signal_text(alternative_finding, tr=tr)
            alternative_location = display_location(alternative_finding.strongest_location, tr=tr)
            alternative_speed = (
                display_speed_band(
                    alternative_finding.evidence.focused_speed_band
                    if alternative_finding.evidence
                    and alternative_finding.evidence.focused_speed_band
                    else alternative_finding.strongest_speed_band,
                    tr=tr,
                )
                or speed_window
            )
            return tr(
                "REPORT_EVIDENCE_SUMMARY_ALT_DETAILED",
                source=source,
                matches=matched_windows,
                speed=speed_window,
                location=location,
                alternative=alternative,
                alternative_signal=alternative_signal,
                alternative_location=alternative_location,
                alternative_speed=alternative_speed,
            )
        return tr(
            "REPORT_EVIDENCE_SUMMARY_ALT",
            source=source,
            matches=matched_windows,
            speed=speed_window,
            location=location,
            alternative=alternative,
        )
    if matched_windows is not None:
        return tr(
            "REPORT_EVIDENCE_SUMMARY_SIMPLE",
            source=source,
            matches=matched_windows,
            speed=speed_window,
            location=location,
        )
    return tr(
        "REPORT_PROOF_SUMMARY_SIMPLE_PLAIN",
        location=location,
    )


def _context_summary_text(
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str:
    speed_window = display_speed_band(primary.primary_speed, tr=tr) or tr("UNKNOWN")
    coverage = report_facts.sensor.coverage
    expected = (
        len(coverage.expected_locations) or len(coverage.active_locations) or primary.sensor_count
    )
    active = len(coverage.active_locations) or primary.sensor_count
    if not coverage.missing_locations and not coverage.partial_locations:
        return tr(
            "REPORT_CONTEXT_SUMMARY_COMPLETE",
            speed=speed_window,
            active=active,
            expected=expected,
        )
    return tr(
        "REPORT_CONTEXT_SUMMARY_PARTIAL",
        speed=speed_window,
        active=active,
        expected=expected,
    )


def _phase_summary_text(
    aggregate: TestRun,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str:
    sequential_summary = _same_source_temporal_phase_summary(
        aggregate,
        report_facts,
        tr=tr,
    )
    if sequential_summary is not None:
        return sequential_summary
    phases: list[str] = []
    for finding in aggregate.effective_top_causes():
        for phase in finding.phases_detected:
            title = display_phase_label(phase, tr=tr)
            if title and title not in phases:
                phases.append(title)
    if not phases:
        return tr("REPORT_PHASE_SUMMARY_NONE")
    return ", ".join(phases)


def _observation_texts(aggregate: TestRun, *, tr: Callable[..., str]) -> list[str]:
    observations: list[str] = []
    for finding in aggregate.findings:
        if not finding.is_informational:
            continue
        source = str(finding.suspected_source).strip().lower()
        if source != "transient_impact" and finding.peak_classification != "transient":
            continue
        location = str(finding.strongest_location or "").strip()
        if not location:
            continue
        text = tr(
            "REPORT_OBSERVATION_TRANSIENT",
            location=display_location(location, short=False, tr=tr),
        )
        if text not in observations:
            observations.append(text)
    return observations[:3]


def _same_source_temporal_proof_summary(
    aggregate: TestRun,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str | None:
    pair = _same_source_temporal_pair(aggregate, report_facts, tr=tr)
    if pair is None:
        return None
    first, second = pair
    first_location = display_location(first.strongest_location, tr=tr)
    second_location = display_location(second.strongest_location, tr=tr)
    first_phase = _finding_phase_label(first, report_facts, tr=tr)
    second_phase = _finding_phase_label(second, report_facts, tr=tr)
    if first_phase and second_phase and first_phase != second_phase:
        return tr(
            "REPORT_PROOF_SUMMARY_SEQUENTIAL_PHASES",
            first_location=first_location,
            first_phase=first_phase,
            second_location=second_location,
            second_phase=second_phase,
        )
    return tr(
        "REPORT_PROOF_SUMMARY_SEQUENTIAL_GENERIC",
        first_location=first_location,
        second_location=second_location,
    )


def _same_source_temporal_evidence_summary(
    aggregate: TestRun,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str | None:
    pair = _same_source_temporal_pair(aggregate, report_facts, tr=tr)
    if pair is None:
        return None
    first, second = pair
    source = human_source(first.suspected_source, tr=tr)
    first_location = display_location(first.strongest_location, tr=tr)
    second_location = display_location(second.strongest_location, tr=tr)
    first_phase = _finding_phase_label(first, report_facts, tr=tr)
    second_phase = _finding_phase_label(second, report_facts, tr=tr)
    if first_phase and second_phase and first_phase != second_phase:
        return tr(
            "REPORT_EVIDENCE_SUMMARY_SEQUENTIAL_PHASES",
            source=source,
            first_location=first_location,
            first_phase=first_phase,
            second_location=second_location,
            second_phase=second_phase,
        )
    return tr(
        "REPORT_EVIDENCE_SUMMARY_SEQUENTIAL_GENERIC",
        source=source,
        first_location=first_location,
        second_location=second_location,
    )


def _same_source_temporal_phase_summary(
    aggregate: TestRun,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str | None:
    pair = _same_source_temporal_pair(aggregate, report_facts, tr=tr)
    if pair is None:
        return None
    first, second = pair
    first_location = display_location(first.strongest_location, tr=tr)
    second_location = display_location(second.strongest_location, tr=tr)
    first_phase = _finding_phase_label(first, report_facts, tr=tr)
    second_phase = _finding_phase_label(second, report_facts, tr=tr)
    if first_phase and second_phase and first_phase != second_phase:
        return tr(
            "REPORT_PHASE_SUMMARY_SEQUENTIAL_PHASES",
            first_location=first_location,
            first_phase=first_phase,
            second_location=second_location,
            second_phase=second_phase,
        )
    return tr(
        "REPORT_PHASE_SUMMARY_SEQUENTIAL_GENERIC",
        first_location=first_location,
        second_location=second_location,
    )
