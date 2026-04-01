"""report_mapping – thin mapper from prepared report inputs to template data.

History-side preparation owns semantic report facts and display decisions
before the renderer boundary. This module consumes the validated prepared
report-input seam, formats those prepared values into renderer dataclasses, and
handles the final template-data orchestration for the PDF renderer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from math import isfinite

from vibesensor.adapters.pdf._candidate_resolver import (
    PrimaryCandidateContext,
    resolve_primary_report_candidate,
)
from vibesensor.adapters.pdf._card_builder import (
    build_system_cards,
    humanize_signatures,
)
from vibesensor.adapters.pdf.pattern_parts import why_parts_listed
from vibesensor.adapters.pdf.peak_table import build_peak_rows
from vibesensor.adapters.pdf.presentation import order_label_human
from vibesensor.adapters.pdf.report_context import (
    ReportMappingContext,
    observed_signature,
    prepare_report_mapping_context,
)
from vibesensor.adapters.pdf.report_data import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    AppendixDData,
    DataTrustItem,
    EvidenceChainRow,
    FindingPresentation,
    MeasurementRow,
    NextStep,
    PatternEvidence,
    RankedCandidateRow,
    Report,
    ReportLabelValueRow,
    ReportTemplateData,
    SensorObservationCell,
    SensorObservationMatrixRow,
    TimelineGraphData,
    TimelineGraphInterval,
    TopologyIntensityRow,
    VerdictPageData,
    build_report_from_renderer_payload,
)
from vibesensor.adapters.pdf.report_sections import (
    build_data_trust,
    build_next_steps,
)
from vibesensor.adapters.pdf.template_builder import build_template_data
from vibesensor.domain import (
    Finding,
    LocationIntensitySummary,
    TestRun,
    VibrationOrigin,
    VibrationSource,
    speed_band_sort_key,
)
from vibesensor.report_i18n import (
    human_location,
    human_source,
    location_candidates,
    normalize_lang,
    resolve_i18n,
)
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.vibration_origin import build_origin_explanation
from vibesensor.shared.constants.phases import PHASE_I18N_KEYS
from vibesensor.shared.types.json_types import JsonValue
from vibesensor.use_cases.history.report_display_facts import (
    PreparedAppendixADisplay,
    PreparedAppendixBSummaryDisplay,
    PreparedVerdictDisplay,
)
from vibesensor.use_cases.history.report_preparation import (
    PreparedReportFacts,
    PreparedReportInput,
    ValidatedPreparedReportInput,
    prepare_report_input,
    validate_prepared_report_input,
)
from vibesensor.vibration_strength import percentile, relative_level_db_scalar

__all__ = [
    "PrimaryCandidateContext",
    "PreparedReportInput",
    "Report",
    "ReportMappingContext",
    "build_system_cards",
    "humanize_signatures",
    "map_summary",
    "prepare_report_input",
    "resolve_primary_report_candidate",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


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
        == _display_location(
            alternative_location,
            short=False,
            tr=tr,
        )
        .strip()
        .lower()
    )


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


def _measurement_signal_label(row: dict[str, object] | object, *, tr: Callable[..., str]) -> str:
    if isinstance(row, dict):
        order_label = str(row.get("order_label") or "").strip()
        if order_label:
            return order_label
        frequency = row.get("frequency_hz")
        if isinstance(frequency, (int, float)):
            return f"{float(frequency):.1f} Hz"
    return tr("REPORT_SIGNAL_FALLBACK")


def _measurement_rows(
    prepared: ValidatedPreparedReportInput,
    *,
    aggregate: TestRun,
    tr: Callable[..., str],
) -> list[MeasurementRow]:
    finding_by_source: dict[str, Finding] = {}
    top_findings = list(aggregate.effective_top_causes())
    for top_finding in top_findings:
        source_key = str(top_finding.suspected_source).strip().lower()
        if source_key and source_key not in finding_by_source:
            finding_by_source[source_key] = top_finding
    primary_finding = top_findings[0] if top_findings else None
    rows: list[MeasurementRow] = []
    for index, row in enumerate(prepared.renderer_payload.peak_table_rows[:4], start=1):
        source_key = str(row.get("suspected_source") or "").strip().lower()
        matched_finding: Finding | None = finding_by_source.get(source_key)
        if matched_finding is None and primary_finding is not None:
            matched_finding = primary_finding
            if not source_key:
                source_key = str(primary_finding.suspected_source).strip().lower()
        peak_db_value = row.get("max_intensity_db")
        if peak_db_value is None:
            peak_db_value = row.get("p95_intensity_db")
        strength_db_value = row.get("strength_db")
        signal_label = (
            _candidate_signal_text(matched_finding, tr=tr)
            if matched_finding is not None
            else _measurement_signal_label(row, tr=tr)
        )
        rows.append(
            MeasurementRow(
                measurement_id=f"M{index:02d}",
                source_name=human_source(
                    matched_finding.suspected_source
                    if matched_finding is not None
                    else source_key or row.get("suspected_source"),
                    tr=tr,
                ),
                signal_label=signal_label,
                frequency_hz=(
                    float(row.get("frequency_hz"))
                    if isinstance(row.get("frequency_hz"), (int, float))
                    else None
                ),
                peak_db=float(peak_db_value) if isinstance(peak_db_value, (int, float)) else None,
                strength_db=(
                    float(strength_db_value)
                    if isinstance(strength_db_value, (int, float))
                    else None
                ),
                speed_window=str(row.get("typical_speed_band") or "").strip() or None,
                dominant_location=(
                    _display_location(matched_finding.strongest_location, tr=tr)
                    if matched_finding is not None
                    else None
                ),
                classification=str(row.get("peak_classification") or "").replace("_", " ").title()
                or None,
            ),
        )
    return rows


def _measurement_refs_by_source(
    measurements: list[MeasurementRow],
) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for row in measurements:
        key = row.source_name.strip().lower()
        refs.setdefault(key, []).append(row.measurement_id)
    return refs


def _matched_evidence_window_count(finding: Finding) -> int | None:
    if finding.matched_points:
        return len(finding.matched_points)
    if finding.evidence is not None and finding.evidence.matched_samples is not None:
        return finding.evidence.matched_samples
    return None


def _evidence_chain_rows(
    aggregate: TestRun,
    *,
    measurements: list[MeasurementRow],
    tr: Callable[..., str],
) -> list[EvidenceChainRow]:
    refs_by_source = _measurement_refs_by_source(measurements)
    rows: list[EvidenceChainRow] = []
    for finding in aggregate.effective_top_causes()[:3]:
        source_name = human_source(finding.suspected_source, tr=tr)
        refs = refs_by_source.get(source_name.strip().lower(), [])
        ambiguity_note = (
            tr("REPORT_EVIDENCE_NOTE_NO_REFS")
            if not refs
            else tr("REPORT_EVIDENCE_NOTE_WEAK")
            if finding.weak_spatial_separation
            else None
        )
        rows.append(
            EvidenceChainRow(
                source_name=_source_with_confidence(finding, tr=tr),
                supporting_signal_label=_candidate_signal_text(finding, tr=tr),
                measurement_refs=refs,
                matched_evidence_window_count=_matched_evidence_window_count(finding),
                speed_window=(
                    str(
                        finding.evidence.focused_speed_band
                        if finding.evidence and finding.evidence.focused_speed_band
                        else finding.strongest_speed_band or ""
                    ).strip()
                    or None
                ),
                dominant_location=_display_location(finding.strongest_location, tr=tr),
                ambiguity_note=ambiguity_note,
            ),
        )
    return rows


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


def _capture_issue_lines(
    data_trust: list[DataTrustItem],
    *,
    tr: Callable[..., str],
) -> list[str]:
    issues = [
        f"{item.check}: {item.detail}" if item.detail else item.check
        for item in data_trust
        if item.state != "pass"
    ]
    return issues[:3] if issues else [tr("REPORT_CAPTURE_ISSUE_GENERIC")]


def _capture_condition_lines(
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> list[str]:
    expected = len(report_facts.coverage_summary.expected_locations) or len(
        report_facts.coverage_summary.active_locations
    )
    return [
        tr("REPORT_CAPTURE_CONDITION_STEADY"),
        tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected),
        tr("REPORT_CAPTURE_CONDITION_REFERENCE"),
    ]


def _build_timeline_graph_data(
    report_facts: PreparedReportFacts,
    *,
    duration_s: float | None,
) -> TimelineGraphData | None:
    max_interval_end = max(
        (interval.end_t_s or 0.0 for interval in report_facts.timeline_intervals),
        default=0.0,
    )
    resolved_duration = max(float(duration_s or 0.0), max_interval_end)
    if resolved_duration <= 0:
        return None
    intervals: list[TimelineGraphInterval] = []
    max_speed = 0.0
    ordered_intervals = sorted(
        report_facts.timeline_intervals,
        key=lambda interval: (
            interval.start_t_s is None,
            interval.start_t_s or 0.0,
            interval.end_t_s or 0.0,
        ),
    )
    for interval in ordered_intervals:
        if interval.start_t_s is None or interval.end_t_s is None:
            continue
        start_t_s = max(0.0, interval.start_t_s)
        end_t_s = min(resolved_duration, interval.end_t_s)
        if end_t_s <= start_t_s:
            continue
        present_speeds = [
            speed for speed in (interval.speed_min_kmh, interval.speed_max_kmh) if speed is not None
        ]
        if present_speeds:
            max_speed = max(max_speed, *present_speeds)
        intervals.append(
            TimelineGraphInterval(
                phase_label=interval.phase,
                start_t_s=start_t_s,
                end_t_s=end_t_s,
                speed_min_kmh=interval.speed_min_kmh,
                speed_max_kmh=interval.speed_max_kmh,
                has_fault_evidence=interval.has_fault_evidence,
            ),
        )
    if not intervals:
        return None
    speed_ceiling_kmh = max(10.0, max_speed * 1.10 if max_speed > 0 else 10.0)
    return TimelineGraphData(
        duration_s=resolved_duration,
        speed_ceiling_kmh=speed_ceiling_kmh,
        intervals=tuple(intervals),
    )


def _build_verdict_page_data(
    *,
    verdict: PreparedVerdictDisplay,
    proof_summary: str | None,
    timeline_graph: TimelineGraphData | None,
) -> VerdictPageData:
    return VerdictPageData(
        speed_window_label=verdict.speed_window_label,
        suspected_source=verdict.suspected_source,
        inspect_first=verdict.inspect_first,
        action_status=verdict.action_status,
        action_status_note=verdict.action_status_note,
        reason_sentence=verdict.reason_sentence,
        dominant_corner=verdict.dominant_corner,
        runner_up_corner=verdict.runner_up_corner,
        location_confidence=verdict.location_confidence,
        coverage_label=verdict.coverage_label,
        also_consider=verdict.also_consider,
        proof_summary=proof_summary,
        proof_caveat=verdict.proof_caveat,
        proof_panel_title=verdict.proof_panel_title,
        timeline_graph=timeline_graph,
        footer_routes=verdict.footer_routes,
    )


def _build_appendix_a_data(
    *,
    appendix: PreparedAppendixADisplay,
    next_steps: list[NextStep],
) -> AppendixAData:
    if appendix.mode == "recapture":
        return AppendixAData(
            mode="recapture",
            capture_issues=list(appendix.capture_issues),
            capture_changes=[step.action for step in next_steps],
            capture_conditions=list(appendix.capture_conditions),
        )
    return AppendixAData(
        mode="workflow",
        primary_source=appendix.primary_source,
        alternative_source=appendix.alternative_source,
        why_primary_first=appendix.why_primary_first,
        why_alternative_next=appendix.why_alternative_next,
        next_if_clean=appendix.next_if_clean,
        ranked_candidates=[
            RankedCandidateRow(
                source_name=row.source_name,
                confidence_pct=row.confidence_pct,
                inspect_first=row.inspect_first,
                path_role=row.path_role,
                reason=row.reason,
            )
            for row in appendix.ranked_candidates
        ],
    )


def _build_appendix_b_data(
    *,
    aggregate: TestRun,
    appendix: PreparedAppendixBSummaryDisplay,
    sensor_locations: list[str],
    sensor_intensity: list[LocationIntensitySummary],
    tr: Callable[..., str],
) -> AppendixBData:
    ranked_rows = sorted(
        sensor_intensity,
        key=lambda row: (
            row.p95_intensity_db if row.p95_intensity_db is not None else float("-inf"),
        ),
        reverse=True,
    )
    intensity_rows = [
        TopologyIntensityRow(
            location=_display_location(row.location, short=False, tr=tr),
            p95_db=row.p95_intensity_db,
            coverage_state=(
                tr("REPORT_COVERAGE_STATE_PARTIAL")
                if row.partial_coverage or row.sample_coverage_warning
                else tr("REPORT_COVERAGE_STATE_COMPLETE")
            ),
        )
        for row in ranked_rows
    ]
    sensor_observation_rows = _sensor_observation_matrix_rows(
        aggregate,
        sensor_locations=sensor_locations,
        tr=tr,
    )
    return AppendixBData(
        dominant_corner=appendix.dominant_corner,
        runner_up_corner=appendix.runner_up_corner,
        dominance_ratio_text=appendix.dominance_ratio_text,
        location_confidence=appendix.location_confidence,
        coverage_label=appendix.coverage_label,
        coverage_notes=list(appendix.coverage_notes),
        intensity_rows=intensity_rows,
        sensor_observation_rows=sensor_observation_rows,
    )


def _sensor_observation_matrix_rows(
    aggregate: TestRun,
    *,
    sensor_locations: list[str],
    tr: Callable[..., str],
) -> list[SensorObservationMatrixRow]:
    if not sensor_locations:
        return []
    sensor_labels = [
        _display_location(location, short=True, tr=tr) for location in sensor_locations
    ]
    rows: list[SensorObservationMatrixRow] = []
    for finding in aggregate.effective_top_causes()[:4]:
        sensor_levels = _sensor_observation_levels(
            finding,
            sensor_labels=sensor_labels,
            tr=tr,
        )
        if not any(cell.relative_level_db is not None for cell in sensor_levels):
            continue
        rows.append(
            SensorObservationMatrixRow(
                source_name=human_source(finding.suspected_source, tr=tr),
                signal_label=_candidate_signal_text(finding, tr=tr),
                sensor_levels=sensor_levels,
            )
        )
    return rows


def _sensor_observation_levels(
    finding: Finding,
    *,
    sensor_labels: list[str],
    tr: Callable[..., str],
) -> list[SensorObservationCell]:
    matched_amps_by_location: dict[str, list[float]] = {}
    for point in finding.matched_points:
        amp = float(point.amp)
        if not isfinite(amp) or amp < 0.0:
            continue
        location = _display_location(point.location, short=True, tr=tr)
        matched_amps_by_location.setdefault(location, []).append(amp)
    representative_amps = {
        location: percentile(sorted(values), 0.95)
        for location, values in matched_amps_by_location.items()
        if values
    }
    if not representative_amps:
        strongest_location = str(finding.strongest_location or "").strip()
        strongest_label = (
            _display_location(strongest_location, short=True, tr=tr) if strongest_location else None
        )
        return [
            SensorObservationCell(
                location=label,
                relative_level_db=0.0 if label == strongest_label else None,
            )
            for label in sensor_labels
        ]
    strongest_amp = max(representative_amps.values())
    return [
        SensorObservationCell(
            location=label,
            relative_level_db=(
                relative_level_db_scalar(
                    representative_amps[label],
                    strongest_amp,
                )
                if label in representative_amps
                else None
            ),
        )
        for label in sensor_labels
    ]


def _build_appendix_c_data(
    *,
    primary: PrimaryCandidateContext,
    aggregate: TestRun,
    measurements: list[MeasurementRow],
    report_facts: PreparedReportFacts,
    data_trust: list[DataTrustItem],
    tr: Callable[..., str],
) -> AppendixCData:
    evidence_rows = _evidence_chain_rows(aggregate, measurements=measurements, tr=tr)
    speed_windows = [row.speed_window for row in evidence_rows if row.speed_window]
    speed_summary = (
        ", ".join(dict.fromkeys(speed_windows))
        if speed_windows
        else tr("REPORT_SPEED_SUMMARY_NONE")
    )
    return AppendixCData(
        evidence_chain_rows=evidence_rows,
        measurement_rows=measurements,
        evidence_summary=_evidence_summary_text(aggregate, primary, report_facts, tr=tr),
        measurement_guide=tr("REPORT_MEASUREMENT_GUIDE"),
        context_summary=_context_summary_text(primary, report_facts, tr=tr),
        limits_summary=_run_limits_summary_text(report_facts, tr=tr),
        speed_band_summary=speed_summary,
        phase_summary=_phase_summary_text(aggregate, report_facts, tr=tr),
        observations=_observation_texts(aggregate, tr=tr),
        suitability_items=data_trust,
    )


def _build_appendix_d_data(
    *,
    context: ReportMappingContext,
    report: Report,
    tr: Callable[..., str],
) -> AppendixDData:
    rows = [
        ReportLabelValueRow(label=tr("RUN_DATE"), value=context.date_str),
        ReportLabelValueRow(label=tr("RUN_ID"), value=report.run_id),
        ReportLabelValueRow(label=tr("TIRE_SIZE"), value=context.tire_spec_text or tr("UNKNOWN")),
    ]
    sensor_model = str(context.sensor_model or "").strip()
    if sensor_model and sensor_model.casefold() != tr("UNKNOWN").casefold():
        rows.append(ReportLabelValueRow(label=tr("SENSOR_MODEL"), value=sensor_model))
    firmware_version = str(context.firmware_version or "").strip()
    if firmware_version and firmware_version.casefold() not in {"none", tr("UNKNOWN").casefold()}:
        rows.append(ReportLabelValueRow(label=tr("FIRMWARE_VERSION"), value=firmware_version))
    rows.extend(
        [
            ReportLabelValueRow(
                label=tr("REPORT_ANALYSIS_ROWS_LABEL"),
                value=str(context.sample_count),
            ),
            ReportLabelValueRow(
                label=tr("RAW_SAMPLE_RATE_HZ_LABEL"),
                value=context.sample_rate_hz or tr("UNKNOWN"),
            ),
        ]
    )
    return AppendixDData(rows=rows)


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def map_summary(prepared: PreparedReportInput) -> ReportTemplateData:
    """Map a prepared report input into the final report template data model.

    Mapping begins by validating the prepared handoff once so the rest of the
    PDF adapter consumes a mapping-ready shape with domain reconstruction and
    report facts already guaranteed.
    """
    validated = validate_prepared_report_input(prepared)
    context = prepare_report_mapping_context(validated)
    lang = str(normalize_lang(validated.language))
    report = build_report_from_renderer_payload(
        validated.renderer_payload,
        language=lang,
    )

    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    return _build_report_template_data(
        validated,
        context=context,
        report=report,
        lang=lang,
        tr=tr,
        test_run=validated.domain_test_run,
        report_facts=validated.report_facts,
    )


def _finding_to_presentation(f: Finding) -> FindingPresentation:
    """Convert a domain ``Finding`` to a presentation-ready snapshot."""
    return FindingPresentation(
        suspected_source=str(f.suspected_source),
        severity=f.severity,
        strongest_location=f.strongest_location,
        peak_classification=f.peaks.classification,
        order=f.order,
        frequency_hz=f.frequency_hz,
        effective_confidence=f.effective_confidence,
    )


def _build_report_template_data(
    prepared: ValidatedPreparedReportInput,
    *,
    context: ReportMappingContext,
    report: Report,
    lang: str,
    tr: Callable[..., str],
    test_run: TestRun,
    report_facts: PreparedReportFacts,
) -> ReportTemplateData:
    """Resolve report sections, then delegate field assignment to the builder."""
    raw_sensor_intensity = list(report_facts.active_sensor_intensity)
    primary = resolve_primary_report_candidate(
        context=context,
        facts=report_facts.primary_candidate_facts,
        tr=tr,
        lang=lang,
    )
    observed = observed_signature(primary)
    observed.strongest_location = _display_location(primary.primary_location, tr=tr)
    system_cards = build_system_cards(
        context,
        primary,
        lang,
        tr,
    )
    recapture_mode = report_facts.action_status_key == "recapture_before_acting"
    data_trust = build_data_trust(
        suitability_checks=report_facts.suitability_checks,
        warnings=report_facts.warnings,
        lang=lang,
        tr=tr,
    )
    next_steps = (
        [NextStep(action=action) for action in report_facts.display.appendix_a.capture_changes]
        if recapture_mode
        else build_next_steps(
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
    pattern_evidence = build_pattern_evidence(
        context,
        primary,
        lang,
        tr,
    )
    findings = [_finding_to_presentation(f) for f in context.domain_aggregate.findings]
    top_causes = [
        _finding_to_presentation(f) for f in context.domain_aggregate.effective_top_causes()
    ]
    peak_rows = build_peak_rows(
        prepared.renderer_payload.peak_table_rows,
        findings=findings,
        lang=lang,
        tr=tr,
    )
    measurements = _measurement_rows(
        prepared,
        aggregate=context.domain_aggregate,
        tr=tr,
    )
    proof_summary = _proof_summary_text(context.domain_aggregate, primary, report_facts, tr=tr)
    timeline_graph = _build_timeline_graph_data(report_facts, duration_s=report.duration_s)
    verdict_page = _build_verdict_page_data(
        verdict=report_facts.display.verdict,
        proof_summary=proof_summary,
        timeline_graph=timeline_graph,
    )
    appendix_a = _build_appendix_a_data(
        appendix=report_facts.display.appendix_a,
        next_steps=next_steps,
    )
    appendix_b = _build_appendix_b_data(
        aggregate=context.domain_aggregate,
        appendix=report_facts.display.appendix_b,
        sensor_locations=context.sensor_locations_active,
        sensor_intensity=raw_sensor_intensity,
        tr=tr,
    )
    appendix_c = _build_appendix_c_data(
        primary=primary,
        aggregate=context.domain_aggregate,
        measurements=measurements,
        report_facts=report_facts,
        data_trust=data_trust,
        tr=tr,
    )
    appendix_d = _build_appendix_d_data(
        context=context,
        report=report,
        tr=tr,
    )

    return build_template_data(
        context=context,
        report=report,
        primary=primary,
        title=tr("REPORT_FOOTER_TITLE"),
        observed=observed,
        system_cards=system_cards,
        next_steps=next_steps,
        data_trust=data_trust,
        pattern_evidence=pattern_evidence,
        peak_rows=peak_rows,
        findings=findings,
        top_causes=top_causes,
        sensor_intensity=raw_sensor_intensity,
        hotspot_rows=list(report_facts.location_hotspot_rows),
        verdict_page=verdict_page,
        appendix_a=appendix_a,
        appendix_b=appendix_b,
        appendix_c=appendix_c,
        appendix_d=appendix_d,
    )
