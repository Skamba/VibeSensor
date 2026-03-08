"""High-level orchestration for mapping summaries into report template data."""

from __future__ import annotations

from collections.abc import Callable

from ..report.report_data import (
    CarMeta,
    ObservedSignature,
    ReportTemplateData,
)
from ..report_i18n import normalize_lang
from ..report_i18n import tr as _tr
from ._types import SummaryData
from .report_mapping_actions import build_data_trust_from_summary, build_next_steps_from_summary
from .report_mapping_context import (
    extract_run_context,
    extract_sensor_locations,
    normalized_origin_location,
    resolve_primary_candidate,
    resolve_sensor_count,
)
from .report_mapping_models import PrimaryCandidateContext, ReportMappingContext
from .report_mapping_peaks import build_peak_rows_from_plots, compute_location_hotspot_rows
from .report_mapping_systems import (
    build_pattern_evidence,
    build_run_metadata_fields,
    build_system_cards,
    build_version_marker,
    filter_active_sensor_intensity,
    has_relevant_reference_gap,
    top_strength_values,
)
from .strength_labels import certainty_label, certainty_tier, strength_label, strength_text


def prepare_report_mapping_context(
    summary: SummaryData,
) -> ReportMappingContext:
    """Extract structural summary context for report mapping."""
    (
        meta,
        car_name,
        car_type,
        date_str,
        top_causes,
        findings_non_ref,
        findings,
        speed_stats,
        origin,
    ) = extract_run_context(summary)
    origin_location = normalized_origin_location(origin)
    sensor_locations_active = extract_sensor_locations(summary)
    return ReportMappingContext(
        meta=meta,
        car_name=car_name,
        car_type=car_type,
        date_str=date_str,
        top_causes=top_causes,
        findings_non_ref=findings_non_ref,
        findings=findings,
        speed_stats=speed_stats,
        origin=origin,
        origin_location=origin_location,
        sensor_locations_active=sensor_locations_active,
    )


def resolve_primary_report_candidate(
    summary: SummaryData,
    *,
    context: ReportMappingContext,
    tr: Callable[..., str],
    lang: str,
) -> PrimaryCandidateContext:
    """Resolve the primary candidate and all derived certainty fields."""
    (
        primary_candidate,
        primary_source,
        primary_system,
        primary_location,
        primary_speed,
        confidence,
    ) = resolve_primary_candidate(
        context.top_causes,
        context.findings_non_ref,
        context.origin_location,
        tr,
    )
    strength_db = top_strength_values(summary, effective_causes=context.top_causes)
    strength_text_value = strength_text(strength_db, lang=lang)
    weak_spatial = bool(
        primary_candidate.get("weak_spatial_separation") if primary_candidate else False
    )
    sensor_count = resolve_sensor_count(summary, context.sensor_locations_active)
    has_ref_gaps = has_relevant_reference_gap(context.findings, primary_source)
    strength_band_key = strength_label(strength_db)[0] if strength_db is not None else None
    certainty_key, certainty_label_text, certainty_pct, certainty_reason = certainty_label(
        confidence,
        lang=lang,
        steady_speed=bool(context.speed_stats.get("steady_speed")),
        weak_spatial=weak_spatial,
        sensor_count=sensor_count,
        has_reference_gaps=has_ref_gaps,
        strength_band_key=strength_band_key,
    )
    tier = certainty_tier(confidence, strength_band_key=strength_band_key)
    return PrimaryCandidateContext(
        primary_candidate=primary_candidate,
        primary_source=primary_source,
        primary_system=primary_system,
        primary_location=primary_location,
        primary_speed=primary_speed,
        confidence=confidence,
        sensor_count=sensor_count,
        weak_spatial=weak_spatial,
        has_reference_gaps=has_ref_gaps,
        strength_db=strength_db,
        strength_text=strength_text_value,
        strength_band_key=strength_band_key,
        certainty_key=certainty_key,
        certainty_label_text=certainty_label_text,
        certainty_pct=certainty_pct,
        certainty_reason=certainty_reason,
        tier=tier,
    )


def build_observed_signature(primary: PrimaryCandidateContext) -> ObservedSignature:
    """Build the observed-signature block for the report template."""
    return ObservedSignature(
        primary_system=primary.primary_system,
        strongest_sensor_location=primary.primary_location,
        speed_band=primary.primary_speed,
        strength_label=primary.strength_text,
        strength_peak_db=primary.strength_db,
        certainty_label=primary.certainty_label_text,
        certainty_pct=primary.certainty_pct,
        certainty_reason=primary.certainty_reason,
    )


def map_summary(summary: SummaryData) -> ReportTemplateData:
    """Map a run summary dict into the final report template data model."""
    lang = str(normalize_lang(summary.get("lang")))

    def tr(key: str, **kw: object) -> str:
        return str(_tr(lang, key, **kw))

    return _build_report_template_data(summary, lang=lang, tr=tr)


def _build_report_template_data(
    summary: SummaryData,
    *,
    lang: str,
    tr: Callable[..., str],
) -> ReportTemplateData:
    """Map a summary dict into the final report template data structure."""
    context = prepare_report_mapping_context(summary)
    primary = resolve_primary_report_candidate(summary, context=context, tr=tr, lang=lang)
    observed = build_observed_signature(primary)
    system_cards = build_system_cards(
        context.top_causes,
        context.findings_non_ref,
        context.findings,
        primary.tier,
        lang,
        tr,
    )
    next_steps = build_next_steps_from_summary(
        summary,
        tier=primary.tier,
        cert_reason=primary.certainty_reason,
        lang=lang,
        tr=tr,
    )
    data_trust = build_data_trust_from_summary(summary, lang=lang, tr=tr)
    pattern_evidence = build_pattern_evidence(
        context.top_causes,
        primary.primary_candidate,
        context.origin,
        primary.primary_location,
        primary.primary_speed,
        primary.strength_text,
        primary.strength_db,
        primary.certainty_label_text,
        primary.certainty_pct,
        primary.certainty_reason,
        primary.weak_spatial,
        lang,
        tr,
    )
    peak_rows = build_peak_rows_from_plots(summary, lang=lang, tr=tr)
    version_marker = build_version_marker()
    run_meta = build_run_metadata_fields(summary, context.meta)

    raw_sensor_intensity_all = summary.get("sensor_intensity_by_location", [])
    if not isinstance(raw_sensor_intensity_all, list):
        raw_sensor_intensity_all = []
    raw_sensor_intensity = filter_active_sensor_intensity(
        raw_sensor_intensity_all,
        context.sensor_locations_active,
    )
    hotspot_rows = compute_location_hotspot_rows(raw_sensor_intensity)

    return ReportTemplateData(
        title=tr("DIAGNOSTIC_WORKSHEET"),
        run_datetime=context.date_str,
        run_id=summary.get("run_id"),
        duration_text=run_meta["duration_text"],
        start_time_utc=run_meta["start_time_utc"],
        end_time_utc=run_meta["end_time_utc"],
        sample_rate_hz=run_meta["sample_rate_hz"],
        tire_spec_text=run_meta["tire_spec_text"],
        sample_count=run_meta["sample_count"],
        sensor_count=primary.sensor_count,
        sensor_locations=context.sensor_locations_active,
        sensor_model=run_meta["sensor_model"],
        firmware_version=run_meta["firmware_version"],
        car=CarMeta(name=context.car_name, car_type=context.car_type),
        observed=observed,
        system_cards=system_cards,
        next_steps=next_steps,
        data_trust=data_trust,
        pattern_evidence=pattern_evidence,
        peak_rows=peak_rows,
        version_marker=version_marker,
        lang=lang,
        certainty_tier_key=primary.tier,
        findings=context.findings,
        top_causes=context.top_causes,
        sensor_intensity_by_location=raw_sensor_intensity,
        location_hotspot_rows=hotspot_rows,
    )
