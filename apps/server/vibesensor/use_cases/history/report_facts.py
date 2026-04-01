"""History-side semantic report-facts preparation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vibesensor.domain import (
    Finding,
    LocationHotspotRow,
    LocationIntensitySummary,
    RecommendedAction,
    TestRun,
    VibrationOrigin,
    coerce_float,
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
    phase_timeline_payload,
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
    coverage_summary: ReportCoverageSummary
    action_status_key: str
    location_confidence_key: str
    alternative_source: object | None
    alternative_source_visible: bool
    confidence_gap_to_alternative: float | None
    timeline_intervals: tuple[ReportTimelineInterval, ...]


@dataclass(frozen=True, slots=True)
class ReportCoverageSummary:
    """Coverage facts used by report preparation and rendering."""

    expected_locations: tuple[str, ...]
    active_locations: tuple[str, ...]
    missing_locations: tuple[str, ...]
    partial_locations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportTimelineInterval:
    """Prepared semantic snapshot for one report timeline interval."""

    phase: str
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    has_fault_evidence: bool


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


def _build_coverage_summary(
    *,
    test_run: TestRun,
    sensor_locations_active: Sequence[str],
    sensor_intensity: Sequence[LocationIntensitySummary],
) -> ReportCoverageSummary:
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


def _primary_location_has_coverage_gap(
    primary_location: str | None,
    coverage_summary: ReportCoverageSummary,
) -> bool:
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


def _resolve_location_confidence_key(
    *,
    primary_candidate_facts: PrimaryReportFacts,
    coverage_summary: ReportCoverageSummary,
) -> str:
    hotspot = primary_candidate_facts.location_hotspot
    dominance_ratio = primary_candidate_facts.dominance_ratio
    primary_gap = _primary_location_has_coverage_gap(
        primary_candidate_facts.primary_location,
        coverage_summary,
    )
    if primary_candidate_facts.weak_spatial or primary_gap:
        return "weak"
    if dominance_ratio is not None:
        if dominance_ratio < 1.25:
            return "weak"
        if dominance_ratio < 1.75 or bool(coverage_summary.partial_locations):
            return "mixed"
        return "strong"
    if hotspot is not None and hotspot.localization_confidence is not None:
        if hotspot.localization_confidence < 0.4:
            return "weak"
        if hotspot.localization_confidence < 0.7 or bool(coverage_summary.partial_locations):
            return "mixed"
        return "strong"
    if coverage_summary.partial_locations or coverage_summary.missing_locations:
        return "mixed"
    return "mixed"


def _relevant_source_candidates(aggregate: TestRun) -> tuple[Finding, ...]:
    return aggregate.effective_top_causes() or aggregate.non_reference_findings


def _resolve_alternative_source(
    aggregate: TestRun,
    *,
    primary_candidate_facts: PrimaryReportFacts,
) -> tuple[object | None, bool, float | None]:
    candidates = _relevant_source_candidates(aggregate)
    primary = primary_candidate_facts.domain_primary
    if primary is None:
        return None, False, None
    primary_source = str(primary.suspected_source).strip().lower()
    primary_conf = primary.effective_confidence
    ambiguity_visible = bool(
        primary_candidate_facts.weak_spatial
        or (
            primary_candidate_facts.location_hotspot is not None
            and primary_candidate_facts.location_hotspot.ambiguous
        )
    )
    for candidate in candidates[1:]:
        source = str(candidate.suspected_source).strip().lower()
        if not source or source == primary_source:
            continue
        confidence_gap = max(0.0, primary_conf - candidate.effective_confidence)
        visible = confidence_gap <= 0.20 or ambiguity_visible
        return candidate.suspected_source, visible, confidence_gap
    return None, False, None


def _is_blocking_suitability(check: RunSuitabilityCheck) -> bool:
    key = str(check.get("check_key") or "").strip().upper()
    state = str(check.get("state") or "").strip().lower()
    if state in {"fail", "error"}:
        return True
    return (
        key
        in {
            "SUITABILITY_CHECK_SENSOR_COVERAGE",
            "SUITABILITY_CHECK_FRAME_INTEGRITY",
        }
        and state != "pass"
    )


def _has_nonblocking_caution_signals(
    *,
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
) -> bool:
    if any(
        str(warning.get("severity") or "").strip().lower() in {"warn", "error"}
        for warning in warnings
    ):
        return True
    return any(
        str(check.get("state") or "").strip().lower() != "pass" for check in suitability_checks
    )


def _resolve_action_status_key(
    *,
    primary_candidate_facts: PrimaryReportFacts,
    location_confidence_key: str,
    alternative_source_visible: bool,
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
) -> str:
    primary = primary_candidate_facts.domain_primary
    if primary is None or primary_candidate_facts.primary_source is None:
        return "recapture_before_acting"
    tier = primary.confidence_assessment.tier if primary.confidence_assessment is not None else "A"
    if (
        tier == "A"
        or location_confidence_key == "weak"
        or primary_candidate_facts.has_reference_gaps
        or any(_is_blocking_suitability(check) for check in suitability_checks)
    ):
        return "recapture_before_acting"
    if (
        tier == "B"
        or location_confidence_key == "mixed"
        or alternative_source_visible
        or _has_nonblocking_caution_signals(
            suitability_checks=suitability_checks,
            warnings=warnings,
        )
    ):
        return "action_ready_caution"
    return "action_ready"


def _coerce_optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return coerce_float(value)
    except (TypeError, ValueError):
        return None


def _timeline_intervals(payload: Mapping[str, object]) -> tuple[ReportTimelineInterval, ...]:
    intervals: list[ReportTimelineInterval] = []
    for row in phase_timeline_payload(payload):
        phase = str(row.get("phase") or "").strip()
        if not phase:
            continue
        intervals.append(
            ReportTimelineInterval(
                phase=phase,
                start_t_s=_coerce_optional_float(row.get("start_t_s")),
                end_t_s=_coerce_optional_float(row.get("end_t_s")),
                speed_min_kmh=_coerce_optional_float(row.get("speed_min_kmh")),
                speed_max_kmh=_coerce_optional_float(row.get("speed_max_kmh")),
                has_fault_evidence=bool(row.get("has_fault_evidence")),
            ),
        )
    return tuple(intervals)


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
    suitability_checks = report_suitability_checks(test_run.suitability)
    warning_payloads = report_warning_payloads(payload, warnings=warnings)
    coverage_summary = _build_coverage_summary(
        test_run=test_run,
        sensor_locations_active=sensor_locations_active,
        sensor_intensity=active_sensor_intensity,
    )
    location_confidence_key = _resolve_location_confidence_key(
        primary_candidate_facts=primary_candidate_facts,
        coverage_summary=coverage_summary,
    )
    alternative_source, alternative_source_visible, confidence_gap_to_alternative = (
        _resolve_alternative_source(
            test_run,
            primary_candidate_facts=primary_candidate_facts,
        )
    )
    action_status_key = _resolve_action_status_key(
        primary_candidate_facts=primary_candidate_facts,
        location_confidence_key=location_confidence_key,
        alternative_source_visible=alternative_source_visible,
        suitability_checks=suitability_checks,
        warnings=warning_payloads,
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
        suitability_checks=suitability_checks,
        warnings=warning_payloads,
        coverage_summary=coverage_summary,
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
        alternative_source=alternative_source,
        alternative_source_visible=alternative_source_visible,
        confidence_gap_to_alternative=confidence_gap_to_alternative,
        timeline_intervals=_timeline_intervals(payload),
    )
