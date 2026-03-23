"""History-side report preparation and prepared-input handoff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from vibesensor.domain import (
    LocationHotspotRow,
    LocationIntensitySummary,
    RecommendedAction,
    VibrationOrigin,
)
from vibesensor.report_i18n import normalize_lang
from vibesensor.shared.boundaries.analysis_payload import (
    AnalysisSummary,
    RunSuitabilityCheck,
    SummaryWarningPayload,
)
from vibesensor.shared.boundaries.analysis_summary import analysis_summary_with_warnings
from vibesensor.shared.boundaries.diagnostic_case import test_run_from_summary
from vibesensor.shared.boundaries.run_suitability import run_suitability_payload
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.helpers import safe_filename
from vibesensor.use_cases.history.report_cache import ReportPdfCacheKey
from vibesensor.use_cases.history.report_interpretation import (
    PrimaryReportFacts,
    compute_location_hotspot_rows,
    filter_active_sensor_intensity,
    normalize_origin_location,
    resolve_primary_report_facts,
    resolve_report_origin,
    tire_spec_text,
)

if TYPE_CHECKING:
    from vibesensor.domain import TestRun


def _has_projectable_analysis(analysis: AnalysisSummary) -> bool:
    return isinstance(analysis.get("findings"), list) or isinstance(
        analysis.get("top_causes"), list
    )


def _default_report_filename(summary: AnalysisSummary) -> str:
    run_id = str(summary.get("run_id") or summary.get("file_name") or "report")
    return f"{safe_filename(run_id)}_report.pdf"


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


@dataclass(frozen=True, slots=True)
class PreparedReportInput:
    """Resolved report input ready for PDF mapping and rendering.

    Invariants:
    - ``analysis_summary`` is a renderer-facing payload copy, not the
      authoritative internal report representation.
    - ``domain_test_run`` is reconstructed at most once and shared across the
      downstream PDF mapping helpers as the authoritative report aggregate.
    - ``report_facts`` contains the semantic report facts that the PDF adapter
      needs so it does not have to call back into history-layer interpretation.
    - ``language`` is canonicalized and copied back onto ``analysis_summary`` so
      renderer helpers consume one consistent locale choice.
    """

    analysis_summary: AnalysisSummary
    language: str
    filename: str
    domain_test_run: TestRun | None
    cache_key: ReportPdfCacheKey | None = None
    report_facts: PreparedReportFacts | None = None


def _reconstruct_report_test_run(analysis_summary: AnalysisSummary) -> TestRun | None:
    if not _has_projectable_analysis(analysis_summary):
        return None
    return test_run_from_summary(analysis_summary)


def _summary_metadata(summary: AnalysisSummary) -> Mapping[str, object]:
    metadata = summary.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _active_sensor_locations(summary: AnalysisSummary) -> tuple[str, ...]:
    connected = summary.get("sensor_locations_connected_throughout")
    locations = connected if isinstance(connected, list) else []
    active = tuple(str(loc).strip() for loc in locations if str(loc).strip())
    if active:
        return active
    fallback = summary.get("sensor_locations")
    fallback_locations = fallback if isinstance(fallback, list) else []
    return tuple(str(loc).strip() for loc in fallback_locations if str(loc).strip())


def _summary_warnings(summary: AnalysisSummary) -> tuple[SummaryWarningPayload, ...]:
    warnings = summary.get("warnings")
    if not isinstance(warnings, list):
        return ()
    return tuple(warning for warning in warnings if isinstance(warning, dict))


def _prepare_report_facts(
    analysis_summary: AnalysisSummary,
    *,
    test_run: TestRun,
) -> PreparedReportFacts:
    metadata = _summary_metadata(analysis_summary)
    sensor_locations_active = _active_sensor_locations(analysis_summary)
    origin = resolve_report_origin(test_run)
    origin_location = normalize_origin_location(origin)
    config_snap = test_run.capture.setup.configuration_snapshot
    active_sensor_intensity = tuple(
        filter_active_sensor_intensity(
            analysis_summary.get("sensor_intensity_by_location") or [],
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
        duration_text=str(analysis_summary.get("record_length") or "").strip() or None,
        start_time_utc=str(analysis_summary.get("start_time_utc") or "").strip() or None,
        end_time_utc=str(analysis_summary.get("end_time_utc") or "").strip() or None,
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
        suitability_checks=tuple(run_suitability_payload(test_run.suitability)),
        warnings=_summary_warnings(analysis_summary),
    )


def _build_prepared_report_input(
    analysis_summary: AnalysisSummary,
    *,
    filename: str | None,
    language: str | None,
    cache_key: ReportPdfCacheKey | None,
) -> PreparedReportInput:
    domain_test_run = _reconstruct_report_test_run(analysis_summary)
    prepared_summary = cast(AnalysisSummary, dict(analysis_summary))
    prepared_language = str(normalize_lang(language or prepared_summary.get("lang")))
    prepared_summary["lang"] = prepared_language
    report_facts = (
        _prepare_report_facts(prepared_summary, test_run=domain_test_run)
        if domain_test_run is not None
        else None
    )
    return PreparedReportInput(
        analysis_summary=prepared_summary,
        language=prepared_language,
        filename=filename or _default_report_filename(prepared_summary),
        domain_test_run=domain_test_run,
        cache_key=cache_key,
        report_facts=report_facts,
    )


def prepare_report_input(
    analysis_summary: AnalysisSummary,
    *,
    filename: str | None = None,
    language: str | None = None,
    cache_key: ReportPdfCacheKey | None = None,
) -> PreparedReportInput:
    """Prepare a direct summary payload for domain-first report mapping."""
    return _build_prepared_report_input(
        cast(AnalysisSummary, dict(analysis_summary)),
        filename=filename,
        language=language,
        cache_key=cache_key,
    )


def prepare_persisted_report_input(
    analysis: PersistedAnalysis,
    *,
    warnings: object | None = None,
    filename: str | None = None,
    language: str | None = None,
    cache_key: ReportPdfCacheKey | None = None,
) -> PreparedReportInput:
    """Prepare a persisted history payload for domain-first report mapping."""
    prepared_summary = cast(AnalysisSummary, analysis.to_json_object())
    if warnings is not None:
        prepared_summary = analysis_summary_with_warnings(prepared_summary, warnings)
    return _build_prepared_report_input(
        prepared_summary,
        filename=filename,
        language=language,
        cache_key=cache_key,
    )
