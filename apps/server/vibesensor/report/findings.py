# ruff: noqa: E501
"""Findings engine – order tracking, reference checks, and action plans."""

from __future__ import annotations

from collections import defaultdict
from math import floor, log1p
from statistics import mean
from typing import Any

from vibesensor_core.vibration_strength import _percentile

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
    _corr_abs,
    _effective_engine_rpm,
    _location_label,
    _primary_vibration_strength_db,
    _sample_top_peaks,
    _speed_bin_label,
    _speed_bin_sort_key,
    _text,
    _tire_reference_from_metadata,
)
from .order_analysis import (
    _finding_actions_for_source,
    _order_hypotheses,
    _order_label,
)
from .test_plan import _location_speedbin_summary


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
) -> list[dict[str, float | str | int]]:
    grouped_amp: dict[str, list[float]] = defaultdict(list)
    sample_counts: dict[str, int] = defaultdict(int)
    dropped_totals: dict[str, list[float]] = defaultdict(list)
    overflow_totals: dict[str, list[float]] = defaultdict(list)
    strength_bucket_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {f"l{idx}": 0 for idx in range(1, 6)}
    )
    strength_bucket_totals: dict[str, int] = defaultdict(int)
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        location = _location_label(sample)
        if not location:
            continue
        if include_locations is not None and location not in include_locations:
            continue
        sample_counts[location] += 1
        amp = _primary_vibration_strength_db(sample)
        if amp is not None:
            grouped_amp[location].append(float(amp))
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
            strength_bucket_counts[location][bucket] += 1
            strength_bucket_totals[location] += 1

    rows: list[dict[str, float | str | int]] = []
    target_locations = set(sample_counts.keys())
    if include_locations is not None:
        target_locations |= set(include_locations)

    for location in sorted(target_locations):
        values = grouped_amp.get(location, [])
        values_sorted = sorted(values)
        dropped_vals = dropped_totals.get(location, [])
        overflow_vals = overflow_totals.get(location, [])
        dropped_delta = int(max(dropped_vals) - min(dropped_vals)) if len(dropped_vals) >= 2 else 0
        overflow_delta = (
            int(max(overflow_vals) - min(overflow_vals)) if len(overflow_vals) >= 2 else 0
        )
        bucket_counts = strength_bucket_counts.get(location, {f"l{idx}": 0 for idx in range(1, 6)})
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
        rows.append(
            {
                "location": location,
                "samples": sample_count,
                "sample_count": sample_count,
                "mean_intensity_db": mean(values) if values else None,
                "p50_intensity_db": _percentile(values_sorted, 0.50) if values else None,
                "p95_intensity_db": _percentile(values_sorted, 0.95) if values else None,
                "max_intensity_db": max(values) if values else None,
                "dropped_frames_delta": dropped_delta,
                "queue_overflow_drops_delta": overflow_delta,
                "strength_bucket_distribution": bucket_distribution,
            }
        )
    rows.sort(
        key=lambda row: (
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
        "suspected_source": suspected_source,
        "evidence_summary": evidence_summary,
        "frequency_hz_or_order": _tr(lang, "REFERENCE_MISSING"),
        "amplitude_metric": {
            "name": "not_available",
            "value": None,
            "units": "n/a",
            "definition": _tr(lang, "REFERENCE_MISSING_ORDER_SPECIFIC_AMPLITUDE_RANKING_SKIPPED"),
        },
        "confidence_0_to_1": 1.0,
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
    lang: object,
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

        for sample in samples:
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

            tolerance_hz = max(ORDER_TOLERANCE_MIN_HZ, predicted_hz * ORDER_TOLERANCE_REL)
            best_hz, best_amp = min(peaks, key=lambda item: abs(item[0] - predicted_hz))
            delta_hz = abs(best_hz - predicted_hz)
            if delta_hz > tolerance_hz:
                continue

            matched += 1
            rel_errors.append(delta_hz / max(1e-9, predicted_hz))
            matched_amp.append(best_amp)
            floor_amp = _as_float(sample.get("strength_floor_amp_g")) or 0.0
            matched_floor.append(max(0.0, floor_amp))
            predicted_vals.append(predicted_hz)
            measured_vals.append(best_hz)
            matched_points.append(
                {
                    "t_s": _as_float(sample.get("t_s")),
                    "speed_kmh": _as_float(sample.get("speed_kmh")),
                    "predicted_hz": predicted_hz,
                    "matched_hz": best_hz,
                    "amp": best_amp,
                    "location": _location_label(sample),
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
        if match_rate < min_match_rate:
            continue

        mean_amp = mean(matched_amp) if matched_amp else 0.0
        mean_floor = mean(matched_floor) if matched_floor else 0.0
        mean_rel_err = mean(rel_errors) if rel_errors else 1.0
        corr = _corr_abs(predicted_vals, measured_vals) if len(matched_points) >= 3 else None
        # When speed is constant, predicted Hz never varies so correlation
        # is degenerate (undefined or misleading).  Zero it out.
        if constant_speed:
            corr = None
        corr_val = corr if corr is not None else 0.0

        error_score = max(0.0, 1.0 - min(1.0, mean_rel_err / 0.25))
        snr_score = min(1.0, log1p(mean_amp / max(1e-6, mean_floor)) / 2.5)
        confidence = (
            0.20
            + (0.35 * match_rate)
            + (0.20 * error_score)
            + (0.15 * corr_val)
            + (0.10 * snr_score)
        )
        if steady_speed:
            confidence *= 0.88
        confidence = max(0.08, min(0.97, confidence))

        ranking_score = (
            match_rate
            * log1p(mean_amp / max(1e-6, mean_floor))
            * max(0.0, (1.0 - min(1.0, mean_rel_err / 0.5)))
        )

        location_line, location_hotspot = _location_speedbin_summary(matched_points, lang=lang)
        ref_text = ", ".join(sorted(ref_sources))
        evidence = _text(
            lang,
            (
                "{order_label} tracked over {matched}/{possible} samples "
                "(match rate {match_rate:.0%}, mean relative error {mean_rel_err:.3f}, "
                "reference {ref_text})."
            ),
            (
                "{order_label} gevolgd over {matched}/{possible} samples "
                "(trefferratio {match_rate:.0%}, gemiddelde relatieve fout {mean_rel_err:.3f}, "
                "referentie {ref_text})."
            ),
        ).format(
            order_label=_order_label(lang, hypothesis.order, hypothesis.order_label_base),
            matched=matched,
            possible=possible,
            match_rate=match_rate,
            mean_rel_err=mean_rel_err,
            ref_text=ref_text,
        )
        if location_line:
            evidence = f"{evidence} {location_line}"

        strongest_location = (
            str(location_hotspot.get("location")) if isinstance(location_hotspot, dict) else ""
        )
        strongest_speed_band = (
            str(location_hotspot.get("speed_range")) if isinstance(location_hotspot, dict) else ""
        )
        weak_spatial_separation = (
            bool(location_hotspot.get("weak_spatial_separation"))
            if isinstance(location_hotspot, dict)
            else True
        )
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
                "definition": _text(
                    lang,
                    "Mean matched peak amplitude from the combined FFT spectrum.",
                    "Gemiddelde gematchte piekamplitude uit het gecombineerde FFT-spectrum.",
                ),
            },
            "confidence_0_to_1": confidence,
            "quick_checks": quick_checks,
            "matched_points": matched_points,
            "location_hotspot": location_hotspot,
            "strongest_location": strongest_location or None,
            "strongest_speed_band": strongest_speed_band or None,
            "dominance_ratio": (
                float(location_hotspot.get("dominance_ratio"))
                if isinstance(location_hotspot, dict)
                else None
            ),
            "weak_spatial_separation": weak_spatial_separation,
            "evidence_metrics": {
                "match_rate": match_rate,
                "mean_relative_error": mean_rel_err,
                "mean_matched_amplitude": mean_amp,
                "mean_noise_floor": mean_floor,
                "possible_samples": possible,
                "matched_samples": matched,
                "frequency_correlation": corr,
            },
            "next_sensor_move": _text(
                lang,
                str(actions[0].get("what") or "Inspect the highest-ranked hotspot path first."),
                str(actions[0].get("what") or "Controleer eerst het hoogste hotspot-pad."),
            ),
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


def _classify_peak_type(
    presence_ratio: float,
    burstiness: float,
) -> str:
    """Classify a frequency peak as ``patterned``, ``persistent``, or ``transient``.

    * **patterned**: high presence and low burstiness → likely a fault vibration.
    * **persistent**: moderate presence → unknown but repeated resonance.
    * **transient**: low presence or very high burstiness → one-off impact/thud.
    """
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
) -> list[dict[str, object]]:
    """Build findings for non-order persistent frequency peaks.

    Uses the same confidence-style scoring as order findings (presence_ratio,
    error/SNR) so the report is consistent.  Peaks already claimed by order
    findings are excluded.  Transient peaks are returned separately.
    """
    if freq_bin_hz <= 0:
        freq_bin_hz = 2.0

    bin_amps: dict[float, list[float]] = defaultdict(list)
    bin_floors: dict[float, list[float]] = defaultdict(list)
    bin_speeds: dict[float, list[float]] = defaultdict(list)
    n_samples = 0

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        n_samples += 1
        speed = _as_float(sample.get("speed_kmh"))
        floor_amp = _as_float(sample.get("strength_floor_amp_g")) or 0.0
        for hz, amp in _sample_top_peaks(sample):
            if hz <= 0 or amp <= 0:
                continue
            bin_low = floor(hz / freq_bin_hz) * freq_bin_hz
            bin_center = bin_low + (freq_bin_hz / 2.0)
            bin_amps[bin_center].append(amp)
            bin_floors[bin_center].append(max(0.0, floor_amp))
            if speed is not None and speed > 0:
                bin_speeds[bin_center].append(speed)

    if n_samples == 0:
        return []

    persistent_findings: list[tuple[float, dict[str, object]]] = []
    transient_findings: list[tuple[float, dict[str, object]]] = []

    for bin_center, amps in bin_amps.items():
        # Skip bins already claimed by order findings
        if any(abs(bin_center - of) < freq_bin_hz for of in order_finding_freqs):
            continue

        sorted_amps = sorted(amps)
        count = len(sorted_amps)
        presence_ratio = count / max(1, n_samples)
        median_amp = _percentile(sorted_amps, 0.50) if count >= 2 else sorted_amps[0]
        p95_amp = _percentile(sorted_amps, 0.95) if count >= 2 else sorted_amps[-1]
        max_amp = sorted_amps[-1]
        burstiness = (max_amp / median_amp) if median_amp > 1e-9 else 0.0

        peak_type = _classify_peak_type(presence_ratio, burstiness)

        mean_floor = mean(bin_floors.get(bin_center, [0.0])) if bin_floors.get(bin_center) else 0.0
        snr_score = min(1.0, log1p(p95_amp / max(1e-6, mean_floor)) / 2.5)

        # Confidence for persistent/patterned peaks (analogous to order confidence)
        if peak_type == "transient":
            confidence = max(0.05, min(0.22, 0.05 + 0.10 * presence_ratio + 0.07 * snr_score))
        else:
            confidence = max(
                0.10,
                min(
                    0.75,
                    0.10
                    + 0.35 * presence_ratio
                    + 0.15 * snr_score
                    + 0.15 * min(1.0, 1.0 - burstiness / 10.0),
                ),
            )

        speeds = bin_speeds.get(bin_center, [])
        speed_band = "-"
        if speeds:
            speed_band = f"{min(speeds):.0f}-{max(speeds):.0f} km/h"

        evidence = _text(
            lang,
            (
                "{freq:.1f} Hz peak present in {pct:.0%} of samples "
                "(p95 amplitude {p95:.4f} {units}, burstiness {burst:.1f}×, "
                "classification: {cls})."
            ),
            (
                "{freq:.1f} Hz piek aanwezig in {pct:.0%} van de samples "
                "(p95 amplitude {p95:.4f} {units}, burstigheid {burst:.1f}×, "
                "classificatie: {cls})."
            ),
        ).format(
            freq=bin_center,
            pct=presence_ratio,
            p95=p95_amp,
            units=accel_units,
            burst=burstiness,
            cls=peak_type,
        )

        finding: dict[str, object] = {
            "finding_id": "F_PEAK",
            "finding_key": f"peak_{bin_center:.0f}hz",
            "suspected_source": "unknown_resonance"
            if peak_type != "transient"
            else "transient_impact",
            "evidence_summary": evidence,
            "frequency_hz_or_order": f"{bin_center:.1f} Hz",
            "amplitude_metric": {
                "name": "strength_p95_band_rms_amp_g",
                "value": p95_amp,
                "units": accel_units,
                "definition": _text(
                    lang,
                    "p95 peak amplitude across matched samples.",
                    "p95 piekamplitude over gematchte samples.",
                ),
            },
            "confidence_0_to_1": confidence,
            "quick_checks": [],
            "peak_classification": peak_type,
            "evidence_metrics": {
                "presence_ratio": presence_ratio,
                "median_amplitude": median_amp,
                "p95_amplitude": p95_amp,
                "max_amplitude": max_amp,
                "burstiness": burstiness,
                "mean_noise_floor": mean_floor,
                "sample_count": count,
                "total_samples": n_samples,
            },
            "strongest_speed_band": speed_band if speed_band != "-" else None,
        }

        ranking_score = presence_ratio * p95_amp
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

    order_findings = _build_order_findings(
        metadata=metadata,
        samples=samples,
        speed_sufficient=speed_sufficient,
        steady_speed=steady_speed,
        speed_stddev_kmh=speed_stddev_kmh,
        tire_circumference_m=tire_circumference_m if speed_sufficient else None,
        engine_ref_sufficient=engine_ref_sufficient,
        raw_sample_rate_hz=raw_sample_rate_hz,
        accel_units=accel_units,
        lang=lang,
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
            samples=samples,
            order_finding_freqs=order_freqs,
            accel_units=accel_units,
            lang=lang,
        )
    )

    findings.sort(key=lambda item: float(item.get("confidence_0_to_1", 0.0)), reverse=True)
    for idx, finding in enumerate(findings, start=1):
        fid = str(finding.get("finding_id", "")).strip()
        if not fid.startswith("REF_"):
            finding["finding_id"] = f"F{idx:03d}"
    return findings
