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
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
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
    metadata = dict(summary_metadata(payload))
    raw_run_id = str(payload.get("run_id") or "").strip()
    if raw_run_id and "run_id" not in metadata:
        metadata["run_id"] = raw_run_id
    typed_metadata = run_metadata_from_mapping(metadata) if metadata else None
    rows = payload.get("rows")
    sample_count = coerce_count(rows)
    sensor_count_raw = payload.get("sensor_count_used")
    sensor_count = coerce_count(sensor_count_raw)
    report_date_str = _normalized_report_date(payload.get("report_date"))
    if report_date_str is None and typed_metadata is not None:
        report_date_str = _normalized_report_date(typed_metadata.report_date)
    return PreparedReportRendererPayload(
        run_id=raw_run_id or (typed_metadata.run_id if typed_metadata is not None else "unknown"),
        car_name=typed_metadata.car_name if typed_metadata is not None else None,
        car_type=typed_metadata.car_type if typed_metadata is not None else None,
        report_date=report_date_str,
        duration_s=report_duration_s(payload),
        sample_count=sample_count,
        sensor_count=sensor_count,
        peak_table_rows=peak_table_rows(payload),
        recorded_utc_offset_seconds=(
            typed_metadata.recorded_utc_offset_seconds if typed_metadata is not None else None
        ),
    )


def _normalized_report_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized_report_date = value.strip()
    return normalized_report_date or None
