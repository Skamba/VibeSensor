"""Pattern, context, and temporal summary builders for PDF mapping."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.adapters.pdf._candidate_resolver import PrimaryCandidateContext
from vibesensor.adapters.pdf.pattern_parts import why_parts_listed
from vibesensor.adapters.pdf.presentation import order_label_human
from vibesensor.adapters.pdf.report_context import ReportMappingContext
from vibesensor.adapters.pdf.report_data import PatternEvidence
from vibesensor.domain import Finding, TestRun, VibrationOrigin, speed_band_sort_key
from vibesensor.report_i18n import human_source, resolve_i18n
from vibesensor.shared.boundaries.vibration_origin import build_origin_explanation
from vibesensor.shared.constants.phases import PHASE_I18N_KEYS
from vibesensor.use_cases.history.report_display_facts.shared import (
    _candidate_signal_text,
    _display_location,
    _uses_shared_overlap_wording,
)
from vibesensor.use_cases.history.report_facts import PreparedReportFacts

__all__ = [
    "_context_summary_text",
    "_evidence_summary_text",
    "_finding_phase_index",
    "_finding_phase_keys",
    "_finding_phase_label",
    "_finding_speed_window",
    "_normalized_phase_key",
    "_observation_texts",
    "_ordered_temporal_pair",
    "_ordered_timeline_phase_keys",
    "_phase_label_text",
    "_phase_summary_text",
    "_proof_summary_text",
    "_run_limits_summary_text",
    "_same_display_location",
    "_same_source_temporal_evidence_summary",
    "_same_source_temporal_pair",
    "_same_source_temporal_phase_summary",
    "_same_source_temporal_proof_summary",
    "build_pattern_evidence",
    "resolve_interpretation",
    "resolve_parts_context",
]


def build_pattern_evidence(
    context: ReportMappingContext,
    primary: PrimaryCandidateContext,
    lang: str,
    tr: Callable,
) -> PatternEvidence:
    """Build the pattern-evidence block for the report template.

    Uses the domain aggregate for system classification when available.
    """
    # Domain-first: use aggregate effective top causes for matched systems
    aggregate = context.domain_aggregate
    assert aggregate is not None
    effective = aggregate.effective_top_causes()
    domain_primary = effective[0] if effective else aggregate.primary_finding
    systems_raw = [human_source(str(f.suspected_source), tr=tr) for f in effective[:3]]
    systems = list(dict.fromkeys(systems_raw))
    interpretation = resolve_interpretation(context.origin, lang=lang, tr=tr)
    source_for_why, order_label_for_why = resolve_parts_context(
        primary.primary_candidate,
        domain_finding=domain_primary,
        lang=lang,
    )
    return PatternEvidence(
        matched_systems=systems,
        strongest_location=_display_location(primary.primary_location, tr=tr),
        speed_band=primary.primary_speed,
        strength_label=primary.strength_text,
        strength_peak_db=primary.strength_db,
        certainty_label=primary.certainty_label_text,
        certainty_pct=primary.certainty_pct,
        certainty_reason=primary.certainty_reason,
        warning=primary.certainty_reason if primary.weak_spatial else None,
        interpretation=interpretation or None,
        why_parts_text=why_parts_listed(source_for_why, order_label_for_why, lang=lang),
    )


def resolve_interpretation(origin: VibrationOrigin | None, *, lang: str, tr: Callable) -> str:
    """Resolve the origin explanation into localized report text."""
    if origin is None:
        return ""

    explanation = build_origin_explanation(
        source=str(origin.suspected_source),
        speed_band=origin.speed_band or "",
        location=origin.summary_location,
        dominance=origin.dominance_ratio,
        weak=origin.weak_spatial_separation,
        dominant_phase=origin.dominant_phase or "",
    )
    return resolve_i18n(lang, explanation, tr=tr)


def resolve_parts_context(
    primary_candidate: Finding | None,
    *,
    domain_finding: Finding | None = None,
    lang: str,
) -> tuple[str, str | None]:
    """Resolve source/order context used for why-parts-listed text."""
    finding = domain_finding or primary_candidate
    if finding is not None:
        source_for_why = str(finding.suspected_source)
        signatures: object = list(finding.signature_labels)
    else:
        source_for_why = ""
        signatures = []
    if isinstance(signatures, list) and signatures:
        order_label = order_label_human(lang, str(signatures[0]))
    else:
        order_label = None
    return source_for_why, order_label


def _normalized_phase_key(value: object) -> str:
    return str(value or "").strip().lower()


def _ordered_timeline_phase_keys(
    report_facts: PreparedReportFacts,
    *,
    fault_only: bool = False,
) -> tuple[str, ...]:
    phase_keys: list[str] = []
    ordered_intervals = sorted(
        report_facts.timeline_intervals,
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
        _display_location(lhs, short=False, tr=tr).strip().lower()
        == _display_location(rhs, short=False, tr=tr).strip().lower()
    )


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
    first_location = _display_location(first.strongest_location, tr=tr)
    second_location = _display_location(second.strongest_location, tr=tr)
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
    first_location = _display_location(first.strongest_location, tr=tr)
    second_location = _display_location(second.strongest_location, tr=tr)
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
    first_location = _display_location(first.strongest_location, tr=tr)
    second_location = _display_location(second.strongest_location, tr=tr)
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


def _proof_summary_text(
    aggregate: TestRun,
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str:
    sequence_summary = _same_source_temporal_proof_summary(
        aggregate,
        report_facts,
        tr=tr,
    )
    if sequence_summary is not None:
        return sequence_summary
    ratio = report_facts.primary_candidate_facts.dominance_ratio
    location = _display_location(primary.primary_location, tr=tr)
    runner_up = report_facts.display.appendix_b.runner_up_corner
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
    tr: Callable[..., str],
) -> str:
    speed_window = str(report_facts.display.verdict.speed_window_label or "").strip() or tr(
        "UNKNOWN"
    )
    if (
        report_facts.action_status_key == "action_ready_caution"
        and report_facts.alternative_source_visible
    ):
        return tr("REPORT_RUN_LIMITS_RECAPTURE_RECIPE", speed=speed_window)
    note = report_facts.display.verdict.proof_caveat
    return note or tr("REPORT_CAPTURE_ISSUE_GENERIC")


def _evidence_summary_text(
    aggregate: TestRun,
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str:
    effective_causes = aggregate.effective_top_causes()
    matched_windows = report_facts.primary_candidate_facts.matched_evidence_window_count
    speed_window = str(primary.primary_speed or "").strip() or tr("UNKNOWN")
    source = primary.primary_system
    location = _display_location(primary.primary_location, tr=tr)
    sequential_summary = _same_source_temporal_evidence_summary(
        aggregate,
        report_facts,
        tr=tr,
    )
    if sequential_summary is not None:
        return sequential_summary
    alternative = (
        human_source(report_facts.alternative_source, tr=tr)
        if report_facts.alternative_source_visible and report_facts.alternative_source is not None
        else None
    )
    alternative_finding = (
        effective_causes[1]
        if report_facts.alternative_source_visible and len(effective_causes) > 1
        else None
    )
    if alternative is not None and matched_windows is not None:
        if alternative_finding is not None:
            if _uses_shared_overlap_wording(effective_causes[0], alternative_finding, tr=tr):
                return tr(
                    "REPORT_EVIDENCE_SUMMARY_ALT_OVERLAP",
                    source=source,
                    matches=matched_windows,
                    speed=speed_window,
                    location=location,
                    alternative=alternative,
                )
            alternative_signal = _candidate_signal_text(alternative_finding, tr=tr)
            alternative_location = _display_location(alternative_finding.strongest_location, tr=tr)
            alternative_speed = (
                str(
                    alternative_finding.evidence.focused_speed_band
                    if alternative_finding.evidence
                    and alternative_finding.evidence.focused_speed_band
                    else alternative_finding.strongest_speed_band or speed_window
                ).strip()
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
    speed_window = str(primary.primary_speed or "").strip() or tr("UNKNOWN")
    coverage = report_facts.coverage_summary
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
            title = str(phase).replace("_", " ").title()
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
            location=_display_location(location, short=False, tr=tr),
        )
        if text not in observations:
            observations.append(text)
    return observations[:3]
