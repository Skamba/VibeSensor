# ruff: noqa: E501
"""Output / aggregation: summaries, confidence labels, plot data, and public entry points."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from math import floor, sqrt
from pathlib import Path
from typing import Any

from ..analysis.vibration_strength import _percentile
from ..analysis_settings import tire_circumference_m_from_spec
from ..report_i18n import tr as _tr
from ..runlog import as_float_or_none as _as_float
from ..runlog import parse_iso8601
from .findings import (
    _build_findings,
    _merge_test_plan,
    _sensor_intensity_by_location,
    _speed_breakdown,
)
from .helpers import (
    ORDER_MIN_CONFIDENCE,
    SPEED_COVERAGE_MIN_PCT,
    SPEED_MIN_POINTS,
    _format_duration,
    _load_run,
    _location_label,
    _mean_variance,
    _normalize_lang,
    _outlier_summary,
    _percent_missing,
    _primary_vibration_strength_db,
    _sample_top_peaks,
    _sensor_limit_g,
    _speed_stats,
    _text,
    _validate_required_strength_metrics,
)

# ---------------------------------------------------------------------------
# Confidence label helper
# ---------------------------------------------------------------------------


def confidence_label(conf_0_to_1: float) -> tuple[str, str, str]:
    """Return (label_key, tone, pct_text) for a 0-1 confidence value.

    * label_key: i18n key  – CONFIDENCE_HIGH / CONFIDENCE_MEDIUM / CONFIDENCE_LOW
    * tone: card/pill tone  – 'success' / 'warn' / 'neutral'
    * pct_text: e.g. '82%'
    """
    pct = max(0.0, min(100.0, conf_0_to_1 * 100.0))
    pct_text = f"{pct:.0f}%"
    if conf_0_to_1 >= 0.70:
        return "CONFIDENCE_HIGH", "success", pct_text
    if conf_0_to_1 >= 0.40:
        return "CONFIDENCE_MEDIUM", "warn", pct_text
    return "CONFIDENCE_LOW", "neutral", pct_text


# ---------------------------------------------------------------------------
# Top-cause selection with drop-off rule and source grouping
# ---------------------------------------------------------------------------


def select_top_causes(
    findings: list[dict[str, object]],
    *,
    drop_off_points: float = 15.0,
    max_causes: int = 3,
) -> list[dict[str, object]]:
    """Group findings by suspected_source, keep best per group, apply drop-off."""
    # Only consider non-reference findings that meet the hard confidence floor
    diag_findings = [
        f
        for f in findings
        if isinstance(f, dict)
        and not str(f.get("finding_id", "")).startswith("REF_")
        and float(f.get("confidence_0_to_1") or 0) >= ORDER_MIN_CONFIDENCE
    ]
    if not diag_findings:
        return []

    # Group by suspected_source
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for f in diag_findings:
        src = str(f.get("suspected_source") or "unknown").strip().lower()
        groups[src].append(f)

    # For each group, pick the highest-confidence finding as representative
    group_reps: list[dict[str, object]] = []
    for members in groups.values():
        members_sorted = sorted(
            members,
            key=lambda m: float(m.get("confidence_0_to_1") or 0),
            reverse=True,
        )
        representative = dict(members_sorted[0])
        # Collect all signatures (frequency_hz_or_order) in this group
        signatures = []
        for m in members_sorted:
            sig = str(m.get("frequency_hz_or_order") or "").strip()
            if sig and sig not in signatures:
                signatures.append(sig)
        representative["signatures_observed"] = signatures
        representative["grouped_count"] = len(members_sorted)
        group_reps.append(representative)

    # Sort groups by best confidence descending
    group_reps.sort(
        key=lambda g: float(g.get("confidence_0_to_1") or 0),
        reverse=True,
    )

    # Apply drop-off rule: include causes within drop_off_points of the best
    best_conf_pct = float(group_reps[0].get("confidence_0_to_1") or 0) * 100.0
    threshold_pct = best_conf_pct - drop_off_points
    selected: list[dict[str, object]] = []
    for rep in group_reps:
        conf_pct = float(rep.get("confidence_0_to_1") or 0) * 100.0
        if conf_pct >= threshold_pct or not selected:
            selected.append(rep)
        if len(selected) >= max_causes:
            break

    # Build output in the format expected by the PDF
    result: list[dict[str, object]] = []
    for rep in selected:
        label_key, tone, pct_text = confidence_label(float(rep.get("confidence_0_to_1") or 0))
        result.append(
            {
                "finding_id": rep.get("finding_id"),
                "source": rep.get("suspected_source"),
                "confidence": rep.get("confidence_0_to_1"),
                "confidence_label_key": label_key,
                "confidence_tone": tone,
                "confidence_pct": pct_text,
                "order": rep.get("frequency_hz_or_order"),
                "signatures_observed": rep.get("signatures_observed", []),
                "grouped_count": rep.get("grouped_count", 1),
                "strongest_location": rep.get("strongest_location"),
                "dominance_ratio": rep.get("dominance_ratio"),
                "strongest_speed_band": rep.get("strongest_speed_band"),
                "weak_spatial_separation": rep.get("weak_spatial_separation"),
            }
        )
    return result


def _most_likely_origin_summary(
    findings: list[dict[str, object]], lang: object
) -> dict[str, object]:
    if not findings:
        return {
            "location": _tr(lang, "UNKNOWN"),
            "source": _tr(lang, "UNKNOWN"),
            "dominance_ratio": None,
            "weak_spatial_separation": True,
            "explanation": _text(
                lang,
                "No ranked finding is available yet.",
                "Nog geen gerangschikte bevinding beschikbaar.",
            ),
        }
    top = findings[0]
    location = str(top.get("strongest_location") or "").strip() or _tr(lang, "UNKNOWN")
    source = str(top.get("suspected_source") or "unknown")
    source_human = (
        "Wheel / Tire"
        if source == "wheel/tire"
        else "Driveline"
        if source == "driveline"
        else "Engine"
        if source == "engine"
        else "Unknown"
    )
    dominance = _as_float(top.get("dominance_ratio"))
    weak = bool(top.get("weak_spatial_separation")) or (dominance is not None and dominance < 1.2)
    speed_band = str(
        top.get("strongest_speed_band") or _text(lang, "unknown band", "onbekende band")
    )
    explanation = _text(
        lang,
        (
            "Based on Finding 1 ({source}) matched samples in {speed_band}, strongest at {location}, "
            "dominance {dominance}."
        ),
        (
            "Gebaseerd op Bevinding 1 ({source}) met gematchte samples in {speed_band}, sterkst bij {location}, "
            "dominantie {dominance}."
        ),
    ).format(
        source=source_human,
        speed_band=speed_band,
        location=location,
        dominance=(f"{dominance:.2f}x" if dominance is not None else _text(lang, "n/a", "n.v.t.")),
    )
    if weak:
        explanation += " " + _text(
            lang,
            "Weak spatial separation; inspect both top nearby components before replacing parts.",
            "Zwakke ruimtelijke scheiding; controleer eerst beide dichtstbijzijnde componenten voordat je onderdelen vervangt.",
        )
    return {
        "location": location,
        "source": source,
        "source_human": source_human,
        "dominance_ratio": dominance,
        "weak_spatial_separation": weak,
        "speed_band": speed_band,
        "explanation": explanation,
    }


def _aggregate_fft_spectrum(
    samples: list[dict[str, Any]],
    *,
    freq_bin_hz: float = 2.0,
) -> list[tuple[float, float]]:
    if freq_bin_hz <= 0:
        freq_bin_hz = 2.0
    bins: dict[float, float] = {}
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        for hz, amp in _sample_top_peaks(sample):
            if hz <= 0 or amp <= 0:
                continue
            bin_low = floor(hz / freq_bin_hz) * freq_bin_hz
            bin_center = bin_low + (freq_bin_hz / 2.0)
            current = bins.get(bin_center, 0.0)
            if amp > current:
                bins[bin_center] = amp
    return sorted(bins.items(), key=lambda item: item[0])


def _spectrogram_from_peaks(samples: list[dict[str, Any]]) -> dict[str, Any]:
    peak_rows: list[tuple[float, float, float]] = []
    time_values: list[float] = []
    speed_values: list[float] = []

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        t_s = _as_float(sample.get("t_s"))
        speed = _as_float(sample.get("speed_kmh"))
        peaks = _sample_top_peaks(sample)
        if t_s is not None and t_s >= 0:
            time_values.append(t_s)
        if speed is not None and speed > 0:
            speed_values.append(speed)
        if not peaks:
            continue
        for hz, amp in peaks:
            if hz <= 0 or amp <= 0:
                continue
            if t_s is not None and t_s >= 0:
                peak_rows.append((t_s, hz, amp))
            elif speed is not None and speed > 0:
                peak_rows.append((speed, hz, amp))

    use_time = bool(time_values)
    if not use_time and not speed_values:
        return {
            "x_axis": "none",
            "x_label_key": "TIME_S",
            "x_bins": [],
            "y_bins": [],
            "cells": [],
            "max_amp": 0.0,
        }

    x_axis = "time_s" if use_time else "speed_kmh"
    x_values = time_values if use_time else speed_values
    x_min = min(x_values)
    x_max = max(x_values)
    x_span = max(0.0, x_max - x_min)
    if x_axis == "time_s":
        x_bin_width = max(2.0, (x_span / 40.0) if x_span > 0 else 2.0)
        x_label_key = "TIME_S"
    else:
        x_bin_width = max(5.0, (x_span / 30.0) if x_span > 0 else 5.0)
        x_label_key = "SPEED_KM_H"

    peak_freqs = [hz for _x, hz, _amp in peak_rows]
    if not peak_freqs:
        return {
            "x_axis": x_axis,
            "x_label_key": x_label_key,
            "x_bins": [],
            "y_bins": [],
            "cells": [],
            "max_amp": 0.0,
        }

    observed_max_hz = max(peak_freqs)
    freq_cap_hz = min(200.0, max(40.0, observed_max_hz))
    freq_bin_hz = max(2.0, freq_cap_hz / 45.0)

    cell_by_bin: dict[tuple[float, float], float] = {}
    for x_val, hz, amp in peak_rows:
        if hz > freq_cap_hz:
            continue
        x_bin_low = floor((x_val - x_min) / x_bin_width) * x_bin_width + x_min
        y_bin_low = floor(hz / freq_bin_hz) * freq_bin_hz
        key = (x_bin_low, y_bin_low)
        current = cell_by_bin.get(key, 0.0)
        if amp > current:
            cell_by_bin[key] = amp

    x_bins = sorted({x for x, _y in cell_by_bin})
    y_bins = sorted({y for _x, y in cell_by_bin})
    if not x_bins or not y_bins:
        return {
            "x_axis": x_axis,
            "x_label_key": x_label_key,
            "x_bins": [],
            "y_bins": [],
            "cells": [],
            "max_amp": 0.0,
        }

    x_index = {value: idx for idx, value in enumerate(x_bins)}
    y_index = {value: idx for idx, value in enumerate(y_bins)}
    cells = [[0.0 for _ in x_bins] for _ in y_bins]
    max_amp = max(cell_by_bin.values()) if cell_by_bin else 0.0
    for (x_key, y_key), amp in cell_by_bin.items():
        yi = y_index[y_key]
        xi = x_index[x_key]
        cells[yi][xi] = amp

    return {
        "x_axis": x_axis,
        "x_label_key": x_label_key,
        "x_bin_width": x_bin_width,
        "y_bin_width": freq_bin_hz,
        "x_bins": [x + (x_bin_width / 2.0) for x in x_bins],
        "y_bins": [y + (freq_bin_hz / 2.0) for y in y_bins],
        "cells": cells,
        "max_amp": max_amp,
    }


def _top_peaks_table_rows(
    samples: list[dict[str, Any]],
    *,
    top_n: int = 12,
    freq_bin_hz: float = 1.0,
) -> list[dict[str, Any]]:
    grouped: dict[float, dict[str, Any]] = {}
    if freq_bin_hz <= 0:
        freq_bin_hz = 1.0

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        speed = _as_float(sample.get("speed_kmh"))
        for hz, amp in _sample_top_peaks(sample):
            if hz <= 0 or amp <= 0:
                continue
            freq_key = round(hz / freq_bin_hz) * freq_bin_hz
            bucket = grouped.setdefault(
                freq_key,
                {
                    "frequency_hz": freq_key,
                    "max_amp_g": 0.0,
                    "speeds": [],
                },
            )
            if amp > float(bucket["max_amp_g"]):
                bucket["max_amp_g"] = amp
            if speed is not None and speed > 0:
                bucket["speeds"].append(speed)

    ordered = sorted(
        grouped.values(),
        key=lambda item: float(item.get("max_amp_g") or 0.0),
        reverse=True,
    )[:top_n]

    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(ordered, start=1):
        speeds = [float(v) for v in item.get("speeds", []) if isinstance(v, (int, float))]
        speed_band = "-"
        if speeds:
            speed_band = f"{min(speeds):.0f}-{max(speeds):.0f} km/h"
        rows.append(
            {
                "rank": idx,
                "frequency_hz": float(item.get("frequency_hz") or 0.0),
                "order_label": "",
                "max_amp_g": float(item.get("max_amp_g") or 0.0),
                "typical_speed_band": speed_band,
            }
        )
    return rows


def _plot_data(summary: dict[str, Any]) -> dict[str, Any]:
    samples: list[dict[str, Any]] = summary.get("samples", [])
    raw_sample_rate_hz = _as_float(summary.get("raw_sample_rate_hz"))
    vib_mag_points: list[tuple[float, float]] = []
    dominant_freq_points: list[tuple[float, float]] = []
    speed_amp_points: list[tuple[float, float]] = []
    matched_by_finding: list[dict[str, object]] = []
    freq_vs_speed_by_finding: list[dict[str, object]] = []
    steady_speed_distribution: dict[str, float] | None = None

    for sample in samples:
        t_s = _as_float(sample.get("t_s"))
        if t_s is None:
            continue
        vib = _primary_vibration_strength_db(sample)
        if vib is not None:
            vib_mag_points.append((t_s, vib))
        if raw_sample_rate_hz and raw_sample_rate_hz > 0:
            dominant_hz = _as_float(sample.get("dominant_freq_hz"))
            if dominant_hz is not None and dominant_hz > 0:
                dominant_freq_points.append((t_s, dominant_hz))

    for row in summary.get("speed_breakdown", []):
        if not isinstance(row, dict):
            continue
        speed_range = str(row.get("speed_range", ""))
        if "-" not in speed_range:
            continue
        prefix = speed_range.split(" ", 1)[0]
        low_text, _, high_text = prefix.partition("-")
        try:
            low = float(low_text)
            high = float(high_text)
        except ValueError:
            continue
        amp = _as_float(row.get("mean_amplitude_g"))
        if amp is None:
            continue
        speed_amp_points.append(((low + high) / 2.0, amp))

    for finding in summary.get("findings", []):
        if not isinstance(finding, dict):
            continue
        points_raw = finding.get("matched_points")
        if not isinstance(points_raw, list):
            continue
        points: list[tuple[float, float]] = []
        for row in points_raw:
            if not isinstance(row, dict):
                continue
            speed = _as_float(row.get("speed_kmh"))
            amp = _as_float(row.get("amp"))
            if speed is None or amp is None or speed <= 0:
                continue
            points.append((speed, amp))
        if points:
            matched_by_finding.append(
                {
                    "label": str(finding.get("frequency_hz_or_order") or finding.get("finding_id")),
                    "points": points,
                }
            )
        freq_points: list[tuple[float, float]] = []
        pred_points: list[tuple[float, float]] = []
        for row in points_raw:
            if not isinstance(row, dict):
                continue
            speed = _as_float(row.get("speed_kmh"))
            matched_hz = _as_float(row.get("matched_hz"))
            predicted_hz = _as_float(row.get("predicted_hz"))
            if speed is None or speed <= 0:
                continue
            if matched_hz is not None and matched_hz > 0:
                freq_points.append((speed, matched_hz))
            if predicted_hz is not None and predicted_hz > 0:
                pred_points.append((speed, predicted_hz))
        if freq_points:
            freq_vs_speed_by_finding.append(
                {
                    "label": str(finding.get("frequency_hz_or_order") or finding.get("finding_id")),
                    "matched": freq_points,
                    "predicted": pred_points,
                }
            )

    speed_stats = summary.get("speed_stats", {})
    if isinstance(speed_stats, dict) and bool(speed_stats.get("steady_speed")) and vib_mag_points:
        vals = sorted(v for _t, v in vib_mag_points if v >= 0)
        if vals:
            steady_speed_distribution = {
                "p10": _percentile(vals, 0.10),
                "p50": _percentile(vals, 0.50),
                "p90": _percentile(vals, 0.90),
                "p95": _percentile(vals, 0.95),
            }

    fft_spectrum = _aggregate_fft_spectrum(samples)
    peaks_spectrogram = _spectrogram_from_peaks(samples)
    peaks_table = _top_peaks_table_rows(samples)

    return {
        "vib_magnitude": vib_mag_points,
        "dominant_freq": dominant_freq_points,
        "amp_vs_speed": speed_amp_points,
        "matched_amp_vs_speed": matched_by_finding,
        "freq_vs_speed_by_finding": freq_vs_speed_by_finding,
        "steady_speed_distribution": steady_speed_distribution,
        "fft_spectrum": fft_spectrum,
        "peaks_spectrogram": peaks_spectrogram,
        "peaks_table": peaks_table,
    }


def build_findings_for_samples(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
) -> list[dict[str, object]]:
    language = _normalize_lang(lang)
    rows = list(samples) if isinstance(samples, list) else []
    _validate_required_strength_metrics(rows)
    speed_values = [
        speed
        for speed in (_as_float(sample.get("speed_kmh")) for sample in rows)
        if speed is not None and speed > 0
    ]
    speed_stats = _speed_stats(speed_values)
    speed_non_null_pct = (len(speed_values) / len(rows) * 100.0) if rows else 0.0
    speed_sufficient = (
        speed_non_null_pct >= SPEED_COVERAGE_MIN_PCT and len(speed_values) >= SPEED_MIN_POINTS
    )
    raw_sample_rate_hz = _as_float(metadata.get("raw_sample_rate_hz"))
    return _build_findings(
        metadata=dict(metadata),
        samples=rows,
        speed_sufficient=speed_sufficient,
        steady_speed=bool(speed_stats.get("steady_speed")),
        speed_stddev_kmh=_as_float(speed_stats.get("stddev_kmh")),
        speed_non_null_pct=speed_non_null_pct,
        raw_sample_rate_hz=raw_sample_rate_hz,
        lang=language,
    )


def summarize_run_data(
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
) -> dict[str, object]:
    """Analyse pre-loaded run data and return the full summary dict.

    This is the single computation path used by both the History UI and the
    PDF report — callers must never re-derive metrics independently.
    """
    language = _normalize_lang(lang)
    _validate_required_strength_metrics(samples)

    run_id = str(metadata.get("run_id") or f"run-{file_name}")
    start_ts = parse_iso8601(metadata.get("start_time_utc"))
    end_ts = parse_iso8601(metadata.get("end_time_utc"))

    if end_ts is None and samples:
        sample_max_t = max((_as_float(sample.get("t_s")) or 0.0) for sample in samples)
        if start_ts is not None:
            end_ts = start_ts.fromtimestamp(start_ts.timestamp() + sample_max_t, tz=UTC)
    duration_s = 0.0
    if start_ts is not None and end_ts is not None:
        duration_s = max(0.0, (end_ts - start_ts).total_seconds())
    elif samples:
        duration_s = max((_as_float(sample.get("t_s")) or 0.0) for sample in samples)

    speed_values = [
        speed
        for speed in (_as_float(sample.get("speed_kmh")) for sample in samples)
        if speed is not None and speed > 0
    ]
    speed_stats = _speed_stats(speed_values)
    speed_non_null_pct = (len(speed_values) / len(samples) * 100.0) if samples else 0.0
    speed_sufficient = (
        speed_non_null_pct >= SPEED_COVERAGE_MIN_PCT and len(speed_values) >= SPEED_MIN_POINTS
    )

    sensor_model = metadata.get("sensor_model")
    sensor_limit = _sensor_limit_g(sensor_model)
    accel_x_vals = [
        value
        for value in (_as_float(sample.get("accel_x_g")) for sample in samples)
        if value is not None
    ]
    accel_y_vals = [
        value
        for value in (_as_float(sample.get("accel_y_g")) for sample in samples)
        if value is not None
    ]
    accel_z_vals = [
        value
        for value in (_as_float(sample.get("accel_z_g")) for sample in samples)
        if value is not None
    ]
    accel_mag_vals = [
        sqrt((sample["x"] ** 2) + (sample["y"] ** 2) + (sample["z"] ** 2))
        for sample in (
            {
                "x": _as_float(row.get("accel_x_g")),
                "y": _as_float(row.get("accel_y_g")),
                "z": _as_float(row.get("accel_z_g")),
            }
            for row in samples
        )
        if sample["x"] is not None and sample["y"] is not None and sample["z"] is not None
    ]
    amp_metric_values = [
        value for value in (_primary_vibration_strength_db(sample) for sample in samples) if value
    ]

    sat_count = 0
    if sensor_limit is not None:
        sat_threshold = sensor_limit * 0.98
        sat_count = sum(
            1
            for sample in samples
            if any(
                abs(val) >= sat_threshold
                for val in (
                    _as_float(sample.get("accel_x_g")) or 0.0,
                    _as_float(sample.get("accel_y_g")) or 0.0,
                    _as_float(sample.get("accel_z_g")) or 0.0,
                )
            )
        )

    x_mean, x_var = _mean_variance(accel_x_vals)
    y_mean, y_var = _mean_variance(accel_y_vals)
    z_mean, z_var = _mean_variance(accel_z_vals)

    raw_sample_rate_hz = _as_float(metadata.get("raw_sample_rate_hz"))
    speed_breakdown = _speed_breakdown(samples) if speed_sufficient else []
    speed_breakdown_skipped_reason = None
    if not speed_sufficient:
        speed_breakdown_skipped_reason = _tr(
            language, "SPEED_DATA_MISSING_OR_INSUFFICIENT_SPEED_BINNED_AND"
        )

    findings = _build_findings(
        metadata=metadata,
        samples=samples,
        speed_sufficient=speed_sufficient,
        steady_speed=bool(speed_stats.get("steady_speed")),
        speed_stddev_kmh=_as_float(speed_stats.get("stddev_kmh")),
        speed_non_null_pct=speed_non_null_pct,
        raw_sample_rate_hz=raw_sample_rate_hz,
        lang=language,
    )
    most_likely_origin = _most_likely_origin_summary(findings, language)
    test_plan = _merge_test_plan(findings, language)

    metadata_dict = metadata if isinstance(metadata, dict) else {}
    reference_complete = bool(
        _as_float(metadata_dict.get("raw_sample_rate_hz"))
        and (
            _as_float(metadata_dict.get("tire_circumference_m"))
            or tire_circumference_m_from_spec(
                _as_float(metadata_dict.get("tire_width_mm")),
                _as_float(metadata_dict.get("tire_aspect_pct")),
                _as_float(metadata_dict.get("rim_in")),
            )
        )
        and (
            _as_float(metadata_dict.get("engine_rpm"))
            or (
                _as_float(metadata_dict.get("final_drive_ratio"))
                and _as_float(metadata_dict.get("current_gear_ratio"))
            )
        )
    )
    run_suitability = [
        {
            "check": _text(language, "Speed variation", "Snelheidsvariatie"),
            "state": ("pass" if not bool(speed_stats.get("steady_speed")) else "warn"),
            "explanation": _text(
                language,
                "Wide enough speed sweep for order tracking."
                if not bool(speed_stats.get("steady_speed"))
                else "Speed sweep is narrow; repeat with +20 to +30 km/h span.",
                "Snelheidssweep is breed genoeg voor orde-tracking."
                if not bool(speed_stats.get("steady_speed"))
                else "Snelheidssweep is smal; herhaal met +20 tot +30 km/u bereik.",
            ),
        },
        {
            "check": _text(language, "Sensor coverage", "Sensordekking"),
            "state": "pass"
            if len(
                {
                    str(s.get("client_id") or "")
                    for s in samples
                    if isinstance(s, dict) and s.get("client_id")
                }
            )
            >= 3
            else "warn",
            "explanation": _text(
                language,
                "Multiple sensor locations observed."
                if len(
                    {
                        str(s.get("client_id") or "")
                        for s in samples
                        if isinstance(s, dict) and s.get("client_id")
                    }
                )
                >= 3
                else "Few active sensors; location ranking is weaker.",
                "Meerdere sensorlocaties waargenomen."
                if len(
                    {
                        str(s.get("client_id") or "")
                        for s in samples
                        if isinstance(s, dict) and s.get("client_id")
                    }
                )
                >= 3
                else "Weinig actieve sensoren; locatierangschikking is zwakker.",
            ),
        },
        {
            "check": _text(language, "Reference completeness", "Referentiecompleetheid"),
            "state": "pass" if reference_complete else "warn",
            "explanation": _text(
                language,
                "Required order references are present."
                if reference_complete
                else "Some order references are missing or derived with uncertainty.",
                "Vereiste ordesreferenties zijn aanwezig."
                if reference_complete
                else "Sommige ordesreferenties ontbreken of zijn onzeker afgeleid.",
            ),
        },
        {
            "check": _text(language, "Saturation and outliers", "Saturatie en uitschieters"),
            "state": "pass" if sat_count == 0 else "warn",
            "explanation": _text(
                language,
                "No obvious saturation detected."
                if sat_count == 0
                else f"{sat_count} potential saturation samples detected.",
                "Geen duidelijke saturatie gedetecteerd."
                if sat_count == 0
                else f"{sat_count} mogelijke saturatiesamples gedetecteerd.",
            ),
        },
    ]
    top_causes = select_top_causes(findings)

    sensor_locations = sorted(
        {
            _location_label(sample)
            for sample in samples
            if isinstance(sample, dict) and _location_label(sample)
        }
    )
    sensor_intensity_by_location = _sensor_intensity_by_location(
        samples,
        include_locations=set(sensor_locations),
    )

    summary: dict[str, Any] = {
        "file_name": file_name,
        "run_id": run_id,
        "rows": len(samples),
        "duration_s": duration_s,
        "record_length": _format_duration(duration_s),
        "lang": language,
        "report_date": datetime.now(UTC).isoformat(),
        "start_time_utc": metadata.get("start_time_utc"),
        "end_time_utc": metadata.get("end_time_utc"),
        "sensor_model": metadata.get("sensor_model"),
        "raw_sample_rate_hz": raw_sample_rate_hz,
        "feature_interval_s": _as_float(metadata.get("feature_interval_s")),
        "fft_window_size_samples": metadata.get("fft_window_size_samples"),
        "fft_window_type": metadata.get("fft_window_type"),
        "peak_picker_method": metadata.get("peak_picker_method"),
        "accel_scale_g_per_lsb": _as_float(metadata.get("accel_scale_g_per_lsb")),
        "incomplete_for_order_analysis": bool(metadata.get("incomplete_for_order_analysis")),
        "metadata": metadata,
        "warnings": [],
        "speed_breakdown": speed_breakdown,
        "speed_breakdown_skipped_reason": speed_breakdown_skipped_reason,
        "findings": findings,
        "top_causes": top_causes,
        "most_likely_origin": most_likely_origin,
        "test_plan": test_plan,
        "speed_stats": speed_stats,
        "sensor_locations": sensor_locations,
        "sensor_count_used": len(sensor_locations),
        "sensor_intensity_by_location": sensor_intensity_by_location,
        "sensor_statistics_by_location": sensor_intensity_by_location,
        "run_suitability": run_suitability,
        "samples": samples,
        "data_quality": {
            "required_missing_pct": {
                "t_s": _percent_missing(samples, "t_s"),
                "speed_kmh": _percent_missing(samples, "speed_kmh"),
                "accel_x_g": _percent_missing(samples, "accel_x_g"),
                "accel_y_g": _percent_missing(samples, "accel_y_g"),
                "accel_z_g": _percent_missing(samples, "accel_z_g"),
            },
            "speed_coverage": {
                "non_null_pct": speed_non_null_pct,
                "min_kmh": min(speed_values) if speed_values else None,
                "max_kmh": max(speed_values) if speed_values else None,
                "mean_kmh": speed_stats.get("mean_kmh"),
                "stddev_kmh": speed_stats.get("stddev_kmh"),
                "count_non_null": len(speed_values),
            },
            "accel_sanity": {
                "x_mean_g": x_mean,
                "x_variance_g2": x_var,
                "y_mean_g": y_mean,
                "y_variance_g2": y_var,
                "z_mean_g": z_mean,
                "z_variance_g2": z_var,
                "sensor_limit_g": sensor_limit,
                "saturation_count": sat_count,
            },
            "outliers": {
                "accel_magnitude_g": _outlier_summary(accel_mag_vals),
                "amplitude_metric": _outlier_summary(amp_metric_values),
            },
        },
    }
    summary["plots"] = _plot_data(summary)
    if not include_samples:
        summary.pop("samples", None)
    return summary


def summarize_log(
    log_path: Path, lang: str | None = None, include_samples: bool = True
) -> dict[str, object]:
    """Backward-compatible wrapper: reads a JSONL run file and analyses it."""
    metadata, samples, _warnings = _load_run(log_path)
    return summarize_run_data(
        metadata,
        samples,
        lang=lang,
        file_name=log_path.name,
        include_samples=include_samples,
    )
