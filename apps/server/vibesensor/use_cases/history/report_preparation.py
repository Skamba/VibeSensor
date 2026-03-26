"""History-side report preparation and prepared-input handoff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.domain import (
    LocationHotspotRow,
    LocationIntensitySummary,
    RecommendedAction,
    VibrationOrigin,
)
from vibesensor.report_i18n import normalize_lang
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
from vibesensor.shared.boundaries.report_payload_gate import has_projectable_report_payload
from vibesensor.shared.boundaries.report_payload_projection import (
    active_sensor_locations,
    sensor_intensity_payload,
    summary_metadata,
)
from vibesensor.shared.boundaries.report_renderer_payload import (
    PreparedReportRendererPayload,
    build_report_renderer_payload,
)
from vibesensor.shared.boundaries.test_run_reconstruction import test_run_from_summary
from vibesensor.shared.run_context_warning import RunContextWarningsInput
from vibesensor.shared.types.history_analysis_contracts import (
    AnalysisSummary,
    RunSuitabilityCheck,
)
from vibesensor.shared.types.history_analysis_contracts import (
    SummaryWarningResponse as SummaryWarningPayload,
)
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.helpers import safe_filename
from vibesensor.use_cases.history.report_cache import ReportPdfCacheKey

if TYPE_CHECKING:
    from vibesensor.domain import TestRun


def _default_report_filename(payload: Mapping[str, object]) -> str:
    """Derive the default PDF filename from stable report-identifying payload fields."""
    run_id = str(payload.get("run_id") or payload.get("file_name") or "report")
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
    - ``domain_test_run`` is reconstructed at most once and shared across the
      downstream PDF mapping helpers as the authoritative report aggregate.
    - ``report_facts`` contains the semantic report facts that the PDF adapter
      needs so it does not have to call back into history-layer interpretation.
    - ``renderer_payload`` contains only the minimal final-edge payload that the
      PDF mapper still needs after domain/report preparation is complete.
    - ``ReportMappingContext`` is adapter-owned and derived later inside
      ``vibesensor.adapters.pdf.report_context`` from this validated handoff.
    - ``language`` is canonicalized once so the renderer consumes one
      consistent locale choice.
    - ``domain_test_run`` and ``report_facts`` may still be ``None`` for
      non-projectable inputs.
    """

    renderer_payload: PreparedReportRendererPayload
    language: str
    filename: str
    domain_test_run: TestRun | None
    cache_key: ReportPdfCacheKey | None = None
    report_facts: PreparedReportFacts | None = None


@dataclass(frozen=True, slots=True)
class ValidatedPreparedReportInput:
    """Prepared report handoff validated for PDF mapping.

    This mapping-ready shape guarantees the domain aggregate and prepared report
    facts are both present before adapter-side context assembly and mapping begin.
    """

    renderer_payload: PreparedReportRendererPayload
    language: str
    filename: str
    domain_test_run: TestRun
    report_facts: PreparedReportFacts
    cache_key: ReportPdfCacheKey | None = None


def validate_prepared_report_input(
    prepared: PreparedReportInput | ValidatedPreparedReportInput,
) -> ValidatedPreparedReportInput:
    """Validate that the prepared report seam is ready for PDF mapping.

    Checks both field presence and cross-object consistency so mismatched
    prepared data fails at the history/report seam instead of surfacing
    later inside template mapping.
    """
    if isinstance(prepared, ValidatedPreparedReportInput):
        return prepared
    if prepared.domain_test_run is None:
        raise ValueError("PreparedReportInput must include a domain_test_run for report mapping")
    if prepared.report_facts is None:
        raise ValueError("PreparedReportInput must include report_facts for report mapping")

    return ValidatedPreparedReportInput(
        renderer_payload=prepared.renderer_payload,
        language=prepared.language,
        filename=prepared.filename,
        domain_test_run=prepared.domain_test_run,
        report_facts=prepared.report_facts,
        cache_key=prepared.cache_key,
    )


def _reconstruct_report_test_run(payload: Mapping[str, object]) -> TestRun | None:
    """Rebuild the report domain aggregate only when the payload is projectable."""
    if not has_projectable_report_payload(payload):
        return None
    return test_run_from_summary(payload)


def _prepare_report_facts(
    payload: Mapping[str, object],
    *,
    test_run: TestRun,
    warnings: RunContextWarningsInput = None,
) -> PreparedReportFacts:
    """Resolve the semantic report facts shared by downstream PDF mapping."""
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


def _build_prepared_report_input(
    payload: Mapping[str, object],
    *,
    filename: str | None,
    language: str | None,
    cache_key: ReportPdfCacheKey | None,
    warnings: RunContextWarningsInput = None,
) -> PreparedReportInput:
    """Assemble the canonical history-side report handoff for PDF rendering."""
    domain_test_run = _reconstruct_report_test_run(payload)
    prepared_language = str(normalize_lang(language or payload.get("lang")))
    renderer_payload = build_report_renderer_payload(payload)
    report_facts = (
        _prepare_report_facts(payload, test_run=domain_test_run, warnings=warnings)
        if domain_test_run is not None
        else None
    )
    return PreparedReportInput(
        renderer_payload=renderer_payload,
        language=prepared_language,
        filename=filename or _default_report_filename(payload),
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
        analysis_summary,
        filename=filename,
        language=language,
        cache_key=cache_key,
    )


def prepare_persisted_report_input(
    analysis: PersistedAnalysis,
    *,
    warnings: RunContextWarningsInput = None,
    filename: str | None = None,
    language: str | None = None,
    cache_key: ReportPdfCacheKey | None = None,
) -> PreparedReportInput:
    """Prepare a persisted history payload for domain-first report mapping."""
    return _build_prepared_report_input(
        analysis,
        filename=filename,
        language=language,
        cache_key=cache_key,
        warnings=warnings,
    )
