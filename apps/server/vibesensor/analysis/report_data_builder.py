"""Builder that converts an analysis summary dict into ReportTemplateData.

This module lives in ``vibesensor.analysis`` because it calls analysis
functions (certainty tiers, strength labels, pattern-parts mapping).
The sibling ``vibesensor.report`` package is renderer-only and imports
only the finished :class:`ReportTemplateData` dataclass.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..report.report_data import (
    CarMeta,
    DataTrustItem,
    NextStep,
    ObservedSignature,
    PatternEvidence,
    PeakRow,
    ReportTemplateData,
    SystemFindingCard,
)
from ..report_i18n import normalize_lang
from ..report_i18n import tr as _tr
from ..runlog import as_float_or_none as _as_float
from .report_mapping_common import (
    extract_confidence as _extract_confidence_impl,
)
from .report_mapping_common import (
    finding_strength_db as _finding_strength_values_impl,
)
from .report_mapping_common import (
    human_source as _human_source_impl,
)
from .report_mapping_common import (
    is_i18n_ref as _is_i18n_ref_impl,
)
from .report_mapping_common import (
    order_label_human as _order_label_human_impl,
)
from .report_mapping_common import (
    peak_classification_text as _peak_classification_text_impl,
)
from .report_mapping_common import (
    resolve_i18n as _resolve_i18n_impl,
)
from .report_mapping_components import (
    build_data_trust_from_summary as _build_data_trust_from_summary_impl,
)
from .report_mapping_components import (
    build_next_steps_from_summary as _build_next_steps_from_summary_impl,
)
from .report_mapping_components import (
    build_pattern_evidence as _build_pattern_evidence_impl,
)
from .report_mapping_components import (
    build_peak_rows_from_plots as _build_peak_rows_from_plots_impl,
)
from .report_mapping_components import (
    build_run_metadata_fields as _build_run_metadata_fields_impl,
)
from .report_mapping_components import (
    build_system_cards as _build_system_cards_impl,
)
from .report_mapping_components import (
    build_version_marker,
)
from .report_mapping_components import (
    compute_location_hotspot_rows as _compute_location_hotspot_rows_impl,
)
from .report_mapping_components import (
    filter_active_sensor_intensity as _filter_active_sensor_intensity_impl,
)
from .report_mapping_components import (
    has_relevant_reference_gap as _has_relevant_reference_gap_impl,
)
from .report_mapping_components import (
    top_strength_values as _top_strength_values_impl,
)
from .report_mapping_context import (
    extract_run_context as _extract_run_context_impl,
)
from .report_mapping_context import (
    extract_sensor_locations as _extract_sensor_locations_impl,
)
from .report_mapping_context import (
    normalized_origin_location,
)
from .report_mapping_context import (
    resolve_primary_candidate as _resolve_primary_candidate_impl,
)
from .strength_labels import certainty_label, certainty_tier, strength_label, strength_text

# ---------------------------------------------------------------------------
# Module-level constant mappings (hoisted out of per-call functions)
# ---------------------------------------------------------------------------

_ORDER_LABEL_NAMES_NL: dict[str, str] = {
    "wheel": "wielorde",
    "engine": "motororde",
    "driveshaft": "aandrijfasorde",
}
_ORDER_LABEL_NAMES_DEFAULT: dict[str, str] = {
    "wheel": "wheel order",
    "engine": "engine order",
    "driveshaft": "driveshaft order",
}

_CLASSIFICATION_I18N_KEYS: dict[str, str] = {
    "patterned": "CLASSIFICATION_PATTERNED",
    "persistent": "CLASSIFICATION_PERSISTENT",
    "transient": "CLASSIFICATION_TRANSIENT",
    "baseline_noise": "CLASSIFICATION_BASELINE_NOISE",
}

# ---------------------------------------------------------------------------
# i18n resolution helpers
# ---------------------------------------------------------------------------


def _is_i18n_ref(value: object) -> bool:
    return _is_i18n_ref_impl(value)


def _resolve_i18n(lang: str, value: object) -> str:
    return _resolve_i18n_impl(lang, value, tr=lambda key, **kw: _tr(lang, key, **kw))


def _order_label_human(lang: str, label: str) -> str:
    return _order_label_human_impl(lang, label)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _human_source(source: object, *, tr: Callable[[str], str]) -> str:
    return _human_source_impl(source, tr=tr)


def _finding_strength_values(finding: dict[str, Any]) -> float | None:
    return _finding_strength_values_impl(finding)


def _top_strength_values(
    summary: dict,
    *,
    effective_causes: list[dict] | None = None,
) -> float | None:
    return _top_strength_values_impl(summary, effective_causes=effective_causes)


def _peak_classification_text(value: object, tr: Callable[..., str]) -> str:
    return _peak_classification_text_impl(value, tr)


def _extract_confidence(d: dict) -> float:
    return _extract_confidence_impl(d)


def _has_relevant_reference_gap(findings: list[dict], primary_source: object) -> bool:
    return _has_relevant_reference_gap_impl(findings, primary_source)


def _compute_location_hotspot_rows(
    sensor_intensity: list[dict],
) -> list[dict]:
    return _compute_location_hotspot_rows_impl(sensor_intensity)


# ---------------------------------------------------------------------------
# map_summary sub-functions
# ---------------------------------------------------------------------------


def _extract_run_context(
    summary: dict,
) -> tuple[dict, str | None, str | None, str, list, list, list, dict, dict]:
    return _extract_run_context_impl(summary)


def _extract_sensor_locations(summary: dict) -> list[str]:
    return _extract_sensor_locations_impl(summary)


def _build_next_steps_from_summary(
    summary: dict,
    *,
    tier: str,
    cert_reason: str,
    lang: str,
    tr: Callable,
) -> list[NextStep]:
    return _build_next_steps_from_summary_impl(
        summary,
        tier=tier,
        cert_reason=cert_reason,
        lang=lang,
        tr=tr,
    )


def _build_data_trust_from_summary(
    summary: dict,
    *,
    lang: str,
    tr: Callable,
) -> list[DataTrustItem]:
    return _build_data_trust_from_summary_impl(summary, lang=lang, tr=tr)


def _build_peak_rows_from_plots(
    summary: dict,
    *,
    lang: str,
    tr: Callable,
) -> list[PeakRow]:
    return _build_peak_rows_from_plots_impl(summary, lang=lang, tr=tr)


# ---------------------------------------------------------------------------
# map_summary component builders
# ---------------------------------------------------------------------------


def _build_system_cards(
    top_causes: list[dict],
    findings_non_ref: list[dict],
    findings: list[dict],
    tier: str,
    lang: str,
    tr: Callable,
) -> list[SystemFindingCard]:
    return _build_system_cards_impl(top_causes, findings_non_ref, findings, tier, lang, tr)


def _build_pattern_evidence(
    top_causes: list[dict],
    primary_candidate: dict | None,
    origin: dict,
    primary_location: str,
    primary_speed: str,
    str_text: str,
    db_val: float | None,
    cert_label_text: str,
    cert_pct: str,
    cert_reason: str,
    weak_spatial: bool,
    lang: str,
    tr: Callable,
) -> PatternEvidence:
    return _build_pattern_evidence_impl(
        top_causes,
        primary_candidate,
        origin,
        primary_location,
        primary_speed,
        str_text,
        db_val,
        cert_label_text,
        cert_pct,
        cert_reason,
        weak_spatial,
        lang,
        tr,
    )


def _resolve_primary_candidate(
    top_causes: list[dict],
    findings_non_ref: list[dict],
    origin_location: str,
    tr: Callable,
) -> tuple[dict | None, object, str, str, str, float]:
    return _resolve_primary_candidate_impl(top_causes, findings_non_ref, origin_location, tr)


def _build_run_metadata_fields(
    summary: dict,
    meta: dict,
) -> dict[str, object]:
    return _build_run_metadata_fields_impl(summary, meta)


def _filter_active_sensor_intensity(
    raw_sensor_intensity_all: list,
    sensor_locations_active: list[str],
) -> list[dict]:
    return _filter_active_sensor_intensity_impl(raw_sensor_intensity_all, sensor_locations_active)


# ---------------------------------------------------------------------------
# Summary → template data mapper
# ---------------------------------------------------------------------------


def map_summary(summary: dict) -> ReportTemplateData:
    """Map a run summary dict to the report template data model."""
    lang = str(normalize_lang(summary.get("lang")))

    def tr(key: str, **kw: object) -> str:
        return str(_tr(lang, key, **kw))

    # -- Context extraction --
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
    ) = _extract_run_context(summary)

    origin_location = normalized_origin_location(origin)

    sensor_locations_active = _extract_sensor_locations(summary)

    # -- Primary candidate: source, system name, location, speed, confidence --
    primary_candidate, primary_source, primary_system, primary_location, primary_speed, conf = (
        _resolve_primary_candidate(top_causes, findings_non_ref, origin_location, tr)
    )

    db_val = _top_strength_values(summary, effective_causes=top_causes)
    str_text = strength_text(db_val, lang=lang)

    steady = bool(speed_stats.get("steady_speed"))
    weak_spatial = bool(
        primary_candidate.get("weak_spatial_separation") if primary_candidate else False
    )
    sensor_count = len(sensor_locations_active)
    if sensor_count <= 0:
        sensor_count = int(_as_float(summary.get("sensor_count_used")) or 0)
    has_ref_gaps = _has_relevant_reference_gap(findings, primary_source)

    _strength_band_key = strength_label(db_val)[0] if db_val is not None else None
    _cert_key, cert_label_text, cert_pct, cert_reason = certainty_label(
        conf,
        lang=lang,
        steady_speed=steady,
        weak_spatial=weak_spatial,
        sensor_count=sensor_count,
        has_reference_gaps=has_ref_gaps,
        strength_band_key=_strength_band_key,
    )

    tier = certainty_tier(conf, strength_band_key=_strength_band_key)

    observed = ObservedSignature(
        primary_system=primary_system,
        strongest_sensor_location=primary_location,
        speed_band=primary_speed,
        strength_label=str_text,
        strength_peak_db=db_val,
        certainty_label=cert_label_text,
        certainty_pct=cert_pct,
        certainty_reason=cert_reason,
    )

    # -- System cards --
    system_cards = _build_system_cards(
        top_causes,
        findings_non_ref,
        findings,
        tier,
        lang,
        tr,
    )

    # -- Next steps --
    next_steps = _build_next_steps_from_summary(
        summary,
        tier=tier,
        cert_reason=cert_reason,
        lang=lang,
        tr=tr,
    )

    # -- Data trust --
    data_trust = _build_data_trust_from_summary(summary, lang=lang, tr=tr)

    # -- Pattern evidence --
    pattern_evidence = _build_pattern_evidence(
        top_causes,
        primary_candidate,
        origin,
        primary_location,
        primary_speed,
        str_text,
        db_val,
        cert_label_text,
        cert_pct,
        cert_reason,
        weak_spatial,
        lang,
        tr,
    )

    # -- Peak rows --
    peak_rows = _build_peak_rows_from_plots(summary, lang=lang, tr=tr)

    # -- Version marker --
    version_marker = build_version_marker()

    # -- Metadata enrichment --
    run_meta = _build_run_metadata_fields(summary, meta)
    sensor_count_used = sensor_count

    # -- Rendering context (pre-computed for the PDF renderer) --
    raw_sensor_intensity_all = summary.get("sensor_intensity_by_location", [])
    if not isinstance(raw_sensor_intensity_all, list):
        raw_sensor_intensity_all = []
    raw_sensor_intensity = _filter_active_sensor_intensity(
        raw_sensor_intensity_all, sensor_locations_active
    )

    # Pre-compute location hotspot rows from findings matched_points
    # so the PDF renderer never reads raw samples.
    hotspot_rows = _compute_location_hotspot_rows(raw_sensor_intensity)

    return ReportTemplateData(
        title=tr("DIAGNOSTIC_WORKSHEET"),
        run_datetime=date_str,
        run_id=summary.get("run_id"),
        duration_text=run_meta["duration_text"],
        start_time_utc=run_meta["start_time_utc"],
        end_time_utc=run_meta["end_time_utc"],
        sample_rate_hz=run_meta["sample_rate_hz"],
        tire_spec_text=run_meta["tire_spec_text"],
        sample_count=run_meta["sample_count"],
        sensor_count=sensor_count_used,
        sensor_locations=sensor_locations_active,
        sensor_model=run_meta["sensor_model"],
        firmware_version=run_meta["firmware_version"],
        car=CarMeta(name=car_name, car_type=car_type),
        observed=observed,
        system_cards=system_cards,
        next_steps=next_steps,
        data_trust=data_trust,
        pattern_evidence=pattern_evidence,
        peak_rows=peak_rows,
        version_marker=version_marker,
        lang=lang,
        certainty_tier_key=tier,
        findings=findings,
        top_causes=top_causes,
        sensor_intensity_by_location=raw_sensor_intensity,
        location_hotspot_rows=hotspot_rows,
    )
