"""History-side semantic report-facts preparation."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import (
    TestRun,
)
from vibesensor.report_i18n import normalize_lang
from vibesensor.shared.boundaries.reporting.contracts import PreparedReportFacts
from vibesensor.shared.boundaries.reporting.payload import NormalizedReportSummary
from vibesensor.shared.boundaries.reporting.projection import (
    compute_location_hotspot_rows,
    filter_active_sensor_intensity,
    normalize_origin_location,
    resolve_primary_report_facts,
    resolve_report_origin,
    tire_spec_text,
)
from vibesensor.shared.report_diagnostics import report_suitability_checks, report_warnings
from vibesensor.shared.run_context_warning import RunContextWarningsInput
from vibesensor.use_cases.history.report_display_mapping import prepare_report_display_facts
from vibesensor.use_cases.history.report_fact_coverage import build_coverage_summary
from vibesensor.use_cases.history.report_fact_decisions import (
    resolve_action_status_key,
    resolve_alternative_source,
    resolve_location_confidence_key,
)


def prepare_report_facts(
    payload: Mapping[str, object],
    *,
    summary: NormalizedReportSummary,
    test_run: TestRun,
    language: str | None = None,
    warnings: RunContextWarningsInput = None,
) -> PreparedReportFacts:
    """Resolve semantic report facts shared by downstream PDF mapping."""
    prepared_language = str(normalize_lang(language or payload.get("lang")))
    sensor_locations_active = summary.active_sensor_locations
    origin = resolve_report_origin(test_run)
    origin_location = normalize_origin_location(origin)
    config_snap = test_run.capture.setup.configuration_snapshot
    active_sensor_intensity = tuple(
        filter_active_sensor_intensity(
            summary.sensor_intensity_rows,
            sensor_locations_active,
        )
    )
    primary_candidate_facts = resolve_primary_report_facts(
        aggregate=test_run,
        origin_location=origin_location,
        sensor_locations_active=sensor_locations_active,
        sensor_intensity=active_sensor_intensity,
    )
    suitability_checks = report_suitability_checks(test_run.suitability)
    warning_models = report_warnings(payload, warnings=warnings)
    coverage_summary = build_coverage_summary(
        test_run=test_run,
        sensor_locations_active=sensor_locations_active,
        sensor_intensity=active_sensor_intensity,
    )
    location_confidence_key = resolve_location_confidence_key(
        primary_candidate_facts=primary_candidate_facts,
        coverage_summary=coverage_summary,
    )
    alternative_source, alternative_source_visible, confidence_gap_to_alternative = (
        resolve_alternative_source(
            test_run,
            primary_candidate_facts=primary_candidate_facts,
        )
    )
    action_status_key = resolve_action_status_key(
        primary_candidate_facts=primary_candidate_facts,
        location_confidence_key=location_confidence_key,
        alternative_source_visible=alternative_source_visible,
        suitability_checks=suitability_checks,
        warnings=warning_models,
    )
    duration_text = summary.record_length
    display = prepare_report_display_facts(
        aggregate=test_run,
        primary_candidate_facts=primary_candidate_facts,
        active_sensor_intensity=active_sensor_intensity,
        duration_text=duration_text,
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
        alternative_source_visible=alternative_source_visible,
        expected_locations=coverage_summary.expected_locations,
        active_locations=coverage_summary.active_locations,
        missing_locations=coverage_summary.missing_locations,
        partial_locations=coverage_summary.partial_locations,
        suitability_checks=suitability_checks,
        warnings=warning_models,
        lang=prepared_language,
    )
    return PreparedReportFacts(
        origin=origin,
        origin_location=origin_location,
        sensor_locations_active=sensor_locations_active,
        duration_text=duration_text,
        start_time_utc=summary.start_time_utc,
        end_time_utc=summary.end_time_utc,
        sample_rate_hz=(
            f"{config_snap.raw_sample_rate_hz:g}"
            if config_snap.raw_sample_rate_hz is not None
            else None
        ),
        tire_spec_text=tire_spec_text(config_snap.tire_spec),
        sample_count=test_run.capture.sample_count,
        sensor_model=config_snap.sensor_model,
        firmware_version=config_snap.firmware_version,
        active_sensor_intensity=active_sensor_intensity,
        location_hotspot_rows=tuple(compute_location_hotspot_rows(active_sensor_intensity)),
        primary_candidate_facts=primary_candidate_facts,
        recommended_actions=test_run.recommended_actions,
        suitability_checks=suitability_checks,
        warnings=warning_models,
        coverage_summary=coverage_summary,
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
        alternative_source=alternative_source,
        alternative_source_visible=alternative_source_visible,
        confidence_gap_to_alternative=confidence_gap_to_alternative,
        timeline_intervals=summary.timeline_intervals,
        display=display,
    )
