"""report_mapping – maps analysis summaries to report-ready data structures."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from statistics import mean as _mean
from typing import Any

from vibesensor import __version__
from vibesensor.adapters.pdf.pattern_parts import parts_for_pattern, why_parts_listed
from vibesensor.adapters.pdf.peak_table import build_peak_rows_from_plots
from vibesensor.adapters.pdf.presentation import order_label_human, strength_label, strength_text
from vibesensor.adapters.pdf.report_data import (
    PartSuggestion,
    PatternEvidence,
    ReportTemplateData,
    SystemFindingCard,
)
from vibesensor.adapters.pdf.report_sections import (
    build_data_trust_from_summary,
    build_next_steps_from_summary,
)
from vibesensor.coerce import coerce_float
from vibesensor.domain import (
    ConfidenceAssessment,
    Finding,
    TestRun,
    VibrationOrigin,
)
from vibesensor.report_i18n import human_source, normalize_lang, resolve_i18n
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.boundaries.vibration_origin import (
    build_origin_explanation,
    vibration_origin_from_payload,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.json_types import JsonObject

__all__ = ["Report", "map_summary"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Report metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Report:
    """Run-level metadata carrier consumed by the report rendering pipeline."""

    run_id: str
    title: str = ""
    lang: str = "en"
    car_name: str | None = None
    car_type: str | None = None
    report_date: str | None = None
    duration_s: float | None = None
    sample_count: int = 0
    sensor_count: int = 0

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must be non-empty")
        if self.duration_s is not None and self.duration_s < 0:
            raise ValueError("duration_s must be non-negative")


# ---------------------------------------------------------------------------
# Intermediate models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportMappingContext:
    """Normalized structural context pulled from an analysis summary.

    Owns display-ready metadata access, primary hotspot / candidate
    selection helpers, and report-mapping decisions that were previously
    spread across helper functions and ``dict.get(...)`` calls.

    Domain ``Finding`` objects are available alongside payload dicts so
    that business decisions (classification, ranking, actionability) use
    the domain model while rendering-level evidence detail comes from
    the payloads.
    """

    car_name: str | None
    car_type: str | None
    date_str: str
    origin: VibrationOrigin | None
    origin_location: str
    sensor_locations_active: list[str]
    # Typed run metadata (replaces dict[str, object] + type: ignore).
    duration_text: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sample_rate_hz: str | None
    tire_spec_text: str | None
    sample_count: int
    sensor_model: str | None
    firmware_version: str | None
    # Domain aggregate — the primary data source for business decisions.
    domain_aggregate: TestRun

    # -- candidate selection ------------------------------------------------

    def top_report_candidate(self) -> Finding | None:
        """Return the primary report candidate (first effective top cause or finding)."""
        effective = self.domain_aggregate.effective_top_causes()
        if effective:
            return effective[0]
        non_ref = self.domain_aggregate.non_reference_findings
        if non_ref:
            return non_ref[0]
        all_findings = self.domain_aggregate.findings
        return all_findings[0] if all_findings else None

    # -- intensity queries --------------------------------------------------

    def has_significant_location_intensity(
        self,
        sensor_intensity: list[dict[str, object]],
    ) -> bool:
        """Whether any sensor location shows significant above-noise intensity."""
        for row in sensor_intensity:
            if not isinstance(row, dict):
                continue
            p95 = _as_float(row.get("p95_intensity_db"))
            if p95 is not None and p95 > 0:
                return True
        return False

    # -- observed signature -------------------------------------------------

    def observed_signature(self, primary: PrimaryCandidateContext) -> PatternEvidence:
        """Build the observed-signature block for the report template."""
        return PatternEvidence(
            primary_system=primary.primary_system,
            strongest_location=primary.primary_location,
            speed_band=primary.primary_speed,
            strength_label=primary.strength_text,
            strength_peak_db=primary.strength_db,
            certainty_label=primary.certainty_label_text,
            certainty_pct=primary.certainty_pct,
            certainty_reason=primary.certainty_reason,
        )


@dataclass(frozen=True)
class PrimaryCandidateContext:
    """Primary report candidate resolved from top causes or findings."""

    primary_candidate: Finding | None
    primary_source: object
    primary_system: str
    primary_location: str
    primary_speed: str
    confidence: float
    sensor_count: int
    weak_spatial: bool
    has_reference_gaps: bool
    strength_db: float | None
    strength_text: str
    strength_band_key: str | None
    certainty_key: str
    certainty_label_text: str
    certainty_pct: str
    certainty_reason: str
    tier: str


def _origin_from_aggregate(
    aggregate: TestRun | None,
    fallback: Mapping[str, Any] | None,
) -> VibrationOrigin | None:
    fallback_origin: VibrationOrigin | None = None
    if isinstance(fallback, Mapping):
        raw_location = str(fallback.get("location") or "").strip()
        alternatives_raw = fallback.get("alternative_locations")
        alternatives = (
            [str(location).strip() for location in alternatives_raw if str(location).strip()]
            if isinstance(alternatives_raw, list)
            else []
        )

        strongest_location = (
            raw_location.split(" / ", maxsplit=1)[0].strip() if raw_location else ""
        )
        hotspot = None
        if strongest_location and strongest_location.lower() != "unknown":
            from vibesensor.domain import LocationHotspot

            hotspot = LocationHotspot.from_analysis_inputs(
                strongest_location=strongest_location,
                dominance_ratio=_as_float(fallback.get("dominance_ratio")),
                weak_spatial_separation=bool(fallback.get("weak_spatial_separation", False)),
                ambiguous=bool(alternatives),
                alternative_locations=alternatives,
            )

        speed_band = str(fallback.get("speed_band") or "").strip() or None
        dominant_phase = str(fallback.get("dominant_phase") or "").strip() or None
        dominance_ratio = _as_float(fallback.get("dominance_ratio"))
        if (
            hotspot is not None
            or speed_band is not None
            or dominant_phase is not None
            or dominance_ratio is not None
        ):
            fallback_origin = vibration_origin_from_payload(
                fallback,
                hotspot=hotspot,
                dominance_ratio=dominance_ratio,
                speed_band=speed_band,
            )

    if aggregate is not None and aggregate.primary_finding is not None:
        primary_origin = VibrationOrigin.from_finding(aggregate.primary_finding)
        if primary_origin is None:
            return fallback_origin
        if not primary_origin.has_sufficient_location and fallback_origin is not None:
            return fallback_origin
        return primary_origin

    return fallback_origin


def normalized_origin_location(origin: VibrationOrigin | None) -> str:
    """Return the report-ready origin location string."""
    if origin is None:
        return ""
    raw = origin.projected_location.strip()
    return "" if raw.lower() == "unknown" else raw


def compute_location_hotspot_rows(sensor_intensity: list[dict]) -> list[dict]:
    """Pre-compute location hotspot rows from sensor intensity data."""
    if not sensor_intensity:
        return []
    amp_by_location = collect_location_intensity(sensor_intensity)
    hotspot_rows = [
        {
            "location": location,
            "count": len(amps),
            "unit": "db",
            "peak_value": max(amps),
            "mean_value": _mean(amps),
        }
        for location, amps in amp_by_location.items()
    ]
    hotspot_rows.sort(
        key=lambda row: (
            _as_float(row.get("peak_value")) or 0.0,
            _as_float(row.get("mean_value")) or 0.0,
        ),
        reverse=True,
    )
    return hotspot_rows


def collect_location_intensity(sensor_intensity: list[dict]) -> dict[str, list[float]]:
    """Collect per-location intensity values from summary sensor intensity rows."""
    amp_by_location: dict[str, list[float]] = defaultdict(list)
    for row in sensor_intensity:
        if not isinstance(row, dict):
            continue
        location = str(row.get("location") or "").strip()
        p95_val = _as_float(row.get("p95_intensity_db"))
        p95 = p95_val if p95_val is not None else _as_float(row.get("mean_intensity_db"))
        if location and p95 is not None and p95 > 0:
            amp_by_location[location].append(p95)
    return amp_by_location


# ---------------------------------------------------------------------------
# System, metadata, and strength helpers
# ---------------------------------------------------------------------------


def _sensor_fallback_strength_db(sensor_intensity: list[JsonObject]) -> float | None:
    """Return the best sensor-intensity dB as a last-resort fallback."""
    sensor_rows = [
        _as_float(row.get("p95_intensity_db")) for row in sensor_intensity if isinstance(row, dict)
    ]
    return max((value for value in sensor_rows if value is not None), default=None)


def build_system_cards(
    context: ReportMappingContext,
    primary: PrimaryCandidateContext,
    lang: str,
    tr: Callable,
) -> list[SystemFindingCard]:
    """Build system finding cards for the report template.

    Uses domain ``Finding`` objects from the aggregate for business
    decisions (source classification, confidence tone).  Rendering-only
    detail (signatures text) is still read from the payload dicts.
    """
    tier = primary.tier
    if tier == "A":
        return []
    aggregate = context.domain_aggregate
    card_sources = (
        aggregate.effective_top_causes() or aggregate.non_reference_findings or aggregate.findings
    )

    cards: list[SystemFindingCard] = []
    for domain_finding in card_sources[:2]:
        source = str(domain_finding.suspected_source)
        source_human = human_source(source, tr=tr)
        # Use domain LocationHotspot for location when available
        if domain_finding.location and domain_finding.location.is_actionable:
            location = domain_finding.location.display_location
        else:
            location = str(domain_finding.strongest_location or tr("UNKNOWN"))
        # Use domain ConfidenceAssessment for tone when available
        if domain_finding.confidence_assessment:
            tone = domain_finding.confidence_assessment.tone
        else:
            tone = domain_finding.confidence_label(
                strength_band_key=primary.strength_band_key,
            )[1]

        # Rendering detail from domain signatures.
        signature_values: object
        if domain_finding.signature_labels:
            signature_values = list(domain_finding.signature_labels)
        else:
            signature_values = []
        signatures_human = humanize_signatures(signature_values, lang=lang)
        pattern_text = ", ".join(signatures_human) if signatures_human else tr("UNKNOWN")
        order_label = signatures_human[0] if signatures_human else None
        parts_list = parts_for_pattern(source, order_label, lang=lang)

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
                tone=tone,
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
    """Build the pattern-evidence block for the report template.

    Uses the domain aggregate for system classification when available.
    """
    # Domain-first: use aggregate effective top causes for matched systems
    aggregate = context.domain_aggregate
    assert aggregate is not None
    domain_primary = None
    effective = aggregate.effective_top_causes()
    domain_primary = effective[0] if effective else aggregate.primary_finding
    systems_raw = [human_source(str(f.suspected_source), tr=tr) for f in effective[:3]]
    systems = list(dict.fromkeys(systems_raw))
    interpretation = resolve_interpretation(context.origin, lang=lang, tr=tr)
    source_for_why, order_label_for_why = resolve_parts_context(
        primary.primary_candidate,
        domain_finding=domain_primary,
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


def resolve_interpretation(origin: VibrationOrigin | None, *, lang: str, tr: Callable) -> str:
    """Resolve the origin explanation into localized report text."""
    if origin is None:
        return ""

    explanation = build_origin_explanation(
        source=str(origin.suspected_source),
        speed_band=origin.speed_band or "",
        location=origin.summary_location,
        dominance=origin.dominance_ratio,
        weak=origin.weak_spatial_separation,
        dominant_phase=origin.dominant_phase or "",
    )
    return resolve_i18n(lang, explanation, tr=tr)


def resolve_parts_context(
    primary_candidate: Finding | None,
    *,
    domain_finding: Finding | None = None,
    lang: str,
) -> tuple[str, str | None]:
    """Resolve source/order context used for why-parts-listed text."""
    finding = domain_finding or primary_candidate
    if finding is not None:
        source_for_why = str(finding.suspected_source)
        signatures: object = list(finding.signature_labels)
    else:
        source_for_why = ""
        signatures = []
    if isinstance(signatures, list) and signatures:
        order_label = order_label_human(lang, str(signatures[0]))
    else:
        order_label = None
    return source_for_why, order_label


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


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def prepare_report_mapping_context(
    summary: AnalysisSummary,
    *,
    test_run: TestRun | None = None,
) -> ReportMappingContext:
    """Extract structural summary context for report mapping.

    Builds a domain ``TestRun`` aggregate from the summary dict
    so that downstream business decisions (effective-cause selection,
    reference-gap detection, strength lookup) are domain-first.

    When *test_run* is supplied, reconstruction is skipped and the
    caller-provided aggregate is used directly (avoids double
    reconstruction when the caller already holds a ``TestRun``).
    """
    meta = summary["metadata"]
    car_name = str(meta.get("car_name") or "").strip() or None
    car_type = str(meta.get("car_type") or "").strip() or None
    report_date = str(summary["report_date"] or "") or utc_now_iso()
    date_str = str(report_date)[:19].replace("T", " ") + " UTC"

    connected = summary["sensor_locations_connected_throughout"]
    sensor_locations_active = [loc for loc in connected if loc.strip()]
    if not sensor_locations_active:
        sensor_locations_active = [loc for loc in summary["sensor_locations"] if loc.strip()]

    # Build domain aggregate for domain-first decisions downstream
    if test_run is None:
        from vibesensor.shared.boundaries.diagnostic_case import test_run_from_summary

        domain_aggregate = test_run_from_summary(summary)
    else:
        domain_aggregate = test_run

    origin_fallback = summary.get("most_likely_origin")
    origin = _origin_from_aggregate(domain_aggregate, origin_fallback)

    origin_location = normalized_origin_location(origin)

    config_snap = domain_aggregate.capture.setup.configuration_snapshot
    rate = config_snap.raw_sample_rate_hz

    return ReportMappingContext(
        car_name=car_name,
        car_type=car_type,
        date_str=date_str,
        origin=origin,
        origin_location=origin_location,
        sensor_locations_active=sensor_locations_active,
        duration_text=summary["record_length"] or None,
        start_time_utc=str(summary["start_time_utc"] or "").strip() or None,
        end_time_utc=str(summary["end_time_utc"] or "").strip() or None,
        sample_rate_hz=f"{rate:g}" if rate is not None else None,
        tire_spec_text=tire_spec_text(meta),
        sample_count=domain_aggregate.capture.sample_count,
        sensor_model=config_snap.sensor_model,
        firmware_version=config_snap.firmware_version,
        domain_aggregate=domain_aggregate,
    )


def resolve_primary_report_candidate(
    *,
    context: ReportMappingContext,
    sensor_intensity: list[JsonObject],
    tr: Callable[..., str],
    lang: str,
) -> PrimaryCandidateContext:
    """Resolve the primary candidate and all derived certainty fields.

    Uses domain ``Finding`` objects from the aggregate for all business
    decisions (classification, ranking, confidence, source, location).
    Payload dicts supply rendering-level evidence detail only.
    """
    primary_candidate = context.top_report_candidate()
    aggregate = context.domain_aggregate

    primary_source: object = None
    # Domain-first: derive all business fields from the aggregate
    effective = aggregate.effective_top_causes()
    domain_primary = effective[0] if effective else aggregate.primary_finding
    if domain_primary:
        primary_source = domain_primary.suspected_source
        primary_system = human_source(primary_source, tr=tr)
        primary_location = context.origin_location or (
            domain_primary.strongest_location or tr("UNKNOWN")
        )
        primary_speed = str(
            domain_primary.strongest_speed_band or tr("UNKNOWN"),
        )
        confidence = domain_primary.effective_confidence
    else:
        primary_system = tr("UNKNOWN")
        primary_location = context.origin_location or tr("UNKNOWN")
        primary_speed = tr("UNKNOWN")
        confidence = 0.0

    # Domain-first strength and reference gap detection
    strength_db = aggregate.top_strength_db()
    # Fall back to sensor intensity if domain aggregate has no strength
    if strength_db is None:
        strength_db = _sensor_fallback_strength_db(sensor_intensity)
    has_ref_gaps = aggregate.has_relevant_reference_gap(
        str(primary_source) if primary_source else "unknown",
    )
    effective = aggregate.effective_top_causes()
    domain_primary = effective[0] if effective else aggregate.primary_finding
    weak_spatial = domain_primary.weak_spatial_separation if domain_primary else False

    strength_text_value = strength_text(strength_db, lang=lang)
    sensor_count = len(context.sensor_locations_active) or len(
        context.domain_aggregate.capture.setup.sensors
    )
    strength_band_key = strength_label(strength_db)[0] if strength_db is not None else None

    # Use domain ConfidenceAssessment when available on the primary finding
    effective = aggregate.effective_top_causes()
    domain_primary = effective[0] if effective else aggregate.primary_finding

    if domain_primary and domain_primary.confidence_assessment:
        ca = domain_primary.confidence_assessment
        certainty_key = ca.label_key
        certainty_label_text = tr(ca.label_key)
        certainty_pct = ca.pct_text
        certainty_reason = ca.reason
        tier = ca.tier
    else:
        certainty_key = "CONFIDENCE_LOW"
        certainty_label_text = tr("CONFIDENCE_LOW")
        certainty_pct = "0%"
        certainty_reason = ""
        tier = ConfidenceAssessment.assess(confidence, strength_band_key=strength_band_key).tier
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


def build_report_from_summary(summary: AnalysisSummary) -> Report:
    """Create a domain Report from a ``SummaryData`` dict.

    Extracts run-level metadata.  Finding-level data is handled
    separately by :func:`prepare_report_mapping_context`.
    """
    meta = summary.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}

    car_name = str(meta.get("car_name") or "").strip() or None
    car_type = str(meta.get("car_type") or "").strip() or None

    rows = summary.get("rows")
    sample_count = int(rows) if isinstance(rows, (int, float, str)) else 0

    sensor_count_raw = summary.get("sensor_count_used")
    sensor_count = int(sensor_count_raw) if isinstance(sensor_count_raw, (int, float, str)) else 0

    duration_s_raw = summary.get("duration_s")
    duration_s: float | None = None
    if duration_s_raw is not None:
        try:
            duration_s = coerce_float(duration_s_raw)
        except (TypeError, ValueError):
            pass

    report_date = summary.get("report_date")
    report_date_str = str(report_date) if isinstance(report_date, str) else None

    run_id = str(summary.get("run_id", ""))

    return Report(
        run_id=run_id or "unknown",
        lang=str(summary.get("lang", "en")),
        car_name=car_name,
        car_type=car_type,
        report_date=report_date_str,
        duration_s=duration_s,
        sample_count=sample_count,
        sensor_count=sensor_count,
    )


def map_summary(
    summary: AnalysisSummary,
    *,
    test_run: TestRun | None = None,
) -> ReportTemplateData:
    """Map a run summary dict into the final report template data model.

    Constructs a domain :class:`~vibesensor.domain.Report` as the
    high-level entry point, then delegates to the template-data builder
    for PDF-specific rendering fields.

    When *test_run* is supplied, reconstruction from the summary dict is
    skipped and the caller-provided aggregate is used directly.
    """
    lang = str(normalize_lang(summary.get("lang")))
    report = build_report_from_summary(summary)

    def tr(key: str, **kw: object) -> str:
        return str(_tr(lang, key, **kw))

    return _build_report_template_data(summary, report=report, lang=lang, tr=tr, test_run=test_run)


def _build_report_template_data(
    summary: AnalysisSummary,
    *,
    report: Report,
    lang: str,
    tr: Callable[..., str],
    test_run: TestRun | None = None,
) -> ReportTemplateData:
    """Map a summary dict into the final report template data structure.

    The *report* domain object provides high-level metadata; rendering-
    specific fields are resolved from the full *summary* dict.
    """
    context = prepare_report_mapping_context(summary, test_run=test_run)
    raw_sensor_intensity = filter_active_sensor_intensity(
        summary["sensor_intensity_by_location"],
        context.sensor_locations_active,
    )
    primary = resolve_primary_report_candidate(
        context=context,
        sensor_intensity=raw_sensor_intensity,
        tr=tr,
        lang=lang,
    )
    observed = context.observed_signature(primary)
    system_cards = build_system_cards(
        context,
        primary,
        lang,
        tr,
    )
    next_steps = build_next_steps_from_summary(
        summary,
        aggregate=context.domain_aggregate,
        tier=primary.tier,
        cert_reason=primary.certainty_reason,
        lang=lang,
        tr=tr,
    )
    data_trust = build_data_trust_from_summary(
        summary,
        aggregate=context.domain_aggregate,
        lang=lang,
        tr=tr,
    )
    pattern_evidence = build_pattern_evidence(
        context,
        primary,
        lang,
        tr,
    )
    peak_rows = build_peak_rows_from_plots(summary, lang=lang, tr=tr)
    version_marker = build_version_marker()

    hotspot_rows = compute_location_hotspot_rows(raw_sensor_intensity)

    return ReportTemplateData(
        title=tr("DIAGNOSTIC_WORKSHEET"),
        run_datetime=context.date_str,
        run_id=report.run_id,
        duration_text=context.duration_text,
        start_time_utc=context.start_time_utc,
        end_time_utc=context.end_time_utc,
        sample_rate_hz=context.sample_rate_hz,
        tire_spec_text=context.tire_spec_text,
        sample_count=context.sample_count,
        sensor_count=primary.sensor_count,
        sensor_locations=context.sensor_locations_active,
        sensor_model=context.sensor_model,
        firmware_version=context.firmware_version,
        car_name=report.car_name or context.car_name,
        car_type=report.car_type or context.car_type,
        observed=observed,
        system_cards=system_cards,
        next_steps=next_steps,
        data_trust=data_trust,
        pattern_evidence=pattern_evidence,
        peak_rows=peak_rows,
        version_marker=version_marker,
        lang=report.lang,
        certainty_tier_key=primary.tier,
        findings=list(context.domain_aggregate.findings),
        top_causes=list(context.domain_aggregate.effective_top_causes()),
        sensor_intensity_by_location=raw_sensor_intensity,
        location_hotspot_rows=hotspot_rows,
    )
