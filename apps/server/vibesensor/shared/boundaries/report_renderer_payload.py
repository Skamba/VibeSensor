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
from vibesensor.shared.time_utils import coerce_utc_offset_seconds
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
    recorded_utc_offset_seconds: int | None = None


def build_report_renderer_payload(
    payload: Mapping[str, object],
) -> PreparedReportRendererPayload:
    """Return the normalized renderer-edge payload derived from a report summary."""
    metadata = summary_metadata(payload)
    rows = payload.get("rows")
    sample_count = coerce_count(rows)
    sensor_count_raw = payload.get("sensor_count_used")
    sensor_count = coerce_count(sensor_count_raw)
    report_date = payload.get("report_date")
    report_date_str = None
    if isinstance(report_date, str):
        normalized_report_date = report_date.strip()
        report_date_str = normalized_report_date or None
    recorded_utc_offset_seconds = coerce_utc_offset_seconds(
        metadata.get("recorded_utc_offset_seconds"),
    )
    car_name, car_type = _car_identity_from_metadata(metadata)
    return PreparedReportRendererPayload(
        run_id=str(payload.get("run_id") or "unknown") or "unknown",
        car_name=car_name,
        car_type=car_type,
        report_date=report_date_str,
        duration_s=report_duration_s(payload),
        sample_count=sample_count,
        sensor_count=sensor_count,
        peak_table_rows=peak_table_rows(payload),
        recorded_utc_offset_seconds=recorded_utc_offset_seconds,
    )


def _car_identity_from_metadata(metadata: Mapping[str, object]) -> tuple[str | None, str | None]:
    raw_snapshot = metadata.get("active_car_snapshot")
    if not isinstance(raw_snapshot, Mapping):
        return None, None
    raw_name = raw_snapshot.get("name")
    raw_type = raw_snapshot.get("type")
    name = str(raw_name).strip() if isinstance(raw_name, str) else ""
    car_type = str(raw_type).strip() if isinstance(raw_type, str) else ""
    return (name or None, car_type or None)
