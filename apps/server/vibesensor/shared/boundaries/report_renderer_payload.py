"""Build the prepared renderer-edge payload for report mapping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vibesensor.shared.boundaries.report_payload_projection import (
    coerce_count,
    peak_table_rows,
    report_duration_s,
    summary_metadata,
)
from vibesensor.shared.types.analysis_views import PeakTableRow

__all__ = [
    "PreparedReportRendererPayload",
    "build_report_renderer_payload",
]


@dataclass(frozen=True, slots=True)
class PreparedReportRendererPayload:
    """Minimal renderer-edge payload prepared from summary or persisted analysis."""

    run_id: str
    car_name: str | None
    car_type: str | None
    report_date: str | None
    duration_s: float | None
    sample_count: int
    sensor_count: int
    peak_table_rows: tuple[PeakTableRow, ...]


def build_report_renderer_payload(
    payload: Mapping[str, object],
) -> PreparedReportRendererPayload:
    metadata = summary_metadata(payload)
    rows = payload.get("rows")
    sample_count = coerce_count(rows)
    sensor_count_raw = payload.get("sensor_count_used")
    sensor_count = coerce_count(sensor_count_raw)
    report_date = payload.get("report_date")
    report_date_str = str(report_date).strip() or None if isinstance(report_date, str) else None
    return PreparedReportRendererPayload(
        run_id=str(payload.get("run_id") or "unknown") or "unknown",
        car_name=str(metadata.get("car_name") or "").strip() or None,
        car_type=str(metadata.get("car_type") or "").strip() or None,
        report_date=report_date_str,
        duration_s=report_duration_s(payload),
        sample_count=sample_count,
        sensor_count=sensor_count,
        peak_table_rows=peak_table_rows(payload),
    )
