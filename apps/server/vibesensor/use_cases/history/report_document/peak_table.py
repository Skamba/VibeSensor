"""Peak-table builders extracted from the PDF report mapper."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from vibesensor.domain import VibrationSource
from vibesensor.shared.boundaries.reporting import FindingPresentation
from vibesensor.shared.boundaries.reporting.document import PeakRow
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.report_presentation import (
    display_speed_band,
    order_label_human,
    peak_classification_text,
)
from vibesensor.shared.types.analysis_views import PeakTableRow

__all__ = [
    "build_peak_rows",
    "build_peak_row",
    "peak_row_system_label",
]

_SOURCE_I18N_KEYS: dict[str, str] = {
    VibrationSource.WHEEL_TIRE: "SOURCE_WHEEL_TIRE",
    VibrationSource.ENGINE: "SOURCE_ENGINE",
    VibrationSource.DRIVELINE: "SOURCE_DRIVELINE",
    VibrationSource.TRANSIENT_IMPACT: "SOURCE_TRANSIENT_IMPACT",
}
_PEAK_FINDING_TOLERANCE_HZ = 2.0


def build_peak_rows(
    rows: Sequence[PeakTableRow],
    *,
    findings: Sequence[FindingPresentation] = (),
    lang: str,
    tr: Callable[..., str],
) -> list[PeakRow]:
    """Build peak-table rows from prepared peak-table payload rows."""
    raw_peaks = [row for row in rows if isinstance(row, Mapping)]
    above_noise = [row for row in raw_peaks if (_as_float(row.get("strength_db")) or 0.0) > 0]
    ranked = above_noise or raw_peaks
    return [build_peak_row(row, findings=findings, lang=lang, tr=tr) for row in ranked[:8]]


def build_peak_row(
    row: PeakTableRow,
    *,
    findings: Sequence[FindingPresentation] = (),
    lang: str,
    tr: Callable[..., str],
) -> PeakRow:
    """Build one report peak row from a plot peak-table row."""
    rank_val = _as_float(row.get("rank"))
    rank = str(int(rank_val)) if rank_val is not None else "—"
    freq_val = _as_float(row.get("frequency_hz"))
    freq = f"{freq_val:.1f}" if freq_val is not None else "—"
    classification = peak_classification_text(row.get("peak_classification"), tr=tr)
    order_label_raw = str(row.get("order_label") or "").strip()
    order = order_label_human(lang, order_label_raw) if order_label_raw else classification
    peak_db_val = _as_float(row.get("p95_intensity_db"))
    peak_db = f"{peak_db_val:.1f}" if peak_db_val is not None else "—"
    strength_db_val = _as_float(row.get("strength_db"))
    strength_db = f"{strength_db_val:.1f}" if strength_db_val is not None else "—"
    speed = display_speed_band(row.get("typical_speed_band") or "—", tr=tr)
    return PeakRow(
        rank=rank,
        system=peak_row_system_label(row, findings=findings, tr=tr),
        freq_hz=freq,
        order=order,
        peak_db=peak_db,
        strength_db=strength_db,
        speed_band=speed,
        relevance=_peak_row_meaning(row, tr=tr),
    )


def peak_row_system_label(
    row: PeakTableRow,
    *,
    findings: Sequence[FindingPresentation] = (),
    tr: Callable[..., str],
) -> str:
    """Resolve the system label shown for one peak row."""
    source_hint = _peak_row_source_hint(row, findings=findings)
    i18n_key = _SOURCE_I18N_KEYS.get(source_hint)
    if i18n_key:
        return str(tr(i18n_key))
    return "—"


def _peak_row_source_hint(
    row: PeakTableRow,
    *,
    findings: Sequence[FindingPresentation],
) -> str:
    """Return the best available source hint for a peak row."""
    source_hint = str(row.get("suspected_source") or "").strip().lower()
    if source_hint in _SOURCE_I18N_KEYS:
        return source_hint
    order_source = _source_hint_for_order(row, findings=findings)
    if order_source is not None:
        return order_source
    frequency_source = _source_hint_for_frequency(row, findings=findings)
    if frequency_source is not None:
        return frequency_source
    return source_hint


def _source_hint_for_order(
    row: PeakTableRow,
    *,
    findings: Sequence[FindingPresentation],
) -> str | None:
    """Match peak rows to findings by shared order label before frequency fallback."""
    order_label = str(row.get("order_label") or "").strip().lower()
    if not order_label:
        return None
    for finding in findings:
        candidate_source = str(finding.suspected_source or "").strip().lower()
        if candidate_source not in _SOURCE_I18N_KEYS:
            continue
        if str(finding.order or "").strip().lower() == order_label:
            return candidate_source
    return None


def _source_hint_for_frequency(
    row: PeakTableRow,
    *,
    findings: Sequence[FindingPresentation],
) -> str | None:
    """Match peak rows to the closest recognized finding frequency."""
    frequency_hz = _as_float(row.get("frequency_hz"))
    if frequency_hz is None:
        return None
    best_source: str | None = None
    best_score: tuple[float, float] | None = None
    for finding in findings:
        candidate_source = str(finding.suspected_source or "").strip().lower()
        if candidate_source not in _SOURCE_I18N_KEYS or finding.frequency_hz is None:
            continue
        distance = abs(finding.frequency_hz - frequency_hz)
        if distance > _PEAK_FINDING_TOLERANCE_HZ:
            continue
        score = (distance, -finding.effective_confidence)
        if best_score is None or score < best_score:
            best_score = score
            best_source = candidate_source
    return best_source


def _peak_row_meaning(row: PeakTableRow, *, tr: Callable[..., str]) -> str:
    classification = str(row.get("peak_classification") or "").strip().lower()
    presence = _as_float(row.get("presence_ratio")) or 0.0
    if classification == "baseline_noise":
        return str(tr("PEAK_ROW_NEAR_NOISE_FLOOR"))
    if classification == "transient" and presence < 0.35:
        return str(tr("PEAK_ROW_BRIEF_EVENT"))
    if presence >= 0.7:
        return str(tr("PEAK_ROW_REPEATED_PATTERN"))
    if presence >= 0.35:
        return str(tr("PEAK_ROW_SEEN_MORE_THAN_ONCE"))
    return str(tr("PEAK_ROW_OCCASIONAL"))
