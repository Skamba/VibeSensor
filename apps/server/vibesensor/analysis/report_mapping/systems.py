"""System, metadata, and strength helpers for summary-to-report mapping."""

from __future__ import annotations

import os
from collections.abc import Callable

from ... import __version__
from ...report.report_data import PartSuggestion, PatternEvidence, SystemFindingCard
from ...runlog import as_float_or_none as _as_float
from .._types import CandidateFinding, Finding, MetadataDict, OriginSummary, SummaryData
from ..pattern_parts import parts_for_pattern, why_parts_listed
from .common import (
    finding_strength_db,
    human_source,
    is_i18n_ref,
    order_label_human,
    resolve_i18n,
)
from .models import PrimaryCandidateContext, ReportMappingContext


def top_strength_values(
    summary: SummaryData,
    *,
    effective_causes: list[CandidateFinding] | None = None,
) -> float | None:
    """Return the best available vibration strength in dB for report text."""
    causes = effective_causes if effective_causes is not None else summary.get("top_causes", [])
    all_findings = summary.get("findings", [])
    for cause in causes:
        if not isinstance(cause, dict):
            continue
        finding_id = cause.get("finding_id")
        for finding in all_findings:
            if not isinstance(finding, dict):
                continue
            if finding.get("finding_id") != finding_id:
                continue
            db = finding_strength_db(finding)
            if db is not None:
                return db
    sensor_rows = [
        _as_float(row.get("p95_intensity_db"))
        for row in summary.get("sensor_intensity_by_location", [])
        if isinstance(row, dict)
    ]
    return max((value for value in sensor_rows if value is not None), default=None)


def has_relevant_reference_gap(findings: list[Finding], primary_source: object) -> bool:
    """Whether the report certainty should mention missing reference inputs."""
    source = str(primary_source or "").strip().lower()
    for finding in findings:
        finding_id = str(finding.get("finding_id") or "").strip().upper()
        if finding_id in {"REF_SPEED", "REF_SAMPLE_RATE"}:
            return True
        if finding_id == "REF_WHEEL" and source in {"wheel/tire", "driveline"}:
            return True
        if finding_id == "REF_ENGINE" and source == "engine":
            return True
    return False


def build_system_cards(
    context: ReportMappingContext,
    primary: PrimaryCandidateContext,
    lang: str,
    tr: Callable,
) -> list[SystemFindingCard]:
    """Build system finding cards for the report template."""
    tier = primary.tier
    if tier == "A":
        return []
    card_sources = context.top_causes or context.findings_non_ref or context.findings
    cards: list[SystemFindingCard] = []
    for cause in card_sources[:2]:
        source = cause.get("source") or cause.get("suspected_source") or "unknown"
        source_human = human_source(source, tr=tr)
        location = str(cause.get("strongest_location") or tr("UNKNOWN"))
        signatures_human = humanize_signatures(cause.get("signatures_observed", []), lang=lang)
        pattern_text = ", ".join(signatures_human) if signatures_human else tr("UNKNOWN")
        order_label = signatures_human[0] if signatures_human else None
        parts_list = parts_for_pattern(str(source), order_label, lang=lang)

        card_system_name = source_human
        card_parts = [PartSuggestion(name=part) for part in parts_list]
        if tier == "B":
            card_system_name = f"{source_human} — {tr('TIER_B_HYPOTHESIS_LABEL')}"
            card_parts = []

        cards.append(
            SystemFindingCard(
                system_name=card_system_name,
                strongest_location=location,
                pattern_summary=pattern_text,
                parts=card_parts,
                tone=cause.get("confidence_tone", "neutral"),
            ),
        )
    return cards


def humanize_signatures(signatures: object, *, lang: str) -> list[str]:
    """Localize a short list of order signatures for report display."""
    if not isinstance(signatures, list):
        return []
    return [order_label_human(lang, str(sig)) for sig in signatures[:3]]


def build_pattern_evidence(
    context: ReportMappingContext,
    primary: PrimaryCandidateContext,
    lang: str,
    tr: Callable,
) -> PatternEvidence:
    """Build the pattern-evidence block for the report template."""
    systems_raw = [
        human_source(cause.get("source") or cause.get("suspected_source"), tr=tr)
        for cause in context.top_causes[:3]
    ]
    systems = list(dict.fromkeys(systems_raw))
    interpretation = resolve_interpretation(context.origin, lang=lang, tr=tr)
    source_for_why, order_label_for_why = resolve_parts_context(
        primary.primary_candidate,
        lang=lang,
    )
    return PatternEvidence(
        matched_systems=systems,
        strongest_location=primary.primary_location,
        speed_band=primary.primary_speed,
        strength_label=primary.strength_text,
        strength_peak_db=primary.strength_db,
        certainty_label=primary.certainty_label_text,
        certainty_pct=primary.certainty_pct,
        certainty_reason=primary.certainty_reason,
        warning=primary.certainty_reason if primary.weak_spatial else None,
        interpretation=interpretation or None,
        why_parts_text=why_parts_listed(source_for_why, order_label_for_why, lang=lang),
    )


def resolve_interpretation(origin: OriginSummary, *, lang: str, tr: Callable) -> str:
    """Resolve the origin explanation into localized report text."""
    interpretation_raw = origin.get("explanation", "") if isinstance(origin, dict) else ""
    if is_i18n_ref(interpretation_raw) or isinstance(interpretation_raw, list):
        return resolve_i18n(lang, interpretation_raw, tr=tr)
    return str(interpretation_raw)


def resolve_parts_context(
    primary_candidate: CandidateFinding | None,
    *,
    lang: str,
) -> tuple[str, str | None]:
    """Resolve source/order context used for why-parts-listed text."""
    source_for_why = str(
        (primary_candidate.get("source") or primary_candidate.get("suspected_source"))
        if primary_candidate
        else "",
    )
    signatures = primary_candidate.get("signatures_observed", []) if primary_candidate else []
    order_label = order_label_human(lang, str(signatures[0])) if signatures else None
    return source_for_why, order_label


def build_run_metadata_fields(summary: SummaryData, meta: MetadataDict) -> dict[str, object]:
    """Extract and format run metadata text fields for the report template."""
    duration_text = str(summary.get("record_length") or "") or None
    start_time_utc = str(summary.get("start_time_utc") or "").strip() or None
    end_time_utc = str(summary.get("end_time_utc") or "").strip() or None
    raw_sample_rate_hz = _as_float(summary.get("raw_sample_rate_hz"))
    sample_rate_hz = f"{raw_sample_rate_hz:g}" if raw_sample_rate_hz is not None else None
    return {
        "duration_text": duration_text,
        "start_time_utc": start_time_utc,
        "end_time_utc": end_time_utc,
        "sample_rate_hz": sample_rate_hz,
        "tire_spec_text": tire_spec_text(meta),
        "sample_count": int(_as_float(summary.get("rows")) or 0),
        "sensor_model": str(summary.get("sensor_model") or "").strip() or None,
        "firmware_version": str(summary.get("firmware_version") or "").strip() or None,
    }


def tire_spec_text(meta: dict) -> str | None:
    """Format tire specification text from metadata when present."""
    tire_width_mm = _as_float(meta.get("tire_width_mm"))
    tire_aspect_pct = _as_float(meta.get("tire_aspect_pct"))
    rim_in = _as_float(meta.get("rim_in"))
    if not (
        tire_width_mm is not None
        and tire_aspect_pct is not None
        and rim_in is not None
        and tire_width_mm > 0
        and tire_aspect_pct > 0
        and rim_in > 0
    ):
        return None
    return f"{tire_width_mm:g}/{tire_aspect_pct:g}R{rim_in:g}"


def filter_active_sensor_intensity(
    raw_sensor_intensity_all: list,
    sensor_locations_active: list[str],
) -> list[dict]:
    """Filter sensor intensity rows to only active locations."""
    active_locations = set(sensor_locations_active)
    if active_locations:
        return [
            row
            for row in raw_sensor_intensity_all
            if isinstance(row, dict) and str(row.get("location") or "") in active_locations
        ]
    return [row for row in raw_sensor_intensity_all if isinstance(row, dict)]


def build_version_marker() -> str:
    """Return the report version marker including the short git sha when present."""
    git_sha = str(os.getenv("GIT_SHA", "")).strip()
    return f"v{__version__} ({git_sha[:8]})" if git_sha else f"v{__version__}"
