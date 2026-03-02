"""Non-order persistent/transient frequency peak findings."""

from __future__ import annotations

from collections import defaultdict
from math import floor, log1p
from statistics import mean
from typing import Any

from vibesensor_core.vibration_strength import percentile
from vibesensor_core.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ...constants import MEMS_NOISE_FLOOR_G
from ...runlog import as_float_or_none as _as_float
from ..helpers import (
    _effective_baseline_floor,
    _estimate_strength_floor_amp_g,
    _location_label,
    _run_noise_baseline_g,
    _sample_top_peaks,
    _speed_bin_label,
)
from ..order_analysis import _i18n_ref
from ..phase_segmentation import DrivingPhase
from ._constants import (
    _NEGLIGIBLE_STRENGTH_MAX_DB,
    _SNR_LOG_DIVISOR,
)
from .speed_profile import _phase_to_str, _speed_profile_from_points

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
    """Classify a frequency peak as patterned/persistent/transient/baseline_noise.

    Categories:
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
    run_noise_baseline_g: float | None = None,
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
    total_location_sample_counts: dict[str, int] = defaultdict(int)
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
        _floor_raw = _estimate_strength_floor_amp_g(sample)
        floor_amp = _floor_raw if _floor_raw is not None else 0.0
        location = _location_label(sample, lang=lang)
        if location:
            total_locations.add(location)
            total_location_sample_counts[location] += 1
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
    if run_noise_baseline_g is None:
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

        # Per-location rescue: in multi-sensor runs, a single-sensor fault's
        # global presence_ratio is diluted by 1/n_sensors.  Compute the best
        # per-location presence ratio and use it when higher.
        if total_location_sample_counts and bin_location_counts.get(bin_center):
            loc_counts = bin_location_counts[bin_center]
            for loc in total_locations:
                loc_hits = loc_counts.get(loc, 0)
                loc_total = total_location_sample_counts.get(loc, 0)
                if loc_total >= 3:
                    loc_presence = loc_hits / loc_total
                    if loc_presence > presence_ratio:
                        presence_ratio = loc_presence

        median_amp = percentile(sorted_amps, 0.50) if count >= 2 else sorted_amps[0]
        p95_amp = percentile(sorted_amps, 0.95) if count >= 2 else sorted_amps[-1]
        max_amp = sorted_amps[-1]
        burstiness = (max_amp / median_amp) if median_amp > 1e-9 else 0.0

        mean_floor = mean(bin_floors.get(bin_center, [0.0])) if bin_floors.get(bin_center) else 0.0
        effective_floor = _effective_baseline_floor(run_noise_baseline_g, extra_fallback=mean_floor)
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

        snr_score = min(1.0, log1p(raw_snr) / _SNR_LOG_DIVISOR)
        location_counts = bin_location_counts.get(bin_center, {})
        spatial_concentration = (
            max(location_counts.values()) / count if location_counts and count > 0 else 1.0
        )
        spatial_penalty = (0.35 + 0.65 * spatial_concentration) if location_counts else 1.0

        # Confidence for persistent/patterned peaks (analogous to order confidence)
        peak_strength_db = canonical_vibration_db(
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
                confidence = min(confidence, 0.40)

        peak_speed_kmh, speed_window_kmh, derived_speed_band = _speed_profile_from_points(
            bin_speed_amp_pairs.get(bin_center, [])
        )
        speed_band = derived_speed_band or "-"

        evidence = _i18n_ref(
            "EVIDENCE_PEAK_PRESENT",
            freq=bin_center,
            pct=presence_ratio,
            p95=peak_strength_db,
            units="dB",
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
                "name": "vibration_strength_db",
                "value": peak_strength_db,
                "units": "dB",
                "definition": _i18n_ref("METRIC_VIBRATION_STRENGTH_DB"),
            },
            "confidence_0_to_1": confidence,
            "quick_checks": [],
            "peak_classification": peak_type,
            "phase_evidence": peak_phase_evidence,
            "evidence_metrics": {
                "presence_ratio": presence_ratio,
                "median_intensity_db": canonical_vibration_db(
                    peak_band_rms_amp_g=median_amp,
                    floor_amp_g=effective_floor,
                ),
                "p95_intensity_db": peak_strength_db,
                "max_intensity_db": canonical_vibration_db(
                    peak_band_rms_amp_g=max_amp,
                    floor_amp_g=effective_floor,
                ),
                "burstiness": burstiness,
                "mean_noise_floor_db": canonical_vibration_db(
                    peak_band_rms_amp_g=max(MEMS_NOISE_FLOOR_G, mean_floor),
                    floor_amp_g=MEMS_NOISE_FLOOR_G,
                ),
                "run_noise_baseline_db": (
                    canonical_vibration_db(
                        peak_band_rms_amp_g=max(MEMS_NOISE_FLOOR_G, run_noise_baseline_g),
                        floor_amp_g=MEMS_NOISE_FLOOR_G,
                    )
                    if run_noise_baseline_g is not None
                    else None
                ),
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
        finding["_ranking_score"] = ranking_score
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
