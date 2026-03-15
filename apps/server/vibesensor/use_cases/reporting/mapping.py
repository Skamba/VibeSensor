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
from vibesensor.adapters.persistence.boundaries.finding import finding_payload_from_domain
from vibesensor.adapters.persistence.boundaries.run_suitability import run_suitability_payload
from vibesensor.adapters.persistence.boundaries.vibration_origin import (
    SuspectedVibrationOrigin,
    origin_payload_from_finding,
)
from vibesensor.adapters.persistence.runlog import utc_now_iso
from vibesensor.domain import Finding, Report, TestRun, VibrationSource
from vibesensor.shared.utils.json_utils import as_float_or_none as _as_float
from vibesensor.use_cases.diagnostics._types import (
    IntensityRow,
    JsonValue,
    MetadataDict,
    RunSuitabilityCheck,
    SpeedStats,
    TestStep,
)
from vibesensor.use_cases.diagnostics.diagnosis_candidates import normalize_origin_location
from vibesensor.use_cases.diagnostics.helpers import PHASE_I18N_KEYS
from vibesensor.use_cases.diagnostics.plots import PeakTableRow
from vibesensor.use_cases.diagnostics.strength_labels import (
    certainty_tier,
    strength_label,
    strength_text,
)
from vibesensor.use_cases.reporting.i18n import normalize_lang
from vibesensor.use_cases.reporting.i18n import tr as _tr

from .pattern_parts import parts_for_pattern, why_parts_listed
from .report_data import (
    DataTrustItem,
    NextStep,
    PartSuggestion,
    PatternEvidence,
    PeakRow,
    ReportTemplateData,
    SystemFindingCard,
)

__all__ = ["map_summary"]

logger = logging.getLogger(__name__)


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

    meta: MetadataDict
    car_name: str | None
    car_type: str | None
    date_str: str
    speed_stats: SpeedStats
    origin: SuspectedVibrationOrigin
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
# Shared i18n and value-resolution helpers
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


def is_i18n_ref(value: object) -> bool:
    """Check whether *value* is a language-neutral i18n reference dict."""
    return isinstance(value, dict) and "_i18n_key" in value


def human_source(source: object, *, tr: Callable[[str], str]) -> str:
    """Resolve a source code to its user-facing label."""
    raw = str(source or "").strip().lower()
    mapping: dict[VibrationSource, str] = {
        VibrationSource.WHEEL_TIRE: tr("SOURCE_WHEEL_TIRE"),
        VibrationSource.DRIVELINE: tr("SOURCE_DRIVELINE"),
        VibrationSource.ENGINE: tr("SOURCE_ENGINE"),
        VibrationSource.BODY_RESONANCE: tr("SOURCE_BODY_RESONANCE"),
        VibrationSource.TRANSIENT_IMPACT: tr("SOURCE_TRANSIENT_IMPACT"),
        VibrationSource.BASELINE_NOISE: tr("SOURCE_BASELINE_NOISE"),
        VibrationSource.UNKNOWN_RESONANCE: tr("SOURCE_UNKNOWN_RESONANCE"),
        VibrationSource.UNKNOWN: tr("UNKNOWN"),
    }
    try:
        key = VibrationSource(raw)
    except ValueError:
        logger.warning(
            "Unrecognized vibration source %r; falling back to titlecase",
            raw,
        )
        return raw.replace("_", " ").title() if raw else tr("UNKNOWN")
    return mapping.get(key, tr("UNKNOWN"))


def resolve_i18n(
    lang: str,
    value: object,
    *,
    tr: Callable[..., str],
) -> str:
    """Resolve plain strings, i18n refs, or lists of i18n refs to text."""
    if isinstance(value, list):
        return " ".join(resolve_i18n(lang, item, tr=tr) for item in value if item)
    if not isinstance(value, dict) or "_i18n_key" not in value:
        return str(value) if value is not None else ""
    key = str(value["_i18n_key"])
    suffix = str(value.get("_suffix", ""))
    params = {k: v for k, v in value.items() if k not in ("_i18n_key", "_suffix")}
    resolved_params: dict[str, JsonValue] = {}
    for param_key, param_value in params.items():
        if is_i18n_ref(param_value):
            resolved_params[param_key] = resolve_i18n(lang, param_value, tr=tr)
        elif param_key == "source" and isinstance(param_value, str):
            resolved_params[param_key] = human_source(param_value, tr=tr)
        elif param_key == "phase" and isinstance(param_value, str):
            i18n_key = PHASE_I18N_KEYS.get(param_value)
            resolved_params[param_key] = tr(i18n_key) if i18n_key else param_value
        else:
            resolved_params[param_key] = param_value
    result = tr(key, **resolved_params)
    return result + suffix if suffix else result


def order_label_human(lang: str, label: str) -> str:
    """Translate a language-neutral order label like ``1x wheel``."""
    names = _ORDER_LABEL_NAMES_NL if lang == "nl" else _ORDER_LABEL_NAMES_DEFAULT
    parts = label.strip().split(" ", 1)
    if len(parts) == 2:
        multiplier, base = parts
        localized = names.get(base.lower(), base)
        return f"{multiplier} {localized}"
    return label


def peak_classification_text(value: object, tr: Callable[..., str]) -> str:
    """Map a peak classification code to report text."""
    normalized = str(value or "").strip().lower()
    i18n_key = _CLASSIFICATION_I18N_KEYS.get(normalized)
    if i18n_key:
        return tr(i18n_key)
    if not normalized:
        return tr("UNKNOWN")
    return str(value).replace("_", " ").title()


# ---------------------------------------------------------------------------
# Context extraction
# ---------------------------------------------------------------------------

_EMPTY_SPEED_STATS: SpeedStats = {
    "min_kmh": None,
    "max_kmh": None,
    "mean_kmh": None,
    "stddev_kmh": None,
    "range_kmh": None,
    "steady_speed": False,
}

_EMPTY_ORIGIN: SuspectedVibrationOrigin = {
    "location": "unknown",
    "alternative_locations": [],
    "suspected_source": "unknown",
    "dominance_ratio": None,
    "weak_spatial_separation": True,
}


def summary_metadata(summary: Mapping[str, Any]) -> MetadataDict:
    return summary.get("metadata") or {}


def summary_report_date(summary: Mapping[str, Any]) -> str:
    return str(summary.get("report_date") or "")


def summary_row_count(summary: Mapping[str, Any]) -> int:
    return int(_as_float(summary.get("rows")) or 0)


def summary_record_length(summary: Mapping[str, Any]) -> str | None:
    return str(summary.get("record_length") or "") or None


def summary_start_time_utc(summary: Mapping[str, Any]) -> str | None:
    return str(summary.get("start_time_utc") or "").strip() or None


def summary_end_time_utc(summary: Mapping[str, Any]) -> str | None:
    return str(summary.get("end_time_utc") or "").strip() or None


def summary_raw_sample_rate_hz(summary: Mapping[str, Any]) -> float | None:
    return _as_float(summary.get("raw_sample_rate_hz"))


def summary_sensor_model(summary: Mapping[str, Any]) -> str | None:
    return str(summary.get("sensor_model") or "").strip() or None


def summary_firmware_version(summary: Mapping[str, Any]) -> str | None:
    return str(summary.get("firmware_version") or "").strip() or None


def summary_sensor_count_used(summary: Mapping[str, Any]) -> int:
    return int(_as_float(summary.get("sensor_count_used")) or 0)


def summary_speed_stats(summary: Mapping[str, Any]) -> SpeedStats:
    return summary.get("speed_stats") or _EMPTY_SPEED_STATS


def summary_origin(summary: Mapping[str, Any]) -> SuspectedVibrationOrigin:
    return summary.get("most_likely_origin") or _EMPTY_ORIGIN


def summary_test_plan(summary: Mapping[str, Any]) -> list[TestStep]:
    return [step for step in summary.get("test_plan", []) if isinstance(step, dict)]


def summary_run_suitability(summary: Mapping[str, Any]) -> list[RunSuitabilityCheck]:
    return [item for item in summary.get("run_suitability", []) if isinstance(item, dict)]  # type: ignore[misc]


def summary_warnings(summary: Mapping[str, Any]) -> list[object]:
    return list(summary.get("warnings", []))


def summary_sensor_intensity_by_location(summary: Mapping[str, Any]) -> list[IntensityRow]:
    return [row for row in summary.get("sensor_intensity_by_location", []) if isinstance(row, dict)]


def summary_sensor_locations_active(summary: Mapping[str, Any]) -> list[str]:
    connected = summary.get("sensor_locations_connected_throughout", [])
    active = [str(loc) for loc in connected if str(loc).strip()]
    if not active:
        active = [str(loc) for loc in summary.get("sensor_locations", []) if str(loc).strip()]
    return active


def summary_sample_rate_hz_text(summary: Mapping[str, Any]) -> str | None:
    rate = summary_raw_sample_rate_hz(summary)
    return f"{rate:g}" if rate is not None else None


def _origin_from_aggregate(
    aggregate: TestRun | None,
    fallback: SuspectedVibrationOrigin,
) -> SuspectedVibrationOrigin:
    if aggregate is None or aggregate.primary_finding is None:
        return fallback

    return origin_payload_from_finding(aggregate.primary_finding, fallback)


def normalized_origin_location(origin: SuspectedVibrationOrigin) -> str:
    """Return the report-ready origin location string."""
    return normalize_origin_location(origin.get("location"))


# ---------------------------------------------------------------------------
# Peak-row and location-hotspot shaping
# ---------------------------------------------------------------------------


def build_peak_rows_from_plots(
    summary: Mapping[str, Any],
    *,
    lang: str,
    tr: Callable,
) -> list[PeakRow]:
    """Build peak-table rows from the plots section."""
    plots = summary.get("plots")
    if plots is None:
        return []
    raw_peaks = [row for row in (plots.get("peaks_table", []) or []) if isinstance(row, dict)]
    above_noise = [
        row
        for row in raw_peaks
        if ((_strength_db := _as_float(row.get("strength_db"))) is None or _strength_db > 0)
    ]
    return [build_peak_row(row, lang=lang, tr=tr) for row in above_noise[:8]]  # type: ignore[arg-type]


def build_peak_row(row: PeakTableRow, *, lang: str, tr: Callable) -> PeakRow:
    """Build one report peak row from a plot peak-table row."""
    rank_val = _as_float(row.get("rank"))
    rank = str(int(rank_val)) if rank_val is not None else "—"
    freq_val = _as_float(row.get("frequency_hz"))
    freq = f"{freq_val:.1f}" if freq_val is not None else "—"
    classification = peak_classification_text(row.get("peak_classification"), tr=tr)
    order_label_raw = str(row.get("order_label") or "").strip()
    order = order_label_human(lang, order_label_raw) if order_label_raw else classification
    peak_db_val = _as_float(row.get("p95_intensity_db"))
    peak_db = f"{peak_db_val:.1f}" if peak_db_val is not None else "—"
    strength_db_val = _as_float(row.get("strength_db"))
    strength_db = f"{strength_db_val:.1f}" if strength_db_val is not None else "—"
    speed = str(row.get("typical_speed_band") or "—")
    presence = _as_float(row.get("presence_ratio")) or 0.0
    score = _as_float(row.get("persistence_score")) or 0.0
    return PeakRow(
        rank=rank,
        system=peak_row_system_label(row, order=order, tr=tr),
        freq_hz=freq,
        order=order,
        peak_db=peak_db,
        strength_db=strength_db,
        speed_band=speed,
        relevance=f"{classification} · {presence:.0%} {tr('PRESENCE')} · {tr('SCORE')} {score:.2f}",
    )


def peak_row_system_label(row: PeakTableRow, *, order: str, tr: Callable[..., str]) -> str:
    """Resolve the system label shown for one peak row."""
    order_lower = order.lower()
    source_hint = str(row.get("source") or "").strip().lower()
    if source_hint == VibrationSource.WHEEL_TIRE or "wheel" in order_lower:
        return str(tr("SOURCE_WHEEL_TIRE"))
    if source_hint == VibrationSource.ENGINE or "engine" in order_lower:
        return str(tr("SOURCE_ENGINE"))
    if (
        source_hint == VibrationSource.DRIVELINE
        or "driveshaft" in order_lower
        or "drive" in order_lower
    ):
        return str(tr("SOURCE_DRIVELINE"))
    if "transient" in order_lower:
        return str(tr("SOURCE_TRANSIENT_IMPACT"))
    return "—"


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
# Action and trust-list builders
# ---------------------------------------------------------------------------


def build_next_steps_from_summary(
    summary: Mapping[str, Any],
    *,
    aggregate: TestRun | None,
    tier: str,
    cert_reason: str,
    lang: str,
    tr: Callable,
) -> list[NextStep]:
    """Build next-step actions from a run summary dict."""
    if tier == "A":
        return [
            NextStep(action=action, why=cert_reason)
            for action in (
                tr("TIER_A_CAPTURE_WIDER_SPEED"),
                tr("TIER_A_CAPTURE_MORE_SENSORS"),
                tr("TIER_A_CAPTURE_REFERENCE_DATA"),
            )
        ]

    next_steps: list[NextStep] = []
    summary_steps = summary_test_plan(summary)
    if aggregate is not None and aggregate.recommended_actions:
        for action in aggregate.recommended_actions:
            next_steps.append(
                NextStep(
                    action=_resolve_step_value(action.instruction, lang=lang, tr=tr),
                    why=_resolve_optional_step_value(action.rationale, lang=lang, tr=tr),
                    confirm=_resolve_optional_step_value(
                        action.confirmation_signal,
                        lang=lang,
                        tr=tr,
                    ),
                    falsify=_resolve_optional_step_value(
                        action.falsification_signal,
                        lang=lang,
                        tr=tr,
                    ),
                    eta=action.estimated_duration,
                ),
            )
        if next_steps:
            return next_steps
    for step in summary_steps:
        next_steps.append(
            NextStep(
                action=_resolve_step_value(step.get("what"), lang=lang, tr=tr),
                why=_resolve_optional_step_value(step.get("why"), lang=lang, tr=tr),
                confirm=_resolve_optional_step_value(step.get("confirm"), lang=lang, tr=tr),
                falsify=_resolve_optional_step_value(step.get("falsify"), lang=lang, tr=tr),
                eta=str(step.get("eta") or "") or None,
            ),
        )
    return next_steps


def _resolve_step_value(value: object, *, lang: str, tr: Callable) -> str:
    """Resolve a required step field into report text."""
    if isinstance(value, str) and value.isupper() and "_" in value:
        translated = str(tr(value))
        if translated and translated != value:
            return translated
    return resolve_i18n(lang, value, tr=tr) if is_i18n_ref(value) else str(value or "")


def _resolve_optional_step_value(
    value: object,
    *,
    lang: str,
    tr: Callable,
) -> str | None:
    """Resolve an optional step field into report text or ``None``."""
    resolved = _resolve_step_value(value, lang=lang, tr=tr).strip()
    return resolved or None


def build_data_trust_from_summary(
    summary: Mapping[str, Any],
    *,
    aggregate: TestRun | None,
    lang: str,
    tr: Callable,
) -> list[DataTrustItem]:
    """Build the data-trust checklist from run_suitability items."""
    data_trust: list[DataTrustItem] = []
    if aggregate is not None and aggregate.suitability is not None:
        projected = run_suitability_payload(
            aggregate.suitability,
        )
        for proj in projected:
            data_trust.append(
                DataTrustItem(
                    check=_resolve_check_text(proj.get("check_key"), lang=lang, tr=tr),
                    state=str(proj.get("state") or "warn"),
                    detail=_resolve_detail_text(proj.get("explanation"), lang=lang, tr=tr),
                ),
            )
    else:
        for summary_item in summary_run_suitability(summary):
            check_text = _resolve_check_text(summary_item.get("check"), lang=lang, tr=tr)
            detail = _resolve_detail_text(summary_item.get("explanation"), lang=lang, tr=tr)
            data_trust.append(
                DataTrustItem(
                    check=check_text,
                    state=str(summary_item.get("state") or "warn"),
                    detail=detail,
                ),
            )
    for warning in summary_warnings(summary):
        if not isinstance(warning, dict):
            continue
        data_trust.append(
            DataTrustItem(
                check=_resolve_detail_text(warning.get("title"), lang=lang, tr=tr) or "",
                state=str(warning.get("severity") or "warn"),
                detail=_resolve_detail_text(warning.get("detail"), lang=lang, tr=tr),
            ),
        )
    return data_trust


def _resolve_check_text(value: object, *, lang: str, tr: Callable[..., str]) -> str:
    """Resolve the checklist label text."""
    if is_i18n_ref(value):
        return resolve_i18n(lang, value, tr=tr)
    if isinstance(value, str) and value.startswith("SUITABILITY_CHECK_"):
        return str(tr(value))
    return str(value or "")


def _resolve_detail_text(value: object, *, lang: str, tr: Callable) -> str | None:
    """Resolve the checklist detail text."""
    if is_i18n_ref(value) or isinstance(value, list):
        resolved = resolve_i18n(lang, value, tr=tr).strip()
    else:
        resolved = str(value or "").strip()
    return resolved or None


# ---------------------------------------------------------------------------
# System, metadata, and strength helpers
# ---------------------------------------------------------------------------


def _sensor_fallback_strength_db(sensor_intensity: list[IntensityRow]) -> float | None:
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


def resolve_interpretation(origin: SuspectedVibrationOrigin, *, lang: str, tr: Callable) -> str:
    """Resolve the origin explanation into localized report text."""
    interpretation_raw = origin.get("explanation", "") if isinstance(origin, dict) else ""
    if is_i18n_ref(interpretation_raw) or isinstance(interpretation_raw, list):
        return resolve_i18n(lang, interpretation_raw, tr=tr)
    return str(interpretation_raw)


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
    summary: Mapping[str, Any],
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
    meta = summary_metadata(summary)
    car_name = str(meta.get("car_name") or "").strip() or None
    car_type = str(meta.get("car_type") or "").strip() or None
    report_date = summary_report_date(summary) or utc_now_iso()
    date_str = str(report_date)[:19].replace("T", " ") + " UTC"

    speed_stats = summary_speed_stats(summary)
    origin = summary_origin(summary)
    sensor_locations_active = summary_sensor_locations_active(summary)

    # Build domain aggregate for domain-first decisions downstream
    if test_run is None:
        from vibesensor.adapters.persistence.boundaries.diagnostic_case import test_run_from_summary

        domain_aggregate = test_run_from_summary(summary)
    else:
        domain_aggregate = test_run

    origin = _origin_from_aggregate(domain_aggregate, origin)

    origin_location = normalized_origin_location(origin)

    return ReportMappingContext(
        meta=meta,
        car_name=car_name,
        car_type=car_type,
        date_str=date_str,
        speed_stats=speed_stats,
        origin=origin,
        origin_location=origin_location,
        sensor_locations_active=sensor_locations_active,
        duration_text=summary_record_length(summary),
        start_time_utc=summary_start_time_utc(summary),
        end_time_utc=summary_end_time_utc(summary),
        sample_rate_hz=summary_sample_rate_hz_text(summary),
        tire_spec_text=tire_spec_text(meta),
        sample_count=summary_row_count(summary),
        sensor_model=summary_sensor_model(summary),
        firmware_version=summary_firmware_version(summary),
        domain_aggregate=domain_aggregate,
    )


def resolve_primary_report_candidate(
    *,
    context: ReportMappingContext,
    sensor_intensity: list[IntensityRow],
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
        tier = certainty_tier(confidence, strength_band_key=strength_band_key)
    else:
        certainty_key = "CONFIDENCE_LOW"
        certainty_label_text = tr("CONFIDENCE_LOW")
        certainty_pct = "0%"
        certainty_reason = ""
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


def build_report_from_summary(summary: dict[str, object]) -> Report:
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
            duration_s = float(duration_s_raw)  # type: ignore[arg-type]
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
    summary: Mapping[str, Any],
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
    report = build_report_from_summary(summary)  # type: ignore[arg-type]

    def tr(key: str, **kw: object) -> str:
        return str(_tr(lang, key, **kw))

    return _build_report_template_data(summary, report=report, lang=lang, tr=tr, test_run=test_run)


def _build_report_template_data(
    summary: Mapping[str, Any],
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
        summary_sensor_intensity_by_location(summary),
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
        findings=[finding_payload_from_domain(f) for f in context.domain_aggregate.findings],
        top_causes=[
            finding_payload_from_domain(f) for f in context.domain_aggregate.effective_top_causes()
        ],
        sensor_intensity_by_location=raw_sensor_intensity,
        location_hotspot_rows=hotspot_rows,
    )
