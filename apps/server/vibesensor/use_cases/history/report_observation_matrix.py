"""Sensor-observation matrix builders shared across history report preparation."""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite

from vibesensor.domain import Finding, TestRun
from vibesensor.shared.boundaries.reporting.document import (
    SensorObservationCell,
    SensorObservationMatrixRow,
)
from vibesensor.shared.report_presentation import (
    candidate_signal_text,
    display_location,
    human_source,
)
from vibesensor.vibration_strength import percentile, relative_level_db_scalar

__all__ = ["build_sensor_observation_matrix_rows"]


def build_sensor_observation_matrix_rows(
    aggregate: TestRun,
    *,
    sensor_locations: list[str],
    tr: Callable[..., str],
) -> list[SensorObservationMatrixRow]:
    if not sensor_locations:
        return []
    sensor_labels = [display_location(location, short=True, tr=tr) for location in sensor_locations]
    rows: list[SensorObservationMatrixRow] = []
    for finding in aggregate.effective_top_causes()[:4]:
        sensor_levels = _sensor_observation_levels(
            finding,
            sensor_labels=sensor_labels,
            tr=tr,
        )
        if not any(cell.relative_level_db is not None for cell in sensor_levels):
            continue
        rows.append(
            SensorObservationMatrixRow(
                source_name=human_source(finding.suspected_source, tr=tr),
                signal_label=candidate_signal_text(finding, tr=tr),
                sensor_levels=sensor_levels,
            )
        )
    return rows


def _sensor_observation_levels(
    finding: Finding,
    *,
    sensor_labels: list[str],
    tr: Callable[..., str],
) -> list[SensorObservationCell]:
    matched_amps_by_location: dict[str, list[float]] = {}
    for point in finding.matched_points:
        amp = float(point.amp)
        if not isfinite(amp) or amp < 0.0:
            continue
        location = display_location(point.location, short=True, tr=tr)
        matched_amps_by_location.setdefault(location, []).append(amp)
    representative_amps = {
        location: percentile(sorted(values), 0.95)
        for location, values in matched_amps_by_location.items()
        if values
    }
    if not representative_amps:
        strongest_location = str(finding.strongest_location or "").strip()
        strongest_label = (
            display_location(strongest_location, short=True, tr=tr) if strongest_location else None
        )
        return [
            SensorObservationCell(
                location=label,
                relative_level_db=0.0 if label == strongest_label else None,
            )
            for label in sensor_labels
        ]

    strongest_value = max(representative_amps.values())
    levels: list[SensorObservationCell] = []
    for label in sensor_labels:
        amplitude = representative_amps.get(label)
        relative_level = (
            relative_level_db_scalar(amplitude, strongest_value) if amplitude is not None else None
        )
        levels.append(
            SensorObservationCell(
                location=label,
                relative_level_db=round(relative_level, 1) if relative_level is not None else None,
            )
        )
    return levels
