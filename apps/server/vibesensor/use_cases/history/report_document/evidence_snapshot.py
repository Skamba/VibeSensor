"""Evidence snapshot row builders shared by page-1 proof and Appendix C."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.report_i18n import human_source
from vibesensor.shared.boundaries.reporting import PreparedReportFacts
from vibesensor.shared.boundaries.reporting.document import ReportLabelValueRow
from vibesensor.shared.report_presentation import (
    confidence_snapshot_text,
    display_location,
)

__all__ = ["build_evidence_snapshot_rows"]


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
    evidence = report_facts.evidence
    if evidence.data_basis == "raw_backed":
        return tr(
            "REPORT_EVIDENCE_BASIS_RAW",
            samples=str(max(0, evidence.raw_backed_sample_count)),
        )
    return tr("REPORT_EVIDENCE_BASIS_SUMMARY")


def _support_window_text(report_facts: PreparedReportFacts, *, tr: Callable[..., str]) -> str:
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
    evidence = report_facts.evidence
    low = evidence.stable_frequency_min_hz
    high = evidence.stable_frequency_max_hz
    if low is None or high is None:
        return tr("REPORT_STABLE_FREQUENCY_UNKNOWN")
    if abs(high - low) < 0.05:
        return tr("REPORT_STABLE_FREQUENCY_SINGLE", hz=f"{low:.1f}")
    return tr("REPORT_STABLE_FREQUENCY_BAND", low=f"{low:.1f}", high=f"{high:.1f}")


def _supporting_sensors_text(report_facts: PreparedReportFacts, *, tr: Callable[..., str]) -> str:
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
