"""Evidence snapshot row builders shared by page-1 proof and Appendix C."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from vibesensor.report_i18n import human_source
from vibesensor.shared.boundaries.reporting import PreparedReportFacts
from vibesensor.shared.boundaries.reporting.document import ReportLabelValueRow
from vibesensor.shared.report_presentation import (
    confidence_snapshot_text,
    display_location,
)

__all__ = ["build_evidence_snapshot_rows"]

if TYPE_CHECKING:
    from vibesensor.shared.boundaries.reporting.summary import ReportWholeRunDiagnosisSummary


def build_evidence_snapshot_rows(
    report_facts: PreparedReportFacts,
    *,
    compact: bool,
    tr: Callable[..., str],
) -> tuple[ReportLabelValueRow, ...]:
    """Build localized evidence snapshot rows for report proof surfaces."""

    rows: list[ReportLabelValueRow] = [
        ReportLabelValueRow(
            label=tr("CONFIDENCE_LABEL"),
            value=confidence_snapshot_text(report_facts.confidence, tr=tr),
        ),
        ReportLabelValueRow(
            label=tr("REPORT_EVIDENCE_BASIS_LABEL"),
            value=_data_basis_text(report_facts, tr=tr),
        ),
        ReportLabelValueRow(
            label=tr("REPORT_SUPPORT_WINDOW_SUMMARY_LABEL"),
            value=_support_window_text(report_facts, tr=tr),
        ),
        ReportLabelValueRow(
            label=tr("REPORT_STABLE_FREQUENCY_LABEL"),
            value=_stable_frequency_text(report_facts, tr=tr),
        ),
    ]
    if not compact:
        rows.extend(
            [
                ReportLabelValueRow(
                    label=tr("REPORT_SUPPORTING_SENSORS_LABEL"),
                    value=_supporting_sensors_text(report_facts, tr=tr),
                ),
                ReportLabelValueRow(
                    label=tr("REPORT_COUNTEREVIDENCE_LABEL"),
                    value=_counterevidence_text(report_facts, tr=tr),
                ),
            ]
        )
    return tuple(row for row in rows if row.value)


def _data_basis_text(report_facts: PreparedReportFacts, *, tr: Callable[..., str]) -> str:
    diagnosis = report_facts.primary_diagnosis
    if diagnosis is not None and diagnosis.data_basis == "raw_backed":
        raw_backed_samples = 0
        for factor in diagnosis.support_factors:
            if (
                factor.factor_key == "raw_backed"
                and factor.details.raw_backed_sample_count is not None
            ):
                raw_backed_samples = factor.details.raw_backed_sample_count
                break
        return tr(
            "REPORT_EVIDENCE_BASIS_RAW",
            samples=str(max(0, raw_backed_samples)),
        )
    if diagnosis is not None and diagnosis.data_basis == "summary_only":
        return tr("REPORT_EVIDENCE_BASIS_SUMMARY")
    evidence = report_facts.evidence
    if evidence.data_basis == "raw_backed":
        return tr(
            "REPORT_EVIDENCE_BASIS_RAW",
            samples=str(max(0, evidence.raw_backed_sample_count)),
        )
    return tr("REPORT_EVIDENCE_BASIS_SUMMARY")


def _support_window_text(report_facts: PreparedReportFacts, *, tr: Callable[..., str]) -> str:
    diagnosis = report_facts.primary_diagnosis
    if diagnosis is not None:
        count = diagnosis.supporting_window_count
        duration_s = diagnosis.supporting_duration_s
        if count is None or count <= 0:
            return tr("REPORT_SUPPORT_WINDOW_SUMMARY_NONE")
        if duration_s is not None and duration_s > 0:
            return tr(
                "REPORT_SUPPORT_WINDOW_SUMMARY_FULL",
                count=str(count),
                duration=f"{duration_s:.1f}",
            )
        return tr("REPORT_SUPPORT_WINDOW_SUMMARY_COUNT_ONLY", count=str(count))
    evidence = report_facts.evidence
    count = evidence.supporting_window_count
    duration_s = evidence.supporting_duration_s
    if count is None or count <= 0:
        return tr("REPORT_SUPPORT_WINDOW_SUMMARY_NONE")
    if duration_s is not None and duration_s > 0:
        return tr(
            "REPORT_SUPPORT_WINDOW_SUMMARY_FULL",
            count=str(count),
            duration=f"{duration_s:.1f}",
        )
    return tr("REPORT_SUPPORT_WINDOW_SUMMARY_COUNT_ONLY", count=str(count))


def _stable_frequency_text(report_facts: PreparedReportFacts, *, tr: Callable[..., str]) -> str:
    diagnosis = report_facts.primary_diagnosis
    if diagnosis is not None:
        low = diagnosis.stable_frequency_min_hz
        high = diagnosis.stable_frequency_max_hz
        if low is None or high is None:
            return tr("REPORT_STABLE_FREQUENCY_UNKNOWN")
        if abs(high - low) < 0.05:
            return tr("REPORT_STABLE_FREQUENCY_SINGLE", hz=f"{low:.1f}")
        return tr("REPORT_STABLE_FREQUENCY_BAND", low=f"{low:.1f}", high=f"{high:.1f}")
    evidence = report_facts.evidence
    low = evidence.stable_frequency_min_hz
    high = evidence.stable_frequency_max_hz
    if low is None or high is None:
        return tr("REPORT_STABLE_FREQUENCY_UNKNOWN")
    if abs(high - low) < 0.05:
        return tr("REPORT_STABLE_FREQUENCY_SINGLE", hz=f"{low:.1f}")
    return tr("REPORT_STABLE_FREQUENCY_BAND", low=f"{low:.1f}", high=f"{high:.1f}")


def _supporting_sensors_text(report_facts: PreparedReportFacts, *, tr: Callable[..., str]) -> str:
    diagnosis = report_facts.primary_diagnosis
    if diagnosis is not None and diagnosis.supporting_sensor_count is not None:
        if diagnosis.dominant_location:
            return tr(
                "REPORT_SUPPORTING_SENSOR_ENTRY",
                location=display_location(diagnosis.dominant_location, tr=tr),
                count=str(diagnosis.supporting_sensor_count),
            )
        if diagnosis.supporting_sensor_count <= 0:
            return tr("REPORT_SUPPORTING_SENSORS_NONE")
    evidence = report_facts.evidence
    if not evidence.supporting_location_counts:
        return tr("REPORT_SUPPORTING_SENSORS_NONE")
    parts = [
        tr(
            "REPORT_SUPPORTING_SENSOR_ENTRY",
            location=display_location(location, tr=tr),
            count=str(count),
        )
        for location, count in evidence.supporting_location_counts
    ]
    return ", ".join(parts)


def _counterevidence_text(report_facts: PreparedReportFacts, *, tr: Callable[..., str]) -> str:
    diagnosis = report_facts.primary_diagnosis
    if diagnosis is not None:
        diagnosis_notes = _diagnosis_counterevidence_texts(diagnosis=diagnosis, tr=tr)
        if diagnosis_notes:
            return "; ".join(diagnosis_notes[:2])
    evidence = report_facts.evidence
    notes: list[str] = []
    if evidence.alternative_source is not None:
        notes.append(
            tr(
                "REPORT_COUNTEREVIDENCE_ALT_SOURCE",
                source=human_source(evidence.alternative_source, tr=tr),
            )
        )
    if evidence.has_weak_spatial_separation:
        notes.append(tr("REPORT_COUNTEREVIDENCE_WEAK_SPATIAL"))
    if evidence.has_reference_gap:
        notes.append(tr("REPORT_COUNTEREVIDENCE_REFERENCE_GAP"))
    if not notes:
        return tr("REPORT_COUNTEREVIDENCE_NONE")
    return "; ".join(notes)


def _diagnosis_counterevidence_texts(
    *,
    diagnosis: ReportWholeRunDiagnosisSummary,
    tr: Callable[..., str],
) -> tuple[str, ...]:
    notes: list[str] = []
    counter_keys = {factor.factor_key for factor in diagnosis.counterevidence_factors}
    if "close_alternative" in counter_keys and diagnosis.alternative_source is not None:
        notes.append(
            tr(
                "REPORT_COUNTEREVIDENCE_ALT_SOURCE",
                source=human_source(diagnosis.alternative_source, tr=tr),
            )
        )
    if "weak_spatial" in counter_keys or diagnosis.weak_spatial_separation:
        notes.append(tr("REPORT_COUNTEREVIDENCE_WEAK_SPATIAL"))
    if "incomplete_reference" in counter_keys or diagnosis.has_reference_gap:
        notes.append(tr("REPORT_COUNTEREVIDENCE_REFERENCE_GAP"))
    if "summary_only" in counter_keys:
        notes.append(tr("REPORT_CONFIDENCE_CAVEAT_SUMMARY_ONLY"))
    if "legacy_context" in counter_keys:
        notes.append(tr("REPORT_CONFIDENCE_CAVEAT_LEGACY_CONTEXT"))
    if "speed_context_gaps" in counter_keys:
        notes.append(tr("REPORT_CONFIDENCE_CAVEAT_SPEED_CONTEXT_GAPS"))
    if "rpm_context_gaps" in counter_keys:
        notes.append(tr("REPORT_CONFIDENCE_CAVEAT_RPM_CONTEXT_GAPS"))
    return tuple(notes)
