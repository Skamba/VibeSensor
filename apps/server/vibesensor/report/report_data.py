"""Intermediate data model for the diagnostic PDF report.

Maps the run summary dict to a clean template data structure used by
the Canvas-based PDF renderer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .. import __version__
from ..report_i18n import normalize_lang, tr as _tr
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


@dataclass
class DataTrustItem:
    check: str
    state: str  # "pass" or "warn"


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


def _top_strength_db(summary: dict) -> float | None:
    """Best vibration_strength_db from top cause or sensor intensity."""
    for cause in summary.get("top_causes", []):
        if not isinstance(cause, dict):
            continue
        for f in summary.get("findings", []):
            if not isinstance(f, dict):
                continue
            if f.get("finding_id") == cause.get("finding_id"):
                amp = f.get("amplitude_metric")
                if isinstance(amp, dict):
                    v = _as_float(amp.get("value"))
                    if v is not None:
                        return v
    for row in summary.get("sensor_intensity_by_location", []):
        if isinstance(row, dict):
            v = _as_float(row.get("p95_intensity_db"))
            if v is not None:
                return v
    return None


def _peak_classification_text(value: object) -> str:
    normalized = str(value or "").strip().lower()
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

    # -- Observed signature --
    if top_causes:
        tc = top_causes[0]
        primary_system = _human_source(tc.get("source") or tc.get("suspected_source"), tr=tr)
        primary_location = str(tc.get("strongest_location") or tr("UNKNOWN"))
        primary_speed = str(tc.get("strongest_speed_band") or tr("UNKNOWN"))
        conf = _as_float(tc.get("confidence")) or _as_float(tc.get("confidence_0_to_1")) or 0.0
    else:
        primary_system = tr("UNKNOWN")
        primary_location = tr("UNKNOWN")
        primary_speed = tr("UNKNOWN")
        conf = 0.0

    db_val = _top_strength_db(summary)
    str_text = strength_text(db_val, lang=lang)

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
        next_steps.append(NextStep(action=what, why=why or None, rank=idx))

    # -- Data trust --
    data_trust: list[DataTrustItem] = []
    for item in summary.get("run_suitability", []):
        if isinstance(item, dict):
            data_trust.append(
                DataTrustItem(
                    check=str(item.get("check") or ""),
                    state=str(item.get("state") or "warn"),
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
    origin = summary.get("most_likely_origin", {})
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
        classification = _peak_classification_text(row.get("peak_classification"))
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
            system = "Transient impact"
        else:
            system = "\u2014"
        relevance = f"{classification} \u00b7 {presence:.0%} presence \u00b7 score {score:.2f}"

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

    return ReportTemplateData(
        title=tr("DIAGNOSTIC_WORKSHEET"),
        run_datetime=date_str,
        run_id=summary.get("run_id"),
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
