"""report_mapping – thin mapper from prepared report inputs to template data.

Context preparation now happens on the PDF side from the validated prepared
report-input seam, while this module keeps focused PDF mapping logic plus the
final renderer-facing orchestration. It receives an explicit prepared report
input and maps it to :class:`ReportTemplateData` for the PDF renderer.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from vibesensor import __version__
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
)
from vibesensor.report_i18n import human_location, human_source, normalize_lang, resolve_i18n
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.vibration_origin import build_origin_explanation
from vibesensor.shared.types.json_types import JsonValue
from vibesensor.use_cases.history.report_preparation import (
    PreparedReportFacts,
    PreparedReportInput,
    ValidatedPreparedReportInput,
    prepare_report_input,
    validate_prepared_report_input,
)

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
        strongest_location=primary.primary_location,
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


def build_version_marker() -> str:
    """Return the report version marker including the short git sha when present."""
    git_sha = str(os.getenv("GIT_SHA", "")).strip()
    return f"v{__version__} ({git_sha[:8]})" if git_sha else f"v{__version__}"


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


def _presented_location_confidence_key(report_facts: PreparedReportFacts) -> str:
    if (
        report_facts.action_status_key == "action_ready_caution"
        and report_facts.location_confidence_key != "weak"
    ):
        return "limited"
    return report_facts.location_confidence_key


def _display_location(value: object, *, short: bool = True, tr: Callable[..., str]) -> str:
    text = str(value or "").strip()
    if not text:
        return tr("UNKNOWN")
    return human_location(text, short=short)


def _coverage_label(
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str:
    coverage = report_facts.coverage_summary
    expected = len(coverage.expected_locations) or len(coverage.active_locations)
    active = len(coverage.active_locations)
    if expected <= 0:
        return tr("REPORT_COVERAGE_UNKNOWN")
    if not coverage.missing_locations and not coverage.partial_locations:
        return tr("REPORT_COVERAGE_ALL_SEEN", active=active, expected=expected)
    if coverage.partial_locations:
        return tr("REPORT_COVERAGE_PARTIAL", active=active, expected=expected)
    return tr("REPORT_COVERAGE_ACTIVE_OF_EXPECTED", active=active, expected=expected)


def _coverage_notes(
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> list[str]:
    coverage = report_facts.coverage_summary
    notes: list[str] = []
    if coverage.missing_locations:
        notes.append(
            tr(
                "REPORT_COVERAGE_NOTE_MISSING",
                locations=", ".join(
                    _display_location(location, short=False, tr=tr)
                    for location in coverage.missing_locations
                ),
            ),
        )
    if coverage.partial_locations:
        notes.append(
            tr(
                "REPORT_COVERAGE_NOTE_PARTIAL",
                locations=", ".join(
                    _display_location(location, short=False, tr=tr)
                    for location in coverage.partial_locations
                ),
            ),
        )
    if not notes:
        notes.append(tr("REPORT_COVERAGE_NOTE_COMPLETE"))
    return notes


def _first_nonpass_detail(data_trust: list[DataTrustItem]) -> str | None:
    for item in data_trust:
        if item.state != "pass":
            detail = str(item.detail or item.check).strip()
            if detail:
                return detail
    return None


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
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str | None:
    ranked_rows = sorted(
        report_facts.active_sensor_intensity,
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
    primary: PrimaryCandidateContext,
    *,
    report_facts: PreparedReportFacts,
    tr: Callable[..., str],
) -> str:
    location = _display_location(primary.primary_location, tr=tr)
    duration = str(report_facts.duration_text or "").strip() or tr("UNKNOWN")
    sensor_count = len(report_facts.coverage_summary.active_locations) or primary.sensor_count
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


def _proof_summary_text(
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str:
    ratio = report_facts.primary_candidate_facts.dominance_ratio
    location = _display_location(primary.primary_location, tr=tr)
    runner_up = _runner_up_corner(report_facts, tr=tr)
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


def _proof_caveat_text(
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str | None:
    if report_facts.action_status_key == "action_ready_caution":
        return None
    reason = (
        str(primary.certainty_reason or "").strip()
        if report_facts.action_status_key != "action_ready"
        else ""
    )
    if reason:
        return reason
    key = report_facts.location_confidence_key
    if key == "weak":
        return tr("REPORT_PROOF_CAVEAT_WEAK")
    if key == "mixed":
        return tr("REPORT_PROOF_CAVEAT_MIXED")
    return None


def _action_status_note_text(
    *,
    aggregate: TestRun,
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    data_trust: list[DataTrustItem],
    tr: Callable[..., str],
) -> str | None:
    if report_facts.action_status_key not in {"action_ready_caution", "recapture_before_acting"}:
        return None
    issue = _first_nonpass_detail(data_trust)
    score_note: str | None = None
    if (
        report_facts.action_status_key == "action_ready_caution"
        and report_facts.alternative_source_visible
    ):
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
    reason = score_note or _proof_caveat_text(primary, report_facts, tr=tr)
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


def _run_limits_summary_text(
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str:
    speed_window = str(primary.primary_speed or "").strip() or tr("UNKNOWN")
    if (
        report_facts.action_status_key == "action_ready_caution"
        and report_facts.alternative_source_visible
    ):
        return tr("REPORT_RUN_LIMITS_RECAPTURE_RECIPE", speed=speed_window)
    note = _proof_caveat_text(primary, report_facts, tr=tr)
    return note or tr("REPORT_CAPTURE_ISSUE_GENERIC")


def _candidate_signal_text(finding: Finding, *, tr: Callable[..., str]) -> str:
    if finding.signature_labels:
        return ", ".join(finding.signature_labels[:2])
    if finding.order:
        return finding.order
    if finding.frequency_hz is not None:
        return f"{finding.frequency_hz:.1f} Hz"
    return tr("REPORT_SIGNAL_FALLBACK")


def _candidate_reason_text(finding: Finding, *, tr: Callable[..., str]) -> str:
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
) -> list[RankedCandidateRow]:
    candidates = list(aggregate.effective_top_causes()[:3])
    rows: list[RankedCandidateRow] = []
    for index, finding in enumerate(candidates):
        rows.append(
            RankedCandidateRow(
                source_name=human_source(finding.suspected_source, tr=tr),
                confidence_pct=_confidence_pct_text(finding),
                inspect_first=_display_location(finding.strongest_location, tr=tr),
                path_role=f"{index + 1}. {_path_role_text(index, tr=tr)}",
                reason=_candidate_reason_text(finding, tr=tr),
            ),
        )
    return rows


def _evidence_summary_text(
    aggregate: TestRun,
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    *,
    tr: Callable[..., str],
) -> str:
    matched_windows = report_facts.primary_candidate_facts.matched_evidence_window_count
    speed_window = str(primary.primary_speed or "").strip() or tr("UNKNOWN")
    source = primary.primary_system
    location = _display_location(primary.primary_location, tr=tr)
    alternative = (
        human_source(report_facts.alternative_source, tr=tr)
        if report_facts.alternative_source_visible and report_facts.alternative_source is not None
        else None
    )
    alternative_finding = (
        aggregate.effective_top_causes()[1]
        if report_facts.alternative_source_visible and len(aggregate.effective_top_causes()) > 1
        else None
    )
    if alternative is not None and matched_windows is not None:
        if alternative_finding is not None:
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


def _next_if_primary_clean(
    aggregate: TestRun,
    *,
    tr: Callable[..., str],
) -> str:
    candidates = list(aggregate.effective_top_causes()[:2])
    if len(candidates) < 2:
        return tr("REPORT_PRIMARY_CLEAN_GENERIC")
    alternative = candidates[1]
    return tr(
        "REPORT_PRIMARY_CLEAN_ALT",
        source=human_source(alternative.suspected_source, tr=tr),
        location=_display_location(alternative.strongest_location, tr=tr),
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


def _phase_summary_text(aggregate: TestRun, *, tr: Callable[..., str]) -> str:
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


def _build_verdict_page_data(
    *,
    aggregate: TestRun,
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
    data_trust: list[DataTrustItem],
    tr: Callable[..., str],
) -> VerdictPageData:
    recapture_before_acting = report_facts.action_status_key == "recapture_before_acting"
    ranked_candidates = list(aggregate.effective_top_causes()[:2])
    return VerdictPageData(
        speed_window_label=str(primary.primary_speed or "").strip() or None,
        suspected_source=(
            tr("REPORT_INCONCLUSIVE_SOURCE") if recapture_before_acting else primary.primary_system
        ),
        inspect_first=(
            None if recapture_before_acting else _display_location(primary.primary_location, tr=tr)
        ),
        action_status=_action_status_text(report_facts.action_status_key, tr=tr),
        action_status_note=_action_status_note_text(
            aggregate=aggregate,
            primary=primary,
            report_facts=report_facts,
            data_trust=data_trust,
            tr=tr,
        ),
        reason_sentence=(
            tr("REPORT_REASON_RECAPTURE_GENERIC")
            if recapture_before_acting
            else _build_primary_reason_sentence(primary, report_facts=report_facts, tr=tr)
        ),
        dominant_corner=_display_location(primary.primary_location, tr=tr),
        runner_up_corner=_runner_up_corner(report_facts, tr=tr),
        location_confidence=_location_confidence_text(
            _presented_location_confidence_key(report_facts),
            tr=tr,
        ),
        coverage_label=_coverage_label(report_facts, tr=tr),
        also_consider=(
            _source_with_confidence(ranked_candidates[1], tr=tr)
            if not recapture_before_acting
            and report_facts.alternative_source_visible
            and len(ranked_candidates) > 1
            else None
        ),
        proof_summary=_proof_summary_text(primary, report_facts, tr=tr),
        proof_caveat=_proof_caveat_text(primary, report_facts, tr=tr),
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


def _build_appendix_a_data(
    *,
    aggregate: TestRun,
    report_facts: PreparedReportFacts,
    next_steps: list[NextStep],
    data_trust: list[DataTrustItem],
    tr: Callable[..., str],
) -> AppendixAData:
    ranked = _ranked_candidates(aggregate, tr=tr)
    if report_facts.action_status_key == "recapture_before_acting":
        return AppendixAData(
            mode="recapture",
            capture_issues=_capture_issue_lines(data_trust, tr=tr),
            capture_changes=[step.action for step in next_steps],
            capture_conditions=_capture_condition_lines(report_facts, tr=tr),
        )
    alternative_source = (
        tr(
            "REPORT_SOURCE_WITH_CONFIDENCE",
            source=ranked[1].source_name,
            confidence=ranked[1].confidence_pct,
        )
        if report_facts.alternative_source_visible and len(ranked) > 1 and ranked[1].confidence_pct
        else ranked[1].source_name
        if report_facts.alternative_source_visible and len(ranked) > 1
        else None
    )
    return AppendixAData(
        mode="workflow",
        primary_source=(
            tr(
                "REPORT_SOURCE_WITH_CONFIDENCE",
                source=ranked[0].source_name,
                confidence=ranked[0].confidence_pct,
            )
            if ranked and ranked[0].confidence_pct
            else ranked[0].source_name
            if ranked
            else None
        ),
        alternative_source=alternative_source,
        why_primary_first=(ranked[0].reason if ranked else None),
        why_alternative_next=(
            ranked[1].reason
            if report_facts.alternative_source_visible and len(ranked) > 1
            else None
        ),
        next_if_clean=_next_if_primary_clean(aggregate, tr=tr),
        ranked_candidates=ranked,
    )


def _build_appendix_b_data(
    *,
    primary: PrimaryCandidateContext,
    report_facts: PreparedReportFacts,
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
    runner_up = ranked_rows[1].location if len(ranked_rows) > 1 else None
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
    dominance_ratio = report_facts.primary_candidate_facts.dominance_ratio
    return AppendixBData(
        dominant_corner=_display_location(primary.primary_location, tr=tr),
        runner_up_corner=(_display_location(runner_up, tr=tr) if runner_up is not None else None),
        dominance_ratio_text=(
            tr("REPORT_DOMINANCE_RATIO_TEXT", ratio=f"{dominance_ratio:.2f}")
            if dominance_ratio is not None
            else tr("REPORT_DOMINANCE_RATIO_UNKNOWN")
        ),
        location_confidence=_location_confidence_text(
            _presented_location_confidence_key(report_facts),
            tr=tr,
        ),
        coverage_label=_coverage_label(report_facts, tr=tr),
        coverage_notes=_coverage_notes(report_facts, tr=tr),
        intensity_rows=intensity_rows,
    )


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
        limits_summary=_run_limits_summary_text(primary, report_facts, tr=tr),
        speed_band_summary=speed_summary,
        phase_summary=_phase_summary_text(aggregate, tr=tr),
        observations=_observation_texts(aggregate, tr=tr),
        suitability_items=data_trust,
    )


def _build_appendix_d_data(
    *,
    context: ReportMappingContext,
    report: Report,
    version_marker: str,
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
            ReportLabelValueRow(label=tr("REPORT_VERSION"), value=version_marker),
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
    system_cards = build_system_cards(
        context,
        primary,
        lang,
        tr,
    )
    recapture_mode = report_facts.action_status_key == "recapture_before_acting"
    next_steps = build_next_steps(
        recommended_actions=report_facts.recommended_actions,
        primary_location=primary.primary_location,
        tier=primary.tier,
        cert_reason=primary.certainty_reason or tr("REPORT_CAPTURE_ISSUE_GENERIC"),
        recapture_mode=recapture_mode,
        lang=lang,
        tr=tr,
    )
    data_trust = build_data_trust(
        suitability_checks=report_facts.suitability_checks,
        warnings=report_facts.warnings,
        lang=lang,
        tr=tr,
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
    version_marker = build_version_marker()
    measurements = _measurement_rows(
        prepared,
        aggregate=context.domain_aggregate,
        tr=tr,
    )
    verdict_page = _build_verdict_page_data(
        aggregate=context.domain_aggregate,
        primary=primary,
        report_facts=report_facts,
        data_trust=data_trust,
        tr=tr,
    )
    appendix_a = _build_appendix_a_data(
        aggregate=context.domain_aggregate,
        report_facts=report_facts,
        next_steps=next_steps,
        data_trust=data_trust,
        tr=tr,
    )
    appendix_b = _build_appendix_b_data(
        primary=primary,
        report_facts=report_facts,
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
        version_marker=version_marker,
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
        version_marker=version_marker,
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
