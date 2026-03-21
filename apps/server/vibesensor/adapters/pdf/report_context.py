"""Report context assembly — data-prep and card-assembly for the PDF mapper.

Owns the intermediate context models (:class:`ReportMappingContext`,
:class:`PrimaryCandidateContext`, :class:`Report`) and the functions that
assemble them from an :class:`AnalysisSummary` and domain aggregates.

Business-policy card logic (tier-based filtering, confidence-tone
selection) also lives here so that the thin mapper in ``mapping.py``
receives pre-computed decisions.

This module may import from ``use_cases/history`` — it acts as the
bridge between domain/use-case preparation and adapter rendering.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from vibesensor.adapters.pdf.pattern_parts import parts_for_pattern
from vibesensor.adapters.pdf.presentation import order_label_human, strength_label, strength_text
from vibesensor.adapters.pdf.report_data import (
    PartSuggestion,
    PatternEvidence,
    SystemFindingCard,
)
from vibesensor.coerce import coerce_float
from vibesensor.domain import (
    ConfidenceAssessment,
    Finding,
    TestRun,
    VibrationOrigin,
)
from vibesensor.report_i18n import human_source
from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.history.report_interpretation import (
    compute_location_hotspot_rows,
    filter_active_sensor_intensity,
    normalize_origin_location,
    resolve_primary_report_facts,
    resolve_report_origin,
    tire_spec_text,
)

__all__ = [
    "PrimaryCandidateContext",
    "Report",
    "ReportMappingContext",
    "build_report_from_summary",
    "build_system_cards",
    "compute_location_hotspot_rows",
    "filter_active_sensor_intensity",
    "humanize_signatures",
    "prepare_report_mapping_context",
    "resolve_primary_report_candidate",
]

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


# ---------------------------------------------------------------------------
# System cards (tier-based business policy)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Pipeline orchestration — context assembly
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
    origin = resolve_report_origin(domain_aggregate, origin_fallback)

    origin_location = normalize_origin_location(origin)

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
    facts = resolve_primary_report_facts(
        aggregate=context.domain_aggregate,
        origin_location=context.origin_location,
        sensor_locations_active=context.sensor_locations_active,
        sensor_intensity=sensor_intensity,
    )
    primary_system = (
        human_source(facts.primary_source, tr=tr) if facts.primary_source else tr("UNKNOWN")
    )
    primary_location = facts.primary_location or tr("UNKNOWN")
    primary_speed = str(facts.primary_speed or tr("UNKNOWN"))
    strength_text_value = strength_text(facts.strength_db, lang=lang)
    strength_band_key = (
        strength_label(facts.strength_db)[0] if facts.strength_db is not None else None
    )

    if facts.domain_primary and facts.domain_primary.confidence_assessment:
        ca = facts.domain_primary.confidence_assessment
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
        tier = ConfidenceAssessment.assess(
            facts.confidence,
            strength_band_key=strength_band_key,
        ).tier
    return PrimaryCandidateContext(
        primary_candidate=primary_candidate,
        primary_source=facts.primary_source,
        primary_system=primary_system,
        primary_location=primary_location,
        primary_speed=primary_speed,
        confidence=facts.confidence,
        sensor_count=facts.sensor_count,
        weak_spatial=facts.weak_spatial,
        has_reference_gaps=facts.has_reference_gaps,
        strength_db=facts.strength_db,
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
