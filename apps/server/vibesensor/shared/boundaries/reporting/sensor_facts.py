"""Sensor and coverage facts for prepared reporting boundaries."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from statistics import mean as _mean
from typing import TYPE_CHECKING

from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary, TestRun
from vibesensor.shared.types.history_analysis_contracts import LocationProofBasis
from vibesensor.vibration_strength import compute_db, percentile

if TYPE_CHECKING:
    from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts

__all__ = [
    "ReportCoverageSummary",
    "ReportSensorFacts",
    "build_report_sensor_facts",
    "enrich_location_proof_sensor_facts",
    "primary_location_has_coverage_gap",
    "sensor_fallback_strength_db",
]


@dataclass(frozen=True, slots=True)
class ReportCoverageSummary:
    """Coverage facts used by report preparation and rendering."""

    expected_locations: tuple[str, ...]
    active_locations: tuple[str, ...]
    missing_locations: tuple[str, ...]
    partial_locations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportSensorFacts:
    """Canonical sensor-facing report facts shared by history and PDF mapping."""

    active_locations: tuple[str, ...]
    active_intensity: tuple[LocationIntensitySummary, ...]
    location_hotspot_rows: tuple[LocationHotspotRow, ...]
    coverage: ReportCoverageSummary
    proof_intensity: tuple[LocationIntensitySummary, ...]
    proof_location_hotspot_rows: tuple[LocationHotspotRow, ...]
    proof_basis: LocationProofBasis


def build_report_sensor_facts(
    *,
    test_run: TestRun,
    sensor_locations_active: Sequence[str],
    sensor_intensity: Sequence[LocationIntensitySummary],
) -> ReportSensorFacts:
    active_intensity = tuple(
        _filter_active_sensor_intensity(
            sensor_intensity,
            sensor_locations_active,
        ),
    )
    return ReportSensorFacts(
        active_locations=tuple(sensor_locations_active),
        active_intensity=active_intensity,
        location_hotspot_rows=tuple(_compute_location_hotspot_rows(active_intensity)),
        coverage=_build_coverage_summary(
            test_run=test_run,
            sensor_locations_active=sensor_locations_active,
            sensor_intensity=active_intensity,
        ),
        proof_intensity=active_intensity,
        proof_location_hotspot_rows=tuple(_compute_location_hotspot_rows(active_intensity)),
        proof_basis="whole_run_summary",
    )


def enrich_location_proof_sensor_facts(
    sensor_facts: ReportSensorFacts,
    *,
    primary_candidate: PrimaryReportFacts,
    evidence_data_basis: str,
) -> ReportSensorFacts:
    """Return sensor facts with diagnosis-supporting location proof when available."""

    proof_intensity = tuple(_supporting_window_location_intensity(primary_candidate))
    if not proof_intensity:
        return sensor_facts
    proof_basis: LocationProofBasis = (
        "supporting_windows_raw_backed"
        if evidence_data_basis == "raw_backed"
        else "supporting_windows_summary_only"
    )
    return ReportSensorFacts(
        active_locations=sensor_facts.active_locations,
        active_intensity=sensor_facts.active_intensity,
        location_hotspot_rows=sensor_facts.location_hotspot_rows,
        coverage=sensor_facts.coverage,
        proof_intensity=proof_intensity,
        proof_location_hotspot_rows=tuple(_compute_location_hotspot_rows(proof_intensity)),
        proof_basis=proof_basis,
    )


def sensor_fallback_strength_db(
    sensor_intensity: Sequence[LocationIntensitySummary],
) -> float | None:
    """Return the best sensor-intensity dB as a last-resort fallback."""
    return max(
        (row.p95_intensity_db for row in sensor_intensity if row.p95_intensity_db is not None),
        default=None,
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


def _collect_location_intensity(
    sensor_intensity: Sequence[LocationIntensitySummary],
) -> dict[str, list[float]]:
    amp_by_location: dict[str, list[float]] = defaultdict(list)
    for row in sensor_intensity:
        location = row.location.strip()
        p95 = row.p95_intensity_db if row.p95_intensity_db is not None else row.mean_intensity_db
        if location and p95 is not None and p95 > 0:
            amp_by_location[location].append(p95)
    return amp_by_location


def _compute_location_hotspot_rows(
    sensor_intensity: Sequence[LocationIntensitySummary],
) -> list[LocationHotspotRow]:
    if not sensor_intensity:
        return []
    hotspot_rows = [
        LocationHotspotRow(
            location=location,
            count=len(amps),
            unit="db",
            peak_value=max(amps),
            mean_value=_mean(amps),
        )
        for location, amps in _collect_location_intensity(sensor_intensity).items()
    ]
    hotspot_rows.sort(
        key=lambda row: (row.peak_value, row.mean_value),
        reverse=True,
    )
    return hotspot_rows


def _filter_active_sensor_intensity(
    raw_sensor_intensity_all: Sequence[LocationIntensitySummary],
    sensor_locations_active: Sequence[str],
) -> list[LocationIntensitySummary]:
    active_locations = set(sensor_locations_active)
    rows: list[LocationIntensitySummary] = []
    for row in raw_sensor_intensity_all:
        if active_locations and row.location not in active_locations:
            continue
        rows.append(row)
    return rows


def _supporting_window_location_intensity(
    primary_candidate: PrimaryReportFacts,
) -> list[LocationIntensitySummary]:
    finding = primary_candidate.domain_primary
    if finding is None or not finding.matched_points:
        return []
    amp_by_location: dict[str, list[float]] = defaultdict(list)
    all_amps: list[float] = []
    for point in finding.matched_points:
        amp = float(point.amp)
        if not isfinite(amp) or amp <= 0.0:
            continue
        location = str(point.location or "").strip()
        if not location:
            continue
        amp_by_location[location].append(amp)
        all_amps.append(amp)
    if not amp_by_location or not all_amps:
        return []
    floor_amp = percentile(sorted(all_amps), 0.20)
    total_points = sum(len(values) for values in amp_by_location.values())
    rows: list[LocationIntensitySummary] = []
    for location, values in amp_by_location.items():
        ordered = sorted(values)
        sample_count = len(ordered)
        rows.append(
            LocationIntensitySummary(
                location=location,
                sample_count=sample_count,
                sample_coverage_ratio=sample_count / max(1, total_points),
                mean_intensity_db=compute_db(_mean(ordered), floor_amp),
                p95_intensity_db=compute_db(percentile(ordered, 0.95), floor_amp),
                max_intensity_db=compute_db(max(ordered), floor_amp),
            )
        )
    rows.sort(
        key=lambda row: (
            row.p95_intensity_db if row.p95_intensity_db is not None else float("-inf"),
            row.mean_intensity_db if row.mean_intensity_db is not None else float("-inf"),
        ),
        reverse=True,
    )
    return rows


def _build_coverage_summary(
    *,
    test_run: TestRun,
    sensor_locations_active: Sequence[str],
    sensor_intensity: Sequence[LocationIntensitySummary],
) -> ReportCoverageSummary:
    expected_locations = _resolve_expected_sensor_locations(test_run) or _ordered_unique(
        tuple(sensor_locations_active),
    )
    active_locations = _ordered_unique(tuple(sensor_locations_active))
    active_tokens = {_normalized_location_token(location) for location in active_locations}
    partial_locations = _ordered_unique(
        tuple(
            row.location
            for row in sensor_intensity
            if row.partial_coverage or row.sample_coverage_warning
        ),
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
