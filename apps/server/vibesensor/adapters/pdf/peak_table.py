"""Peak-table builders extracted from the PDF report mapper."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.adapters.pdf.presentation import order_label_human, peak_classification_text
from vibesensor.adapters.pdf.report_data import PeakRow
from vibesensor.adapters.pdf.report_types import PeakTableRow
from vibesensor.domain import VibrationSource
from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.json_utils import as_float_or_none as _as_float

__all__ = [
    "build_peak_row",
    "build_peak_rows_from_plots",
    "peak_row_system_label",
]


def build_peak_rows_from_plots(
    summary: AnalysisSummary,
    *,
    lang: str,
    tr: Callable[..., str],
) -> list[PeakRow]:
    """Build peak-table rows from the plots section."""
    plots = summary.get("plots")
    if plots is None:
        return []
    raw_peaks = [row for row in (plots.get("peaks_table", []) or []) if isinstance(row, dict)]
    above_noise = [row for row in raw_peaks if (_as_float(row.get("strength_db")) or 0.0) > 0]
    ranked = above_noise or raw_peaks
    return [build_peak_row(row, lang=lang, tr=tr) for row in ranked[:8]]


def build_peak_row(row: PeakTableRow, *, lang: str, tr: Callable[..., str]) -> PeakRow:
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
    speed = str(row.get("typical_speed_band") or "—")
    presence = _as_float(row.get("presence_ratio")) or 0.0
    score = _as_float(row.get("persistence_score")) or 0.0
    return PeakRow(
        rank=rank,
        system=peak_row_system_label(row, tr=tr),
        freq_hz=freq,
        order=order,
        peak_db=peak_db,
        strength_db=strength_db,
        speed_band=speed,
        relevance=f"{classification} · {presence:.0%} {tr('PRESENCE')} · {tr('SCORE')} {score:.2f}",
    )


def peak_row_system_label(row: PeakTableRow, *, tr: Callable[..., str]) -> str:
    """Resolve the system label shown for one peak row."""
    source_hint = str(row.get("suspected_source") or "").strip().lower()
    source_map: dict[str, str] = {
        VibrationSource.WHEEL_TIRE: "SOURCE_WHEEL_TIRE",
        VibrationSource.ENGINE: "SOURCE_ENGINE",
        VibrationSource.DRIVELINE: "SOURCE_DRIVELINE",
        VibrationSource.TRANSIENT_IMPACT: "SOURCE_TRANSIENT_IMPACT",
    }
    i18n_key = source_map.get(source_hint)
    if i18n_key:
        return str(tr(i18n_key))
    return "—"
