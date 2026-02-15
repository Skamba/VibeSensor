from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil, floor, log1p, sqrt
from pathlib import Path
from statistics import mean
from typing import Any

from .analysis_settings import tire_circumference_m_from_spec
from .report_i18n import tr as _tr
from .runlog import parse_iso8601, read_jsonl_run

SPEED_BIN_WIDTH_KMH = 10
SPEED_COVERAGE_MIN_PCT = 35.0
SPEED_MIN_POINTS = 8

ORDER_TOLERANCE_REL = 0.08
ORDER_TOLERANCE_MIN_HZ = 0.5
ORDER_MIN_MATCH_POINTS = 4
ORDER_MIN_COVERAGE_POINTS = 6


def _normalize_lang(lang: object) -> str:
    if isinstance(lang, str) and lang.strip().lower().startswith("nl"):
        return "nl"
    return "en"


def _as_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _format_duration(seconds: float) -> str:
    total = max(0.0, float(seconds))
    minutes = int(total // 60)
    rem = total - (minutes * 60)
    return f"{minutes:02d}:{rem:04.1f}"


def _required_text(value: object, consequence: str, lang: object = "en") -> str:
    if value in (None, "", []):
        return _tr(lang, "MISSING_CONSEQUENCE", consequence=consequence)
    return str(value)


def _text(lang: object, en_text: str, nl_text: str) -> str:
    return nl_text if _normalize_lang(lang) == "nl" else en_text


def _percent_missing(samples: list[dict[str, Any]], key: str) -> float:
    if not samples:
        return 100.0
    missing = sum(1 for sample in samples if sample.get(key) in (None, ""))
    return (missing / len(samples)) * 100.0


def _mean_variance(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    m = mean(values)
    var = sum((v - m) ** 2 for v in values) / len(values)
    return m, var


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = max(0.0, min(1.0, q)) * (len(sorted_values) - 1)
    lo = floor(pos)
    hi = ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] + ((sorted_values[hi] - sorted_values[lo]) * frac)


def _outlier_summary(values: list[float]) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "outlier_count": 0,
            "outlier_pct": 0.0,
            "lower_bound": None,
            "upper_bound": None,
        }
    sorted_vals = sorted(values)
    q1 = _percentile(sorted_vals, 0.25)
    q3 = _percentile(sorted_vals, 0.75)
    iqr = max(0.0, q3 - q1)
    low = q1 - (1.5 * iqr)
    high = q3 + (1.5 * iqr)
    outliers = [v for v in sorted_vals if v < low or v > high]
    return {
        "count": len(sorted_vals),
        "outlier_count": len(outliers),
        "outlier_pct": (len(outliers) / len(sorted_vals)) * 100.0,
        "lower_bound": low,
        "upper_bound": high,
    }


def _speed_bin_label(kmh: float) -> str:
    low = int(kmh // SPEED_BIN_WIDTH_KMH) * SPEED_BIN_WIDTH_KMH
    high = low + SPEED_BIN_WIDTH_KMH
    return f"{low}-{high} km/h"


def _speed_bin_sort_key(label: str) -> int:
    head = label.split(" ", 1)[0]
    low_text = head.split("-", 1)[0]
    try:
        return int(low_text)
    except ValueError:
        return 0


def _sensor_limit_g(sensor_model: object) -> float | None:
    if not isinstance(sensor_model, str):
        return None
    if "adxl345" in sensor_model.lower():
        return 16.0
    return None


def _tire_reference_from_metadata(metadata: dict[str, Any]) -> tuple[float | None, str | None]:
    direct = _as_float(metadata.get("tire_circumference_m"))
    if direct is not None and direct > 0:
        return direct, "metadata.tire_circumference_m"

    derived = tire_circumference_m_from_spec(
        _as_float(metadata.get("tire_width_mm")),
        _as_float(metadata.get("tire_aspect_pct")),
        _as_float(metadata.get("rim_in")),
    )
    if derived is not None and derived > 0:
        return derived, "derived_from_tire_dimensions"
    return None, None


def _effective_engine_rpm(
    sample: dict[str, Any],
    metadata: dict[str, Any],
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    measured = _as_float(sample.get("engine_rpm"))
    if measured is not None and measured > 0:
        return measured, str(sample.get("engine_rpm_source") or "measured")

    estimated_in_sample = _as_float(sample.get("engine_rpm_estimated"))
    if estimated_in_sample is not None and estimated_in_sample > 0:
        return estimated_in_sample, "estimated_from_speed_and_ratios"

    speed_kmh = _as_float(sample.get("speed_kmh"))
    final_drive_ratio = _as_float(sample.get("final_drive_ratio")) or _as_float(
        metadata.get("final_drive_ratio")
    )
    gear_ratio = _as_float(sample.get("gear")) or _as_float(metadata.get("current_gear_ratio"))
    if (
        speed_kmh is None
        or speed_kmh <= 0
        or tire_circumference_m is None
        or tire_circumference_m <= 0
        or final_drive_ratio is None
        or final_drive_ratio <= 0
        or gear_ratio is None
        or gear_ratio <= 0
    ):
        return None, "missing"

    wheel_hz = (speed_kmh / 3.6) / tire_circumference_m
    return wheel_hz * final_drive_ratio * gear_ratio * 60.0, "estimated_from_speed_and_ratios"


def _load_run(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".jsonl":
        raise ValueError(f"Unsupported run format for report: {path.name}")
    run_data = read_jsonl_run(path)
    return dict(run_data.metadata), list(run_data.samples), []


def _primary_vibration_amp(sample: dict[str, Any]) -> float | None:
    return (
        _as_float(sample.get("vib_mag_rms_g"))
        or _as_float(sample.get("accel_magnitude_rms_g"))
        or _as_float(sample.get("dominant_peak_amp_g"))
    )


def _speed_breakdown(samples: list[dict[str, Any]]) -> list[dict[str, object]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for sample in samples:
        speed = _as_float(sample.get("speed_kmh"))
        if speed is None or speed <= 0:
            continue
        label = _speed_bin_label(speed)
        counts[label] += 1
        amp = _primary_vibration_amp(sample)
        if amp is not None:
            grouped[label].append(amp)

    rows: list[dict[str, object]] = []
    for label in sorted(counts.keys(), key=_speed_bin_sort_key):
        values = grouped.get(label, [])
        rows.append(
            {
                "speed_range": label,
                "count": counts[label],
                "mean_amplitude_g": mean(values) if values else None,
                "max_amplitude_g": max(values) if values else None,
            }
        )
    return rows


def _corr_abs(x_vals: list[float], y_vals: list[float]) -> float | None:
    if len(x_vals) != len(y_vals) or len(x_vals) < 3:
        return None
    mx = mean(x_vals)
    my = mean(y_vals)
    cov = sum((x - mx) * (y - my) for x, y in zip(x_vals, y_vals, strict=False))
    sx = sqrt(sum((x - mx) ** 2 for x in x_vals))
    sy = sqrt(sum((y - my) ** 2 for y in y_vals))
    if sx <= 1e-9 or sy <= 1e-9:
        return None
    return abs(cov / (sx * sy))


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


def _sample_top_peaks(sample: dict[str, Any]) -> list[tuple[float, float]]:
    top_peaks = sample.get("top_peaks")
    out: list[tuple[float, float]] = []
    if isinstance(top_peaks, list):
        for peak in top_peaks[:8]:
            if not isinstance(peak, dict):
                continue
            hz = _as_float(peak.get("hz"))
            amp = _as_float(peak.get("amp"))
            if hz is None or amp is None or hz <= 0:
                continue
            out.append((hz, amp))
    if out:
        return out
    dom_hz = _as_float(sample.get("dominant_freq_hz"))
    dom_amp = _as_float(sample.get("dominant_peak_amp_g"))
    if dom_hz is not None and dom_hz > 0 and dom_amp is not None:
        return [(dom_hz, dom_amp)]
    return []


def _location_label(sample: dict[str, Any]) -> str:
    client_name_raw = str(sample.get("client_name") or "").strip()
    if client_name_raw:
        return client_name_raw
    client_id_raw = str(sample.get("client_id") or "").strip()
    if client_id_raw:
        return f"Sensor {client_id_raw[-4:]}"
    return "Unlabeled sensor"


def _wheel_hz(sample: dict[str, Any], tire_circumference_m: float | None) -> float | None:
    speed_kmh = _as_float(sample.get("speed_kmh"))
    if speed_kmh is None or speed_kmh <= 0:
        return None
    if tire_circumference_m is None or tire_circumference_m <= 0:
        return None
    return (speed_kmh / 3.6) / tire_circumference_m


def _driveshaft_hz(
    sample: dict[str, Any],
    metadata: dict[str, Any],
    tire_circumference_m: float | None,
) -> float | None:
    whz = _wheel_hz(sample, tire_circumference_m)
    fd = _as_float(sample.get("final_drive_ratio")) or _as_float(metadata.get("final_drive_ratio"))
    if whz is None or fd is None or fd <= 0:
        return None
    return whz * fd


def _engine_hz(
    sample: dict[str, Any],
    metadata: dict[str, Any],
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    rpm, src = _effective_engine_rpm(sample, metadata, tire_circumference_m)
    if rpm is None or rpm <= 0:
        return None, src
    return rpm / 60.0, src


def _order_label(lang: object, order: int, base: str) -> str:
    if _normalize_lang(lang) == "nl":
        names = {"wheel": "wielorde", "engine": "motororde", "driveshaft": "aandrijfasorde"}
    else:
        names = {"wheel": "wheel order", "engine": "engine order", "driveshaft": "driveshaft order"}
    return f"{order}x {names.get(base, base)}"


@dataclass(slots=True)
class _OrderHypothesis:
    key: str
    suspected_source: str
    order_label_base: str
    order: int

    def predicted_hz(
        self,
        sample: dict[str, Any],
        metadata: dict[str, Any],
        tire_circumference_m: float | None,
    ) -> tuple[float | None, str]:
        if self.key.startswith("wheel_"):
            base = _wheel_hz(sample, tire_circumference_m)
            return (base * self.order, "speed+tire") if base is not None else (None, "missing")
        if self.key.startswith("driveshaft_"):
            base = _driveshaft_hz(sample, metadata, tire_circumference_m)
            if base is None:
                return None, "missing"
            return base * self.order, "speed+tire+final_drive"
        if self.key.startswith("engine_"):
            base, src = _engine_hz(sample, metadata, tire_circumference_m)
            return (base * self.order, src) if base is not None else (None, "missing")
        return None, "missing"


def _order_hypotheses() -> list[_OrderHypothesis]:
    return [
        _OrderHypothesis("wheel_1x", "wheel/tire", "wheel", 1),
        _OrderHypothesis("wheel_2x", "wheel/tire", "wheel", 2),
        _OrderHypothesis("driveshaft_1x", "driveline", "driveshaft", 1),
        _OrderHypothesis("engine_1x", "engine", "engine", 1),
        _OrderHypothesis("engine_2x", "engine", "engine", 2),
    ]


def _quick_checks_for_source(lang: object, source: str) -> list[str]:
    if source == "wheel/tire":
        return [
            _tr(lang, "SWAP_FRONT_REAR_WHEEL_POSITIONS_AND_REPEAT_THE"),
            _tr(lang, "INSPECT_WHEEL_BALANCE_AND_RADIAL_LATERAL_RUNOUT"),
            _tr(lang, "CHECK_DRIVESHAFT_RUNOUT_AND_JOINT_CONDITION_FOR_HIGHER"),
        ]
    if source == "driveline":
        return [
            _tr(lang, "CHECK_DRIVESHAFT_RUNOUT_AND_JOINT_CONDITION_FOR_HIGHER"),
            _tr(lang, "REPEAT_RUN_WITH_STABLE_ROUTE_AND_VERIFY_PEAK"),
            _tr(lang, "CROSS_CHECK_WITH_A_SECOND_SENSOR_LOCATION_TO"),
        ]
    if source == "engine":
        return [
            _tr(lang, "HOLD_ENGINE_AT_THE_SAME_RPM_IN_NEUTRAL"),
            _tr(lang, "INSPECT_ENGINE_MOUNTS_AND_ACCESSORY_DRIVE"),
            _tr(lang, "COMPARE_UNDER_LOAD_VS_NO_LOAD_AT_MATCHED"),
        ]
    return [
        _tr(lang, "REPEAT_RUN_WITH_STABLE_ROUTE_AND_VERIFY_PEAK"),
        _tr(lang, "CROSS_CHECK_WITH_A_SECOND_SENSOR_LOCATION_TO"),
    ]


def _location_speedbin_summary(
    matches: list[dict[str, object]],
    lang: object,
) -> tuple[str, dict[str, object] | None]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in matches:
        speed = _as_float(row.get("speed_kmh"))
        amp = _as_float(row.get("amp"))
        location = str(row.get("location") or "").strip()
        if speed is None or speed <= 0 or amp is None or amp <= 0 or not location:
            continue
        grouped[_speed_bin_label(speed)][location].append(amp)

    if not grouped:
        return "", None

    best: dict[str, object] | None = None
    for bin_label, per_loc in grouped.items():
        ranked = sorted(
            ((loc, mean(vals)) for loc, vals in per_loc.items() if vals),
            key=lambda item: item[1],
            reverse=True,
        )
        if not ranked:
            continue
        top_loc, top_amp = ranked[0]
        second_amp = ranked[1][1] if len(ranked) > 1 else top_amp
        dominance = (top_amp / second_amp) if second_amp > 0 else 1.0
        candidate = {
            "speed_range": bin_label,
            "location": top_loc,
            "mean_amp": top_amp,
            "dominance_ratio": dominance,
            "location_count": len(ranked),
        }
        if best is None or float(candidate["mean_amp"]) > float(best["mean_amp"]):
            best = candidate

    if best is None:
        return "", None

    sentence = _text(
        lang,
        (
            "Strongest at {location} in {speed_range} "
            "(~{dominance:.2f}x vs next location in that speed bin)."
        ),
        (
            "Sterkst bij {location} in {speed_range} "
            "(~{dominance:.2f}x t.o.v. volgende locatie in die snelheidsband)."
        ),
    ).format(
        location=best["location"],
        speed_range=best["speed_range"],
        dominance=float(best["dominance_ratio"]),
    )
    return sentence, best


def _build_order_findings(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    speed_sufficient: bool,
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
            floor_amp = _as_float(sample.get("noise_floor_amp")) or 0.0
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
        if match_rate < 0.25:
            continue

        mean_amp = mean(matched_amp) if matched_amp else 0.0
        mean_floor = mean(matched_floor) if matched_floor else 0.0
        mean_rel_err = mean(rel_errors) if rel_errors else 1.0
        corr = _corr_abs(predicted_vals, measured_vals) if len(matched_points) >= 3 else None
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

        finding = {
            "finding_id": "F_ORDER",
            "suspected_source": hypothesis.suspected_source,
            "evidence_summary": evidence,
            "frequency_hz_or_order": _order_label(
                lang, hypothesis.order, hypothesis.order_label_base
            ),
            "amplitude_metric": {
                "name": "dominant_peak_amp_g",
                "value": mean_amp,
                "units": accel_units,
                "definition": _text(
                    lang,
                    "Mean matched peak amplitude from the combined FFT spectrum.",
                    "Gemiddelde gematchte piekamplitude uit het gecombineerde FFT-spectrum.",
                ),
            },
            "confidence_0_to_1": confidence,
            "quick_checks": _quick_checks_for_source(lang, hypothesis.suspected_source),
            "matched_points": matched_points,
            "location_hotspot": location_hotspot,
        }
        findings.append((ranking_score, finding))

    findings.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in findings[:3]]


def _build_findings(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    speed_sufficient: bool,
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

    findings.extend(
        _build_order_findings(
            metadata=metadata,
            samples=samples,
            speed_sufficient=speed_sufficient,
            tire_circumference_m=tire_circumference_m if speed_sufficient else None,
            engine_ref_sufficient=engine_ref_sufficient,
            raw_sample_rate_hz=raw_sample_rate_hz,
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


def _plot_data(summary: dict[str, Any]) -> dict[str, Any]:
    samples: list[dict[str, Any]] = summary.get("samples", [])
    raw_sample_rate_hz = _as_float(summary.get("raw_sample_rate_hz"))
    vib_mag_points: list[tuple[float, float]] = []
    dominant_freq_points: list[tuple[float, float]] = []
    speed_amp_points: list[tuple[float, float]] = []
    matched_by_finding: list[dict[str, object]] = []

    for sample in samples:
        t_s = _as_float(sample.get("t_s"))
        if t_s is None:
            continue
        vib = _primary_vibration_amp(sample)
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

    return {
        "vib_magnitude": vib_mag_points,
        "dominant_freq": dominant_freq_points,
        "amp_vs_speed": speed_amp_points,
        "matched_amp_vs_speed": matched_by_finding,
    }


def build_findings_for_samples(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
) -> list[dict[str, object]]:
    language = _normalize_lang(lang)
    rows = list(samples) if isinstance(samples, list) else []
    speed_values = [
        speed
        for speed in (_as_float(sample.get("speed_kmh")) for sample in rows)
        if speed is not None and speed > 0
    ]
    speed_non_null_pct = (len(speed_values) / len(rows) * 100.0) if rows else 0.0
    speed_sufficient = (
        speed_non_null_pct >= SPEED_COVERAGE_MIN_PCT and len(speed_values) >= SPEED_MIN_POINTS
    )
    raw_sample_rate_hz = _as_float(metadata.get("raw_sample_rate_hz"))
    return _build_findings(
        metadata=dict(metadata),
        samples=rows,
        speed_sufficient=speed_sufficient,
        speed_non_null_pct=speed_non_null_pct,
        raw_sample_rate_hz=raw_sample_rate_hz,
        lang=language,
    )


def summarize_log(log_path: Path, lang: str | None = None) -> dict[str, object]:
    language = _normalize_lang(lang)
    metadata, samples, warnings = _load_run(log_path)

    run_id = str(metadata.get("run_id") or f"run-{log_path.stem}")
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
        value for value in (_primary_vibration_amp(sample) for sample in samples) if value
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
        speed_non_null_pct=speed_non_null_pct,
        raw_sample_rate_hz=raw_sample_rate_hz,
        lang=language,
    )

    summary: dict[str, Any] = {
        "file_name": log_path.name,
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
        "warnings": warnings,
        "speed_breakdown": speed_breakdown,
        "speed_breakdown_skipped_reason": speed_breakdown_skipped_reason,
        "findings": findings,
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
    return summary
