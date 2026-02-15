from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from io import BytesIO
from math import ceil, floor, sqrt
from pathlib import Path
from statistics import mean
from typing import Any

from .analysis_settings import tire_circumference_m_from_spec
from .report_i18n import tr as _tr
from .report_i18n import variants as _tr_variants
from .runlog import parse_iso8601, read_jsonl_run

SPEED_BIN_WIDTH_KMH = 10
SPEED_COVERAGE_MIN_PCT = 35.0
SPEED_MIN_POINTS = 8


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
    model = sensor_model.lower()
    if "adxl345" in model:
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


def _speed_breakdown(samples: list[dict[str, Any]]) -> list[dict[str, object]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for sample in samples:
        speed = _as_float(sample.get("speed_kmh"))
        if speed is None or speed <= 0:
            continue
        label = _speed_bin_label(speed)
        counts[label] += 1
        amp = _as_float(sample.get("accel_magnitude_rms_g"))
        if amp is None:
            amp = _as_float(sample.get("dominant_peak_amp_g"))
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
    falsifiers: list[str],
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
        "falsifiers": falsifiers[:3],
    }


def _dominant_cluster_finding(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    speed_sufficient: bool,
    tire_circumference_m: float | None,
    tire_reference_label: str | None,
    engine_ref_sufficient: bool,
    raw_sample_rate_hz: float | None,
    lang: object = "en",
) -> dict[str, object] | None:
    PeakPoint = tuple[float, float | None, float | None, float | None, str, str | None, str | None]
    freq_points: list[PeakPoint] = []
    for sample in samples:
        hz = _as_float(sample.get("dominant_freq_hz"))
        if hz is None or hz <= 0:
            continue
        amp = _as_float(sample.get("dominant_peak_amp_g"))
        speed = _as_float(sample.get("speed_kmh"))
        rpm, rpm_source = _effective_engine_rpm(sample, metadata, tire_circumference_m)
        client_name_raw = str(sample.get("client_name") or "").strip()
        client_name = client_name_raw if client_name_raw else None
        client_id_raw = str(sample.get("client_id") or "").strip()
        client_id = client_id_raw if client_id_raw else None
        freq_points.append((hz, amp, speed, rpm, rpm_source, client_name, client_id))
    if not freq_points:
        return None

    freq_bin_hz = 0.5
    clusters: dict[float, list[PeakPoint]] = defaultdict(list)
    for point in freq_points:
        key = round(point[0] / freq_bin_hz) * freq_bin_hz
        clusters[key].append(point)
    dominant_cluster = max(
        clusters.values(),
        key=lambda cluster: (
            len(cluster),
            mean([p[1] for p in cluster if p[1] is not None])
            if any(p[1] is not None for p in cluster)
            else 0,
        ),
    )

    freq_values = [p[0] for p in dominant_cluster]
    amp_values = [p[1] for p in dominant_cluster if p[1] is not None]
    center_hz = mean(freq_values)
    amp_mean = mean(amp_values) if amp_values else None

    suspected_source = "unknown"
    evidence = _tr(
        lang,
        "DOMINANT_FREQUENCY_CLUSTER_NEAR_CENTER_HZ_2F_HZ",
        center_hz=center_hz,
        count=len(dominant_cluster),
    )
    freq_or_order = f"{center_hz:.2f} Hz" if raw_sample_rate_hz else _tr(lang, "REFERENCE_MISSING")
    quick_checks = [
        _tr(lang, "REPEAT_RUN_WITH_STABLE_ROUTE_AND_VERIFY_PEAK"),
        _tr(lang, "CROSS_CHECK_WITH_A_SECOND_SENSOR_LOCATION_TO"),
    ]
    falsifiers = [
        _tr(lang, "PEAK_DISAPPEARS_AFTER_SENSOR_REMOUNT_OR_CABLE_RESEAT"),
        _tr(lang, "PEAK_FREQUENCY_SHIFTS_RANDOMLY_WITH_NO_REPEATABLE_OPERATING"),
    ]
    reference_bonus = 0.0

    if speed_sufficient and tire_circumference_m and tire_circumference_m > 0:
        matched: dict[int, list[float]] = {1: [], 2: [], 3: []}
        for hz, _amp, speed_kmh, _rpm, _rpm_source, _client_name, _client_id in dominant_cluster:
            if speed_kmh is None or speed_kmh <= 0:
                continue
            wheel_hz = (speed_kmh / 3.6) / tire_circumference_m
            if wheel_hz <= 0:
                continue
            ratio = hz / wheel_hz
            for order in (1, 2, 3):
                matched[order].append(abs(ratio - order))
        order_errors = {
            order: mean(values) for order, values in matched.items() if len(values) >= 4
        }
        if order_errors:
            best_order = min(order_errors.keys(), key=lambda order: order_errors[order])
            best_error = order_errors[best_order]
            if best_error <= 0.18:
                suspected_source = "wheel/tire" if best_order == 1 else "driveline"
                tire_ref_note = (
                    _tr(lang, "MEASURED_TIRE_CIRCUMFERENCE")
                    if tire_reference_label == "metadata.tire_circumference_m"
                    else _tr(lang, "TIRE_SIZE")
                )
                evidence = _tr(
                    lang,
                    "FREQUENCY_TRACKS_WHEEL_ORDER_USING_VEHICLE_SPEED_AND",
                    tire_ref_note=tire_ref_note,
                    best_order=best_order,
                    best_error=best_error,
                )
                freq_or_order = _tr(lang, "BEST_ORDER_X_WHEEL_ORDER", best_order=best_order)
                quick_checks = [
                    _tr(lang, "SWAP_FRONT_REAR_WHEEL_POSITIONS_AND_REPEAT_THE"),
                    _tr(lang, "INSPECT_WHEEL_BALANCE_AND_RADIAL_LATERAL_RUNOUT"),
                    _tr(lang, "CHECK_DRIVESHAFT_RUNOUT_AND_JOINT_CONDITION_FOR_HIGHER"),
                ]
                falsifiers = [
                    _tr(lang, "ORDER_MATCH_DEGRADES_WHEN_USING_MEASURED_TIRE_CIRCUMFERENCE"),
                    _tr(lang, "PEAK_DOES_NOT_SCALE_WITH_VEHICLE_SPEED_ACROSS"),
                ]
                reference_bonus = 0.18

    if suspected_source == "unknown" and engine_ref_sufficient:
        order_errors: dict[int, list[float]] = {1: [], 2: [], 3: []}
        rpm_sources_used: set[str] = set()
        for hz, _amp, _speed_kmh, rpm, rpm_source, _client_name, _client_id in dominant_cluster:
            if rpm is None or rpm <= 0:
                continue
            rpm_sources_used.add(rpm_source)
            engine_hz = rpm / 60.0
            if engine_hz <= 0:
                continue
            ratio = hz / engine_hz
            for order in (1, 2, 3):
                order_errors[order].append(abs(ratio - order))
        valid = {order: mean(vals) for order, vals in order_errors.items() if len(vals) >= 4}
        if valid:
            best_order = min(valid.keys(), key=lambda order: valid[order])
            best_error = valid[best_order]
            if best_error <= 0.18:
                suspected_source = "engine"
                ref_label = (
                    _tr(lang, "MEASURED_ENGINE_RPM")
                    if rpm_sources_used == {"measured"}
                    else _tr(lang, "ENGINE_RPM_ESTIMATED_FROM_VEHICLE_SPEED_AND_DRIVETRAIN")
                )
                evidence = _tr(
                    lang,
                    "FREQUENCY_TRACKS_ENGINE_ORDER_USING_REF_LABEL_BEST",
                    ref_label=ref_label,
                    best_order=best_order,
                    best_error=best_error,
                )
                freq_or_order = _tr(lang, "BEST_ORDER_X_ENGINE_ORDER", best_order=best_order)
                quick_checks = [
                    _tr(lang, "HOLD_ENGINE_AT_THE_SAME_RPM_IN_NEUTRAL"),
                    _tr(lang, "INSPECT_ENGINE_MOUNTS_AND_ACCESSORY_DRIVE"),
                    _tr(lang, "COMPARE_UNDER_LOAD_VS_NO_LOAD_AT_MATCHED"),
                ]
                falsifiers = [
                    _tr(lang, "PEAK_DOES_NOT_TRACK_RPM_DURING_STEADY_STATE"),
                    _tr(lang, "PEAK_FOLLOWS_WHEEL_SPEED_INSTEAD_OF_ENGINE_SPEED"),
                ]
                reference_bonus = 0.18

    if suspected_source == "unknown":
        speed_pairs = [(p[2], p[0]) for p in dominant_cluster if p[2] is not None and p[2] > 0]
        if len(speed_pairs) >= 6:
            corr = _corr_abs([p[0] for p in speed_pairs], [p[1] for p in speed_pairs])
            if corr is not None and corr < 0.25:
                suspected_source = "body resonance"
                evidence = _tr(
                    lang,
                    "DOMINANT_FREQUENCY_NEAR_CENTER_HZ_2F_HZ_SHOWS",
                    center_hz=center_hz,
                    corr=corr,
                )
                quick_checks = [
                    _tr(lang, "TAP_TEST_NEARBY_PANELS_SEATS_AND_COMPARE_RESONANCE"),
                    _tr(lang, "ADD_TEMPORARY_DAMPING_MASS_AND_REPEAT_THE_RUN"),
                ]
                falsifiers = [
                    _tr(lang, "FREQUENCY_SCALES_CLEARLY_WITH_WHEEL_OR_ENGINE_REFERENCES"),
                    _tr(lang, "PEAK_VANISHES_WHEN_SENSOR_IS_MOVED_OFF_THE"),
                ]

    # Add location-based evidence so findings can point to the most likely physical source.
    location_amp_values: dict[str, list[float]] = defaultdict(list)
    observed_locations: set[str] = set()
    for _hz, amp, _speed, _rpm, _rpm_source, client_name, client_id in dominant_cluster:
        label = client_name or (f"Sensor {client_id[-4:]}" if client_id else "Unlabeled sensor")
        observed_locations.add(label)
        if amp is not None and amp > 0:
            location_amp_values[label].append(amp)
    if location_amp_values:
        strongest_location = max(
            location_amp_values.keys(),
            key=lambda name: max(location_amp_values[name]),
        )
        strongest_peak = max(location_amp_values[strongest_location])
        coverage_count = len(observed_locations)
        location_count = len(location_amp_values)
        if location_count >= 2:
            if location_count == coverage_count:
                distribution_text = _tr(
                    lang,
                    "DETECTED_ACROSS_ALL_MONITORED_LOCATIONS_LOCATION_COUNT",
                    location_count=location_count,
                )
            else:
                distribution_text = _tr(
                    lang,
                    "DETECTED_AT_LOCATION_COUNT_OF_COVERAGE_COUNT_MONITORED",
                    location_count=location_count,
                    coverage_count=coverage_count,
                )
        else:
            distribution_text = _tr(lang, "DETECTED_AT_ONE_MONITORED_LOCATION")
        evidence += _tr(
            lang,
            "SPATIAL_PATTERN_SIGNATURE_WAS_DISTRIBUTION_TEXT_WITH_THE",
            distribution_text=distribution_text,
            strongest_location=strongest_location,
            strongest_peak=strongest_peak,
        )
        if (
            suspected_source == "wheel/tire"
            and location_count >= 3
            and "wheel" in strongest_location.lower()
        ):
            evidence += _tr(
                lang,
                "THIS_MOST_STRONGLY_INDICATES_A_FAULT_NEAR_THE",
                strongest_location=strongest_location,
            )
            reference_bonus += 0.05

    coverage = len(dominant_cluster) / max(1, len(freq_points))
    amp_ratio = (
        (amp_mean / max(amp_values))
        if amp_values and amp_mean is not None and max(amp_values) > 0
        else 0.0
    )
    confidence = 0.30 + (0.35 * coverage) + (0.17 * amp_ratio) + reference_bonus
    confidence = max(0.1, min(0.97, confidence))

    amp_value = amp_mean
    amp_definition = _tr(lang, "LARGEST_SINGLE_SIDED_FFT_PEAK_AMPLITUDE_ACROSS_AXES")

    return {
        "finding_id": "F001",
        "suspected_source": suspected_source,
        "evidence_summary": evidence,
        "frequency_hz_or_order": freq_or_order,
        "amplitude_metric": {
            "name": "dominant_peak_amp_g",
            "value": amp_value,
            "units": "g",
            "definition": amp_definition,
        },
        "confidence_0_to_1": confidence,
        "quick_checks": quick_checks[:3],
        "falsifiers": falsifiers[:3],
    }


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

    if not speed_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SPEED",
                suspected_source="unknown",
                evidence_summary=(
                    _tr(
                        lang,
                        "VEHICLE_SPEED_COVERAGE_IS_SPEED_NON_NULL_PCT",
                        speed_non_null_pct=speed_non_null_pct,
                        threshold=SPEED_COVERAGE_MIN_PCT,
                    )
                ),
                quick_checks=[
                    _tr(lang, "RECORD_VEHICLE_SPEED_FOR_MOST_SAMPLES_GPS_OR"),
                    _tr(lang, "VERIFY_TIMESTAMP_ALIGNMENT_BETWEEN_SPEED_AND_ACCELERATION_STREAM"),
                ],
                falsifiers=[
                    _tr(lang, "COVERAGE_RISES_ABOVE_THRESHOLD_AND_WHEEL_ORDER_CHECKS"),
                ],
                lang=lang,
            )
        )

    tire_circumference_m, tire_reference_label = _tire_reference_from_metadata(metadata)
    if speed_sufficient and not (tire_circumference_m and tire_circumference_m > 0):
        findings.append(
            _reference_missing_finding(
                finding_id="REF_WHEEL",
                suspected_source="wheel/tire",
                evidence_summary=(
                    _tr(lang, "VEHICLE_SPEED_IS_AVAILABLE_BUT_TIRE_CIRCUMFERENCE_REFERENCE")
                ),
                quick_checks=[
                    _tr(lang, "PROVIDE_TIRE_CIRCUMFERENCE_OR_TIRE_SIZE_WIDTH_ASPECT"),
                    _tr(lang, "RE_RUN_WITH_MEASURED_LOADED_TIRE_CIRCUMFERENCE"),
                ],
                falsifiers=[
                    _tr(lang, "WHEEL_ORDER_LABELS_BECOME_AVAILABLE_ONCE_TIRE_REFERENCE"),
                ],
                lang=lang,
            )
        )

    engine_ref_count = 0
    engine_ref_sources: set[str] = set()
    for sample in samples:
        rpm, source = _effective_engine_rpm(sample, metadata, tire_circumference_m)
        if rpm is not None and rpm > 0:
            engine_ref_count += 1
            engine_ref_sources.add(source)
    engine_rpm_non_null_pct = (engine_ref_count / len(samples) * 100.0) if samples else 0.0
    engine_ref_sufficient = engine_rpm_non_null_pct >= SPEED_COVERAGE_MIN_PCT
    if not engine_ref_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_ENGINE",
                suspected_source="engine",
                evidence_summary=(
                    _tr(
                        lang,
                        "ENGINE_SPEED_REFERENCE_COVERAGE_IS_ENGINE_RPM_NON",
                        engine_rpm_non_null_pct=engine_rpm_non_null_pct,
                    )
                ),
                quick_checks=[
                    _tr(lang, "LOG_ENGINE_RPM_FROM_CAN_OBD_FOR_THE"),
                    _tr(lang, "KEEP_TIMESTAMP_BASE_SHARED_WITH_ACCELEROMETER_AND_SPEED"),
                ],
                falsifiers=[
                    _tr(lang, "ENGINE_ORDER_CHECKS_BECOME_AVAILABLE_WITH_ADEQUATE_RPM"),
                ],
                lang=lang,
            )
        )
    elif engine_ref_sources == {"estimated_from_speed_and_ratios"}:
        findings.append(
            {
                "finding_id": "INFO_ENGINE_REF",
                "suspected_source": "engine",
                "evidence_summary": (
                    _tr(lang, "ENGINE_ORDER_REFERENCE_IS_DERIVED_FROM_VEHICLE_SPEED")
                ),
                "frequency_hz_or_order": _tr(lang, "REFERENCE_AVAILABLE_DERIVED"),
                "amplitude_metric": {
                    "name": "not_available",
                    "value": None,
                    "units": "n/a",
                    "definition": _tr(lang, "INFORMATIONAL_REFERENCE_NOTE"),
                },
                "confidence_0_to_1": 0.7,
                "quick_checks": [
                    _tr(lang, "VALIDATE_GEARING_SLIP_ASSUMPTIONS_AGAINST_REAL_RPM_IF"),
                ],
                "falsifiers": [
                    _tr(lang, "MEASURED_RPM_BASED_ORDER_MATCHING_DISAGREES_WITH_DERIVED"),
                ],
            }
        )

    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SAMPLE_RATE",
                suspected_source="unknown",
                evidence_summary=(
                    _tr(lang, "RAW_ACCELEROMETER_SAMPLE_RATE_IS_MISSING_SO_DOMINANT")
                ),
                quick_checks=[
                    _tr(lang, "RECORD_THE_TRUE_ACCELEROMETER_SAMPLE_RATE_IN_RUN"),
                ],
                falsifiers=[
                    _tr(lang, "FREQUENCY_CONFIDENCE_IMPROVES_ONCE_SAMPLE_RATE_METADATA_IS"),
                ],
                lang=lang,
            )
        )

    dominant = _dominant_cluster_finding(
        metadata=metadata,
        samples=samples,
        speed_sufficient=speed_sufficient,
        tire_circumference_m=tire_circumference_m if speed_sufficient else None,
        tire_reference_label=tire_reference_label,
        engine_ref_sufficient=engine_ref_sufficient,
        raw_sample_rate_hz=raw_sample_rate_hz,
        lang=lang,
    )
    if dominant is not None:
        findings.append(dominant)

    findings.sort(key=lambda item: float(item.get("confidence_0_to_1", 0.0)), reverse=True)
    for idx, finding in enumerate(findings, start=1):
        existing = str(finding.get("finding_id", "")).strip()
        if not existing or existing.startswith("F"):
            finding["finding_id"] = f"F{idx:03d}"
    return findings


def _plot_data(summary: dict[str, Any]) -> dict[str, Any]:
    samples: list[dict[str, Any]] = summary.get("samples", [])
    raw_sample_rate_hz = _as_float(summary.get("raw_sample_rate_hz"))
    accel_mag_points: list[tuple[float, float]] = []
    accel_x_points: list[tuple[float, float]] = []
    accel_y_points: list[tuple[float, float]] = []
    accel_z_points: list[tuple[float, float]] = []
    dominant_freq_points: list[tuple[float, float]] = []
    speed_amp_points: list[tuple[float, float]] = []

    for sample in samples:
        t_s = _as_float(sample.get("t_s"))
        if t_s is None:
            continue

        ax = _as_float(sample.get("accel_x_g"))
        ay = _as_float(sample.get("accel_y_g"))
        az = _as_float(sample.get("accel_z_g"))
        if ax is not None:
            accel_x_points.append((t_s, ax))
        if ay is not None:
            accel_y_points.append((t_s, ay))
        if az is not None:
            accel_z_points.append((t_s, az))
        if ax is not None and ay is not None and az is not None:
            accel_mag_points.append((t_s, sqrt((ax * ax) + (ay * ay) + (az * az))))

        if raw_sample_rate_hz and raw_sample_rate_hz > 0:
            dominant_hz = _as_float(sample.get("dominant_freq_hz"))
            if dominant_hz is not None and dominant_hz > 0:
                dominant_freq_points.append((t_s, dominant_hz))

    for row in summary.get("speed_breakdown", []):
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

    return {
        "accel_magnitude": accel_mag_points,
        "accel_axes": {
            "x": accel_x_points,
            "y": accel_y_points,
            "z": accel_z_points,
        },
        "dominant_freq": dominant_freq_points,
        "amp_vs_speed": speed_amp_points,
    }


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
        value
        for value in (
            _as_float(sample.get("accel_magnitude_rms_g"))
            or _as_float(sample.get("dominant_peak_amp_g"))
            for sample in samples
        )
        if value is not None
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


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _fallback_pdf(summary: dict[str, object]) -> bytes:
    lang = _normalize_lang(summary.get("lang"))
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    findings = summary.get("findings", [])

    lines = [
        _tr(lang, "VIBESENSOR_NVH_REPORT"),
        "",
        _tr(lang, "GENERATED_GENERATED", generated=generated),
        _tr(lang, "RUN_FILE_NAME", name=summary.get("file_name", "")),
        f"Run ID: {summary.get('run_id', '')}",
        _tr(lang, "ROWS_ROWS", rows=summary.get("rows", 0)),
        _tr(lang, "DURATION_DURATION_1F_S", duration=float(summary.get("duration_s", 0.0))),
        _tr(lang, "FINDINGS"),
    ]
    if isinstance(findings, list) and findings:
        for idx, finding in enumerate(findings[:8], start=1):
            if not isinstance(finding, dict):
                continue
            lines.append(
                f"{idx}. {finding.get('suspected_source', 'unknown')} | "
                f"{finding.get('evidence_summary', '')}"
            )
    else:
        lines.append(_tr(lang, "T_1_NO_FINDINGS_GENERATED"))

    lines = lines[:44]
    content_lines = ["BT", "/F1 11 Tf", "50 790 Td", "14 TL"]
    for i, line in enumerate(lines):
        safe = _pdf_escape(str(line))
        if i == 0:
            content_lines.append(f"({safe}) Tj")
        else:
            content_lines.append(f"T* ({safe}) Tj")
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>".encode("ascii") + b"\nstream\n" + content + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_start = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)


def _reportlab_pdf(summary: dict[str, object]) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    page_size = landscape(LETTER)
    content_width = page_size[0] - 48
    lang = _normalize_lang(summary.get("lang"))

    def tr(key: str, **kwargs: object) -> str:
        return _tr(lang, key, **kwargs)

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "TitleMain",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#1f3a52"),
        spaceAfter=8,
    )
    style_h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor("#1f3a52"),
        spaceAfter=4,
        spaceBefore=8,
    )
    style_body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=8.5, leading=11)
    style_note = ParagraphStyle(
        "Note",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#4f5d73"),
    )
    style_table_head = ParagraphStyle(
        "TableHead",
        parent=style_note,
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9.0,
        textColor=colors.HexColor("#1f3a52"),
    )
    style_h3 = ParagraphStyle(
        "H3",
        parent=styles["Heading3"],
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#1f3a52"),
        spaceBefore=5,
        spaceAfter=2,
    )

    def ptext(value: object, *, header: bool = False, break_underscores: bool = False) -> Paragraph:
        text = escape(str(value if value is not None else ""))
        text = text.replace("\n", "<br/>")
        if break_underscores:
            text = text.replace("_", "_<br/>")
        return Paragraph(text, style_table_head if header else style_note)

    def human_source(source: object) -> str:
        raw = str(source or "").strip().lower()
        mapping = {
            "wheel/tire": tr("SOURCE_WHEEL_TIRE"),
            "driveline": tr("SOURCE_DRIVELINE"),
            "engine": tr("SOURCE_ENGINE"),
            "body resonance": tr("SOURCE_BODY_RESONANCE"),
            "unknown": tr("UNKNOWN"),
        }
        return mapping.get(raw, raw.replace("_", " ").title() if raw else tr("UNKNOWN"))

    def human_finding_title(finding: dict[str, object], index: int) -> str:
        fid = str(finding.get("finding_id", "")).strip().upper()
        source = human_source(finding.get("suspected_source"))
        mapping = {
            "REF_SPEED": tr("MISSING_SPEED_REFERENCE"),
            "REF_WHEEL": tr("MISSING_WHEEL_REFERENCE"),
            "REF_ENGINE": tr("MISSING_ENGINE_REFERENCE"),
            "INFO_ENGINE_REF": tr("DERIVED_ENGINE_REFERENCE"),
            "REF_SAMPLE_RATE": tr("MISSING_SAMPLE_RATE_METADATA"),
        }
        if fid in mapping:
            return mapping[fid]
        if fid.startswith("F") and fid[1:].isdigit():
            return tr("FINDING_INDEX_SOURCE", index=index, source=source)
        return tr("FINDING_INDEX_SOURCE", index=index, source=source)

    def human_frequency_text(value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return tr("REFERENCE_NOT_AVAILABLE")
        lowered = raw.lower()
        missing_markers = {item.lower() for item in _tr_variants("REFERENCE_MISSING")}
        derived_markers = {item.lower() for item in _tr_variants("REFERENCE_AVAILABLE_DERIVED")}
        if lowered in missing_markers:
            return tr("REFERENCE_NOT_AVAILABLE")
        if lowered in derived_markers:
            return tr("REFERENCE_AVAILABLE_DERIVED_FROM_OTHER_MEASUREMENTS")
        return raw

    def human_amp_text(amp: object) -> str:
        if not isinstance(amp, dict):
            return tr("NOT_AVAILABLE")
        name_raw = str(amp.get("name", "")).strip()
        value = _as_float(amp.get("value"))
        units = str(amp.get("units", "")).strip()
        definition = str(amp.get("definition", "")).strip()
        if name_raw == "not_available":
            if definition:
                return f"{tr('NOT_AVAILABLE')}. {definition}"
            return tr("NOT_AVAILABLE")
        name_map = {
            "dominant_peak_amp_g": tr("DOMINANT_PEAK_AMPLITUDE"),
            "not_available": tr("NOT_AVAILABLE"),
        }
        label = name_map.get(
            name_raw,
            name_raw.replace("_", " ").title() if name_raw else tr("METRIC_LABEL"),
        )
        value_text = tr("NOT_AVAILABLE_2") if value is None else f"{value:.4f} {units}".strip()
        if definition:
            return f"{label}: {value_text}. {definition}"
        return f"{label}: {value_text}"

    def human_list(items: object) -> Paragraph:
        if not isinstance(items, list):
            return ptext(tr("NONE_LISTED"))
        cleaned = [str(v).strip() for v in items if str(v).strip()]
        if not cleaned:
            return ptext(tr("NONE_LISTED"))
        lines = [f"{i + 1}. {escape(val)}" for i, val in enumerate(cleaned)]
        return Paragraph("<br/>".join(lines), style_note)

    def top_actions(findings_list: object) -> list[dict[str, str]]:
        if not isinstance(findings_list, list):
            return []
        actions: list[dict[str, str]] = []
        for finding in findings_list:
            if not isinstance(finding, dict):
                continue
            fid = str(finding.get("finding_id", "")).strip().upper()
            source = human_source(finding.get("suspected_source"))
            confidence = _as_float(finding.get("confidence_0_to_1")) or 0.0
            checks = finding.get("quick_checks")
            action_text = (
                str(checks[0]).strip()
                if isinstance(checks, list) and checks and str(checks[0]).strip()
                else tr("REPEAT_RUN_AFTER_CHECKING_SENSOR_MOUNTING_AND_ROUTING")
            )
            if fid in {"REF_SPEED", "REF_WHEEL", "REF_ENGINE", "REF_SAMPLE_RATE"}:
                priority = tr("HIGH")
                eta = tr("T_10_20_MIN")
            elif confidence >= 0.72:
                priority = tr("HIGH")
                eta = tr("T_20_40_MIN")
            elif confidence >= 0.45:
                priority = tr("MEDIUM")
                eta = tr("T_15_30_MIN")
            else:
                priority = tr("LOW")
                eta = tr("T_10_20_MIN")
            reason = str(finding.get("evidence_summary", "")).strip()
            if len(reason) > 180:
                reason = reason[:177].rstrip() + "..."
            actions.append(
                {
                    "priority": priority,
                    "action": action_text,
                    "why": reason
                    or tr(
                        "SOURCE_EVIDENCE_REQUIRES_ADDITIONAL_CHECKS",
                        source=source,
                    ),
                    "eta": eta,
                }
            )
            if len(actions) >= 3:
                break
        return actions

    def location_hotspots(samples_obj: object) -> tuple[list[dict[str, object]], str, int, int]:
        if not isinstance(samples_obj, list):
            return [], tr("LOCATION_ANALYSIS_UNAVAILABLE"), 0, 0
        all_locations: set[str] = set()
        amp_by_location: dict[str, list[float]] = defaultdict(list)
        for sample in samples_obj:
            if not isinstance(sample, dict):
                continue
            client_name = str(sample.get("client_name") or "").strip()
            client_id = str(sample.get("client_id") or "").strip()
            location = client_name or (
                f"Sensor {client_id[-4:]}" if client_id else tr("UNLABELED_SENSOR")
            )
            all_locations.add(location)
            amp = _as_float(sample.get("dominant_peak_amp_g"))
            if amp is None:
                amp = _as_float(sample.get("accel_magnitude_rms_g"))
            if amp is not None and amp > 0:
                amp_by_location[location].append(amp)

        rows: list[dict[str, object]] = []
        for location, amps in amp_by_location.items():
            rows.append(
                {
                    "location": location,
                    "count": len(amps),
                    "peak_g": max(amps),
                    "mean_g": mean(amps),
                }
            )
        rows.sort(key=lambda row: (float(row["peak_g"]), float(row["mean_g"])), reverse=True)
        if not rows:
            return (
                [],
                tr("NO_USABLE_AMPLITUDE_BY_LOCATION_DATA_WAS_FOUND"),
                0,
                len(all_locations),
            )

        active_count = len(rows)
        monitored_count = len(all_locations)
        strongest = rows[0]
        strongest_loc = str(strongest["location"])
        strongest_peak = float(strongest["peak_g"])
        summary = tr(
            "VIBRATION_SIGNATURE_WAS_DETECTED_AT_ACTIVE_COUNT_OF",
            active_count=active_count,
            monitored_count=monitored_count,
            strongest_loc=strongest_loc,
            strongest_peak=strongest_peak,
        )
        if (
            monitored_count >= 3
            and active_count == monitored_count
            and "wheel" in strongest_loc.lower()
        ):
            if len(rows) >= 2:
                second_peak = float(rows[1]["peak_g"])
                if second_peak > 0 and (strongest_peak / second_peak) >= 1.15:
                    summary += tr(
                        "SINCE_ALL_SENSORS_SAW_THE_SIGNATURE_BUT_STRONGEST",
                        strongest_loc=strongest_loc,
                    )
        return rows, summary, active_count, monitored_count

    def mk_table(
        data: list[list[object]],
        col_widths: list[int] | None = None,
        header: bool = True,
        repeat_rows: int | None = None,
    ) -> Table:
        table = Table(
            data,
            colWidths=col_widths,
            repeatRows=repeat_rows if repeat_rows is not None else (1 if header else 0),
        )
        style = TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.7, colors.HexColor("#b9c7d5")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#b9c7d5")),
                ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.HexColor("#d6dee8")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
        if header:
            style.add("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5"))
            style.add("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f3a52"))
            style.add("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")
            style.add("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor("#c8d3df"))
        table.setStyle(style)
        return table

    def downsample(
        points: list[tuple[float, float]], max_points: int = 260
    ) -> list[tuple[float, float]]:
        if len(points) <= max_points:
            return points
        step = max(1, len(points) // max_points)
        sampled = [points[i] for i in range(0, len(points), step)]
        if sampled[-1] != points[-1]:
            sampled.append(points[-1])
        return sampled

    def line_plot(
        *,
        title: str,
        x_label: str,
        y_label: str,
        series: list[tuple[str, str, list[tuple[float, float]]]],
    ) -> Drawing:
        drawing = Drawing(content_width, 230)
        plot_x0 = 48
        plot_y0 = 34
        plot_w = content_width - 72
        plot_h = 160

        drawing.add(
            String(
                8,
                202,
                title,
                fontName="Helvetica-Bold",
                fontSize=9,
                fillColor=colors.HexColor("#1f3a52"),
            )
        )
        drawing.add(
            Line(
                plot_x0,
                plot_y0,
                plot_x0 + plot_w,
                plot_y0,
                strokeColor=colors.HexColor("#7b8da0"),
            )
        )
        drawing.add(
            Line(
                plot_x0,
                plot_y0,
                plot_x0,
                plot_y0 + plot_h,
                strokeColor=colors.HexColor("#7b8da0"),
            )
        )
        drawing.add(String(plot_x0 + (plot_w / 2) - 10, 10, x_label, fontSize=7))
        drawing.add(String(6, plot_y0 + (plot_h / 2), y_label, fontSize=7))

        active_series = [
            (name, color, downsample(points)) for name, color, points in series if points
        ]
        if not active_series:
            drawing.add(String(150, 110, tr("PLOT_NO_DATA_AVAILABLE"), fontSize=8))
            return drawing

        all_points = [point for _name, _color, points in active_series for point in points]
        x_min = min(point[0] for point in all_points)
        x_max = max(point[0] for point in all_points)
        y_min = min(point[1] for point in all_points)
        y_max = max(point[1] for point in all_points)
        if abs(x_max - x_min) < 1e-9:
            x_max = x_min + 1.0
        if abs(y_max - y_min) < 1e-9:
            y_max = y_min + 1.0

        def map_x(x_val: float) -> float:
            return plot_x0 + ((x_val - x_min) / (x_max - x_min) * plot_w)

        def map_y(y_val: float) -> float:
            return plot_y0 + ((y_val - y_min) / (y_max - y_min) * plot_h)

        legend_x = plot_x0 + 4
        legend_y = 192
        for idx, (name, color, points) in enumerate(active_series):
            flat_points: list[float] = []
            for x_val, y_val in points:
                flat_points.append(map_x(x_val))
                flat_points.append(map_y(y_val))
            drawing.add(
                PolyLine(
                    flat_points,
                    strokeColor=colors.HexColor(color),
                    strokeWidth=1.2,
                )
            )
            drawing.add(
                String(
                    legend_x + (idx * 150),
                    legend_y,
                    name,
                    fontSize=7,
                    fillColor=colors.HexColor(color),
                )
            )

        drawing.add(
            String(
                plot_x0 + plot_w - 120,
                plot_y0 - 12,
                f"x:[{x_min:.2f}, {x_max:.2f}]",
                fontSize=6.5,
                fillColor=colors.HexColor("#5a6778"),
            )
        )
        drawing.add(
            String(
                plot_x0 + plot_w - 120,
                plot_y0 + plot_h + 4,
                f"y:[{y_min:.3f}, {y_max:.3f}]",
                fontSize=6.5,
                fillColor=colors.HexColor("#5a6778"),
            )
        )
        return drawing

    def req(value: object, consequence_key: str) -> str:
        return _required_text(value, tr(consequence_key), lang=lang)

    report_date = summary.get("report_date") or datetime.now(UTC).isoformat()
    quality = summary.get("data_quality", {})
    required_missing = quality.get("required_missing_pct", {}) if isinstance(quality, dict) else {}
    speed_cov = quality.get("speed_coverage", {}) if isinstance(quality, dict) else {}
    accel_sanity = quality.get("accel_sanity", {}) if isinstance(quality, dict) else {}
    outliers = quality.get("outliers", {}) if isinstance(quality, dict) else {}
    findings = summary.get("findings", [])
    plots = summary.get("plots", {}) if isinstance(summary.get("plots"), dict) else {}

    metadata_rows = [
        [tr("FIELD"), tr("VALUE")],
        [
            tr("START_TIME_UTC"),
            req(summary.get("start_time_utc"), "CONSEQUENCE_TIMELINE_ALIGNMENT_IMPOSSIBLE"),
        ],
        [
            tr("END_TIME_UTC"),
            req(summary.get("end_time_utc"), "CONSEQUENCE_DURATION_INFERRED_FROM_LAST_SAMPLE"),
        ],
        [
            tr("SENSOR_MODEL"),
            req(summary.get("sensor_model"), "CONSEQUENCE_SENSOR_SANITY_LIMITS_CANNOT_BE_APPLIED"),
        ],
        [
            tr("RAW_SAMPLE_RATE_HZ_LABEL"),
            req(summary.get("raw_sample_rate_hz"), "CONSEQUENCE_FREQUENCY_CONFIDENCE_REDUCED"),
        ],
        [
            tr("FEATURE_INTERVAL_S_LABEL"),
            req(
                summary.get("feature_interval_s"),
                "CONSEQUENCE_TIME_DENSITY_INTERPRETATION_REDUCED",
            ),
        ],
        [
            tr("FFT_WINDOW_SIZE_SAMPLES_LABEL"),
            req(summary.get("fft_window_size_samples"), "CONSEQUENCE_SPECTRAL_RESOLUTION_UNKNOWN"),
        ],
        [
            tr("FFT_WINDOW_TYPE_LABEL"),
            req(summary.get("fft_window_type"), "CONSEQUENCE_WINDOW_LEAKAGE_ASSUMPTIONS_UNKNOWN"),
        ],
        [
            tr("PEAK_PICKER_METHOD_LABEL"),
            req(summary.get("peak_picker_method"), "CONSEQUENCE_PEAK_REPRODUCIBILITY_UNCLEAR"),
        ],
        [
            tr("TIRE_WIDTH_MM_LABEL"),
            req(
                summary.get("metadata", {}).get("tire_width_mm"),
                "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE",
            )
            if isinstance(summary.get("metadata"), dict)
            else req(None, "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE"),
        ],
        [
            tr("TIRE_ASPECT_PCT_LABEL"),
            req(
                summary.get("metadata", {}).get("tire_aspect_pct"),
                "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE",
            )
            if isinstance(summary.get("metadata"), dict)
            else req(None, "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE"),
        ],
        [
            tr("RIM_SIZE_IN_LABEL"),
            req(
                summary.get("metadata", {}).get("rim_in"),
                "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE",
            )
            if isinstance(summary.get("metadata"), dict)
            else req(None, "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE"),
        ],
        [
            tr("FINAL_DRIVE_RATIO_LABEL"),
            req(
                summary.get("metadata", {}).get("final_drive_ratio"),
                "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE",
            )
            if isinstance(summary.get("metadata"), dict)
            else req(None, "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE"),
        ],
        [
            tr("CURRENT_GEAR_RATIO_LABEL"),
            req(
                summary.get("metadata", {}).get("current_gear_ratio"),
                "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE",
            )
            if isinstance(summary.get("metadata"), dict)
            else req(None, "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE"),
        ],
    ]

    location_rows, location_summary, active_locations, monitored_locations = location_hotspots(
        summary.get("samples", [])
    )
    finding_ids = {
        str(item.get("finding_id", "")).strip().upper()
        for item in findings
        if isinstance(item, dict)
    }
    top_finding = (
        findings[0]
        if isinstance(findings, list) and findings and isinstance(findings[0], dict)
        else {}
    )
    top_source = (
        human_source(top_finding.get("suspected_source"))
        if isinstance(top_finding, dict)
        else tr("UNKNOWN")
    )
    top_confidence = (
        _as_float(top_finding.get("confidence_0_to_1")) if isinstance(top_finding, dict) else 0.0
    )
    if any(fid.startswith("REF_") for fid in finding_ids):
        overall_status = tr("STATUS_REFERENCE_GAPS")
    elif (top_confidence or 0.0) >= 0.7:
        overall_status = tr("STATUS_ACTIONABLE_HIGH_CONFIDENCE")
    else:
        overall_status = tr("STATUS_PRELIMINARY")

    speed_ready = (_as_float(speed_cov.get("non_null_pct")) or 0.0) >= SPEED_COVERAGE_MIN_PCT
    sample_rate_ready = _as_float(summary.get("raw_sample_rate_hz")) is not None
    engine_ready = "REF_ENGINE" not in finding_ids
    readiness_line = tr(
        "READINESS_LINE",
        speed_state=tr("READY") if speed_ready else tr("MISSING_LOW"),
        sample_rate_state=tr("READY") if sample_rate_ready else tr("MISSING_STATE"),
        engine_state=tr("READY") if engine_ready else tr("MISSING_LOW"),
        active=active_locations,
        total=monitored_locations if monitored_locations else 0,
    )

    likely_origin = tr("UNKNOWN")
    origin_reason = tr("ORIGIN_NOT_ENOUGH_LOCATION_CONTRAST")
    if location_rows:
        strongest_location = str(location_rows[0]["location"])
        strongest_peak = float(location_rows[0]["peak_g"])
        second_peak = (
            float(location_rows[1]["peak_g"]) if len(location_rows) > 1 else strongest_peak
        )
        dominance = (strongest_peak / second_peak) if second_peak > 0 else 1.0
        if "wheel" in strongest_location.lower():
            likely_origin = tr("LOCATION_WHEEL_AREA", location=strongest_location)
        else:
            likely_origin = strongest_location
        origin_reason = tr(
            "ORIGIN_STRONGEST_PEAK_DOMINANCE",
            location=strongest_location,
            dominance=dominance,
        )
    elif isinstance(top_finding, dict):
        likely_origin = top_source
        origin_reason = str(top_finding.get("evidence_summary", tr("LOCATION_RANKING_UNAVAILABLE")))

    story: list[object] = [
        Paragraph(tr("NVH_DIAGNOSTIC_REPORT"), style_title),
        mk_table(
            [
                [
                    tr("REPORT_DATE"),
                    tr("RUN_FILE"),
                    tr("RUN_ID"),
                    tr("DURATION"),
                ],
                [
                    str(report_date)[:19].replace("T", " "),
                    str(summary.get("file_name", "")),
                    str(summary.get("run_id", "")),
                    str(
                        summary.get(
                            "record_length",
                            tr("MISSING_DURATION_UNAVAILABLE"),
                        )
                    ),
                ],
            ],
            col_widths=[150, 260, 220, 110],
        ),
        Paragraph(tr("RUN_TRIAGE"), style_h2),
        mk_table(
            [
                [tr("ITEM"), tr("SUMMARY")],
                [tr("OVERALL_STATUS"), Paragraph(overall_status, style_note)],
                [
                    tr("MOST_LIKELY_ORIGIN"),
                    Paragraph(f"{likely_origin}<br/>{escape(origin_reason)}", style_note),
                ],
                [tr("DATA_READINESS"), Paragraph(readiness_line, style_note)],
            ],
            col_widths=[170, 570],
        ),
    ]

    action_rows = [
        [
            tr("PRIORITY"),
            tr("RECOMMENDED_ACTION"),
            tr("WHY"),
            tr("ESTIMATED_TIME"),
        ]
    ]
    for action in top_actions(findings):
        action_rows.append(
            [
                action["priority"],
                Paragraph(action["action"], style_note),
                Paragraph(action["why"], style_note),
                action["eta"],
            ]
        )
    if len(action_rows) == 1:
        action_rows.append(
            [
                tr("INFO"),
                tr("COLLECT_A_LONGER_RUN_WITH_STABLE_DRIVING_CONDITIONS"),
                tr("NO_ACTIONABLE_FINDINGS_WERE_GENERATED_FROM_CURRENT_DATA"),
                tr("T_10_20_MIN"),
            ]
        )
    story.extend(
        [
            Paragraph(tr("TOP_ACTIONS"), style_h2),
            mk_table(action_rows, col_widths=[70, 240, 370, 90]),
        ]
    )

    warnings = summary.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        warning_text = "<br/>".join(str(w) for w in warnings)
        story.extend(
            [
                Spacer(1, 6),
                Paragraph(
                    f"<b>{tr('INPUT_WARNINGS')}</b><br/>{warning_text}",
                    style_note,
                ),
            ]
        )

    story.extend([PageBreak(), Paragraph(tr("RANKED_FINDINGS"), style_h2)])
    if isinstance(findings, list) and findings:
        for idx, finding in enumerate(findings[:5], start=1):
            if not isinstance(finding, dict):
                continue
            amp = finding.get("amplitude_metric", {})
            title = human_finding_title(finding, idx)
            source = human_source(finding.get("suspected_source"))
            confidence_pct = f"{((_as_float(finding.get('confidence_0_to_1')) or 0.0) * 100):.0f}%"
            story.extend(
                [
                    Paragraph(title, style_h3),
                    Paragraph(
                        (
                            f"<b>{tr('LIKELY_SOURCE_LABEL')}:</b> {source} &nbsp;&nbsp; "
                            f"<b>{tr('CONFIDENCE_LABEL')}:</b> {confidence_pct}"
                        ),
                        style_note,
                    ),
                    Paragraph(str(finding.get("evidence_summary", "")), style_note),
                    mk_table(
                        [
                            [tr("MATCHED_FREQUENCY_ORDER"), tr("AMPLITUDE_SUMMARY")],
                            [
                                human_frequency_text(finding.get("frequency_hz_or_order")),
                                human_amp_text(amp),
                            ],
                        ],
                        col_widths=[250, 490],
                    ),
                    Paragraph(f"<b>{tr('QUICK_CHECKS')}</b>", style_note),
                    human_list(finding.get("quick_checks")),
                    Spacer(1, 5),
                ]
            )
    else:
        story.append(
            Paragraph(
                tr("NO_FINDINGS_WERE_GENERATED_FROM_THE_AVAILABLE_DATA"),
                style_body,
            )
        )

    story.extend([Paragraph(tr("WHERE_VIBRATION_IS_STRONGEST"), style_h2)])
    story.append(Paragraph(location_summary, style_body))
    if location_rows:
        strongest_peak = float(location_rows[0]["peak_g"])
        location_table = [
            [
                tr("LOCATION"),
                tr("PEAK_AMPLITUDE_G"),
                tr("MEAN_AMPLITUDE_G"),
                tr("SAMPLES"),
                tr("RELATIVE"),
            ]
        ]
        for row in location_rows[:8]:
            peak = float(row["peak_g"])
            rel = (peak / strongest_peak * 100.0) if strongest_peak > 0 else 0.0
            location_table.append(
                [
                    str(row["location"]),
                    f"{peak:.4f}",
                    f"{float(row['mean_g']):.4f}",
                    str(int(row["count"])),
                    tr("REL_0F_OF_STRONGEST", rel=rel),
                ]
            )
        story.append(mk_table(location_table, col_widths=[220, 140, 140, 90, 120]))

    story.extend([PageBreak(), Paragraph(tr("SPEED_BINNED_ANALYSIS"), style_h2)])
    skipped_reason = summary.get("speed_breakdown_skipped_reason")
    if skipped_reason:
        story.append(Paragraph(str(skipped_reason), style_body))
    else:
        speed_rows = [
            [
                tr("SPEED_RANGE"),
                tr("SAMPLES"),
                tr("MEAN_AMPLITUDE_G"),
                tr("MAX_AMPLITUDE_G"),
            ]
        ]
        for row in summary.get("speed_breakdown", []):
            if not isinstance(row, dict):
                continue
            speed_rows.append(
                [
                    str(row.get("speed_range", "")),
                    str(int(_as_float(row.get("count")) or 0)),
                    req(row.get("mean_amplitude_g"), "CONSEQUENCE_SPEED_BIN_AMPLITUDE_UNAVAILABLE"),
                    req(row.get("max_amplitude_g"), "CONSEQUENCE_SPEED_BIN_AMPLITUDE_UNAVAILABLE"),
                ]
            )
        if len(speed_rows) == 1:
            speed_rows.append(
                [
                    tr("MISSING_2"),
                    "0",
                    tr("MISSING_SPEED_BINS_UNAVAILABLE"),
                    tr("MISSING_SPEED_BINS_UNAVAILABLE"),
                ]
            )
        story.append(mk_table(speed_rows, col_widths=[130, 90, 140, 140]))

    story.extend([Paragraph(tr("PLOTS"), style_h2)])
    accel_mag = plots.get("accel_magnitude", []) if isinstance(plots, dict) else []
    accel_axes = plots.get("accel_axes", {}) if isinstance(plots, dict) else {}
    dominant_freq = plots.get("dominant_freq", []) if isinstance(plots, dict) else []
    amp_vs_speed = plots.get("amp_vs_speed", []) if isinstance(plots, dict) else []

    story.append(
        line_plot(
            title=tr("PLOT_ACCEL_MAG_OVER_TIME"),
            x_label=tr("TIME_S"),
            y_label="|a| (g)",
            series=[(tr("PLOT_SERIES_MAGNITUDE"), "#1f77b4", accel_mag)],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        line_plot(
            title=tr("PLOT_PER_AXIS_ACCEL_OVER_TIME"),
            x_label=tr("TIME_S"),
            y_label="accel (g)",
            series=[
                (
                    "accel_x_g",
                    "#d62728",
                    accel_axes.get("x", []) if isinstance(accel_axes, dict) else [],
                ),
                (
                    "accel_y_g",
                    "#2ca02c",
                    accel_axes.get("y", []) if isinstance(accel_axes, dict) else [],
                ),
                (
                    "accel_z_g",
                    "#1f77b4",
                    accel_axes.get("z", []) if isinstance(accel_axes, dict) else [],
                ),
            ],
        )
    )
    if dominant_freq:
        story.append(Spacer(1, 6))
        story.append(
            line_plot(
                title=tr("PLOT_DOM_FREQ_OVER_TIME"),
                x_label=tr("TIME_S"),
                y_label=tr("FREQUENCY_HZ"),
                series=[("dominant_freq_hz", "#9467bd", dominant_freq)],
            )
        )
    else:
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                tr("PLOT_DOM_FREQ_SKIPPED"),
                style_note,
            )
        )

    if amp_vs_speed:
        story.append(Spacer(1, 6))
        story.append(
            line_plot(
                title=tr("PLOT_AMP_VS_SPEED_BINS"),
                x_label=tr("SPEED_KM_H"),
                y_label=tr("PLOT_Y_MEAN_AMPLITUDE_G"),
                series=[(tr("PLOT_SERIES_MEAN_AMPLITUDE"), "#ff7f0e", amp_vs_speed)],
            )
        )

    story.extend(
        [
            Spacer(1, 8),
            Paragraph(
                (tr("THIS_REPORT_IS_GENERATED_FROM_EXPLICIT_REFERENCES_ONLY")),
                style_note,
            ),
        ]
    )

    story.extend([PageBreak(), Paragraph(tr("APPENDIX_A_DATA_QUALITY_CHECKS"), style_h2)])
    missing_rows = [[tr("REQUIRED_COLUMN"), tr("MISSING")]]
    for col_name in ("t_s", "speed_kmh", "accel_x_g", "accel_y_g", "accel_z_g"):
        pct = _as_float(required_missing.get(col_name))
        missing_text = req(None, "CONSEQUENCE_QUALITY_METRIC_UNAVAILABLE")
        missing_rows.append(
            [
                col_name,
                f"{pct:.1f}%" if pct is not None else missing_text,
            ]
        )
    story.append(mk_table(missing_rows, col_widths=[300, 120]))

    speed_note = tr(
        "SPEED_COVERAGE_LINE",
        non_null_pct=f"{_as_float(speed_cov.get('non_null_pct')) or 0.0:.1f}",
        min_kmh=req(speed_cov.get("min_kmh"), "CONSEQUENCE_SPEED_BINS_UNAVAILABLE"),
        max_kmh=req(speed_cov.get("max_kmh"), "CONSEQUENCE_SPEED_BINS_UNAVAILABLE"),
    )
    story.append(Paragraph(speed_note, style_body))

    sanity_rows = [
        [tr("AXIS"), tr("MEAN_G"), tr("VARIANCE_G_2")],
        [
            "X",
            req(accel_sanity.get("x_mean_g"), "CONSEQUENCE_MEAN_UNAVAILABLE"),
            req(accel_sanity.get("x_variance_g2"), "CONSEQUENCE_VARIANCE_UNAVAILABLE"),
        ],
        [
            "Y",
            req(accel_sanity.get("y_mean_g"), "CONSEQUENCE_MEAN_UNAVAILABLE"),
            req(accel_sanity.get("y_variance_g2"), "CONSEQUENCE_VARIANCE_UNAVAILABLE"),
        ],
        [
            "Z",
            req(accel_sanity.get("z_mean_g"), "CONSEQUENCE_MEAN_UNAVAILABLE"),
            req(accel_sanity.get("z_variance_g2"), "CONSEQUENCE_VARIANCE_UNAVAILABLE"),
        ],
    ]
    story.append(mk_table(sanity_rows, col_widths=[100, 170, 170]))

    limit_text = req(accel_sanity.get("sensor_limit_g"), "CONSEQUENCE_SENSOR_LIMIT_UNKNOWN")
    sat_count_text = int(_as_float(accel_sanity.get("saturation_count")) or 0)
    sat_line = tr("SATURATION_CHECKS_LINE", limit=limit_text, count=sat_count_text)
    story.append(Paragraph(sat_line, style_body))

    accel_out = outliers.get("accel_magnitude_g", {}) if isinstance(outliers, dict) else {}
    amp_out = outliers.get("amplitude_metric", {}) if isinstance(outliers, dict) else {}
    outlier_text = tr(
        "OUTLIER_SUMMARY_LINE",
        accel_pct=f"{_as_float(accel_out.get('outlier_pct')) or 0.0:.1f}",
        accel_count=int(_as_float(accel_out.get("outlier_count")) or 0),
        accel_total=int(_as_float(accel_out.get("count")) or 0),
        amp_pct=f"{_as_float(amp_out.get('outlier_pct')) or 0.0:.1f}",
        amp_count=int(_as_float(amp_out.get("outlier_count")) or 0),
        amp_total=int(_as_float(amp_out.get("count")) or 0),
    )
    story.append(Paragraph(outlier_text, style_body))

    story.extend([PageBreak(), Paragraph(tr("APPENDIX_B_FULL_RUN_METADATA"), style_h2)])
    story.append(mk_table(metadata_rows, col_widths=[250, 470]))

    story.extend([PageBreak(), Paragraph(tr("APPENDIX_C_DETAILED_FINDINGS_TABLE"), style_h2)])
    detailed_rows: list[list[object]] = [
        [
            ptext(tr("FINDING"), header=True),
            ptext(tr("LIKELY_SOURCE"), header=True),
            ptext(tr("WHY_WE_THINK_THIS"), header=True),
            ptext(tr("MATCHED_FREQUENCY_ORDER"), header=True),
            ptext(tr("AMPLITUDE_SUMMARY"), header=True),
            ptext(tr("CONFIDENCE_LABEL"), header=True),
            ptext(tr("QUICK_CHECKS"), header=True),
        ]
    ]
    if isinstance(findings, list) and findings:
        for idx, finding in enumerate(findings, start=1):
            if not isinstance(finding, dict):
                continue
            detailed_rows.append(
                [
                    ptext(human_finding_title(finding, idx)),
                    ptext(human_source(finding.get("suspected_source"))),
                    ptext(finding.get("evidence_summary", "")),
                    ptext(human_frequency_text(finding.get("frequency_hz_or_order"))),
                    ptext(human_amp_text(finding.get("amplitude_metric"))),
                    ptext(f"{((_as_float(finding.get('confidence_0_to_1')) or 0.0) * 100):.0f}%"),
                    human_list(finding.get("quick_checks")),
                ]
            )
    else:
        detailed_rows.append(
            [
                ptext(tr("NO_DIAGNOSTIC_FINDINGS")),
                ptext(tr("UNKNOWN")),
                ptext(tr("NO_FINDINGS_WERE_GENERATED_FROM_THE_AVAILABLE_DATA")),
                ptext(tr("REFERENCE_NOT_AVAILABLE")),
                ptext(tr("NOT_AVAILABLE")),
                ptext("0%"),
                ptext(tr("RECORD_ADDITIONAL_DATA")),
            ]
        )
    story.append(mk_table(detailed_rows, col_widths=[90, 84, 230, 118, 166, 58, 70], repeat_rows=1))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=24,
        rightMargin=24,
        topMargin=28,
        bottomMargin=22,
    )

    def draw_footer(canvas, document) -> None:  # pragma: no cover - formatting callback
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5a6778"))
        canvas.drawString(document.leftMargin, 12, tr("REPORT_FOOTER_TITLE"))
        canvas.drawRightString(
            page_size[0] - document.rightMargin,
            12,
            tr("PAGE_LABEL", page=canvas.getPageNumber()),
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()


def build_report_pdf(summary: dict[str, object]) -> bytes:
    try:
        return _reportlab_pdf(summary)
    except Exception:
        return _fallback_pdf(summary)
