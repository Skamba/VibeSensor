"""Coverage helpers for prepared history report facts."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.domain import LocationIntensitySummary, TestRun
from vibesensor.shared.boundaries.report_prepared_input import ReportCoverageSummary

__all__ = [
    "ReportCoverageSummary",
    "build_coverage_summary",
    "primary_location_has_coverage_gap",
]


def _normalized_location_token(value: object) -> str:
    text = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    parts = [part for part in text.split() if part not in {"wheel", "sensor"}]
    return " ".join(parts)


def _ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)
    return tuple(ordered)


def _resolve_expected_sensor_locations(test_run: TestRun) -> tuple[str, ...]:
    configured = tuple(
        sensor.placement.display_name if sensor.placement is not None else sensor.display_name
        for sensor in test_run.capture.setup.sensors
        if (sensor.placement is not None and sensor.placement.display_name) or sensor.display_name
    )
    return _ordered_unique(configured)


def build_coverage_summary(
    *,
    test_run: TestRun,
    sensor_locations_active: Sequence[str],
    sensor_intensity: Sequence[LocationIntensitySummary],
) -> ReportCoverageSummary:
    """Build normalized coverage facts from the run and active sensors."""

    expected_locations = _resolve_expected_sensor_locations(test_run) or _ordered_unique(
        tuple(sensor_locations_active)
    )
    active_locations = _ordered_unique(tuple(sensor_locations_active))
    active_tokens = {_normalized_location_token(location) for location in active_locations}
    partial_locations = _ordered_unique(
        tuple(
            row.location
            for row in sensor_intensity
            if row.partial_coverage or row.sample_coverage_warning
        )
    )
    missing_locations = tuple(
        location
        for location in expected_locations
        if _normalized_location_token(location) not in active_tokens
    )
    return ReportCoverageSummary(
        expected_locations=expected_locations,
        active_locations=active_locations,
        missing_locations=_ordered_unique(missing_locations),
        partial_locations=_ordered_unique(partial_locations),
    )


def primary_location_has_coverage_gap(
    primary_location: str | None,
    coverage_summary: ReportCoverageSummary,
) -> bool:
    """Return whether the primary location lands in missing or partial coverage."""

    token = _normalized_location_token(primary_location)
    if not token:
        return False
    missing_tokens = {
        _normalized_location_token(location) for location in coverage_summary.missing_locations
    }
    partial_tokens = {
        _normalized_location_token(location) for location in coverage_summary.partial_locations
    }
    return token in missing_tokens or token in partial_tokens
