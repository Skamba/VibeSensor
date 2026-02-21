"""Intermediate data model for the diagnostic PDF report.

Maps the run summary dict to a clean template data structure used by
the Canvas-based PDF renderer.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .. import __version__
from ..report_i18n import normalize_lang
from ..report_i18n import tr as _tr
from ..runlog import as_float_or_none as _as_float
from .pattern_parts import parts_for_pattern, why_parts_listed
from .strength_labels import certainty_label, strength_text

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CarMeta:
    name: str | None = None
    car_type: str | None = None


@dataclass
class ObservedSignature:
    primary_system: str | None = None
    strongest_sensor_location: str | None = None
    speed_band: str | None = None
    strength_label: str | None = None
    certainty_label: str | None = None
    certainty_pct: str | None = None
    certainty_reason: str | None = None


@dataclass
class PartSuggestion:
    name: str
    why_shown: str | None = None


@dataclass
class SystemFindingCard:
    system_name: str
    strongest_location: str | None = None
    pattern_summary: str | None = None
    parts: list[PartSuggestion] = field(default_factory=list)
    tone: str = "neutral"


@dataclass
class NextStep:
    action: str = ""
    why: str | None = None
    rank: int = 999
    speed_band: str | None = None
    confirm: str | None = None
    falsify: str | None = None
    eta: str | None = None


@dataclass
class DataTrustItem:
    check: str
    state: str  # "pass" or "warn"
    detail: str | None = None


@dataclass
class PatternEvidence:
    matched_systems: list[str] = field(default_factory=list)
    strongest_location: str | None = None
    speed_band: str | None = None
    strength_label: str | None = None
    certainty_label: str | None = None
    certainty_pct: str | None = None
    certainty_reason: str | None = None
    warning: str | None = None
    interpretation: str | None = None
    why_parts_text: str | None = None


@dataclass
class PeakRow:
    rank: str
    system: str
    freq_hz: str
    order: str
    amp_g: str
    speed_band: str
    relevance: str


@dataclass
class ReportTemplateData:
    title: str = ""
    run_datetime: str | None = None
    run_id: str | None = None
    duration_text: str | None = None
    start_time_utc: str | None = None
    end_time_utc: str | None = None
    sample_rate_hz: str | None = None
    tire_spec_text: str | None = None
    sample_count: int = 0
    sensor_count: int = 0
    sensor_locations: list[str] = field(default_factory=list)
    sensor_model: str | None = None
    firmware_version: str | None = None
    car: CarMeta = field(default_factory=CarMeta)
    observed: ObservedSignature = field(default_factory=ObservedSignature)
    system_cards: list[SystemFindingCard] = field(default_factory=list)
    next_steps: list[NextStep] = field(default_factory=list)
    data_trust: list[DataTrustItem] = field(default_factory=list)
    pattern_evidence: PatternEvidence = field(default_factory=PatternEvidence)
    peak_rows: list[PeakRow] = field(default_factory=list)
    version_marker: str = ""
    lang: str = "en"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _human_source(source: object, *, tr) -> str:  # type: ignore[type-arg]
    raw = str(source or "").strip().lower()
    mapping = {
        "wheel/tire": tr("SOURCE_WHEEL_TIRE"),
        "driveline": tr("SOURCE_DRIVELINE"),
        "engine": tr("SOURCE_ENGINE"),
        "body resonance": tr("SOURCE_BODY_RESONANCE"),
        "unknown": tr("UNKNOWN"),
    }
    return mapping.get(raw, raw.replace("_", " ").title() if raw else tr("UNKNOWN"))


def _finding_strength_values(finding: dict) -> tuple[float | None, float | None]:
    from math import log10

    amp_metric = finding.get("amplitude_metric")
    peak_amp_g = _as_float(amp_metric.get("value")) if isinstance(amp_metric, dict) else None

    evidence_metrics = finding.get("evidence_metrics")
    db_value = (
        _as_float(evidence_metrics.get("vibration_strength_db"))
        if isinstance(evidence_metrics, dict)
        else None
    )
    if db_value is not None:
        return (db_value, peak_amp_g)

    if isinstance(evidence_metrics, dict):
        noise_floor = _as_float(evidence_metrics.get("mean_noise_floor"))
        if peak_amp_g is not None and noise_floor is not None and noise_floor > 0:
            ratio = (peak_amp_g + 1e-12) / (noise_floor + 1e-12)
            return (20.0 * log10(max(ratio, 1e-12)), peak_amp_g)

    return (None, peak_amp_g)


def _top_strength_values(summary: dict) -> tuple[float | None, float | None]:
    """Return best ``(vibration_strength_db, peak_amp_g)`` for observed strength text."""
    db_value: float | None = None
    peak_amp_g: float | None = None
    for cause in summary.get("top_causes", []):
        if not isinstance(cause, dict):
            continue
        for finding in summary.get("findings", []):
            if not isinstance(finding, dict):
                continue
            if finding.get("finding_id") != cause.get("finding_id"):
                continue
            finding_db, finding_peak = _finding_strength_values(finding)
            if db_value is None and finding_db is not None:
                db_value = finding_db
            if peak_amp_g is None and finding_peak is not None:
                peak_amp_g = finding_peak
            if db_value is not None and peak_amp_g is not None:
                break
        if db_value is not None and peak_amp_g is not None:
            break

    for row in summary.get("sensor_intensity_by_location", []):
        if isinstance(row, dict):
            v = _as_float(row.get("p95_intensity_db"))
            if v is not None:
                db_value = db_value if db_value is not None else v
                break
    return (db_value, peak_amp_g)


def _peak_classification_text(value: object, tr: Callable[..., str] | None = None) -> str:
    normalized = str(value or "").strip().lower()
    if tr is not None:
        if normalized == "patterned":
            return tr("CLASSIFICATION_PATTERNED")
        if normalized == "persistent":
            return tr("CLASSIFICATION_PERSISTENT")
        if normalized == "transient":
            return tr("CLASSIFICATION_TRANSIENT")
        return tr("CLASSIFICATION_PERSISTENT")
    # Fallback without translator (backward compat)
    if normalized == "patterned":
        return "patterned"
    if normalized == "persistent":
        return "persistent"
    if normalized == "transient":
        return "transient impact"
    return "persistent"


# ---------------------------------------------------------------------------
# Summary → template data mapper
# ---------------------------------------------------------------------------


def map_summary(summary: dict) -> ReportTemplateData:
    """Map a run summary dict to the report template data model."""
    lang = normalize_lang(summary.get("lang"))

    def tr(key: str, **kw: object) -> str:
        return _tr(lang, key, **kw)

    # -- Metadata --
    meta = summary.get("metadata", {}) if isinstance(summary.get("metadata"), dict) else {}
    car_name = str(meta.get("car_name") or meta.get("vehicle_name") or "").strip() or None
    car_type = str(meta.get("car_type") or meta.get("vehicle_type") or "").strip() or None

    # -- Date --
    report_date = summary.get("report_date") or datetime.now(UTC).isoformat()
    date_str = str(report_date)[:19].replace("T", " ")

    # -- Top causes and findings --
    top_causes = [c for c in summary.get("top_causes", []) if isinstance(c, dict)]
    findings = [f for f in summary.get("findings", []) if isinstance(f, dict)]
    speed_stats = (
        summary.get("speed_stats", {}) if isinstance(summary.get("speed_stats"), dict) else {}
    )
    origin = summary.get("most_likely_origin", {})
    if not isinstance(origin, dict):
        origin = {}
    origin_location = str(origin.get("location") or "").strip()

    # -- Observed signature --
    if top_causes:
        tc = top_causes[0]
        primary_system = _human_source(tc.get("source") or tc.get("suspected_source"), tr=tr)
        primary_location = origin_location or str(tc.get("strongest_location") or tr("UNKNOWN"))
        primary_speed = str(tc.get("strongest_speed_band") or tr("UNKNOWN"))
        conf = _as_float(tc.get("confidence")) or _as_float(tc.get("confidence_0_to_1")) or 0.0
    else:
        primary_system = tr("UNKNOWN")
        primary_location = origin_location or tr("UNKNOWN")
        primary_speed = tr("UNKNOWN")
        conf = 0.0

    db_val, peak_amp_g = _top_strength_values(summary)
    str_text = strength_text(db_val, lang=lang, peak_amp_g=peak_amp_g)

    steady = bool(speed_stats.get("steady_speed"))
    weak_spatial = bool(top_causes[0].get("weak_spatial_separation") if top_causes else False)
    sensor_count = int(_as_float(summary.get("sensor_count_used")) or 0)
    has_ref_gaps = any(str(f.get("finding_id", "")).startswith("REF_") for f in findings)

    cert_key, cert_label_text, cert_pct, cert_reason = certainty_label(
        conf,
        lang=lang,
        steady_speed=steady,
        weak_spatial=weak_spatial,
        sensor_count=sensor_count,
        has_reference_gaps=has_ref_gaps,
    )

    observed = ObservedSignature(
        primary_system=primary_system,
        strongest_sensor_location=primary_location,
        speed_band=primary_speed,
        strength_label=str_text,
        certainty_label=cert_label_text,
        certainty_pct=cert_pct,
        certainty_reason=cert_reason,
    )

    # -- System cards --
    system_cards: list[SystemFindingCard] = []
    for cause in top_causes[:3]:
        src = cause.get("source") or cause.get("suspected_source") or "unknown"
        src_human = _human_source(src, tr=tr)
        location = str(cause.get("strongest_location") or tr("UNKNOWN"))
        sigs = cause.get("signatures_observed", [])
        pattern_text = ", ".join(str(s) for s in sigs[:3]) if sigs else tr("UNKNOWN")
        order_label = str(sigs[0]) if sigs else None
        parts_list = parts_for_pattern(str(src), order_label, lang=lang)
        c_conf = (
            _as_float(cause.get("confidence")) or _as_float(cause.get("confidence_0_to_1")) or 0.0
        )
        _ck, _cl, _cp, c_reason = certainty_label(c_conf, lang=lang)
        tone = cause.get("confidence_tone", "neutral")

        system_cards.append(
            SystemFindingCard(
                system_name=src_human,
                strongest_location=location,
                pattern_summary=pattern_text,
                parts=[PartSuggestion(name=p, why_shown=c_reason) for p in parts_list],
                tone=tone,
            )
        )

    # -- Next steps --
    test_plan = [s for s in summary.get("test_plan", []) if isinstance(s, dict)]
    next_steps: list[NextStep] = []
    for idx, step in enumerate(test_plan[:5], start=1):
        what = str(step.get("what") or "")
        why = str(step.get("why") or "")
        next_steps.append(
            NextStep(
                action=what,
                why=why or None,
                rank=idx,
                speed_band=str(step.get("speed_band") or "") or None,
                confirm=str(step.get("confirm") or "") or None,
                falsify=str(step.get("falsify") or "") or None,
                eta=str(step.get("eta") or "") or None,
            )
        )

    # -- Data trust --
    data_trust: list[DataTrustItem] = []
    for item in summary.get("run_suitability", []):
        if isinstance(item, dict):
            check_raw = str(item.get("check") or "")
            check_text = tr(check_raw) if check_raw.startswith("SUITABILITY_CHECK_") else check_raw
            detail = str(item.get("explanation") or "").strip() or None
            data_trust.append(
                DataTrustItem(
                    check=check_text,
                    state=str(item.get("state") or "warn"),
                    detail=detail,
                )
            )

    # -- Pattern evidence --
    systems = [
        _human_source(c.get("source") or c.get("suspected_source"), tr=tr) for c in top_causes[:3]
    ]
    pe_loc = (
        str(top_causes[0].get("strongest_location") or tr("UNKNOWN"))
        if top_causes
        else tr("UNKNOWN")
    )
    pe_speed = (
        str(top_causes[0].get("strongest_speed_band") or tr("UNKNOWN"))
        if top_causes
        else tr("UNKNOWN")
    )
    interp = str(origin.get("explanation", "")) if isinstance(origin, dict) else ""
    src_why = str(
        (top_causes[0].get("source") or top_causes[0].get("suspected_source")) if top_causes else ""
    )
    sigs_why = top_causes[0].get("signatures_observed", []) if top_causes else []
    order_lbl_why = str(sigs_why[0]) if sigs_why else None
    why_text = why_parts_listed(src_why, order_lbl_why, lang=lang)

    warning_text = cert_reason if weak_spatial else None

    pattern_evidence = PatternEvidence(
        matched_systems=systems,
        strongest_location=pe_loc,
        speed_band=pe_speed,
        strength_label=str_text,
        certainty_label=cert_label_text,
        certainty_pct=cert_pct,
        certainty_reason=cert_reason,
        warning=warning_text,
        interpretation=interp or None,
        why_parts_text=why_text,
    )

    # -- Peak rows --
    plots = summary.get("plots", {}) if isinstance(summary.get("plots"), dict) else {}
    peak_rows: list[PeakRow] = []
    for row in (plots.get("peaks_table", []) or [])[:8]:
        if not isinstance(row, dict):
            continue
        rank = str(int(_as_float(row.get("rank")) or 0))
        freq = f"{(_as_float(row.get('frequency_hz')) or 0.0):.1f}"
        classification = _peak_classification_text(row.get("peak_classification"), tr=tr)
        order_label = str(row.get("order_label") or "").strip()
        order = order_label or classification
        amp = f"{(_as_float(row.get('p95_amp_g')) or 0.0):.4f}"
        speed = str(row.get("typical_speed_band") or "\u2014")
        presence = float(_as_float(row.get("presence_ratio")) or 0.0)
        score = float(_as_float(row.get("persistence_score")) or 0.0)

        order_lower = order.lower()
        if "wheel" in order_lower:
            system = tr("SOURCE_WHEEL_TIRE")
        elif "engine" in order_lower:
            system = tr("SOURCE_ENGINE")
        elif "driveshaft" in order_lower or "drive" in order_lower:
            system = tr("SOURCE_DRIVELINE")
        elif "transient" in order_lower:
            system = tr("SOURCE_TRANSIENT_IMPACT")
        else:
            system = "\u2014"
        relevance = f"{classification} \u00b7 {presence:.0%} {tr('PRESENCE')} \u00b7 {tr('SCORE')} {score:.2f}"

        peak_rows.append(
            PeakRow(
                rank=rank,
                system=system,
                freq_hz=freq,
                order=order,
                amp_g=amp,
                speed_band=speed,
                relevance=relevance,
            )
        )

    # -- Version marker --
    git_sha = str(os.getenv("GIT_SHA", "")).strip()
    version_marker = f"v{__version__} ({git_sha[:8]})" if git_sha else f"v{__version__}"

    # -- Metadata enrichment --
    duration_text = str(summary.get("record_length") or "") or None
    start_time_utc = str(summary.get("start_time_utc") or "").strip() or None
    end_time_utc = str(summary.get("end_time_utc") or "").strip() or None
    raw_sample_rate_hz = _as_float(summary.get("raw_sample_rate_hz"))
    sample_rate_hz = f"{raw_sample_rate_hz:g}" if raw_sample_rate_hz is not None else None

    tire_width_mm = _as_float(meta.get("tire_width_mm"))
    tire_aspect_pct = _as_float(meta.get("tire_aspect_pct"))
    rim_in = _as_float(meta.get("rim_in"))
    tire_spec_text: str | None = None
    if (
        tire_width_mm is not None
        and tire_aspect_pct is not None
        and rim_in is not None
        and tire_width_mm > 0
        and tire_aspect_pct > 0
        and rim_in > 0
    ):
        tire_spec_text = f"{tire_width_mm:g}/{tire_aspect_pct:g}R{rim_in:g}"

    sample_count = int(_as_float(summary.get("rows")) or 0)
    sensor_locations_list = summary.get("sensor_locations", [])
    if not isinstance(sensor_locations_list, list):
        sensor_locations_list = []
    sensor_count_used = int(_as_float(summary.get("sensor_count_used")) or 0)
    sensor_model_val = str(summary.get("sensor_model") or "").strip() or None
    firmware_version_val = str(summary.get("firmware_version") or "").strip() or None

    return ReportTemplateData(
        title=tr("DIAGNOSTIC_WORKSHEET"),
        run_datetime=date_str,
        run_id=summary.get("run_id"),
        duration_text=duration_text,
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
        sample_rate_hz=sample_rate_hz,
        tire_spec_text=tire_spec_text,
        sample_count=sample_count,
        sensor_count=sensor_count_used,
        sensor_locations=[str(loc) for loc in sensor_locations_list],
        sensor_model=sensor_model_val,
        firmware_version=firmware_version_val,
        car=CarMeta(name=car_name, car_type=car_type),
        observed=observed,
        system_cards=system_cards,
        next_steps=next_steps,
        data_trust=data_trust,
        pattern_evidence=pattern_evidence,
        peak_rows=peak_rows,
        version_marker=version_marker,
        lang=lang,
    )
