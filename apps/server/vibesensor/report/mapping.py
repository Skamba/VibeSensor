"""report_mapping – maps analysis summaries to report-ready data structures."""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from statistics import mean as _mean

from .. import __version__
from ..analysis._types import (
    CandidateFinding,
    Finding,
    IntensityRow,
    JsonValue,
    MetadataDict,
    OriginSummary,
    RunSuitabilityCheck,
    SpeedStats,
    SummaryData,
    TestStep,
    TopCause,
)
from ..analysis.diagnosis_candidates import normalize_origin_location, select_effective_top_causes
from ..analysis.helpers import PHASE_I18N_KEYS
from ..analysis.pattern_parts import parts_for_pattern, why_parts_listed
from ..analysis.plots import PeakTableRow
from ..analysis.strength_labels import (
    certainty_label,
    certainty_tier,
    strength_label,
    strength_text,
)
from ..domain_models import as_float_or_none as _as_float
from ..report_i18n import normalize_lang
from ..report_i18n import tr as _tr
from ..runlog import utc_now_iso
from .report_data import (
    CarMeta,
    DataTrustItem,
    NextStep,
    ObservedSignature,
    PartSuggestion,
    PatternEvidence,
    PeakRow,
    ReportTemplateData,
    SystemFindingCard,
)

__all__ = ["map_summary"]


# ---------------------------------------------------------------------------
# Intermediate models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportMappingContext:
    """Normalized structural context pulled from an analysis summary.

    Owns display-ready metadata access, primary hotspot / candidate
    selection helpers, and report-mapping decisions that were previously
    spread across helper functions and ``dict.get(...)`` calls.
    """

    meta: MetadataDict
    car_name: str | None
    car_type: str | None
    date_str: str
    top_causes: list[CandidateFinding]
    findings_non_ref: list[Finding]
    findings: list[Finding]
    speed_stats: SpeedStats
    origin: OriginSummary
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

    # -- candidate selection ------------------------------------------------

    def top_report_candidate(self) -> CandidateFinding | None:
        """Return the primary report candidate (first effective top cause or finding)."""
        candidates = self.top_causes or self.findings_non_ref
        return candidates[0] if candidates else None

    def primary_hotspot(self) -> CandidateFinding | None:
        """Return the top cause as the primary hotspot for the report."""
        return self.top_causes[0] if self.top_causes else None

    # -- display helpers ----------------------------------------------------

    def display_duration(self) -> str | None:
        """Return the formatted run duration text."""
        return self.duration_text

    def display_speed_range(self) -> str | None:
        """Return the formatted speed range from speed stats."""
        min_kmh = self.speed_stats.get("min_kmh")
        max_kmh = self.speed_stats.get("max_kmh")
        if min_kmh is not None and max_kmh is not None:
            return f"{min_kmh:.0f}\u2013{max_kmh:.0f} km/h"
        return None

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

    def observed_signature(self, primary: PrimaryCandidateContext) -> ObservedSignature:
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


@dataclass(frozen=True)
class PrimaryCandidateContext:
    """Primary report candidate resolved from top causes or findings."""

    primary_candidate: CandidateFinding | None
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
    mapping = {
        "wheel/tire": tr("SOURCE_WHEEL_TIRE"),
        "driveline": tr("SOURCE_DRIVELINE"),
        "engine": tr("SOURCE_ENGINE"),
        "body resonance": tr("SOURCE_BODY_RESONANCE"),
        "transient_impact": tr("SOURCE_TRANSIENT_IMPACT"),
        "baseline_noise": tr("SOURCE_BASELINE_NOISE"),
        "unknown_resonance": tr("SOURCE_UNKNOWN_RESONANCE"),
        "unknown": tr("UNKNOWN"),
    }
    return mapping.get(raw, raw.replace("_", " ").title() if raw else tr("UNKNOWN"))


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


def extract_confidence(item: Finding | TopCause) -> float:
    """Return the confidence value from a cause/finding dict."""
    value = _as_float(item.get("confidence"))
    return value if value is not None else 0.0


def finding_strength_db(finding: Finding) -> float | None:
    """Extract a finding's vibration-strength dB value if present."""
    evidence_metrics = finding.get("evidence_metrics")
    return (
        _as_float(evidence_metrics.get("vibration_strength_db"))
        if isinstance(evidence_metrics, dict)
        else None
    )


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

_EMPTY_ORIGIN: OriginSummary = {
    "location": "unknown",
    "alternative_locations": [],
    "source": "unknown",
    "dominance_ratio": None,
    "weak_spatial_separation": True,
}


class SummaryView:
    """Typed accessor over a ``SummaryData`` dict for report mapping.

    Replaces scattered ``summary.get(...)`` chains with typed properties
    that centralise default handling and type coercion.  The underlying
    dict is **not** copied – mutations through the view are visible in
    the original dict and vice-versa.
    """

    __slots__ = ("_d",)

    def __init__(self, summary: SummaryData) -> None:
        self._d = summary

    @property
    def data(self) -> SummaryData:
        return self._d

    # -- metadata ----------------------------------------------------------

    @property
    def metadata(self) -> MetadataDict:
        return self._d.get("metadata") or {}

    @property
    def report_date(self) -> str:
        return str(self._d.get("report_date") or "")

    @property
    def row_count(self) -> int:
        return int(_as_float(self._d.get("rows")) or 0)

    @property
    def record_length(self) -> str | None:
        return str(self._d.get("record_length") or "") or None

    @property
    def start_time_utc(self) -> str | None:
        return str(self._d.get("start_time_utc") or "").strip() or None

    @property
    def end_time_utc(self) -> str | None:
        return str(self._d.get("end_time_utc") or "").strip() or None

    @property
    def raw_sample_rate_hz(self) -> float | None:
        return _as_float(self._d.get("raw_sample_rate_hz"))

    @property
    def sensor_model(self) -> str | None:
        return str(self._d.get("sensor_model") or "").strip() or None

    @property
    def firmware_version(self) -> str | None:
        return str(self._d.get("firmware_version") or "").strip() or None

    @property
    def sensor_count_used(self) -> int:
        return int(_as_float(self._d.get("sensor_count_used")) or 0)

    # -- collections -------------------------------------------------------

    @property
    def findings(self) -> list[Finding]:
        raw = self._d.get("findings", [])
        return list(raw) if isinstance(raw, list) else []

    @property
    def top_causes(self) -> list[TopCause]:
        raw = self._d.get("top_causes", [])
        return list(raw) if isinstance(raw, list) else []

    @property
    def speed_stats(self) -> SpeedStats:
        return self._d.get("speed_stats") or _EMPTY_SPEED_STATS

    @property
    def origin(self) -> OriginSummary:
        return self._d.get("most_likely_origin") or _EMPTY_ORIGIN

    @property
    def test_plan(self) -> list[TestStep]:
        return [step for step in self._d.get("test_plan", []) if isinstance(step, dict)]

    @property
    def run_suitability(self) -> list[RunSuitabilityCheck]:
        return [item for item in self._d.get("run_suitability", []) if isinstance(item, dict)]

    @property
    def warnings(self) -> list[object]:
        return list(self._d.get("warnings", []))

    @property
    def sensor_intensity_by_location(self) -> list[IntensityRow]:
        return [
            row for row in self._d.get("sensor_intensity_by_location", [])
            if isinstance(row, dict)
        ]

    # -- sensor locations --------------------------------------------------

    @property
    def sensor_locations_active(self) -> list[str]:
        """Return active sensor locations (connected-throughout, fallback to all)."""
        connected = self._d.get("sensor_locations_connected_throughout", [])
        active = [str(loc) for loc in connected if str(loc).strip()]
        if not active:
            active = [str(loc) for loc in self._d.get("sensor_locations", []) if str(loc).strip()]
        return active

    # -- display helpers ---------------------------------------------------

    @property
    def sample_rate_hz_text(self) -> str | None:
        rate = self.raw_sample_rate_hz
        return f"{rate:g}" if rate is not None else None


def extract_sensor_locations(summary: SummaryData) -> list[str]:
    """Return active sensor locations for report rendering."""
    return SummaryView(summary).sensor_locations_active


def normalized_origin_location(origin: OriginSummary) -> str:
    """Return the report-ready origin location string."""
    return normalize_origin_location(origin.get("location"))


def resolve_sensor_count(summary: SummaryData, sensor_locations_active: list[str]) -> int:
    """Resolve the effective sensor count used by report certainty logic."""
    sensor_count = len(sensor_locations_active)
    if sensor_count <= 0:
        sensor_count = SummaryView(summary).sensor_count_used
    return sensor_count


# ---------------------------------------------------------------------------
# Peak-row and location-hotspot shaping
# ---------------------------------------------------------------------------


def build_peak_rows_from_plots(
    summary: SummaryData,
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
    return [build_peak_row(row, lang=lang, tr=tr) for row in above_noise[:8]]


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
    source_hint = str(row.get("source") or row.get("suspected_source") or "").strip().lower()
    if source_hint == "wheel/tire" or "wheel" in order_lower:
        return str(tr("SOURCE_WHEEL_TIRE"))
    if source_hint == "engine" or "engine" in order_lower:
        return str(tr("SOURCE_ENGINE"))
    if source_hint == "driveline" or "driveshaft" in order_lower or "drive" in order_lower:
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
    summary: SummaryData,
    *,
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
    view = SummaryView(summary)
    for step in view.test_plan:
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
    summary: SummaryData,
    *,
    lang: str,
    tr: Callable,
) -> list[DataTrustItem]:
    """Build the data-trust checklist from run_suitability items."""
    view = SummaryView(summary)
    data_trust: list[DataTrustItem] = []
    for item in view.run_suitability:
        check_text = _resolve_check_text(item.get("check"), lang=lang, tr=tr)
        detail = _resolve_detail_text(item.get("explanation"), lang=lang, tr=tr)
        data_trust.append(
            DataTrustItem(
                check=check_text,
                state=str(item.get("state") or "warn"),
                detail=detail,
            ),
        )
    for warning in view.warnings:
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


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def prepare_report_mapping_context(
    summary: SummaryData,
) -> ReportMappingContext:
    """Extract structural summary context for report mapping.

    Uses :class:`SummaryView` for typed access to summary dict fields,
    eliminating scattered ``.get()`` chains and type coercion.
    """
    view = SummaryView(summary)
    meta = view.metadata
    car_name = str(meta.get("car_name") or "").strip() or None
    car_type = str(meta.get("car_type") or "").strip() or None
    report_date = view.report_date or utc_now_iso()
    date_str = str(report_date)[:19].replace("T", " ") + " UTC"

    findings, findings_non_ref, _top_causes_all, top_causes = select_effective_top_causes(
        view.top_causes,
        view.findings,
    )

    speed_stats = view.speed_stats
    origin = view.origin
    origin_location = normalized_origin_location(origin)
    sensor_locations_active = view.sensor_locations_active

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
        duration_text=view.record_length,
        start_time_utc=view.start_time_utc,
        end_time_utc=view.end_time_utc,
        sample_rate_hz=view.sample_rate_hz_text,
        tire_spec_text=tire_spec_text(meta),
        sample_count=view.row_count,
        sensor_model=view.sensor_model,
        firmware_version=view.firmware_version,
    )


def resolve_primary_report_candidate(
    summary: SummaryData,
    *,
    context: ReportMappingContext,
    tr: Callable[..., str],
    lang: str,
) -> PrimaryCandidateContext:
    """Resolve the primary candidate and all derived certainty fields."""
    primary_candidate = context.top_report_candidate()
    if primary_candidate:
        primary_source = primary_candidate.get("source") or primary_candidate.get(
            "suspected_source"
        )
        primary_system = human_source(primary_source, tr=tr)
        primary_location = context.origin_location or str(
            primary_candidate.get("strongest_location") or tr("UNKNOWN"),
        )
        primary_speed = str(
            primary_candidate.get("strongest_speed_band")
            or primary_candidate.get("speed_band")
            or tr("UNKNOWN"),
        )
        confidence = extract_confidence(primary_candidate)
    else:
        primary_source = None
        primary_system = tr("UNKNOWN")
        primary_location = context.origin_location or tr("UNKNOWN")
        primary_speed = tr("UNKNOWN")
        confidence = 0.0

    strength_db = top_strength_values(summary, effective_causes=context.top_causes)
    strength_text_value = strength_text(strength_db, lang=lang)
    weak_spatial = bool(
        primary_candidate.get("weak_spatial_separation") if primary_candidate else False,
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
    view = SummaryView(summary)
    context = prepare_report_mapping_context(summary)
    primary = resolve_primary_report_candidate(summary, context=context, tr=tr, lang=lang)
    observed = context.observed_signature(primary)
    system_cards = build_system_cards(
        context,
        primary,
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
        context,
        primary,
        lang,
        tr,
    )
    peak_rows = build_peak_rows_from_plots(summary, lang=lang, tr=tr)
    version_marker = build_version_marker()

    raw_sensor_intensity = filter_active_sensor_intensity(
        view.sensor_intensity_by_location,
        context.sensor_locations_active,
    )
    hotspot_rows = compute_location_hotspot_rows(raw_sensor_intensity)

    return ReportTemplateData(
        title=tr("DIAGNOSTIC_WORKSHEET"),
        run_datetime=context.date_str,
        run_id=summary.get("run_id"),
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
        findings=context.findings,  # type: ignore[arg-type]
        top_causes=context.top_causes,  # type: ignore[arg-type]
        sensor_intensity_by_location=raw_sensor_intensity,
        location_hotspot_rows=hotspot_rows,
    )
