"""Measurement and observation matrix builders for PDF mapping."""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite

from vibesensor.shared.boundaries.reporting.document import (
    EvidenceChainRow,
    MeasurementRow,
    SensorObservationCell,
    SensorObservationMatrixRow,
)
from vibesensor.domain import Finding, TestRun
from vibesensor.report_i18n import human_source
from vibesensor.shared.boundaries.reporting.summary_codec import NormalizedReportSummary
from vibesensor.shared.report_presentation import (
    candidate_signal_text,
    display_location,
    source_with_confidence,
)
from vibesensor.vibration_strength import percentile, relative_level_db_scalar

__all__ = [
    "_evidence_chain_rows",
    "_measurement_rows",
    "_sensor_observation_matrix_rows",
]


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
    summary: NormalizedReportSummary,
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
    for index, row in enumerate(summary.peak_table_rows[:4], start=1):
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
            candidate_signal_text(matched_finding, tr=tr)
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
                    display_location(matched_finding.strongest_location, tr=tr)
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
                source_name=source_with_confidence(finding, tr=tr),
                supporting_signal_label=candidate_signal_text(finding, tr=tr),
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
                dominant_location=display_location(finding.strongest_location, tr=tr),
                ambiguity_note=ambiguity_note,
            ),
        )
    return rows


def _sensor_observation_matrix_rows(
    aggregate: TestRun,
    *,
    sensor_locations: list[str],
    tr: Callable[..., str],
) -> list[SensorObservationMatrixRow]:
    if not sensor_locations:
        return []
    sensor_labels = [display_location(location, short=True, tr=tr) for location in sensor_locations]
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
                signal_label=candidate_signal_text(finding, tr=tr),
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
        location = display_location(point.location, short=True, tr=tr)
        matched_amps_by_location.setdefault(location, []).append(amp)
    representative_amps = {
        location: percentile(sorted(values), 0.95)
        for location, values in matched_amps_by_location.items()
        if values
    }
    if not representative_amps:
        strongest_location = str(finding.strongest_location or "").strip()
        strongest_label = (
            display_location(strongest_location, short=True, tr=tr) if strongest_location else None
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
