"""Measurement and observation matrix builders for PDF mapping."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.domain import Finding, TestRun
from vibesensor.shared.boundaries.reporting.document import (
    EvidenceChainRow,
    MeasurementRow,
)
from vibesensor.shared.boundaries.reporting.facts import ReportRunFacts
from vibesensor.shared.report_presentation import (
    candidate_signal_text,
    display_location,
    display_speed_band,
    human_source,
    order_label_human,
    source_with_confidence,
)

__all__ = [
    "_evidence_chain_rows",
    "_measurement_rows",
]


def _measurement_signal_label(row: dict[str, object] | object, *, tr: Callable[..., str]) -> str:
    if isinstance(row, dict):
        order_label = str(row.get("order_label") or "").strip()
        if order_label:
            return order_label_human(_report_lang(tr), order_label)
        frequency = row.get("frequency_hz")
        if isinstance(frequency, (int, float)):
            return f"{float(frequency):.1f} Hz"
    return tr("REPORT_SIGNAL_FALLBACK")


def _measurement_rows(
    run_facts: ReportRunFacts,
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
    for index, row in enumerate(run_facts.peak_table_rows[:4], start=1):
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
                speed_window=display_speed_band(row.get("typical_speed_band"), tr=tr) or None,
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
                speed_window=display_speed_band(
                    finding.evidence.focused_speed_band
                    if finding.evidence and finding.evidence.focused_speed_band
                    else finding.strongest_speed_band,
                    tr=tr,
                )
                or None,
                dominant_location=display_location(finding.strongest_location, tr=tr),
                ambiguity_note=ambiguity_note,
            ),
        )
    return rows


def _report_lang(tr: Callable[..., str]) -> str:
    try:
        return "nl" if tr("UNKNOWN") == "Onbekend" else "en"
    except Exception:
        return "en"
