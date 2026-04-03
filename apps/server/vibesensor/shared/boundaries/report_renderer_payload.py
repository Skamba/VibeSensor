"""Build the prepared renderer-edge payload for report mapping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vibesensor.shared.boundaries.report_summary_codec import (
    report_summary_from_mapping,
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
    recorded_utc_offset_seconds: int | None = None


def build_report_renderer_payload(
    payload: Mapping[str, object],
) -> PreparedReportRendererPayload:
    """Return the normalized renderer-edge payload derived from a report summary."""
    summary = report_summary_from_mapping(payload)
    typed_metadata = summary.metadata
    return PreparedReportRendererPayload(
        run_id=summary.run_id,
        car_name=typed_metadata.car_name if typed_metadata is not None else None,
        car_type=typed_metadata.car_type if typed_metadata is not None else None,
        report_date=summary.report_date,
        duration_s=summary.duration_s,
        sample_count=summary.sample_count,
        sensor_count=summary.sensor_count,
        peak_table_rows=summary.peak_table_rows,
        recorded_utc_offset_seconds=(
            typed_metadata.recorded_utc_offset_seconds if typed_metadata is not None else None
        ),
    )
