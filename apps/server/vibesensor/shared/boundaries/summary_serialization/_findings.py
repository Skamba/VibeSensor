"""Finding-specific summary serialization helpers."""

from __future__ import annotations

from statistics import median as _median

from vibesensor.domain import (
    Finding as DomainFinding,
)
from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.boundaries.finding import finding_payload_from_domain
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.history_analysis_contracts import FindingPayload
from vibesensor.shared.types.json_types import is_json_object


def serialize_findings(findings: tuple[DomainFinding, ...]) -> list[FindingPayload]:
    return [finding_payload_from_domain(finding) for finding in findings]


def annotate_peaks_with_order_labels(summary: AnalysisSummary) -> None:
    """Back-fill peak-table order labels by matching order findings to peak rows."""
    plots = summary.get("plots")
    if not is_json_object(plots):
        return
    raw_peaks_table = plots.get("peaks_table", [])
    peaks_table = (
        [row for row in raw_peaks_table if is_json_object(row)]
        if isinstance(raw_peaks_table, list)
        else []
    )
    raw_findings = summary.get("findings", [])
    findings = (
        [finding for finding in raw_findings if is_json_object(finding)]
        if isinstance(raw_findings, list)
        else []
    )
    if not peaks_table or not findings:
        return

    order_annotations: list[tuple[float, str, str]] = []
    for finding in findings:
        if finding.get("finding_id") != "F_ORDER":
            continue
        label = str(finding.get("frequency_hz_or_order") or "").strip()
        suspected_source = str(finding.get("suspected_source") or "").strip()
        matched_points = finding.get("matched_points")
        if not label or not isinstance(matched_points, list) or not matched_points:
            continue
        matched_freqs = [
            value
            for point in matched_points
            if isinstance(point, dict) and (value := _as_float(point.get("matched_hz"))) is not None
        ]
        if matched_freqs:
            order_annotations.append((_median(matched_freqs), label, suspected_source))

    if not order_annotations:
        return

    tolerance_hz = 2.0
    used_rows: set[int] = set()
    for median_hz, label, suspected_source in order_annotations:
        best_idx: int | None = None
        best_dist = tolerance_hz + 1.0
        for idx, row in enumerate(peaks_table):
            if idx in used_rows:
                continue
            freq = _as_float(row.get("frequency_hz"))
            if freq is None:
                continue
            dist = abs(freq - median_hz)
            if dist < best_dist:
                best_idx = idx
                best_dist = dist
        if best_idx is not None and best_dist <= tolerance_hz:
            peaks_table[best_idx]["order_label"] = label
            peaks_table[best_idx]["suspected_source"] = suspected_source
            used_rows.add(best_idx)
