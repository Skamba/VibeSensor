"""Peak-row and location-hotspot shaping for report mapping."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from statistics import mean as _mean

from ..report.report_data import PeakRow
from ..runlog import as_float_or_none as _as_float
from ._types import SummaryData
from .plot_peak_table import PeakTableRow
from .report_mapping_common import order_label_human, peak_classification_text


def build_peak_rows_from_plots(
    summary: SummaryData,
    *,
    lang: str,
    tr: Callable,
) -> list[PeakRow]:
    """Build peak-table rows from the plots section."""
    plots = summary.get("plots")
    if plots is None:
        return []
    raw_peaks = [row for row in (plots.get("peaks_table", []) or []) if isinstance(row, dict)]
    above_noise = [
        row
        for row in raw_peaks
        if ((_strength_db := _as_float(row.get("strength_db"))) is None or _strength_db > 0)
    ]
    return [build_peak_row(row, lang=lang, tr=tr) for row in above_noise[:8]]


def build_peak_row(row: PeakTableRow, *, lang: str, tr: Callable) -> PeakRow:
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
        system=peak_row_system_label(row, order=order, tr=tr),
        freq_hz=freq,
        order=order,
        peak_db=peak_db,
        strength_db=strength_db,
        speed_band=speed,
        relevance=f"{classification} · {presence:.0%} {tr('PRESENCE')} · {tr('SCORE')} {score:.2f}",
    )


def peak_row_system_label(
    row: PeakTableRow, *, order: str, tr: Callable[..., str]
) -> str:
    """Resolve the system label shown for one peak row."""
    order_lower = order.lower()
    source_hint = str(row.get("source") or row.get("suspected_source") or "").strip().lower()
    if source_hint == "wheel/tire" or "wheel" in order_lower:
        return str(tr("SOURCE_WHEEL_TIRE"))
    if source_hint == "engine" or "engine" in order_lower:
        return str(tr("SOURCE_ENGINE"))
    if source_hint == "driveline" or "driveshaft" in order_lower or "drive" in order_lower:
        return str(tr("SOURCE_DRIVELINE"))
    if "transient" in order_lower:
        return str(tr("SOURCE_TRANSIENT_IMPACT"))
    return "—"


def compute_location_hotspot_rows(sensor_intensity: list[dict]) -> list[dict]:
    """Pre-compute location hotspot rows from sensor intensity data."""
    if not sensor_intensity:
        return []
    amp_by_location = collect_location_intensity(sensor_intensity)
    hotspot_rows = [
        {
            "location": location,
            "count": len(amps),
            "unit": "db",
            "peak_value": max(amps),
            "mean_value": _mean(amps),
        }
        for location, amps in amp_by_location.items()
    ]
    hotspot_rows.sort(
        key=lambda row: (
            _as_float(row.get("peak_value")) or 0.0,
            _as_float(row.get("mean_value")) or 0.0,
        ),
        reverse=True,
    )
    return hotspot_rows


def collect_location_intensity(sensor_intensity: list[dict]) -> dict[str, list[float]]:
    """Collect per-location intensity values from summary sensor intensity rows."""
    amp_by_location: dict[str, list[float]] = defaultdict(list)
    for row in sensor_intensity:
        if not isinstance(row, dict):
            continue
        location = str(row.get("location") or "").strip()
        p95_val = _as_float(row.get("p95_intensity_db"))
        p95 = p95_val if p95_val is not None else _as_float(row.get("mean_intensity_db"))
        if location and p95 is not None and p95 > 0:
            amp_by_location[location].append(p95)
    return amp_by_location
