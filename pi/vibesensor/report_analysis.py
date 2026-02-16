from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil, floor, log1p, log10, sqrt
from pathlib import Path
from statistics import mean
from typing import Any

from .analysis_settings import tire_circumference_m_from_spec
from .report_i18n import tr as _tr
from .runlog import parse_iso8601, read_jsonl_run
from .strength_bands import bucket_for_strength

SPEED_BIN_WIDTH_KMH = 10
SPEED_COVERAGE_MIN_PCT = 35.0
SPEED_MIN_POINTS = 8

ORDER_TOLERANCE_REL = 0.08
ORDER_TOLERANCE_MIN_HZ = 0.5
ORDER_MIN_MATCH_POINTS = 4
ORDER_MIN_COVERAGE_POINTS = 6
STEADY_SPEED_STDDEV_KMH = 2.0
STEADY_SPEED_RANGE_KMH = 8.0


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


def _speed_stats(speed_values: list[float]) -> dict[str, float | None]:
    if not speed_values:
        return {
            "min_kmh": None,
            "max_kmh": None,
            "mean_kmh": None,
            "stddev_kmh": None,
            "range_kmh": None,
            "steady_speed": True,
        }
    vmin = min(speed_values)
    vmax = max(speed_values)
    vmean, var = _mean_variance(speed_values)
    stddev = sqrt(var)
    vrange = max(0.0, vmax - vmin)
    return {
        "min_kmh": vmin,
        "max_kmh": vmax,
        "mean_kmh": vmean,
        "stddev_kmh": stddev,
        "range_kmh": vrange,
        "steady_speed": stddev < STEADY_SPEED_STDDEV_KMH or vrange < STEADY_SPEED_RANGE_KMH,
    }


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
    eps = 1e-9
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        location = _location_label(sample)
        if not location:
            continue
        if include_locations is not None and location not in include_locations:
            continue
        sample_counts[location] += 1
        amp = _primary_vibration_amp(sample)
        if amp is not None and amp > 0:
            grouped_amp[location].append(float(amp))
        dropped_total = _as_float(sample.get("frames_dropped_total"))
        if dropped_total is None:
            dropped_total = _as_float(sample.get("dropped_frames"))
        if dropped_total is None:
            dropped_total = _as_float(sample.get("frames_dropped"))
        if dropped_total is not None:
            dropped_totals[location].append(dropped_total)
        overflow_total = _as_float(sample.get("queue_overflow_drops"))
        if overflow_total is not None:
            overflow_totals[location].append(overflow_total)
        peaks = _sample_top_peaks(sample)
        band_rms = peaks[0][1] if peaks else (_as_float(sample.get("dominant_peak_amp_g")) or amp)
        floor_amp = _as_float(sample.get("noise_floor_amp")) or 0.0
        # Approximate per-sample strength as peak-over-floor dB; epsilon avoids log/divide-by-zero.
        strength_db = 20.0 * log10((max(0.0, band_rms) + eps) / (max(0.0, floor_amp) + eps))
        bucket = bucket_for_strength(strength_db, max(0.0, band_rms))
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
        dropped_delta = (
            int(max(dropped_vals) - min(dropped_vals)) if len(dropped_vals) >= 2 else 0
        )
        overflow_delta = (
            int(max(overflow_vals) - min(overflow_vals)) if len(overflow_vals) >= 2 else 0
        )
        bucket_counts = strength_bucket_counts.get(
            location, {f"l{idx}": 0 for idx in range(1, 6)}
        )
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
            "mean_intensity_g": mean(values) if values else None,
            "p50_intensity_g": _percentile(values_sorted, 0.50) if values else None,
            "p95_intensity_g": _percentile(values_sorted, 0.95) if values else None,
            "max_intensity_g": max(values) if values else None,
                "dropped_frames_delta": dropped_delta,
                "queue_overflow_drops_delta": overflow_delta,
                "strength_bucket_distribution": bucket_distribution,
            }
        )
    rows.sort(
        key=lambda row: (
            float(row.get("p95_intensity_g") or 0.0),
            float(row.get("max_intensity_g") or 0.0),
        ),
        reverse=True,
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


def _locations_connected_throughout_run(samples: list[dict[str, Any]]) -> set[str]:
    by_location_times: dict[str, list[float]] = defaultdict(list)
    all_times: list[float] = []

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        location = _location_label(sample)
        if not location:
            continue
        t_s = _as_float(sample.get("t_s"))
        if t_s is None:
            continue
        by_location_times[location].append(t_s)
        all_times.append(t_s)

    if not by_location_times:
        return set()
    if not all_times:
        return set(by_location_times.keys())

    run_start = min(all_times)
    run_end = max(all_times)
    run_duration = max(0.0, run_end - run_start)
    edge_tolerance_s = max(0.75, min(3.0, run_duration * 0.08))

    counts_by_location = {
        location: len(times)
        for location, times in by_location_times.items()
    }
    max_count = max(counts_by_location.values()) if counts_by_location else 0
    min_required_count = int(max_count * 0.80) if max_count >= 5 else 1

    connected: set[str] = set()
    for location, times in by_location_times.items():
        if not times:
            continue
        if len(times) < min_required_count:
            continue
        loc_start = min(times)
        loc_end = max(times)
        if loc_start <= (run_start + edge_tolerance_s) and loc_end >= (run_end - edge_tolerance_s):
            connected.add(location)

    return connected if connected else set(by_location_times.keys())


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


def _wheel_focus_from_location(lang: object, location: str) -> str:
    token = location.strip().lower()
    if "front-left wheel" in token:
        return _text(lang, "front-left wheel", "linkervoorwiel")
    if "front-right wheel" in token:
        return _text(lang, "front-right wheel", "rechtervoorwiel")
    if "rear-left wheel" in token:
        return _text(lang, "rear-left wheel", "linkerachterwiel")
    if "rear-right wheel" in token:
        return _text(lang, "rear-right wheel", "rechterachterwiel")
    if "rear" in token or "trunk" in token:
        return _text(lang, "rear wheels", "achterwielen")
    if "front" in token or "engine" in token:
        return _text(lang, "front wheels", "voorwielen")
    return _text(lang, "all wheels", "alle wielen")


def _finding_actions_for_source(
    lang: object,
    source: str,
    *,
    strongest_location: str = "",
    strongest_speed_band: str = "",
    weak_spatial_separation: bool = False,
) -> list[dict[str, str]]:
    location = strongest_location.strip()
    speed_band = strongest_speed_band.strip()
    speed_hint = (
        _text(
            lang,
            f" with focus around {speed_band}",
            f" met focus rond {speed_band}",
        )
        if speed_band
        else ""
    )
    if source == "wheel/tire":
        wheel_focus = _wheel_focus_from_location(lang, location)
        location_hint = (
            _text(
                lang,
                f"Near the strongest location ({location}),",
                f"Nabij de sterkste locatie ({location}),",
            )
            if location
            else _text(lang, "At the wheel/tire corners,", "Bij de wiel/band-hoeken,")
        )
        return [
            {
                "action_id": "wheel_balance_and_runout",
                "what": _text(
                    lang,
                    f"Inspect and balance {wheel_focus}; measure radial/lateral runout on the wheel and tire{speed_hint}.",
                    f"Controleer en balanceer {wheel_focus}; meet radiale/laterale slingering op wiel en band{speed_hint}.",
                ),
                "why": _text(
                    lang,
                    f"{location_hint} wheel-order signatures are most likely caused by imbalance, runout, or tire deformation.",
                    f"{location_hint} wielorde-signaturen komen meestal door onbalans, slingering of banddeformatie.",
                ),
                "confirm": _text(
                    lang,
                    "A clear imbalance or runout is found and corrected, with vibration complaint reduced.",
                    "Er wordt duidelijke onbalans of slingering gevonden en gecorrigeerd, waarna de trillingsklacht afneemt.",
                ),
                "falsify": _text(
                    lang,
                    "Balance and runout are within spec on all checked wheels/tires and complaint remains unchanged.",
                    "Balans en slingering zijn binnen specificatie op alle gecontroleerde wielen/banden en de klacht blijft gelijk.",
                ),
                "eta": "20-45 min",
            },
            {
                "action_id": "wheel_tire_condition",
                "what": _text(
                    lang,
                    f"Inspect {wheel_focus} for tire defects: flat spots, belt shift, uneven wear, pressure mismatch.",
                    f"Controleer {wheel_focus} op banddefecten: vlakke plekken, gordelverschuiving, ongelijk slijtagebeeld, drukverschillen.",
                ),
                "why": _text(
                    lang,
                    "Tire structural issues often create strong 1x/2x wheel-order vibration.",
                    "Structurele bandproblemen veroorzaken vaak sterke 1x/2x wielorde-trillingen.",
                ),
                "confirm": _text(
                    lang,
                    "Visible/measureable tire defect aligns with complaint speed band.",
                    "Zichtbaar/meetbaar banddefect sluit aan op de klachten-snelheidsband.",
                ),
                "falsify": _text(
                    lang,
                    "No tire condition anomaly is found on inspected wheels.",
                    "Er wordt geen bandtoestandsafwijking gevonden op de gecontroleerde wielen.",
                ),
                "eta": "10-20 min",
            },
        ]
    if source == "driveline":
        driveline_focus = (
            _text(
                lang,
                f"near {location}",
                f"nabij {location}",
            )
            if location
            else _text(
                lang,
                "along the tunnel/rear driveline path",
                "langs de tunnel/achterste aandrijflijn",
            )
        )
        return [
            {
                "action_id": "driveline_inspection",
                "what": _text(
                    lang,
                    f"Inspect propshaft runout/balance, center support bearing, CV/guibo joints {driveline_focus}.",
                    f"Controleer cardanas slingering/balans, middenlager, homokineten/hardy-schijf {driveline_focus}.",
                ),
                "why": _text(
                    lang,
                    "Driveline-order vibration is commonly caused by shaft imbalance, joint wear, or support bearing issues.",
                    "Aandrijflijnorde-trillingen komen vaak door onbalans van de as, slijtage van koppelingen of problemen met het middenlager.",
                ),
                "confirm": _text(
                    lang,
                    "Mechanical defect or out-of-spec runout/play is found in driveline components.",
                    "Mechanisch defect of buiten-specificatie slingering/speling wordt gevonden in aandrijflijncomponenten.",
                ),
                "falsify": _text(
                    lang,
                    "No driveline play/runout/balance issue is found.",
                    "Er wordt geen aandrijflijn-issue in speling/slingering/balans gevonden.",
                ),
                "eta": "20-35 min",
            },
            {
                "action_id": "driveline_mounts_and_fasteners",
                "what": _text(
                    lang,
                    "Check driveline mounts and fastening torque (diff mounts, shaft couplings, carrier brackets).",
                    "Controleer aandrijflijnsteunen en aanhaalmomenten (diff-steunen, askoppelingen, draagbeugels).",
                ),
                "why": _text(
                    lang,
                    "Loose or degraded mounts can amplify normal order content into cabin vibration.",
                    "Losse of versleten steunen kunnen normale orde-inhoud versterken tot voelbare trillingen in de auto.",
                ),
                "confirm": _text(
                    lang,
                    "Loose mount/fastener or cracked rubber support is found.",
                    "Losse bevestiging of gescheurde rubbersteun wordt gevonden.",
                ),
                "falsify": _text(
                    lang,
                    "All inspected mounts and fasteners are within condition/torque spec.",
                    "Alle gecontroleerde steunen en bevestigingen zijn binnen conditie-/koppelspecificatie.",
                ),
                "eta": "10-20 min",
            },
        ]
    if source == "engine":
        return [
            {
                "action_id": "engine_mounts_and_accessories",
                "what": _text(
                    lang,
                    "Inspect engine mounts and accessory drive (idler, tensioner, pulleys) for play or resonance.",
                    "Controleer motorsteunen en hulpaandrijving (spanrol, geleiderol, poelies) op speling of resonantie.",
                ),
                "why": _text(
                    lang,
                    "Engine-order vibration often transfers through weakened mounts or accessory imbalance.",
                    "Motororde-trillingen worden vaak doorgegeven via verzwakte steunen of onbalans in hulpaandrijving.",
                ),
                "confirm": _text(
                    lang,
                    "A worn mount or accessory imbalance is identified.",
                    "Een versleten steun of onbalans in hulpaandrijving wordt vastgesteld.",
                ),
                "falsify": _text(
                    lang,
                    "Mounts and accessory drive are within acceptable condition.",
                    "Steunen en hulpaandrijving zijn binnen acceptabele conditie.",
                ),
                "eta": "15-30 min",
            },
            {
                "action_id": "engine_combustion_quality",
                "what": _text(
                    lang,
                    "Check misfire counters and fuel/ignition adaptation for cylinders contributing to roughness.",
                    "Controleer misfire-tellers en brandstof/ontsteking-adaptaties op cilinders die ruwloop veroorzaken.",
                ),
                "why": _text(
                    lang,
                    "Combustion imbalance can create engine-order vibration without obvious mechanical noise.",
                    "Verbrandingsonbalans kan motororde-trillingen geven zonder duidelijk mechanisch geluid.",
                ),
                "confirm": _text(
                    lang,
                    "Cylinder-specific deviation aligns with the vibration complaint.",
                    "Cilinderspecifieke afwijking sluit aan op de trillingsklacht.",
                ),
                "falsify": _text(
                    lang,
                    "Combustion quality indicators are stable and balanced.",
                    "Verbrandingskwaliteits-indicatoren zijn stabiel en gebalanceerd.",
                ),
                "eta": "10-20 min",
            },
        ]
    fallback_why = _text(
        lang,
        "Use direct mechanical checks first because source classification is not specific enough yet.",
        "Gebruik eerst directe mechanische controles omdat de bronclassificatie nog niet specifiek genoeg is.",
    )
    if weak_spatial_separation:
        fallback_why = _text(
            lang,
            "Spatial separation is weak, so prioritize broad underbody and mount checks before part replacement.",
            "Ruimtelijke scheiding is zwak, dus prioriteer brede onderstel- en steuncontroles vóór onderdeelvervanging.",
        )
    return [
        {
            "action_id": "general_mechanical_inspection",
            "what": _text(
                lang,
                "Inspect wheel bearings, suspension bushings, subframe mounts, and loose fasteners in the hotspot area.",
                "Controleer wiellagers, ophangrubbers, subframe-steunen en losse bevestigingen in de hotspot-zone.",
            ),
            "why": fallback_why,
            "confirm": _text(
                lang,
                "A clear mechanical issue is found at or near the hotspot.",
                "Een duidelijke mechanische afwijking wordt bij of nabij de hotspot gevonden.",
            ),
            "falsify": _text(
                lang,
                "No abnormal wear, play, or looseness is found.",
                "Er wordt geen abnormale slijtage, speling of losheid gevonden.",
            ),
            "eta": "20-35 min",
        }
    ]


def _merge_test_plan(
    findings: list[dict[str, object]],
    lang: object,
) -> list[dict[str, object]]:
    # Priority ordering: inspection/visual first, then balance/runout, then deeper
    ACTION_PRIORITY = {
        "wheel_tire_condition": 1,       # visual inspection – least invasive
        "wheel_balance_and_runout": 2,    # balance/runout check
        "engine_mounts_and_accessories": 3,
        "driveline_mounts_and_fasteners": 3,
        "driveline_inspection": 4,
        "engine_combustion_quality": 5,
        "general_mechanical_inspection": 6,
    }
    steps: list[dict[str, object]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding_confidence = _as_float(finding.get("confidence_0_to_1"))
        finding_speed_band = str(finding.get("strongest_speed_band") or "").strip()
        finding_frequency = str(finding.get("frequency_hz_or_order") or "").strip()
        actions = finding.get("actions")
        if isinstance(actions, list) and actions:
            for step in actions:
                if not isinstance(step, dict):
                    continue
                enriched_step = dict(step)
                if finding_confidence is not None:
                    enriched_step.setdefault("certainty_0_to_1", f"{finding_confidence:.4f}")
                if finding_speed_band:
                    enriched_step.setdefault("speed_band", finding_speed_band)
                if finding_frequency:
                    enriched_step.setdefault("frequency_hz_or_order", finding_frequency)
                steps.append(enriched_step)
            continue
        source = str(finding.get("suspected_source") or "").strip().lower()
        generated_steps = _finding_actions_for_source(
            lang,
            source,
            strongest_location=str(finding.get("strongest_location") or ""),
            strongest_speed_band=str(finding.get("strongest_speed_band") or ""),
            weak_spatial_separation=bool(finding.get("weak_spatial_separation")),
        )
        for step in generated_steps:
            enriched_step = dict(step)
            if finding_confidence is not None:
                enriched_step.setdefault("certainty_0_to_1", f"{finding_confidence:.4f}")
            if finding_speed_band:
                enriched_step.setdefault("speed_band", finding_speed_band)
            if finding_frequency:
                enriched_step.setdefault("frequency_hz_or_order", finding_frequency)
            steps.append(enriched_step)

    dedup: dict[str, dict[str, object]] = {}
    ordered: list[dict[str, object]] = []
    for step in steps:
        action_id = str(step.get("action_id") or "").strip().lower()
        if not action_id:
            continue
        if action_id in dedup:
            continue
        dedup[action_id] = step
        ordered.append(step)

    # Sort by priority (least-invasive first), then preserve original order as tiebreak
    ordered.sort(key=lambda s: ACTION_PRIORITY.get(
        str(s.get("action_id") or "").strip().lower(), 99
    ))

    if ordered:
        return ordered[:5]
    return [
        {
            "action_id": "general_mechanical_inspection",
            "what": _text(
                lang,
                "Inspect wheel bearings, suspension bushings, subframe mounts, and loose fasteners in the vibration path.",
                "Controleer wiellagers, ophangrubbers, subframe-steunen en losse bevestigingen in het trillingspad.",
            ),
            "why": _text(
                lang,
                "No specific source could be ranked with enough confidence.",
                "Er kon geen specifieke bron met voldoende betrouwbaarheid worden gerangschikt.",
            ),
            "confirm": _text(
                lang,
                "A concrete mechanical issue is identified.",
                "Een concrete mechanische afwijking wordt vastgesteld.",
            ),
            "falsify": _text(
                lang,
                "No abnormal play, wear, or looseness is detected.",
                "Er wordt geen abnormale speling, slijtage of losheid gedetecteerd.",
            ),
            "eta": "20-35 min",
        }
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
            "weak_spatial_separation": dominance < 1.2,
        }
        if best is None or float(candidate["mean_amp"]) > float(best["mean_amp"]):
            best = candidate

    if best is None:
        return "", None

    sentence = _text(
        lang,
        (
            "Strongest at {location} in {speed_range} "
            "(~{dominance:.2f}x vs next location in that speed bin{weak_note})."
        ),
        (
            "Sterkst bij {location} in {speed_range} "
            "(~{dominance:.2f}x t.o.v. volgende locatie in die snelheidsband{weak_note})."
        ),
    ).format(
        location=best["location"],
        speed_range=best["speed_range"],
        dominance=float(best["dominance_ratio"]),
        weak_note=(
            _text(lang, ", weak spatial separation", ", zwakke ruimtelijke scheiding")
            if bool(best.get("weak_spatial_separation"))
            else ""
        ),
    )
    return sentence, best


def _build_order_findings(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    speed_sufficient: bool,
    steady_speed: bool,
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
    return [item[1] for item in findings[:3]]


def _build_findings(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    speed_sufficient: bool,
    steady_speed: bool,
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
            steady_speed=steady_speed,
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
    # Only consider non-reference findings
    diag_findings = [
        f for f in findings
        if isinstance(f, dict) and not str(f.get("finding_id", "")).startswith("REF_")
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
        label_key, tone, pct_text = confidence_label(
            float(rep.get("confidence_0_to_1") or 0)
        )
        result.append({
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
        })
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
        speed_non_null_pct=speed_non_null_pct,
        raw_sample_rate_hz=raw_sample_rate_hz,
        lang=language,
    )


def summarize_log(
    log_path: Path, lang: str | None = None, include_samples: bool = True
) -> dict[str, object]:
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
        steady_speed=bool(speed_stats.get("steady_speed")),
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
