"""report_mapping – thin mapper from prepared report inputs to template data.

Context preparation now happens on the history side, while this module keeps
focused PDF mapping logic plus the final renderer-facing orchestration. It
receives an explicit prepared report input and maps it to
:class:`ReportTemplateData` for the PDF renderer.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from vibesensor import __version__
from vibesensor.adapters.pdf._candidate_resolver import (
    PrimaryCandidateContext,
    resolve_primary_report_candidate,
)
from vibesensor.adapters.pdf._card_builder import (
    build_system_cards,
    humanize_signatures,
)
from vibesensor.adapters.pdf.pattern_parts import why_parts_listed
from vibesensor.adapters.pdf.peak_table import build_peak_rows
from vibesensor.adapters.pdf.presentation import order_label_human
from vibesensor.adapters.pdf.report_context import (
    ReportMappingContext,
    observed_signature,
)
from vibesensor.adapters.pdf.report_data import (
    FindingPresentation,
    PatternEvidence,
    Report,
    ReportTemplateData,
    build_report_from_renderer_payload,
)
from vibesensor.adapters.pdf.report_sections import (
    build_data_trust,
    build_next_steps,
)
from vibesensor.domain import (
    Finding,
    TestRun,
    VibrationOrigin,
)
from vibesensor.report_i18n import human_source, normalize_lang, resolve_i18n
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.vibration_origin import build_origin_explanation
from vibesensor.shared.types.json_types import JsonValue
from vibesensor.use_cases.history.report_preparation import (
    PreparedReportFacts,
    PreparedReportInput,
    ValidatedPreparedReportInput,
    prepare_report_input,
    validate_prepared_report_input,
)

__all__ = [
    "PrimaryCandidateContext",
    "PreparedReportInput",
    "Report",
    "ReportMappingContext",
    "build_system_cards",
    "humanize_signatures",
    "map_summary",
    "prepare_report_input",
    "resolve_primary_report_candidate",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


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


def build_version_marker() -> str:
    """Return the report version marker including the short git sha when present."""
    git_sha = str(os.getenv("GIT_SHA", "")).strip()
    return f"v{__version__} ({git_sha[:8]})" if git_sha else f"v{__version__}"


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def map_summary(prepared: PreparedReportInput) -> ReportTemplateData:
    """Map a prepared report input into the final report template data model.

    Mapping begins by validating the prepared handoff once so the rest of the
    PDF adapter consumes a mapping-ready shape with domain reconstruction and
    report facts already guaranteed.
    """
    validated = validate_prepared_report_input(prepared)
    lang = str(normalize_lang(validated.language))
    report = build_report_from_renderer_payload(
        validated.renderer_payload,
        language=lang,
    )

    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    return _build_report_template_data(
        validated,
        report=report,
        lang=lang,
        tr=tr,
        test_run=validated.domain_test_run,
        report_facts=validated.report_facts,
    )


def _finding_to_presentation(f: Finding) -> FindingPresentation:
    """Convert a domain ``Finding`` to a presentation-ready snapshot."""
    return FindingPresentation(
        suspected_source=str(f.suspected_source),
        severity=f.severity,
        strongest_location=f.strongest_location,
        peak_classification=f.peaks.classification,
        order=f.order,
        frequency_hz=f.frequency_hz,
        effective_confidence=f.effective_confidence,
    )


def _build_report_template_data(
    prepared: ValidatedPreparedReportInput,
    *,
    report: Report,
    lang: str,
    tr: Callable[..., str],
    test_run: TestRun,
    report_facts: PreparedReportFacts,
) -> ReportTemplateData:
    """Map a prepared report input into the final report template data structure.

    The *report* metadata and renderer payload are prepared on the history side;
    the PDF adapter only resolves final presentation details.
    """
    context = prepared.mapping_context
    raw_sensor_intensity = list(report_facts.active_sensor_intensity)
    primary = resolve_primary_report_candidate(
        context=context,
        facts=report_facts.primary_candidate_facts,
        tr=tr,
        lang=lang,
    )
    observed = observed_signature(primary)
    system_cards = build_system_cards(
        context,
        primary,
        lang,
        tr,
    )
    next_steps = build_next_steps(
        recommended_actions=report_facts.recommended_actions,
        tier=primary.tier,
        cert_reason=primary.certainty_reason,
        lang=lang,
        tr=tr,
    )
    data_trust = build_data_trust(
        suitability_checks=report_facts.suitability_checks,
        warnings=report_facts.warnings,
        lang=lang,
        tr=tr,
    )
    pattern_evidence = build_pattern_evidence(
        context,
        primary,
        lang,
        tr,
    )
    peak_rows = build_peak_rows(prepared.renderer_payload.peak_table_rows, lang=lang, tr=tr)
    version_marker = build_version_marker()

    hotspot_rows = list(report_facts.location_hotspot_rows)

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
        findings=[_finding_to_presentation(f) for f in context.domain_aggregate.findings],
        top_causes=[
            _finding_to_presentation(f) for f in context.domain_aggregate.effective_top_causes()
        ],
        sensor_intensity_by_location=raw_sensor_intensity,
        location_hotspot_rows=hotspot_rows,
    )
