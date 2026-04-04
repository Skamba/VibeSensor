"""Traceability builders for report document composition."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.shared.boundaries.reporting.document import ReportLabelValueRow

__all__ = ["build_traceability_rows"]


def build_traceability_rows(
    *,
    date_str: str,
    run_id: str,
    tire_spec_text: str | None,
    sensor_model: str | None,
    firmware_version: str | None,
    sample_count: int,
    sample_rate_hz: str | None,
    tr: Callable[..., str],
) -> list[ReportLabelValueRow]:
    rows = [
        ReportLabelValueRow(label=tr("RUN_DATE"), value=date_str),
        ReportLabelValueRow(label=tr("RUN_ID"), value=run_id),
        ReportLabelValueRow(label=tr("TIRE_SIZE"), value=tire_spec_text or tr("UNKNOWN")),
    ]
    sensor_model = str(sensor_model or "").strip()
    if sensor_model and sensor_model.casefold() != tr("UNKNOWN").casefold():
        rows.append(ReportLabelValueRow(label=tr("SENSOR_MODEL"), value=sensor_model))
    firmware_version = str(firmware_version or "").strip()
    if firmware_version and firmware_version.casefold() not in {"none", tr("UNKNOWN").casefold()}:
        rows.append(ReportLabelValueRow(label=tr("FIRMWARE_VERSION"), value=firmware_version))
    rows.extend(
        [
            ReportLabelValueRow(
                label=tr("REPORT_ANALYSIS_ROWS_LABEL"),
                value=str(sample_count),
            ),
            ReportLabelValueRow(
                label=tr("RAW_SAMPLE_RATE_HZ_LABEL"),
                value=sample_rate_hz or tr("UNKNOWN"),
            ),
        ]
    )
    return rows
