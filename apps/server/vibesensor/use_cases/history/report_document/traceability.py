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
    strength_algorithm_version: str | None,
    peak_detector_version: str | None,
    calibration_profile_id: str | None,
    vehicle_baseline_profile_id: str | None,
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
    strength_algorithm_version = str(strength_algorithm_version or "").strip()
    if strength_algorithm_version:
        rows.append(
            ReportLabelValueRow(
                label=tr("STRENGTH_ALGORITHM_VERSION_LABEL"),
                value=strength_algorithm_version,
            )
        )
    peak_detector_version = str(peak_detector_version or "").strip()
    if peak_detector_version:
        rows.append(
            ReportLabelValueRow(
                label=tr("PEAK_DETECTOR_VERSION_LABEL"),
                value=peak_detector_version,
            )
        )
    calibration_profile_id = str(calibration_profile_id or "").strip()
    if calibration_profile_id:
        rows.append(
            ReportLabelValueRow(
                label=tr("CALIBRATION_PROFILE_LABEL"),
                value=calibration_profile_id,
            )
        )
    vehicle_baseline_profile_id = str(vehicle_baseline_profile_id or "").strip()
    if vehicle_baseline_profile_id:
        rows.append(
            ReportLabelValueRow(
                label=tr("VEHICLE_BASELINE_PROFILE_LABEL"),
                value=vehicle_baseline_profile_id,
            )
        )
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
