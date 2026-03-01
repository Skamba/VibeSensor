"""Builder that converts an analysis summary dict into ReportTemplateData.

This module lives in ``vibesensor.analysis`` because it calls analysis
functions (certainty tiers, strength labels, pattern-parts mapping).
The sibling ``vibesensor.report`` package is renderer-only and imports
only the finished :class:`ReportTemplateData` dataclass.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from statistics import mean as _mean

from vibesensor_core.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from .. import __version__
from ..report.report_data import (
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
from ..report_i18n import normalize_lang
from ..report_i18n import tr as _tr
from ..runlog import as_float_or_none as _as_float
from .pattern_parts import parts_for_pattern, why_parts_listed
from .strength_labels import certainty_label, certainty_tier, strength_label, strength_text

# ---------------------------------------------------------------------------
# i18n resolution helpers
# ---------------------------------------------------------------------------


def _is_i18n_ref(value: object) -> bool:
    """Check whether *value* is a language-neutral i18n reference dict."""
    return isinstance(value, dict) and "_i18n_key" in value


def _resolve_i18n(lang: str, value: object) -> str:
    """Resolve a value that may be an i18n reference dict, a list of refs, or a plain string.

    - If *value* is a dict with ``_i18n_key``, translate using ``tr(lang, key, **params)``.
    - If *value* is a list of i18n refs, resolve each and join with spaces.
    - Otherwise return ``str(value)``.
    """
    if isinstance(value, list):
        return " ".join(_resolve_i18n(lang, item) for item in value if item)
    if not isinstance(value, dict) or "_i18n_key" not in value:
        return str(value) if value is not None else ""
    key = str(value["_i18n_key"])
    suffix = str(value.get("_suffix", ""))
    params = {k: v for k, v in value.items() if k not in ("_i18n_key", "_suffix")}
    # Recursively resolve any nested i18n refs in params
    resolved_params: dict[str, object] = {}
    for pk, pv in params.items():
        if _is_i18n_ref(pv):
            resolved_params[pk] = _resolve_i18n(lang, pv)
        elif pk == "source" and isinstance(pv, str):
            # Translate known source codes to human-readable form
            resolved_params[pk] = _human_source(pv, tr=lambda k, **kw: _tr(lang, k, **kw))
        elif pk == "phase" and isinstance(pv, str):
            # Translate phase codes to human-readable form
            _phase_map = {
                "acceleration": "DRIVING_PHASE_ACCELERATION",
                "deceleration": "DRIVING_PHASE_DECELERATION",
                "coast_down": "DRIVING_PHASE_COAST_DOWN",
            }
            i18n_key = _phase_map.get(pv)
            resolved_params[pk] = _tr(lang, i18n_key) if i18n_key else pv
        else:
            resolved_params[pk] = pv
    result = _tr(lang, key, **resolved_params)
    return result + suffix if suffix else result


def _order_label_human(lang: str, label: str) -> str:
    """Translate a language-neutral order label like ``'1x wheel'`` to localized form."""
    if lang == "nl":
        names = {"wheel": "wielorde", "engine": "motororde", "driveshaft": "aandrijfasorde"}
    else:
        names = {"wheel": "wheel order", "engine": "engine order", "driveshaft": "driveshaft order"}
    # Parse "Nx base" format
    parts = label.split(" ", 1)
    if len(parts) == 2:
        multiplier, base = parts
        localized = names.get(base.lower(), base)
        return f"{multiplier} {localized}"
    return label


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _human_source(source: object, *, tr: Callable[[str], str]) -> str:
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


def _finding_strength_values(finding: dict) -> float | None:
    amp_metric = finding.get("amplitude_metric")
    peak_amp = _as_float(amp_metric.get("value")) if isinstance(amp_metric, dict) else None

    evidence_metrics = finding.get("evidence_metrics")
    db_value = (
        _as_float(evidence_metrics.get("vibration_strength_db"))
        if isinstance(evidence_metrics, dict)
        else None
    )
    if db_value is not None:
        return db_value

    if isinstance(evidence_metrics, dict):
        noise_floor = _as_float(evidence_metrics.get("mean_noise_floor"))
        if peak_amp is not None and noise_floor is not None and noise_floor > 0:
            return canonical_vibration_db(
                peak_band_rms_amp_g=peak_amp,
                floor_amp_g=noise_floor,
            )

    return None


def _top_strength_values(
    summary: dict,
    *,
    effective_causes: list[dict] | None = None,
) -> float | None:
    """Return best vibration strength in dB for observed strength text.

    When *effective_causes* is provided the strength values are drawn from those
    causes (matching by ``finding_id`` against the summary's findings list).
    This ensures the displayed strength traces to the same finding that is shown
    as the primary system rather than a potentially-filtered raw top_cause.
    """
    causes = effective_causes if effective_causes is not None else summary.get("top_causes", [])
    for cause in causes:
        if not isinstance(cause, dict):
            continue
        for finding in summary.get("findings", []):
            if not isinstance(finding, dict):
                continue
            if finding.get("finding_id") != cause.get("finding_id"):
                continue
            finding_db = _finding_strength_values(finding)
            if finding_db is not None:
                return finding_db

    sensor_rows = [
        _as_float(row.get("p95_intensity_db"))
        for row in summary.get("sensor_intensity_by_location", [])
        if isinstance(row, dict)
    ]
    sensor_db = max((value for value in sensor_rows if value is not None), default=None)
    return sensor_db


def _dominant_phase(phase_info: dict | None) -> str | None:
    """Return the dominant non-idle driving phase from a phase_info summary dict."""
    if not isinstance(phase_info, dict):
        return None
    counts = phase_info.get("phase_counts")
    if not isinstance(counts, dict) or not counts:
        return None
    # Prefer the non-idle phase with the highest sample count.
    _IDLE_KEY = "idle"
    best_phase: str | None = None
    best_count = 0
    for phase_key, count in counts.items():
        if phase_key == _IDLE_KEY:
            continue
        if isinstance(count, (int, float)) and count > best_count:
            best_count = int(count)
            best_phase = phase_key
    return best_phase


def _peak_classification_text(value: object, tr: Callable[..., str]) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "patterned":
        return tr("CLASSIFICATION_PATTERNED")
    if normalized == "persistent":
        return tr("CLASSIFICATION_PERSISTENT")
    if normalized == "transient":
        return tr("CLASSIFICATION_TRANSIENT")
    if normalized == "baseline_noise":
        return tr("CLASSIFICATION_BASELINE_NOISE")
    if not normalized:
        return tr("UNKNOWN")
    return str(value).replace("_", " ").title()


def _has_relevant_reference_gap(findings: list[dict], primary_source: object) -> bool:
    src = str(primary_source or "").strip().lower()
    for finding in findings:
        fid = str(finding.get("finding_id") or "").strip().upper()
        if fid in {"REF_SPEED", "REF_SAMPLE_RATE"}:
            return True
        if fid == "REF_WHEEL" and src in {"wheel/tire", "driveline"}:
            return True
        if fid == "REF_ENGINE" and src == "engine":
            return True
    return False


def _compute_location_hotspot_rows(
    findings: list[dict],
    sensor_intensity: list[dict],
) -> list[dict]:
    """Pre-compute location hotspot rows from findings matched_points.

    Falls back to sensor_intensity_by_location when no matched_points
    are available.  Never reads raw time-series samples.
    """
    amp_by_location: dict[str, list[float]] = defaultdict(list)

    if sensor_intensity:
        for row in sensor_intensity:
            if not isinstance(row, dict):
                continue
            location = str(row.get("location") or "").strip()
            p95_val = _as_float(row.get("p95_intensity_db"))
            p95 = p95_val if p95_val is not None else _as_float(row.get("mean_intensity_db"))
            if location and p95 is not None and p95 > 0:
                amp_by_location[location].append(p95)
        amp_unit = "db"
    else:
        return []

    hotspot_rows: list[dict] = []
    for location, amps in amp_by_location.items():
        peak_val = max(amps)
        mean_val = _mean(amps)
        row: dict = {
            "location": location,
            "count": len(amps),
            "unit": amp_unit,
            "peak_value": peak_val,
            "mean_value": mean_val,
        }
        row["peak_db"] = peak_val
        row["mean_db"] = mean_val
        hotspot_rows.append(row)
    hotspot_rows.sort(
        key=lambda r: (float(r["peak_value"]), float(r["mean_value"])),
        reverse=True,
    )
    return hotspot_rows


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
    car_name = str(meta.get("car_name") or "").strip() or None
    car_type = str(meta.get("car_type") or "").strip() or None

    # -- Date --
    report_date = summary.get("report_date") or datetime.now(UTC).isoformat()
    date_str = str(report_date)[:19].replace("T", " ") + " UTC"

    # -- Top causes and findings --
    findings = [f for f in summary.get("findings", []) if isinstance(f, dict)]
    findings_non_ref = [
        f for f in findings if not str(f.get("finding_id") or "").strip().upper().startswith("REF_")
    ]
    top_causes_all = [c for c in summary.get("top_causes", []) if isinstance(c, dict)]
    top_causes_non_ref = [
        c
        for c in top_causes_all
        if not str(c.get("finding_id") or "").strip().upper().startswith("REF_")
    ]
    top_causes_actionable = [
        c
        for c in top_causes_non_ref
        if str(c.get("source") or c.get("suspected_source") or "").strip().lower()
        not in {"unknown_resonance", "unknown"}
        or str(c.get("strongest_location") or "").strip().lower()
        not in {"", "unknown", "not available", "n/a"}
    ]
    top_causes = top_causes_actionable or findings_non_ref or top_causes_non_ref or top_causes_all
    speed_stats = (
        summary.get("speed_stats", {}) if isinstance(summary.get("speed_stats"), dict) else {}
    )
    origin = summary.get("most_likely_origin", {})
    if not isinstance(origin, dict):
        origin = {}
    origin_location = str(origin.get("location") or "").strip()
    # The analysis layer stores "unknown" as a language-neutral placeholder.
    # Clear it so the report builder falls through to tr("UNKNOWN") which
    # produces the properly localised label (e.g. "Onbekend" in NL).
    if origin_location.lower() == "unknown":
        origin_location = ""

    sensor_locations_all = summary.get("sensor_locations", [])
    if not isinstance(sensor_locations_all, list):
        sensor_locations_all = []
    connected_locations = summary.get("sensor_locations_connected_throughout", [])
    if not isinstance(connected_locations, list):
        connected_locations = []
    sensor_locations_active = [str(loc) for loc in connected_locations if str(loc).strip()]
    if not sensor_locations_active:
        sensor_locations_active = [str(loc) for loc in sensor_locations_all if str(loc).strip()]

    # -- Phase info --
    raw_phase_info = summary.get("phase_info")
    phase_info = dict(raw_phase_info) if isinstance(raw_phase_info, dict) else None
    dom_phase = _dominant_phase(phase_info)

    # -- Observed signature --
    primary_candidates = top_causes or findings_non_ref
    primary_candidate = primary_candidates[0] if primary_candidates else None
    if primary_candidate:
        primary_source = primary_candidate.get("source") or primary_candidate.get(
            "suspected_source"
        )
        primary_system = _human_source(primary_source, tr=tr)
        primary_location = origin_location or str(
            primary_candidate.get("strongest_location") or tr("UNKNOWN")
        )
        primary_speed = str(
            primary_candidate.get("strongest_speed_band")
            or primary_candidate.get("speed_band")
            or primary_candidate.get("dominant_speed_band")
            or tr("UNKNOWN")
        )
        _conf_val = _as_float(primary_candidate.get("confidence"))
        if _conf_val is None:
            _conf_val = _as_float(primary_candidate.get("confidence_0_to_1"))
        conf = _conf_val if _conf_val is not None else 0.0
    else:
        primary_source = None
        primary_system = tr("UNKNOWN")
        primary_location = origin_location or tr("UNKNOWN")
        primary_speed = tr("UNKNOWN")
        conf = 0.0

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
    cert_key, cert_label_text, cert_pct, cert_reason = certainty_label(
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
        phase=dom_phase,
        strength_label=str_text,
        strength_peak_db=db_val,
        certainty_label=cert_label_text,
        certainty_pct=cert_pct,
        certainty_reason=cert_reason,
    )

    # -- System cards --
    system_cards: list[SystemFindingCard] = []
    if tier == "A":
        # Tier A: suppress specific system findings entirely.
        pass
    else:
        card_sources = top_causes or findings_non_ref or findings
        for cause in card_sources[:2]:
            src = cause.get("source") or cause.get("suspected_source") or "unknown"
            src_human = _human_source(src, tr=tr)
            location = str(cause.get("strongest_location") or tr("UNKNOWN"))
            sigs = cause.get("signatures_observed", [])
            # Translate language-neutral order labels (e.g. "1x wheel" → "1x wheel order")
            sigs_human = [_order_label_human(lang, str(s)) for s in sigs[:3]] if sigs else []
            pattern_text = ", ".join(sigs_human) if sigs_human else tr("UNKNOWN")
            order_label = sigs_human[0] if sigs_human else None
            parts_list = parts_for_pattern(str(src), order_label, lang=lang)
            _c_conf_val = _as_float(cause.get("confidence"))
            if _c_conf_val is None:
                _c_conf_val = _as_float(cause.get("confidence_0_to_1"))
            c_conf = _c_conf_val if _c_conf_val is not None else 0.0
            _ck, _cl, _cp, c_reason = certainty_label(c_conf, lang=lang)
            tone = cause.get("confidence_tone", "neutral")

            card_system_name = src_human
            card_parts = [PartSuggestion(name=p, why_shown=c_reason) for p in parts_list]
            if tier == "B":
                # Tier B: label as hypothesis, suppress repair-oriented parts.
                card_system_name = f"{src_human} — {tr('TIER_B_HYPOTHESIS_LABEL')}"
                card_parts = []

            system_cards.append(
                SystemFindingCard(
                    system_name=card_system_name,
                    strongest_location=location,
                    pattern_summary=pattern_text,
                    parts=card_parts,
                    tone=tone,
                )
            )

    # -- Next steps --
    next_steps: list[NextStep] = []
    if tier == "A":
        # Tier A: replace repair steps with data-collection guidance.
        _guidance = [
            (tr("TIER_A_CAPTURE_WIDER_SPEED"), cert_reason),
            (tr("TIER_A_CAPTURE_MORE_SENSORS"), cert_reason),
            (tr("TIER_A_CAPTURE_REFERENCE_DATA"), cert_reason),
        ]
        for idx, (action, why) in enumerate(_guidance, start=1):
            next_steps.append(NextStep(action=action, why=why, rank=idx))
    else:
        test_plan = [s for s in summary.get("test_plan", []) if isinstance(s, dict)]
        for idx, step in enumerate(test_plan, start=1):
            what_raw = step.get("what") or ""
            why_raw = step.get("why") or ""
            what = _resolve_i18n(lang, what_raw) if _is_i18n_ref(what_raw) else str(what_raw)
            why = _resolve_i18n(lang, why_raw) if _is_i18n_ref(why_raw) else str(why_raw)
            confirm_raw = step.get("confirm") or ""
            falsify_raw = step.get("falsify") or ""
            confirm = (
                _resolve_i18n(lang, confirm_raw) if _is_i18n_ref(confirm_raw) else str(confirm_raw)
            )
            falsify = (
                _resolve_i18n(lang, falsify_raw) if _is_i18n_ref(falsify_raw) else str(falsify_raw)
            )
            next_steps.append(
                NextStep(
                    action=what,
                    why=why or None,
                    rank=idx,
                    speed_band=str(step.get("speed_band") or "") or None,
                    confirm=confirm or None,
                    falsify=falsify or None,
                    eta=str(step.get("eta") or "") or None,
                )
            )

    # -- Data trust --
    data_trust: list[DataTrustItem] = []
    for item in summary.get("run_suitability", []):
        if isinstance(item, dict):
            check_raw = item.get("check") or ""
            if _is_i18n_ref(check_raw):
                check_text = _resolve_i18n(lang, check_raw)
            elif isinstance(check_raw, str) and check_raw.startswith("SUITABILITY_CHECK_"):
                check_text = tr(check_raw)
            else:
                check_text = str(check_raw)
            explanation_raw = item.get("explanation") or ""
            detail = (
                _resolve_i18n(lang, explanation_raw).strip()
                if _is_i18n_ref(explanation_raw) or isinstance(explanation_raw, list)
                else (str(explanation_raw).strip() or None)
            )
            data_trust.append(
                DataTrustItem(
                    check=check_text,
                    state=str(item.get("state") or "warn"),
                    detail=detail,
                )
            )

    # -- Pattern evidence --
    systems_raw = [
        _human_source(c.get("source") or c.get("suspected_source"), tr=tr) for c in top_causes[:3]
    ]
    # Deduplicate while preserving order so that e.g. three baseline_noise
    # findings don't appear as three repeated system names.
    systems = list(dict.fromkeys(systems_raw))
    pe_loc = primary_location
    pe_speed = primary_speed
    interp_raw = origin.get("explanation", "") if isinstance(origin, dict) else ""
    interp = (
        _resolve_i18n(lang, interp_raw)
        if _is_i18n_ref(interp_raw) or isinstance(interp_raw, list)
        else str(interp_raw)
    )
    src_why = str(
        (primary_candidate.get("source") or primary_candidate.get("suspected_source"))
        if primary_candidate
        else ""
    )
    sigs_why = primary_candidate.get("signatures_observed", []) if primary_candidate else []
    order_lbl_why = _order_label_human(lang, str(sigs_why[0])) if sigs_why else None
    why_text = why_parts_listed(src_why, order_lbl_why, lang=lang)

    warning_text = cert_reason if weak_spatial else None

    pattern_evidence = PatternEvidence(
        matched_systems=systems,
        strongest_location=pe_loc,
        speed_band=pe_speed,
        strength_label=str_text,
        strength_peak_db=db_val,
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
    # Filter out noise-floor peaks (≤ 0 dB) before taking the top 8.
    # Iterate over all peaks so that significant peaks beyond early noise
    # entries are still included.
    raw_peaks = [r for r in (plots.get("peaks_table", []) or []) if isinstance(r, dict)]
    above_noise = [
        r for r in raw_peaks if ((_sdb := _as_float(r.get("strength_db"))) is None or _sdb > 0)
    ]
    for row in above_noise[:8]:
        rank_val = _as_float(row.get("rank"))
        rank = str(int(rank_val)) if rank_val is not None else "\u2014"
        freq_val = _as_float(row.get("frequency_hz"))
        freq = f"{freq_val:.1f}" if freq_val is not None else "\u2014"
        classification = _peak_classification_text(row.get("peak_classification"), tr=tr)
        order_label_raw = str(row.get("order_label") or "").strip()
        order = _order_label_human(lang, order_label_raw) if order_label_raw else classification
        peak_db_val = _as_float(row.get("p95_intensity_db"))
        peak_db = f"{peak_db_val:.1f}" if peak_db_val is not None else "\u2014"
        strength_db_val = _as_float(row.get("strength_db"))
        strength_db = f"{strength_db_val:.1f}" if strength_db_val is not None else "\u2014"
        speed = str(row.get("typical_speed_band") or "\u2014")
        presence = float(_as_float(row.get("presence_ratio")) or 0.0)
        score = float(_as_float(row.get("persistence_score")) or 0.0)

        order_lower = order.lower()
        source_hint = str(row.get("source") or row.get("suspected_source") or "").strip().lower()
        if (source_hint == "wheel/tire") or ("wheel" in order_lower):
            system = tr("SOURCE_WHEEL_TIRE")
        elif (source_hint == "engine") or ("engine" in order_lower):
            system = tr("SOURCE_ENGINE")
        elif (
            (source_hint == "driveline")
            or ("driveshaft" in order_lower)
            or ("drive" in order_lower)
        ):
            system = tr("SOURCE_DRIVELINE")
        elif "transient" in order_lower:
            system = tr("SOURCE_TRANSIENT_IMPACT")
        else:
            system = "\u2014"
        relevance = (
            f"{classification} \u00b7 {presence:.0%} "
            f"{tr('PRESENCE')} \u00b7 {tr('SCORE')} {score:.2f}"
        )

        peak_rows.append(
            PeakRow(
                rank=rank,
                system=system,
                freq_hz=freq,
                order=order,
                peak_db=peak_db,
                strength_db=strength_db,
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
    sensor_count_used = sensor_count
    sensor_model_val = str(summary.get("sensor_model") or "").strip() or None
    firmware_version_val = str(summary.get("firmware_version") or "").strip() or None

    # -- Rendering context (pre-computed for the PDF renderer) --
    raw_findings = [f for f in summary.get("findings", []) if isinstance(f, dict)]
    raw_sensor_intensity_all = summary.get("sensor_intensity_by_location", [])
    if not isinstance(raw_sensor_intensity_all, list):
        raw_sensor_intensity_all = []
    active_locations = set(sensor_locations_active)
    if active_locations:
        raw_sensor_intensity = [
            row
            for row in raw_sensor_intensity_all
            if isinstance(row, dict) and str(row.get("location") or "") in active_locations
        ]
    else:
        raw_sensor_intensity = [row for row in raw_sensor_intensity_all if isinstance(row, dict)]

    # Pre-compute location hotspot rows from findings matched_points
    # so the PDF renderer never reads raw samples.
    hotspot_rows = _compute_location_hotspot_rows(raw_findings, raw_sensor_intensity)

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
        sensor_locations=sensor_locations_active,
        sensor_model=sensor_model_val,
        firmware_version=firmware_version_val,
        car=CarMeta(name=car_name, car_type=car_type),
        observed=observed,
        system_cards=system_cards,
        next_steps=next_steps,
        data_trust=data_trust,
        pattern_evidence=pattern_evidence,
        peak_rows=peak_rows,
        phase_info=phase_info,
        version_marker=version_marker,
        lang=lang,
        certainty_tier_key=tier,
        findings=raw_findings,
        top_causes=top_causes,
        sensor_intensity_by_location=raw_sensor_intensity,
        location_hotspot_rows=hotspot_rows,
    )
