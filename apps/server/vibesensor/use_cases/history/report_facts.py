"""History-side semantic report-facts preparation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vibesensor.domain import (
    LocationHotspotRow,
    LocationIntensitySummary,
    RecommendedAction,
    TestRun,
    VibrationOrigin,
)
from vibesensor.shared.boundaries.report_facts_projection import (
    report_suitability_checks,
    report_warning_payloads,
)
from vibesensor.shared.boundaries.report_interpretation import (
    PrimaryReportFacts,
    compute_location_hotspot_rows,
    filter_active_sensor_intensity,
    normalize_origin_location,
    resolve_primary_report_facts,
    resolve_report_origin,
    tire_spec_text,
)
from vibesensor.shared.boundaries.report_payload_projection import (
    active_sensor_locations,
    sensor_intensity_payload,
    summary_metadata,
)
from vibesensor.shared.run_context_warning import RunContextWarningsInput
from vibesensor.shared.types.history_analysis_contracts import RunSuitabilityCheck
from vibesensor.shared.types.history_analysis_contracts import (
    SummaryWarningResponse as SummaryWarningPayload,
)


@dataclass(frozen=True, slots=True)
class PreparedReportFacts:
    """History-prepared semantic report facts consumed by the PDF adapter."""

    origin: VibrationOrigin | None
    origin_location: str
    sensor_locations_active: tuple[str, ...]
    duration_text: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sample_rate_hz: str | None
    tire_spec_text: str | None
    sample_count: int
    sensor_model: str | None
    firmware_version: str | None
    active_sensor_intensity: tuple[LocationIntensitySummary, ...]
    location_hotspot_rows: tuple[LocationHotspotRow, ...]
    primary_candidate_facts: PrimaryReportFacts
    recommended_actions: tuple[RecommendedAction, ...]
    suitability_checks: tuple[RunSuitabilityCheck, ...]
    warnings: tuple[SummaryWarningPayload, ...]


def prepare_report_facts(
    payload: Mapping[str, object],
    *,
    test_run: TestRun,
    warnings: RunContextWarningsInput = None,
) -> PreparedReportFacts:
    """Resolve semantic report facts shared by downstream PDF mapping."""
    metadata = summary_metadata(payload)
    sensor_locations_active = active_sensor_locations(payload)
    origin = resolve_report_origin(test_run)
    origin_location = normalize_origin_location(origin)
    config_snap = test_run.capture.setup.configuration_snapshot
    active_sensor_intensity = tuple(
        filter_active_sensor_intensity(
            sensor_intensity_payload(payload),
            sensor_locations_active,
        )
    )
    primary_candidate_facts = resolve_primary_report_facts(
        aggregate=test_run,
        origin_location=origin_location,
        sensor_locations_active=sensor_locations_active,
        sensor_intensity=active_sensor_intensity,
    )
    return PreparedReportFacts(
        origin=origin,
        origin_location=origin_location,
        sensor_locations_active=sensor_locations_active,
        duration_text=str(payload.get("record_length") or "").strip() or None,
        start_time_utc=str(payload.get("start_time_utc") or "").strip() or None,
        end_time_utc=str(payload.get("end_time_utc") or "").strip() or None,
        sample_rate_hz=(
            f"{config_snap.raw_sample_rate_hz:g}"
            if config_snap.raw_sample_rate_hz is not None
            else None
        ),
        tire_spec_text=tire_spec_text(metadata),
        sample_count=test_run.capture.sample_count,
        sensor_model=config_snap.sensor_model,
        firmware_version=config_snap.firmware_version,
        active_sensor_intensity=active_sensor_intensity,
        location_hotspot_rows=tuple(compute_location_hotspot_rows(active_sensor_intensity)),
        primary_candidate_facts=primary_candidate_facts,
        recommended_actions=test_run.recommended_actions,
        suitability_checks=report_suitability_checks(test_run.suitability),
        warnings=report_warning_payloads(payload, warnings=warnings),
    )
