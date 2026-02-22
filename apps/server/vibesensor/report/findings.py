# ruff: noqa: E501
"""Findings engine – order tracking, reference checks, and action plans."""

from __future__ import annotations

from collections import defaultdict
from math import floor, log1p
from statistics import mean
from typing import Any

from vibesensor_core.vibration_strength import percentile, vibration_strength_db_scalar

from ..report_i18n import tr as _tr
from ..runlog import as_float_or_none as _as_float
from .helpers import (
    CONSTANT_SPEED_STDDEV_KMH,
    ORDER_CONSTANT_SPEED_MIN_MATCH_RATE,
    ORDER_MIN_CONFIDENCE,
    ORDER_MIN_COVERAGE_POINTS,
    ORDER_MIN_MATCH_POINTS,
    ORDER_TOLERANCE_MIN_HZ,
    ORDER_TOLERANCE_REL,
    SPEED_COVERAGE_MIN_PCT,
    _amplitude_weighted_speed_window,
    _corr_abs,
    _effective_engine_rpm,
    _location_label,
    _locations_connected_throughout_run,
    _primary_vibration_strength_db,
    _run_noise_baseline_g,
    _sample_top_peaks,
    _speed_bin_label,
    _speed_bin_sort_key,
    _tire_reference_from_metadata,
)
from .order_analysis import (
    _finding_actions_for_source,
    _order_hypotheses,
    _order_label,
)
from .phase_segmentation import DrivingPhase, diagnostic_sample_mask, segment_run_phases
from .strength_labels import _STRENGTH_THRESHOLDS
from .test_plan import _location_speedbin_summary

_NEGLIGIBLE_STRENGTH_MAX_DB = (
    float(_STRENGTH_THRESHOLDS[1][0]) if len(_STRENGTH_THRESHOLDS) > 1 else 8.0
)
_LIGHT_STRENGTH_MAX_DB = (
    float(_STRENGTH_THRESHOLDS[2][0]) if len(_STRENGTH_THRESHOLDS) > 2 else 16.0
)
# Minimum realistic MEMS accelerometer noise floor (~0.001 g).
# Used as the lower bound for SNR computations to prevent ratio blow-up
# when the measured floor is near zero (sensor artifact / perfectly clean signal).
_MEMS_NOISE_FLOOR_G = 0.001


def _phase_to_str(phase: object) -> str | None:
    """Return the string value for a phase object (DrivingPhase or str)."""
    if phase is None:
        return None
    return phase.value if hasattr(phase, "value") else str(phase)


def _weighted_percentile(
    pairs: list[tuple[float, float]],
    q: float,
) -> float | None:
    if not pairs:
        return None
    q_clamped = max(0.0, min(1.0, q))
    filtered = [(value, weight) for value, weight in pairs if weight > 0]
    if not filtered:
        return None
    ordered = sorted(filtered, key=lambda item: item[0])
    total_weight = sum(weight for _, weight in ordered)
    if total_weight <= 0:
        return None
    threshold = q_clamped * total_weight
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def _speed_profile_from_points(
    points: list[tuple[float, float]],
    *,
    allowed_speed_bins: list[str] | tuple[str, ...] | set[str] | None = None,
) -> tuple[float | None, tuple[float, float] | None, str | None]:
    valid = [(speed, amp) for speed, amp in points if speed > 0 and amp > 0]
    if allowed_speed_bins:
        allowed = set(allowed_speed_bins)
        valid = [(speed, amp) for speed, amp in valid if _speed_bin_label(speed) in allowed]
    if not valid:
        return None, None, None

    peak_speed_kmh = max(valid, key=lambda item: item[1])[0]
    low = _weighted_percentile(valid, 0.10)
    high = _weighted_percentile(valid, 0.90)
    if low is None or high is None:
        return peak_speed_kmh, None, None
    if high < low:
        low, high = high, low
    speed_window_kmh = (low, high)
    low_speed, high_speed = _amplitude_weighted_speed_window(
        [speed_kmh for speed_kmh, _amp in valid],
        [amp for _speed_kmh, amp in valid],
    )
    strongest_speed_band = (
        f"{low_speed:.0f}-{high_speed:.0f} km/h"
        if low_speed is not None and high_speed is not None
        else None
    )
    return peak_speed_kmh, speed_window_kmh, strongest_speed_band


def _phase_speed_breakdown(
    samples: list[dict[str, Any]],
    per_sample_phases: list,
) -> list[dict[str, object]]:
    """Group vibration statistics by driving phase (temporal context).

    Unlike ``_speed_breakdown`` which bins by speed magnitude, this function
    groups by the temporal driving phase (IDLE, ACCELERATION, CRUISE, etc.)
    so callers can see how vibration differs across phases at the same speed.

    Addresses issue #189: adds temporal phase context to speed breakdown.
    """
    from .phase_segmentation import DrivingPhase

    grouped_amp: dict[str, list[float]] = defaultdict(list)
    grouped_speeds: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)

    for sample, phase in zip(samples, per_sample_phases, strict=False):
        phase_key = phase.value if isinstance(phase, DrivingPhase) else str(phase)
        counts[phase_key] += 1
        speed = _as_float(sample.get("speed_kmh"))
        if speed is not None and speed > 0:
            grouped_speeds[phase_key].append(speed)
        amp = _primary_vibration_strength_db(sample)
        if amp is not None:
            grouped_amp[phase_key].append(amp)

    # Output in a canonical phase order
    phase_order = [p.value for p in DrivingPhase]
    rows: list[dict[str, object]] = []
    for phase_key in phase_order:
        if phase_key not in counts:
            continue
        amp_vals = grouped_amp.get(phase_key, [])
        speed_vals = grouped_speeds.get(phase_key, [])
        rows.append(
            {
                "phase": phase_key,
                "count": counts[phase_key],
                "mean_speed_kmh": mean(speed_vals) if speed_vals else None,
                "max_speed_kmh": max(speed_vals) if speed_vals else None,
                "mean_vibration_strength_db": mean(amp_vals) if amp_vals else None,
                "max_vibration_strength_db": max(amp_vals) if amp_vals else None,
            }
        )
    return rows


def _speed_breakdown(samples: list[dict[str, Any]]) -> list[dict[str, object]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for sample in samples:
        speed = _as_float(sample.get("speed_kmh"))
        if speed is None or speed <= 0:
            continue
        label = _speed_bin_label(speed)
        counts[label] += 1
        amp = _primary_vibration_strength_db(sample)
        if amp is not None:
            grouped[label].append(amp)

    rows: list[dict[str, object]] = []
    for label in sorted(counts.keys(), key=_speed_bin_sort_key):
        values = grouped.get(label, [])
        rows.append(
            {
                "speed_range": label,
                "count": counts[label],
                "mean_vibration_strength_db": mean(values) if values else None,
                "max_vibration_strength_db": max(values) if values else None,
            }
        )
    return rows


def _sensor_intensity_by_location(
    samples: list[dict[str, Any]],
    include_locations: set[str] | None = None,
    *,
    lang: object = "en",
    connected_locations: set[str] | None = None,
    per_sample_phases: list | None = None,
) -> list[dict[str, float | str | int | bool]]:
    """Compute per-location vibration intensity statistics.

    When ``per_sample_phases`` is provided, also computes per-phase intensity
    breakdown for each location so callers can see how vibration differs across
    IDLE, ACCELERATION, CRUISE, etc. at each sensor position.
    Addresses issue #192: aggregate entire run loses phase context.
    """
    grouped_amp: dict[str, list[float]] = defaultdict(list)
    sample_counts: dict[str, int] = defaultdict(int)
    dropped_totals: dict[str, list[float]] = defaultdict(list)
    overflow_totals: dict[str, list[float]] = defaultdict(list)
    strength_bucket_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {f"l{idx}": 0 for idx in range(0, 6)}
    )
    strength_bucket_totals: dict[str, int] = defaultdict(int)
    # Per-phase intensity: {location: {phase_key: [amp_values]}}
    phase_amp: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)

    for i, sample in enumerate(samples):
        if not isinstance(sample, dict):
            continue
        location = _location_label(sample, lang=lang)
        if not location:
            continue
        if include_locations is not None and location not in include_locations:
            continue
        sample_counts[location] += 1
        amp = _primary_vibration_strength_db(sample)
        if amp is not None:
            grouped_amp[location].append(float(amp))
            if has_phases and per_sample_phases is not None:
                phase_key = str(
                    per_sample_phases[i].value
                    if hasattr(per_sample_phases[i], "value")
                    else per_sample_phases[i]
                )
                phase_amp[location][phase_key].append(float(amp))
        dropped_total = _as_float(sample.get("frames_dropped_total"))
        if dropped_total is not None:
            dropped_totals[location].append(dropped_total)
        overflow_total = _as_float(sample.get("queue_overflow_drops"))
        if overflow_total is not None:
            overflow_totals[location].append(overflow_total)
        vibration_strength_db = _as_float(sample.get("vibration_strength_db"))
        bucket = str(sample.get("strength_bucket") or "")
        if vibration_strength_db is None:
            continue
        if bucket:
            strength_bucket_counts[location][bucket] = (
                strength_bucket_counts[location].get(bucket, 0) + 1
            )
            strength_bucket_totals[location] += 1

    rows: list[dict[str, float | str | int | bool]] = []
    target_locations = set(sample_counts.keys())
    if include_locations is not None:
        target_locations |= set(include_locations)
    max_sample_count = max(
        (sample_counts.get(location, 0) for location in target_locations), default=0
    )

    for location in sorted(target_locations):
        values = grouped_amp.get(location, [])
        values_sorted = sorted(values)
        dropped_vals = dropped_totals.get(location, [])
        overflow_vals = overflow_totals.get(location, [])
        dropped_delta = int(max(dropped_vals) - min(dropped_vals)) if len(dropped_vals) >= 2 else 0
        overflow_delta = (
            int(max(overflow_vals) - min(overflow_vals)) if len(overflow_vals) >= 2 else 0
        )
        bucket_counts = strength_bucket_counts.get(location, {f"l{idx}": 0 for idx in range(0, 6)})
        bucket_total = max(0, strength_bucket_totals.get(location, 0))
        bucket_distribution: dict[str, float | int] = {
            "total": bucket_total,
            "counts": dict(bucket_counts),
        }
        for idx in range(1, 6):
            key = f"l{idx}"
            bucket_distribution[f"percent_time_{key}"] = (
                (bucket_counts[key] / bucket_total * 100.0) if bucket_total > 0 else 0.0
            )
        sample_count = int(sample_counts.get(location, 0))
        sample_coverage_ratio = (sample_count / max_sample_count) if max_sample_count > 0 else 1.0
        sample_coverage_warning = max_sample_count >= 5 and sample_coverage_ratio <= 0.20
        partial_coverage = bool(
            connected_locations is not None and location not in connected_locations
        )
        # Per-phase intensity summary for this location (issue #192)
        location_phase_intensity: dict[str, object] | None = None
        if has_phases:
            loc_phases = phase_amp.get(location, {})
            location_phase_intensity = {
                phase_key: {
                    "count": len(phase_vals),
                    "mean_intensity_db": mean(phase_vals) if phase_vals else None,
                    "max_intensity_db": max(phase_vals) if phase_vals else None,
                }
                for phase_key, phase_vals in loc_phases.items()
                if phase_vals
            }
        rows.append(
            {
                "location": location,
                "partial_coverage": partial_coverage,
                "samples": sample_count,
                "sample_count": sample_count,
                "sample_coverage_ratio": sample_coverage_ratio,
                "sample_coverage_warning": sample_coverage_warning,
                "mean_intensity_db": mean(values) if values else None,
                "p50_intensity_db": percentile(values_sorted, 0.50) if values else None,
                "p95_intensity_db": percentile(values_sorted, 0.95) if values else None,
                "max_intensity_db": max(values) if values else None,
                "dropped_frames_delta": dropped_delta,
                "queue_overflow_drops_delta": overflow_delta,
                "strength_bucket_distribution": bucket_distribution,
                "phase_intensity": location_phase_intensity,
            }
        )
    rows.sort(
        key=lambda row: (
            1 if not bool(row.get("partial_coverage")) else 0,
            1 if not bool(row.get("sample_coverage_warning")) else 0,
            float(row.get("p95_intensity_db") or 0.0),
            float(row.get("max_intensity_db") or 0.0),
        ),
        reverse=True,
    )
    return rows


def _reference_missing_finding(
    *,
    finding_id: str,
    suspected_source: str,
    evidence_summary: str,
    quick_checks: list[str],
    lang: object = "en",
) -> dict[str, object]:
    return {
        "finding_id": finding_id,
        "finding_type": "reference",
        "suspected_source": suspected_source,
        "evidence_summary": evidence_summary,
        "frequency_hz_or_order": _tr(lang, "REFERENCE_MISSING"),
        "amplitude_metric": {
            "name": "not_available",
            "value": None,
            "units": "n/a",
            "definition": _tr(lang, "REFERENCE_MISSING_ORDER_SPECIFIC_AMPLITUDE_RANKING_SKIPPED"),
        },
        "confidence_0_to_1": None,
        "quick_checks": quick_checks[:3],
    }


def _build_order_findings(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    speed_sufficient: bool,
    steady_speed: bool,
    speed_stddev_kmh: float | None,
    tire_circumference_m: float | None,
    engine_ref_sufficient: bool,
    raw_sample_rate_hz: float | None,
    accel_units: str,
    connected_locations: set[str],
    lang: object,
    per_sample_phases: list | None = None,
) -> list[dict[str, object]]:
    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        return []

    findings: list[tuple[float, dict[str, object]]] = []
    for hypothesis in _order_hypotheses():
        if hypothesis.key.startswith(("wheel_", "driveshaft_")) and (
            not speed_sufficient or tire_circumference_m is None or tire_circumference_m <= 0
        ):
            continue
        if hypothesis.key.startswith("engine_") and not engine_ref_sufficient:
            continue

        possible = 0
        matched = 0
        matched_amp: list[float] = []
        matched_floor: list[float] = []
        rel_errors: list[float] = []
        predicted_vals: list[float] = []
        measured_vals: list[float] = []
        matched_points: list[dict[str, object]] = []
        ref_sources: set[str] = set()
        possible_by_speed_bin: dict[str, int] = defaultdict(int)
        matched_by_speed_bin: dict[str, int] = defaultdict(int)
        possible_by_phase: dict[str, int] = defaultdict(int)
        matched_by_phase: dict[str, int] = defaultdict(int)
        # Per-location tracking: multi-sensor runs dilute the global match rate
        # because only the fault sensor matches.  Track per-location stats so we
        # can recognise a single-sensor signal even when the global rate is low.
        possible_by_location: dict[str, int] = defaultdict(int)
        matched_by_location: dict[str, int] = defaultdict(int)
        has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)

        for sample_idx, sample in enumerate(samples):
            peaks = _sample_top_peaks(sample)
            if not peaks:
                continue
            predicted_hz, ref_source = hypothesis.predicted_hz(
                sample,
                metadata,
                tire_circumference_m,
            )
            if predicted_hz is None or predicted_hz <= 0:
                continue
            possible += 1
            ref_sources.add(ref_source)
            sample_location = _location_label(sample, lang=lang)
            if sample_location:
                possible_by_location[sample_location] += 1
            sample_speed = _as_float(sample.get("speed_kmh"))
            sample_speed_bin = (
                _speed_bin_label(sample_speed)
                if sample_speed is not None and sample_speed > 0
                else None
            )
            if sample_speed_bin is not None:
                possible_by_speed_bin[sample_speed_bin] += 1
            if has_phases:
                assert per_sample_phases is not None
                ph = per_sample_phases[sample_idx]
                phase_key = str(ph.value if hasattr(ph, "value") else ph)
                possible_by_phase[phase_key] += 1

            tolerance_hz = max(ORDER_TOLERANCE_MIN_HZ, predicted_hz * ORDER_TOLERANCE_REL)
            best_hz, best_amp = min(peaks, key=lambda item: abs(item[0] - predicted_hz))
            delta_hz = abs(best_hz - predicted_hz)
            if delta_hz > tolerance_hz:
                continue

            matched += 1
            if sample_location:
                matched_by_location[sample_location] += 1
            if sample_speed_bin is not None:
                matched_by_speed_bin[sample_speed_bin] += 1
            if has_phases:
                matched_by_phase[phase_key] += 1
            rel_errors.append(delta_hz / max(1e-9, predicted_hz))
            matched_amp.append(best_amp)
            floor_amp = _as_float(sample.get("strength_floor_amp_g")) or 0.0
            matched_floor.append(max(0.0, floor_amp))
            predicted_vals.append(predicted_hz)
            measured_vals.append(best_hz)
            sample_phase: str | None = None
            if per_sample_phases is not None and sample_idx < len(per_sample_phases):
                sample_phase = _phase_to_str(per_sample_phases[sample_idx])
            matched_points.append(
                {
                    "t_s": _as_float(sample.get("t_s")),
                    "speed_kmh": _as_float(sample.get("speed_kmh")),
                    "predicted_hz": predicted_hz,
                    "matched_hz": best_hz,
                    "rel_error": delta_hz / max(1e-9, predicted_hz),
                    "amp": best_amp,
                    "location": _location_label(sample, lang=lang),
                    "phase": sample_phase,
                }
            )

        if possible < ORDER_MIN_COVERAGE_POINTS or matched < ORDER_MIN_MATCH_POINTS:
            continue
        match_rate = matched / max(1, possible)
        # At constant speed the predicted frequency never varies, so random
        # broadband peaks match by chance at ~30-40%.  A genuine order source
        # would be present in the vast majority of samples.  Require a much
        # higher match rate before claiming a finding.
        constant_speed = (
            speed_stddev_kmh is not None and speed_stddev_kmh < CONSTANT_SPEED_STDDEV_KMH
        )
        min_match_rate = ORDER_CONSTANT_SPEED_MIN_MATCH_RATE if constant_speed else 0.25
        effective_match_rate = match_rate
        focused_speed_band: str | None = None
        if match_rate < min_match_rate and possible_by_speed_bin:
            highest_speed_bin = max(possible_by_speed_bin.keys(), key=_speed_bin_sort_key)
            focused_possible = int(possible_by_speed_bin.get(highest_speed_bin, 0))
            focused_matched = int(matched_by_speed_bin.get(highest_speed_bin, 0))
            focused_rate = focused_matched / max(1, focused_possible)
            min_focused_possible = max(ORDER_MIN_MATCH_POINTS, ORDER_MIN_COVERAGE_POINTS // 2)
            if (
                focused_possible >= min_focused_possible
                and focused_matched >= ORDER_MIN_MATCH_POINTS
                and focused_rate >= min_match_rate
            ):
                focused_speed_band = highest_speed_bin
                effective_match_rate = focused_rate
        # ── Per-location match-rate rescue ──────────────────────────────
        # In multi-sensor setups the global match rate is diluted because
        # only the fault sensor matches the order.  E.g. 1 of 4 sensors
        # matching = 25% global rate, even though the fault-sensor rate is
        # 100%.  When a single location independently exceeds the threshold,
        # accept that as the effective match rate.
        per_location_dominant: bool = False
        if effective_match_rate < min_match_rate and possible_by_location:
            best_loc_rate = 0.0
            for loc, loc_possible in possible_by_location.items():
                loc_matched = matched_by_location.get(loc, 0)
                if (
                    loc_possible >= ORDER_MIN_COVERAGE_POINTS
                    and loc_matched >= ORDER_MIN_MATCH_POINTS
                ):
                    loc_rate = loc_matched / max(1, loc_possible)
                    if loc_rate > best_loc_rate:
                        best_loc_rate = loc_rate
            if best_loc_rate >= min_match_rate:
                effective_match_rate = best_loc_rate
                per_location_dominant = True
        if effective_match_rate < min_match_rate:
            continue

        # Per-phase confidence: compute match rate for each driving phase.
        # Phases with sufficient matches act as independent evidence sources.
        per_phase_confidence: dict[str, float] | None = None
        phases_with_evidence = 0
        if has_phases and possible_by_phase:
            per_phase_confidence = {}
            for ph_key, ph_possible in possible_by_phase.items():
                ph_matched = matched_by_phase.get(ph_key, 0)
                per_phase_confidence[ph_key] = ph_matched / max(1, ph_possible)
                if (
                    ph_matched >= ORDER_MIN_MATCH_POINTS
                    and per_phase_confidence[ph_key] >= min_match_rate
                ):
                    phases_with_evidence += 1

        mean_amp = mean(matched_amp) if matched_amp else 0.0
        mean_floor = mean(matched_floor) if matched_floor else 0.0
        mean_rel_err = mean(rel_errors) if rel_errors else 1.0
        corr = _corr_abs(predicted_vals, measured_vals) if len(matched_points) >= 3 else None
        # When speed is constant, predicted Hz never varies so correlation
        # is degenerate (undefined or misleading).  Zero it out.
        if constant_speed:
            corr = None
        corr_val = corr if corr is not None else 0.0

        # Compute location hotspot BEFORE confidence so spatial info is available.
        # When order evidence is accepted via focused high-speed coverage,
        # localize within that same speed band to avoid low-speed road-noise
        # bins dominating strongest-location selection.
        relevant_speed_bins = [focused_speed_band] if focused_speed_band else None
        try:
            location_line, location_hotspot = _location_speedbin_summary(
                matched_points,
                lang=lang,
                relevant_speed_bins=relevant_speed_bins,
                connected_locations=connected_locations,
            )
        except TypeError as exc:
            if "connected_locations" not in str(exc):
                raise
            location_line, location_hotspot = _location_speedbin_summary(
                matched_points,
                lang=lang,
                relevant_speed_bins=relevant_speed_bins,
            )
        weak_spatial_separation = (
            bool(location_hotspot.get("weak_spatial_separation"))
            if isinstance(location_hotspot, dict)
            else True
        )
        dominance_ratio = (
            _as_float(location_hotspot.get("dominance_ratio"))
            if isinstance(location_hotspot, dict)
            else None
        )
        localization_confidence = (
            float(location_hotspot.get("localization_confidence"))
            if isinstance(location_hotspot, dict)
            else 0.05
        )

        # ── Single-sensor dominance override ────────────────────────────
        # When matched points cluster at one location but multiple sensors
        # were connected, the standard localization_confidence formula
        # computes dominance_ratio = 1.0 (no second sensor to compare).
        # That gives localization_confidence ≈ 0.05, wrongly penalising a
        # finding that is actually well-localised.
        # Fix: absence of matches from other connected sensors IS strong
        # spatial evidence.
        unique_match_locations = {
            str(pt.get("location") or "") for pt in matched_points if pt.get("location")
        }
        if (
            per_location_dominant
            and len(unique_match_locations) == 1
            and len(connected_locations) >= 2
        ):
            # Strong localization: 1 of N sensors matched.
            localization_confidence = min(1.0, 0.50 + 0.15 * (len(connected_locations) - 1))
            weak_spatial_separation = False
        elif (
            len(unique_match_locations) == 1
            and len(connected_locations) >= 2
            and matched >= ORDER_MIN_MATCH_POINTS
        ):
            # Weaker case: global rate passed but all matches still from one sensor.
            localization_confidence = max(
                localization_confidence,
                min(1.0, 0.40 + 0.10 * (len(connected_locations) - 1)),
            )
            weak_spatial_separation = False

        # Count how many distinct locations independently detected this order
        corroborating_locations = len(
            {str(pt.get("location") or "") for pt in matched_points if pt.get("location")}
        )

        error_score = max(0.0, 1.0 - min(1.0, mean_rel_err / 0.25))
        snr_score = min(1.0, log1p(mean_amp / max(_MEMS_NOISE_FLOOR_G, mean_floor)) / 2.5)
        # Absolute-strength guard: amplitude barely above MEMS noise cannot score > 0.40 on SNR.
        if mean_amp <= 2 * _MEMS_NOISE_FLOOR_G:
            snr_score = min(snr_score, 0.40)
        absolute_strength_db = vibration_strength_db_scalar(
            peak_band_rms_amp_g=mean_amp,
            floor_amp_g=mean_floor,
        )

        # --- Confidence formula (calibrated) ---
        # Base is intentionally low; weight must come from evidence.
        confidence = (
            0.10
            + (0.35 * effective_match_rate)
            + (0.20 * error_score)
            + (0.15 * corr_val)
            + (0.15 * snr_score)  # was 0.10 — SNR matters more
        )
        # Penalty: negligible/light absolute signal strength (shared dB bands).
        if absolute_strength_db < _NEGLIGIBLE_STRENGTH_MAX_DB:
            confidence = min(confidence, 0.45)
        elif absolute_strength_db < _LIGHT_STRENGTH_MAX_DB:
            confidence *= 0.80
        # Penalty: location ambiguity / weak localization confidence
        confidence *= 0.70 + (0.30 * max(0.0, min(1.0, localization_confidence)))
        # Penalty: weak spatial separation
        if weak_spatial_separation:
            confidence *= 0.70 if dominance_ratio is not None and dominance_ratio < 1.05 else 0.80
        # Penalty: steady/constant speed reduces order-tracking value
        if constant_speed:
            confidence *= 0.75  # was 0.88 for steady; constant is stricter
        elif steady_speed:
            confidence *= 0.82  # was 0.88 — still significant
        # Bonus: more matched samples → higher trust (diminishing returns)
        # Keep a meaningful penalty near the minimum 4-match threshold while
        # saturating confidence support once evidence reaches ~20 matches.
        sample_factor = min(1.0, matched / 20.0)  # saturates at 20 samples
        confidence = confidence * (0.70 + 0.30 * sample_factor)
        # Bonus: multi-sensor corroboration — multiple independent locations
        # detecting the same order strengthens the finding.
        if corroborating_locations >= 3:
            confidence *= 1.08
        elif corroborating_locations >= 2:
            confidence *= 1.04
        # Bonus: multi-phase corroboration — order detected consistently across
        # multiple driving phases (e.g., both CRUISE and ACCELERATION) indicates
        # a genuine mechanical source rather than a phase-specific artefact.
        if phases_with_evidence >= 3:
            confidence *= 1.06
        elif phases_with_evidence >= 2:
            confidence *= 1.03
        confidence = max(0.08, min(0.97, confidence))

        ranking_score = (
            effective_match_rate
            * log1p(mean_amp / max(_MEMS_NOISE_FLOOR_G, mean_floor))
            * max(0.0, (1.0 - min(1.0, mean_rel_err / 0.5)))
        )

        ref_text = ", ".join(sorted(ref_sources))
        evidence = _tr(
            lang,
            "EVIDENCE_ORDER_TRACKED",
            order_label=_order_label(lang, hypothesis.order, hypothesis.order_label_base),
            matched=matched,
            possible=possible,
            match_rate=effective_match_rate,
            mean_rel_err=mean_rel_err,
            ref_text=ref_text,
        )
        if location_line:
            evidence = f"{evidence} {location_line}"

        strongest_location = (
            str(location_hotspot.get("location")) if isinstance(location_hotspot, dict) else ""
        )
        hotspot_speed_band = (
            str(location_hotspot.get("speed_range")) if isinstance(location_hotspot, dict) else ""
        )
        speed_points: list[tuple[float, float]] = []
        for point in matched_points:
            point_speed = _as_float(point.get("speed_kmh"))
            point_amp = _as_float(point.get("amp"))
            if point_speed is None or point_amp is None:
                continue
            speed_points.append((point_speed, point_amp))
        peak_speed_kmh, speed_window_kmh, strongest_speed_band = _speed_profile_from_points(
            speed_points,
            allowed_speed_bins=[focused_speed_band] if focused_speed_band else None,
        )
        if not strongest_speed_band:
            strongest_speed_band = hotspot_speed_band
        if focused_speed_band and not strongest_speed_band:
            strongest_speed_band = focused_speed_band
        actions = _finding_actions_for_source(
            lang,
            hypothesis.suspected_source,
            strongest_location=strongest_location,
            strongest_speed_band=strongest_speed_band,
            weak_spatial_separation=weak_spatial_separation,
        )
        quick_checks = [
            str(action.get("what") or "")
            for action in actions
            if str(action.get("what") or "").strip()
        ][:3]

        # Compute phase evidence: how much of the matched evidence came from CRUISE phase.
        # CRUISE (steady driving) provides the most reliable diagnostic signal.
        _cruise_phase_val = DrivingPhase.CRUISE.value
        matched_phase_strs = [
            str(pt.get("phase") or "") for pt in matched_points if pt.get("phase")
        ]
        _cruise_matched = sum(1 for p in matched_phase_strs if p == _cruise_phase_val)
        phase_evidence: dict[str, object] = {
            "cruise_fraction": _cruise_matched / len(matched_points) if matched_points else 0.0,
            "phases_detected": sorted(set(matched_phase_strs)),
        }
        # Dominant non-cruise onset phase helps explain whether issue appears on transitions.
        _phase_onset_relevant = {
            DrivingPhase.ACCELERATION.value,
            DrivingPhase.DECELERATION.value,
            DrivingPhase.COAST_DOWN.value,
        }
        dominant_phase: str | None = None
        onset_phase_labels = [p for p in matched_phase_strs if p in _phase_onset_relevant]
        if onset_phase_labels and len(onset_phase_labels) >= max(2, len(matched_points) // 2):
            from collections import Counter as _Counter

            top_phase, top_count = _Counter(onset_phase_labels).most_common(1)[0]
            if top_count / len(matched_points) >= 0.50:
                dominant_phase = top_phase

        finding = {
            "finding_id": "F_ORDER",
            "finding_key": hypothesis.key,
            "suspected_source": hypothesis.suspected_source,
            "evidence_summary": evidence,
            "frequency_hz_or_order": _order_label(
                lang, hypothesis.order, hypothesis.order_label_base
            ),
            "amplitude_metric": {
                "name": "strength_peak_band_rms_amp_g",
                "value": mean_amp,
                "units": accel_units,
                "definition": _tr(lang, "METRIC_MEAN_MATCHED_PEAK_AMPLITUDE"),
            },
            "confidence_0_to_1": confidence,
            "quick_checks": quick_checks,
            "matched_points": matched_points,
            "location_hotspot": location_hotspot,
            "strongest_location": strongest_location or None,
            "strongest_speed_band": strongest_speed_band or None,
            "dominant_phase": dominant_phase,
            "peak_speed_kmh": peak_speed_kmh,
            "speed_window_kmh": list(speed_window_kmh) if speed_window_kmh else None,
            "dominance_ratio": (
                float(location_hotspot.get("dominance_ratio"))
                if isinstance(location_hotspot, dict)
                else None
            ),
            "localization_confidence": localization_confidence,
            "weak_spatial_separation": weak_spatial_separation,
            "corroborating_locations": corroborating_locations,
            "phase_evidence": phase_evidence,
            "evidence_metrics": {
                "match_rate": effective_match_rate,
                "global_match_rate": match_rate,
                "focused_speed_band": focused_speed_band,
                "mean_relative_error": mean_rel_err,
                "mean_matched_amplitude": mean_amp,
                "mean_noise_floor": mean_floor,
                "vibration_strength_db": absolute_strength_db,
                "possible_samples": possible,
                "matched_samples": matched,
                "frequency_correlation": corr,
                "per_phase_confidence": per_phase_confidence,
                "phases_with_evidence": phases_with_evidence,
            },
            "next_sensor_move": str(actions[0].get("what") or "")
            or _tr(lang, "NEXT_SENSOR_MOVE_DEFAULT"),
            "actions": actions,
        }
        findings.append((ranking_score, finding))

    findings.sort(key=lambda item: item[0], reverse=True)
    return [
        item[1]
        for item in findings[:3]
        if float(item[1].get("confidence_0_to_1", 0)) >= ORDER_MIN_CONFIDENCE
    ]


PERSISTENT_PEAK_MIN_PRESENCE = 0.15
TRANSIENT_BURSTINESS_THRESHOLD = 5.0
PERSISTENT_PEAK_MAX_FINDINGS = 3
# Minimum SNR for a peak to be considered above baseline noise
BASELINE_NOISE_SNR_THRESHOLD = 1.5


def _classify_peak_type(
    presence_ratio: float,
    burstiness: float,
    *,
    snr: float | None = None,
    spatial_uniformity: float | None = None,
    speed_uniformity: float | None = None,
) -> str:
    """Classify a frequency peak as ``patterned``, ``persistent``, ``transient``, or ``baseline_noise``.

    * **patterned**: high presence and low burstiness → likely a fault vibration.
    * **persistent**: moderate presence → unknown but repeated resonance.
    * **transient**: low presence or very high burstiness → one-off impact/thud.
    * **baseline_noise**: low SNR → consistent with measurement noise floor.

    Parameters
    ----------
    presence_ratio : float
        Fraction of samples where this peak appears.
    burstiness : float
        Ratio of max to median amplitude.
    snr : float | None
        Signal-to-noise ratio (peak amp / noise floor). If below threshold,
        peak is classified as baseline noise regardless of presence.
    spatial_uniformity : float | None
        Fraction of distinct run locations where this peak appears.
        High values suggest environmental noise rather than a localized source.
    speed_uniformity : float | None
        Standard deviation of per-speed-bin hit rates for this peak.
        Lower values indicate uniform presence across speed bins.
    """
    # Baseline noise: appears everywhere at similar level, or very low SNR
    if snr is not None and snr < BASELINE_NOISE_SNR_THRESHOLD:
        return "baseline_noise"
    if (
        spatial_uniformity is not None
        and spatial_uniformity > 0.85
        and presence_ratio >= 0.60
        and burstiness < 2.0
    ):
        return "baseline_noise"
    if (
        spatial_uniformity is not None
        and speed_uniformity is not None
        and spatial_uniformity >= 0.80
        and speed_uniformity <= 0.10
        and 0.20 <= presence_ratio <= 0.40
        and 3.0 <= burstiness <= 5.0
    ):
        return "baseline_noise"

    if presence_ratio < PERSISTENT_PEAK_MIN_PRESENCE:
        return "transient"
    if burstiness > TRANSIENT_BURSTINESS_THRESHOLD:
        return "transient"
    if presence_ratio >= 0.40 and burstiness < 3.0:
        return "patterned"
    return "persistent"


def _build_persistent_peak_findings(
    *,
    samples: list[dict[str, Any]],
    order_finding_freqs: set[float],
    accel_units: str,
    lang: object,
    freq_bin_hz: float = 2.0,
    per_sample_phases: list | None = None,
) -> list[dict[str, object]]:
    """Build findings for non-order persistent frequency peaks.

    Uses the same confidence-style scoring as order findings (presence_ratio,
    error/SNR) so the report is consistent.  Peaks already claimed by order
    findings are excluded.  Transient peaks are returned separately.

    When ``per_sample_phases`` is provided, each finding includes a
    ``phase_presence`` dict showing the per-phase presence ratio for that
    frequency bin so callers can see which driving phases the peak is observed
    in (IDLE, ACCELERATION, CRUISE, DECELERATION, COAST_DOWN).
    Addresses TODO 4: ``_build_persistent_peak_findings()`` has no phase awareness.
    """
    if freq_bin_hz <= 0:
        freq_bin_hz = 2.0

    bin_amps: dict[float, list[float]] = defaultdict(list)
    bin_floors: dict[float, list[float]] = defaultdict(list)
    bin_speeds: dict[float, list[float]] = defaultdict(list)
    bin_speed_amp_pairs: dict[float, list[tuple[float, float]]] = defaultdict(list)
    bin_location_counts: dict[float, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    bin_speed_bin_counts: dict[float, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    bin_phase_counts: dict[float, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total_speed_bin_counts: dict[str, int] = defaultdict(int)
    total_locations: set[str] = set()
    n_samples = 0
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)

    for i, sample in enumerate(samples):
        if not isinstance(sample, dict):
            continue
        n_samples += 1
        speed = _as_float(sample.get("speed_kmh"))
        sample_speed_bin = _speed_bin_label(speed) if speed is not None and speed > 0 else None
        if sample_speed_bin is not None:
            total_speed_bin_counts[sample_speed_bin] += 1
        floor_amp = _as_float(sample.get("strength_floor_amp_g")) or 0.0
        location = _location_label(sample, lang=lang)
        if location:
            total_locations.add(location)
        sample_phase: str | None = None
        if per_sample_phases is not None and i < len(per_sample_phases):
            sample_phase = _phase_to_str(per_sample_phases[i])
        for hz, amp in _sample_top_peaks(sample):
            if hz <= 0 or amp <= 0:
                continue
            bin_low = floor(hz / freq_bin_hz) * freq_bin_hz
            bin_center = bin_low + (freq_bin_hz / 2.0)
            bin_amps[bin_center].append(amp)
            bin_floors[bin_center].append(max(0.0, floor_amp))
            if speed is not None and speed > 0:
                bin_speeds[bin_center].append(speed)
                bin_speed_amp_pairs[bin_center].append((speed, amp))
            if location:
                bin_location_counts[bin_center][location] += 1
            if sample_speed_bin is not None:
                bin_speed_bin_counts[bin_center][sample_speed_bin] += 1
            if sample_phase is not None:
                bin_phase_counts[bin_center][sample_phase] += 1

    if n_samples == 0:
        return []
    run_noise_baseline_g = _run_noise_baseline_g(samples)

    persistent_findings: list[tuple[float, dict[str, object]]] = []
    transient_findings: list[tuple[float, dict[str, object]]] = []

    for bin_center, amps in bin_amps.items():
        # Skip bins already claimed by order findings
        if any(abs(bin_center - of) < freq_bin_hz for of in order_finding_freqs):
            continue

        sorted_amps = sorted(amps)
        count = len(sorted_amps)
        presence_ratio = count / max(1, n_samples)
        median_amp = percentile(sorted_amps, 0.50) if count >= 2 else sorted_amps[0]
        p95_amp = percentile(sorted_amps, 0.95) if count >= 2 else sorted_amps[-1]
        max_amp = sorted_amps[-1]
        burstiness = (max_amp / median_amp) if median_amp > 1e-9 else 0.0

        mean_floor = mean(bin_floors.get(bin_center, [0.0])) if bin_floors.get(bin_center) else 0.0
        effective_floor = max(0.001, run_noise_baseline_g or mean_floor or 0.0)
        raw_snr = p95_amp / effective_floor
        spatial_uniformity: float | None = None
        if len(total_locations) >= 2:
            spatial_uniformity = len(bin_location_counts.get(bin_center, {})) / len(total_locations)

        speed_uniformity: float | None = None
        if len(total_speed_bin_counts) >= 2:
            hit_rates: list[float] = []
            per_bin_hits = bin_speed_bin_counts.get(bin_center, {})
            for speed_bin, total_count in total_speed_bin_counts.items():
                if total_count <= 0:
                    continue
                hit_rates.append(float(per_bin_hits.get(speed_bin, 0)) / float(total_count))
            if hit_rates:
                hit_rate_mean = mean(hit_rates)
                speed_uniformity = (
                    mean([(rate - hit_rate_mean) ** 2 for rate in hit_rates]) ** 0.5
                    if len(hit_rates) > 1
                    else 0.0
                )

        peak_type = _classify_peak_type(
            presence_ratio,
            burstiness,
            snr=raw_snr,
            spatial_uniformity=spatial_uniformity,
            speed_uniformity=speed_uniformity,
        )

        snr_score = min(1.0, log1p(raw_snr) / 2.5)
        location_counts = bin_location_counts.get(bin_center, {})
        spatial_concentration = (
            max(location_counts.values()) / count if location_counts and count > 0 else 1.0
        )
        spatial_penalty = (0.35 + 0.65 * spatial_concentration) if location_counts else 1.0

        # Confidence for persistent/patterned peaks (analogous to order confidence)
        peak_strength_db = vibration_strength_db_scalar(
            peak_band_rms_amp_g=p95_amp,
            floor_amp_g=effective_floor,
        )
        if peak_type == "baseline_noise":
            confidence = max(0.02, min(0.12, 0.02 + 0.05 * presence_ratio))
        elif peak_type == "transient":
            confidence = max(0.05, min(0.22, 0.05 + 0.10 * presence_ratio + 0.07 * snr_score))
        else:
            base_confidence = max(
                0.10,
                min(
                    0.75,
                    0.10
                    + 0.35 * presence_ratio
                    + 0.15 * snr_score
                    + 0.15 * min(1.0, 1.0 - burstiness / 10.0),
                ),
            )
            confidence = base_confidence * spatial_penalty
            if location_counts and spatial_concentration <= 0.35:
                confidence = min(confidence, 0.35)
            if peak_strength_db < _NEGLIGIBLE_STRENGTH_MAX_DB:
                confidence = min(confidence, 0.35)

        peak_speed_kmh, speed_window_kmh, derived_speed_band = _speed_profile_from_points(
            bin_speed_amp_pairs.get(bin_center, [])
        )
        speed_band = derived_speed_band or "-"

        evidence = _tr(
            lang,
            "EVIDENCE_PEAK_PRESENT",
            freq=bin_center,
            pct=presence_ratio,
            p95=p95_amp,
            units=accel_units,
            burst=burstiness,
            cls=peak_type,
        )

        # Compute phase evidence for this frequency bin.
        _cruise_phase_val = DrivingPhase.CRUISE.value
        phases_in_bin = bin_phase_counts.get(bin_center, {})
        _total_phase_hits = sum(phases_in_bin.values())
        _cruise_hits = phases_in_bin.get(_cruise_phase_val, 0)
        peak_phase_evidence: dict[str, object] = {
            "cruise_fraction": _cruise_hits / _total_phase_hits if _total_phase_hits > 0 else 0.0,
            "phases_detected": sorted(k for k, v in phases_in_bin.items() if v > 0),
        }
        phase_presence: dict[str, float] | None = None
        if has_phases and _total_phase_hits > 0:
            phase_presence = {
                phase_key: phase_hits / _total_phase_hits
                for phase_key, phase_hits in phases_in_bin.items()
                if phase_hits > 0
            }

        finding: dict[str, object] = {
            "finding_id": "F_PEAK",
            "finding_key": f"peak_{bin_center:.0f}hz",
            "severity": "info" if peak_type == "transient" else "diagnostic",
            "suspected_source": (
                "baseline_noise"
                if peak_type == "baseline_noise"
                else "transient_impact"
                if peak_type == "transient"
                else "unknown_resonance"
            ),
            "evidence_summary": evidence,
            "frequency_hz_or_order": f"{bin_center:.1f} Hz",
            "amplitude_metric": {
                "name": "strength_p95_band_rms_amp_g",
                "value": p95_amp,
                "units": accel_units,
                "definition": _tr(lang, "METRIC_P95_PEAK_AMPLITUDE"),
            },
            "confidence_0_to_1": confidence,
            "quick_checks": [],
            "peak_classification": peak_type,
            "phase_evidence": peak_phase_evidence,
            "evidence_metrics": {
                "presence_ratio": presence_ratio,
                "median_amplitude": median_amp,
                "p95_amplitude": p95_amp,
                "max_amplitude": max_amp,
                "burstiness": burstiness,
                "mean_noise_floor": mean_floor,
                "run_noise_baseline_g": run_noise_baseline_g,
                "median_relative_to_run_noise": median_amp / effective_floor,
                "p95_relative_to_run_noise": p95_amp / effective_floor,
                "sample_count": count,
                "total_samples": n_samples,
                "spatial_concentration": spatial_concentration,
                "spatial_uniformity": spatial_uniformity,
                "speed_uniformity": speed_uniformity,
            },
            "peak_speed_kmh": peak_speed_kmh,
            "speed_window_kmh": list(speed_window_kmh) if speed_window_kmh else None,
            "strongest_speed_band": speed_band if speed_band != "-" else None,
            "phase_presence": phase_presence,
        }

        ranking_score = (presence_ratio**2) * p95_amp
        if peak_type == "transient":
            transient_findings.append((ranking_score, finding))
        else:
            persistent_findings.append((ranking_score, finding))

    # Sort persistent findings by ranking score, take top N
    persistent_findings.sort(key=lambda item: item[0], reverse=True)
    transient_findings.sort(key=lambda item: item[0], reverse=True)

    results: list[dict[str, object]] = []
    for _score, finding in persistent_findings[:PERSISTENT_PEAK_MAX_FINDINGS]:
        results.append(finding)
    for _score, finding in transient_findings[:PERSISTENT_PEAK_MAX_FINDINGS]:
        results.append(finding)
    return results


def _build_findings(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    speed_sufficient: bool,
    steady_speed: bool,
    speed_stddev_kmh: float | None,
    speed_non_null_pct: float,
    raw_sample_rate_hz: float | None,
    lang: object = "en",
    per_sample_phases: list | None = None,
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    tire_circumference_m, _ = _tire_reference_from_metadata(metadata)
    units_obj = metadata.get("units")
    accel_units = str(units_obj.get("accel_x_g")) if isinstance(units_obj, dict) else "g"

    if not speed_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SPEED",
                suspected_source="unknown",
                evidence_summary=_tr(
                    lang,
                    "VEHICLE_SPEED_COVERAGE_IS_SPEED_NON_NULL_PCT",
                    speed_non_null_pct=speed_non_null_pct,
                    threshold=SPEED_COVERAGE_MIN_PCT,
                ),
                quick_checks=[
                    _tr(lang, "RECORD_VEHICLE_SPEED_FOR_MOST_SAMPLES_GPS_OR"),
                    _tr(lang, "VERIFY_TIMESTAMP_ALIGNMENT_BETWEEN_SPEED_AND_ACCELERATION_STREAM"),
                ],
                lang=lang,
            )
        )

    if speed_sufficient and not (tire_circumference_m and tire_circumference_m > 0):
        findings.append(
            _reference_missing_finding(
                finding_id="REF_WHEEL",
                suspected_source="wheel/tire",
                evidence_summary=_tr(
                    lang,
                    "VEHICLE_SPEED_IS_AVAILABLE_BUT_TIRE_CIRCUMFERENCE_REFERENCE",
                ),
                quick_checks=[
                    _tr(lang, "PROVIDE_TIRE_CIRCUMFERENCE_OR_TIRE_SIZE_WIDTH_ASPECT"),
                    _tr(lang, "RE_RUN_WITH_MEASURED_LOADED_TIRE_CIRCUMFERENCE"),
                ],
                lang=lang,
            )
        )

    engine_ref_count = 0
    for sample in samples:
        rpm, _ = _effective_engine_rpm(sample, metadata, tire_circumference_m)
        if rpm is not None and rpm > 0:
            engine_ref_count += 1
    engine_rpm_non_null_pct = (engine_ref_count / len(samples) * 100.0) if samples else 0.0
    engine_ref_sufficient = engine_rpm_non_null_pct >= SPEED_COVERAGE_MIN_PCT
    if not engine_ref_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_ENGINE",
                suspected_source="engine",
                evidence_summary=_tr(
                    lang,
                    "ENGINE_SPEED_REFERENCE_COVERAGE_IS_ENGINE_RPM_NON",
                    engine_rpm_non_null_pct=engine_rpm_non_null_pct,
                ),
                quick_checks=[
                    _tr(lang, "LOG_ENGINE_RPM_FROM_CAN_OBD_FOR_THE"),
                    _tr(lang, "KEEP_TIMESTAMP_BASE_SHARED_WITH_ACCELEROMETER_AND_SPEED"),
                ],
                lang=lang,
            )
        )

    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SAMPLE_RATE",
                suspected_source="unknown",
                evidence_summary=_tr(lang, "RAW_ACCELEROMETER_SAMPLE_RATE_IS_MISSING_SO_DOMINANT"),
                quick_checks=[_tr(lang, "RECORD_THE_TRUE_ACCELEROMETER_SAMPLE_RATE_IN_RUN")],
                lang=lang,
            )
        )

    # Phase-filter: exclude IDLE samples from order and persistent-peak analysis.
    # IDLE samples (engine-off / stationary) add broadband noise that dilutes
    # order-tracking evidence and inflates persistent-peak presence ratios.
    # Issues #190 and #191.
    # Use caller-supplied phases when available to avoid redundant recomputation.
    if per_sample_phases is not None and len(per_sample_phases) == len(samples):
        _per_sample_phases = per_sample_phases
    else:
        _per_sample_phases, _ = segment_run_phases(samples)
    _diagnostic_mask = diagnostic_sample_mask(_per_sample_phases)
    diagnostic_samples = [s for s, keep in zip(samples, _diagnostic_mask, strict=False) if keep]
    # Fall back to all samples if phase filtering removes too many (< 5 remaining)
    analysis_samples = diagnostic_samples if len(diagnostic_samples) >= 5 else samples
    # Compute per-sample phases aligned with analysis_samples for phase-evidence tracking.
    if analysis_samples is diagnostic_samples:
        analysis_phases: list = [
            p for p, keep in zip(_per_sample_phases, _diagnostic_mask, strict=False) if keep
        ]
    else:
        analysis_phases = list(_per_sample_phases)

    order_findings = _build_order_findings(
        metadata=metadata,
        samples=analysis_samples,
        speed_sufficient=speed_sufficient,
        steady_speed=steady_speed,
        speed_stddev_kmh=speed_stddev_kmh,
        tire_circumference_m=tire_circumference_m if speed_sufficient else None,
        engine_ref_sufficient=engine_ref_sufficient,
        raw_sample_rate_hz=raw_sample_rate_hz,
        accel_units=accel_units,
        connected_locations=_locations_connected_throughout_run(analysis_samples, lang=lang),
        lang=lang,
        per_sample_phases=analysis_phases,
    )
    findings.extend(order_findings)

    # Collect frequencies already claimed by order findings to avoid duplicates
    order_freqs: set[float] = set()
    for of in order_findings:
        pts = of.get("matched_points")
        if isinstance(pts, list):
            for pt in pts:
                if isinstance(pt, dict):
                    mhz = _as_float(pt.get("matched_hz"))
                    if mhz is not None and mhz > 0:
                        order_freqs.add(mhz)

    findings.extend(
        _build_persistent_peak_findings(
            samples=analysis_samples,  # IDLE-filtered; issue #191
            order_finding_freqs=order_freqs,
            accel_units=accel_units,
            lang=lang,
            per_sample_phases=analysis_phases,
        )
    )

    reference_findings = [
        item for item in findings if str(item.get("finding_id", "")).startswith("REF_")
    ]
    non_reference_findings = [
        item for item in findings if not str(item.get("finding_id", "")).startswith("REF_")
    ]
    informational_findings = [
        item
        for item in non_reference_findings
        if str(item.get("severity") or "").strip().lower() == "info"
    ]
    diagnostic_findings = [
        item
        for item in non_reference_findings
        if str(item.get("severity") or "").strip().lower() != "info"
    ]
    diagnostic_findings.sort(
        key=lambda item: float(item.get("confidence_0_to_1", 0.0)), reverse=True
    )
    informational_findings.sort(
        key=lambda item: float(item.get("confidence_0_to_1", 0.0)), reverse=True
    )
    findings = reference_findings + diagnostic_findings + informational_findings
    for idx, finding in enumerate(findings, start=1):
        fid = str(finding.get("finding_id", "")).strip()
        if not fid.startswith("REF_"):
            finding["finding_id"] = f"F{idx:03d}"
    return findings
