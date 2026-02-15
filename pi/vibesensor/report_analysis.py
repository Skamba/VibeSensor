from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from math import sqrt
from pathlib import Path
from statistics import mean
from typing import Any

from .diagnostics_shared import ORDER_CLASS_KEYS, build_diagnostic_settings, classify_peak_hz
from .report_helpers import (
    as_float as _as_float,
)
from .report_helpers import (
    effective_engine_rpm as _effective_engine_rpm,
)
from .report_helpers import (
    mean_variance as _mean_variance,
)
from .report_helpers import (
    outlier_summary as _outlier_summary,
)
from .report_helpers import (
    percent_missing as _percent_missing,
)
from .report_helpers import (
    sensor_limit_g as _sensor_limit_g,
)
from .report_helpers import (
    speed_breakdown as _speed_breakdown,
)
from .report_helpers import (
    tire_reference_from_metadata as _tire_reference_from_metadata,
)
from .report_i18n import tr as _tr
from .runlog import parse_iso8601, read_jsonl_run

SPEED_COVERAGE_MIN_PCT = 35.0
SPEED_MIN_POINTS = 8


def _normalize_lang(lang: object) -> str:
    if isinstance(lang, str) and lang.strip().lower().startswith("nl"):
        return "nl"
    return "en"


def _format_duration(seconds: float) -> str:
    total = max(0.0, float(seconds))
    minutes = int(total // 60)
    rem = total - (minutes * 60)
    return f"{minutes:02d}:{rem:04.1f}"


def _required_text(value: object, consequence: str, lang: object = "en") -> str:
    if value in (None, "", []):
        return _tr(lang, "MISSING_CONSEQUENCE", consequence=consequence)
    return str(value)


def _load_run(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".jsonl":
        raise ValueError(f"Unsupported run format for report: {path.name}")
    run_data = read_jsonl_run(path)
    return dict(run_data.metadata), list(run_data.samples), []


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


def _diagnostic_settings_from_metadata(metadata: dict[str, Any]) -> dict[str, float]:
    return build_diagnostic_settings(
        {
            "tire_width_mm": metadata.get("tire_width_mm"),
            "tire_aspect_pct": metadata.get("tire_aspect_pct"),
            "rim_in": metadata.get("rim_in"),
            "final_drive_ratio": metadata.get("final_drive_ratio"),
            "current_gear_ratio": metadata.get("current_gear_ratio"),
            "wheel_bandwidth_pct": metadata.get("wheel_bandwidth_pct"),
            "driveshaft_bandwidth_pct": metadata.get("driveshaft_bandwidth_pct"),
            "engine_bandwidth_pct": metadata.get("engine_bandwidth_pct"),
            "speed_uncertainty_pct": metadata.get("speed_uncertainty_pct"),
            "tire_diameter_uncertainty_pct": metadata.get("tire_diameter_uncertainty_pct"),
            "final_drive_uncertainty_pct": metadata.get("final_drive_uncertainty_pct"),
            "gear_uncertainty_pct": metadata.get("gear_uncertainty_pct"),
            "min_abs_band_hz": metadata.get("min_abs_band_hz"),
            "max_band_half_width_pct": metadata.get("max_band_half_width_pct"),
        }
    )


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
    PeakPoint = tuple[float, float | None, float | None, str | None, str | None]
    freq_points: list[PeakPoint] = []
    for sample in samples:
        hz = _as_float(sample.get("dominant_freq_hz"))
        if hz is None or hz <= 0:
            continue
        amp = _as_float(sample.get("dominant_peak_amp_g"))
        speed = _as_float(sample.get("speed_kmh"))
        client_name_raw = str(sample.get("client_name") or "").strip()
        client_name = client_name_raw if client_name_raw else None
        client_id_raw = str(sample.get("client_id") or "").strip()
        client_id = client_id_raw if client_id_raw else None
        freq_points.append((hz, amp, speed, client_name, client_id))
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

    settings = _diagnostic_settings_from_metadata(metadata)
    class_scores: dict[str, float] = defaultdict(float)
    class_best: dict[str, dict[str, object]] = {}
    for hz, amp, speed_kmh, _client_name, _client_id in dominant_cluster:
        speed_mps = (speed_kmh / 3.6) if isinstance(speed_kmh, float) and speed_kmh > 0 else None
        classified = classify_peak_hz(peak_hz=hz, speed_mps=speed_mps, settings=settings)
        class_key = str(classified.get("key") or "other")
        weight = float(amp) if isinstance(amp, float) and amp > 0 else 1.0
        class_scores[class_key] += weight
        existing = class_best.get(class_key)
        rel_err = classified.get("rel_err")
        rel_err_num = float(rel_err) if isinstance(rel_err, (int, float)) else 999.0
        if existing is None:
            class_best[class_key] = {"payload": classified, "rel_err": rel_err_num}
        elif rel_err_num < float(existing.get("rel_err", 999.0)):
            class_best[class_key] = {"payload": classified, "rel_err": rel_err_num}

    dominant_class = max(class_scores.keys(), key=lambda key: class_scores[key])
    dominant_payload = class_best.get(dominant_class, {}).get("payload", {"key": "other"})
    suspected_source = str(dominant_payload.get("suspected_source") or "unknown")

    evidence = _tr(
        lang,
        "DOMINANT_FREQUENCY_CLUSTER_NEAR_CENTER_HZ_2F_HZ",
        center_hz=center_hz,
        count=len(dominant_cluster),
    )
    freq_or_order = f"{center_hz:.2f} Hz"
    quick_checks = [
        _tr(lang, "REPEAT_RUN_WITH_STABLE_ROUTE_AND_VERIFY_PEAK"),
        _tr(lang, "CROSS_CHECK_WITH_A_SECOND_SENSOR_LOCATION_TO"),
    ]
    falsifiers = [
        _tr(lang, "PEAK_DISAPPEARS_AFTER_SENSOR_REMOUNT_OR_CABLE_RESEAT"),
        _tr(lang, "PEAK_FREQUENCY_SHIFTS_RANDOMLY_WITH_NO_REPEATABLE_OPERATING"),
    ]
    reference_bonus = 0.0

    if dominant_class in {"wheel1", "wheel2"}:
        order_num = 1 if dominant_class == "wheel1" else 2
        rel_err = float(class_best[dominant_class]["rel_err"])
        tire_ref_note = (
            _tr(lang, "MEASURED_TIRE_CIRCUMFERENCE")
            if tire_reference_label == "metadata.tire_circumference_m"
            else _tr(lang, "TIRE_SIZE")
        )
        evidence = _tr(
            lang,
            "FREQUENCY_TRACKS_WHEEL_ORDER_USING_VEHICLE_SPEED_AND",
            tire_ref_note=tire_ref_note,
            best_order=order_num,
            best_error=rel_err,
        )
        freq_or_order = _tr(lang, "BEST_ORDER_X_WHEEL_ORDER", best_order=order_num)
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
    elif dominant_class in {"eng1", "eng2"} and engine_ref_sufficient:
        order_num = 1 if dominant_class == "eng1" else 2
        rel_err = float(class_best[dominant_class]["rel_err"])
        evidence = _tr(
            lang,
            "FREQUENCY_TRACKS_ENGINE_ORDER_USING_REF_LABEL_BEST",
            ref_label=_tr(lang, "ENGINE_RPM_ESTIMATED_FROM_VEHICLE_SPEED_AND_DRIVETRAIN"),
            best_order=order_num,
            best_error=rel_err,
        )
        freq_or_order = _tr(lang, "BEST_ORDER_X_ENGINE_ORDER", best_order=order_num)
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
    elif dominant_class == "road":
        suspected_source = "body resonance"
        quick_checks = [
            _tr(lang, "TAP_TEST_NEARBY_PANELS_SEATS_AND_COMPARE_RESONANCE"),
            _tr(lang, "ADD_TEMPORARY_DAMPING_MASS_AND_REPEAT_THE_RUN"),
        ]
        falsifiers = [
            _tr(lang, "FREQUENCY_SCALES_CLEARLY_WITH_WHEEL_OR_ENGINE_REFERENCES"),
            _tr(lang, "PEAK_VANISHES_WHEN_SENSOR_IS_MOVED_OFF_THE"),
        ]
        reference_bonus = 0.08
    elif dominant_class in ORDER_CLASS_KEYS:
        reference_bonus = 0.12
        order_label = str(dominant_payload.get("order_label") or "")
        if order_label:
            freq_or_order = order_label

    # Add location-based evidence so findings can point to the most likely physical source.
    location_amp_values: dict[str, list[float]] = defaultdict(list)
    observed_locations: set[str] = set()
    for _hz, amp, _speed, client_name, client_id in dominant_cluster:
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
    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        freq_or_order = _tr(lang, "REFERENCE_MISSING")

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


def build_findings_for_samples(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
) -> list[dict[str, object]]:
    language = _normalize_lang(lang)
    speed_values = [
        speed
        for speed in (_as_float(sample.get("speed_kmh")) for sample in samples)
        if speed is not None and speed > 0
    ]
    speed_non_null_pct = (len(speed_values) / len(samples) * 100.0) if samples else 0.0
    speed_sufficient = (
        speed_non_null_pct >= SPEED_COVERAGE_MIN_PCT and len(speed_values) >= SPEED_MIN_POINTS
    )
    raw_sample_rate_hz = _as_float(metadata.get("raw_sample_rate_hz"))
    return _build_findings(
        metadata=metadata,
        samples=samples,
        speed_sufficient=speed_sufficient,
        speed_non_null_pct=speed_non_null_pct,
        raw_sample_rate_hz=raw_sample_rate_hz,
        lang=language,
    )


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

    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang=language)

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
