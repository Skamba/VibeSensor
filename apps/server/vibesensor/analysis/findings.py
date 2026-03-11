"""Findings: speed profiles, persistence scoring, intensity stats, and orchestration.

Consolidates the former ``findings_speed_profile``, ``findings_builder_support``,
``findings_persistent``, ``findings_intensity``, and ``findings_builder`` modules.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from math import floor as _math_floor
from math import log1p

from vibesensor.vibration_strength import percentile
from vibesensor.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ..constants import (
    MEMS_NOISE_FLOOR_G,
    NEGLIGIBLE_STRENGTH_MAX_DB,
    ORDER_SUPPRESS_PERSISTENT_MIN_CONF,
    SNR_LOG_DIVISOR,
    SPEED_COVERAGE_MIN_PCT,
)
from ..domain_models import as_float_or_none as _as_float
from ._types import (
    Finding,
    FindingEvidenceMetrics,
    IntensityRow,
    JsonObject,
    JsonValue,
    MetadataDict,
    PhaseEvidence,
    PhaseLabels,
    PhaseSpeedBreakdownRow,
    Sample,
    SpeedBreakdownRow,
    i18n_ref,
)
from .helpers import (
    _effective_baseline_floor,
    _effective_engine_rpm,
    _estimate_strength_floor_amp_g,
    _location_label,
    _locations_connected_throughout_run,
    _phase_to_str,
    _primary_vibration_strength_db,
    _run_noise_baseline_g,
    _sample_top_peaks,
    _speed_bin_label,
    _speed_bin_sort_key,
    _speed_profile_from_points,
    _tire_reference_from_metadata,
    counter_delta,
)
from .order_analysis import _build_order_findings
from .phase_segmentation import (
    DrivingPhase,
    diagnostic_sample_mask,
    segment_run_phases,
)
from .top_cause_selection import finding_sort_key

# ---------------------------------------------------------------------------
# Builder support helpers
# ---------------------------------------------------------------------------


_MIN_DIAGNOSTIC_SAMPLES = 5

_REF_MISSING: dict[str, str] = {"_i18n_key": "REFERENCE_MISSING"}
_REF_MISSING_AMPLITUDE: dict[str, str] = {
    "_i18n_key": "REFERENCE_MISSING_ORDER_SPECIFIC_AMPLITUDE_RANKING_SKIPPED",
}


def _reference_missing_finding(
    *,
    finding_id: str,
    suspected_source: str,
    evidence_summary: JsonValue,
    quick_checks: list[JsonValue],
) -> Finding:
    return {
        "finding_id": finding_id,
        "finding_type": "reference",
        "suspected_source": suspected_source,
        "evidence_summary": evidence_summary,
        "frequency_hz_or_order": {**_REF_MISSING},
        "amplitude_metric": {
            "name": "not_available",
            "value": None,
            "units": "n/a",
            "definition": {**_REF_MISSING_AMPLITUDE},
        },
        "confidence": None,
        "quick_checks": quick_checks[:3],
    }


def build_reference_findings(
    *,
    metadata: MetadataDict,
    samples: list[Sample],
    speed_sufficient: bool,
    speed_non_null_pct: float,
    tire_circumference_m: float | None,
    raw_sample_rate_hz: float | None,
) -> tuple[list[Finding], bool]:
    """Build reference-missing findings and return engine reference sufficiency."""
    findings: list[Finding] = []
    if not speed_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SPEED",
                suspected_source="unknown",
                evidence_summary=i18n_ref(
                    "VEHICLE_SPEED_COVERAGE_IS_SPEED_NON_NULL_PCT",
                    speed_non_null_pct=speed_non_null_pct,
                    threshold=SPEED_COVERAGE_MIN_PCT,
                ),
                quick_checks=[
                    i18n_ref("RECORD_VEHICLE_SPEED_FOR_MOST_SAMPLES_GPS_OR"),
                    i18n_ref("VERIFY_TIMESTAMP_ALIGNMENT_BETWEEN_SPEED_AND_ACCELERATION_STREAM"),
                ],
            ),
        )

    if speed_sufficient and not (tire_circumference_m and tire_circumference_m > 0):
        findings.append(
            _reference_missing_finding(
                finding_id="REF_WHEEL",
                suspected_source="wheel/tire",
                evidence_summary=i18n_ref(
                    "VEHICLE_SPEED_IS_AVAILABLE_BUT_TIRE_CIRCUMFERENCE_REFERENCE",
                ),
                quick_checks=[
                    i18n_ref("PROVIDE_TIRE_CIRCUMFERENCE_OR_TIRE_SIZE_WIDTH_ASPECT"),
                    i18n_ref("RE_RUN_WITH_MEASURED_LOADED_TIRE_CIRCUMFERENCE"),
                ],
            ),
        )

    engine_ref_sufficient = has_engine_reference(
        samples,
        metadata=metadata,
        tire_circumference_m=tire_circumference_m,
    )
    if not engine_ref_sufficient:
        engine_rpm_non_null_pct = engine_reference_coverage_pct(
            samples,
            metadata=metadata,
            tire_circumference_m=tire_circumference_m,
        )
        findings.append(
            _reference_missing_finding(
                finding_id="REF_ENGINE",
                suspected_source="engine",
                evidence_summary=i18n_ref(
                    "ENGINE_SPEED_REFERENCE_COVERAGE_IS_ENGINE_RPM_NON",
                    engine_rpm_non_null_pct=engine_rpm_non_null_pct,
                ),
                quick_checks=[
                    i18n_ref("LOG_ENGINE_RPM_FROM_CAN_OBD_FOR_THE"),
                    i18n_ref("KEEP_TIMESTAMP_BASE_SHARED_WITH_ACCELEROMETER_AND_SPEED"),
                ],
            ),
        )

    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SAMPLE_RATE",
                suspected_source="unknown",
                evidence_summary=i18n_ref("RAW_ACCELEROMETER_SAMPLE_RATE_IS_MISSING_SO_DOMINANT"),
                quick_checks=[i18n_ref("RECORD_THE_TRUE_ACCELEROMETER_SAMPLE_RATE_IN_RUN")],
            ),
        )
    return findings, engine_ref_sufficient


def engine_reference_coverage_pct(
    samples: list[Sample],
    *,
    metadata: MetadataDict,
    tire_circumference_m: float | None,
) -> float:
    """Compute engine reference coverage percentage from samples and metadata."""
    engine_ref_count = sum(
        1
        for sample in samples
        if ((_effective_engine_rpm(sample, metadata, tire_circumference_m))[0] or 0) > 0
    )
    return (engine_ref_count / len(samples) * 100.0) if samples else 0.0


def has_engine_reference(
    samples: list[Sample],
    *,
    metadata: MetadataDict,
    tire_circumference_m: float | None,
) -> bool:
    """Return whether the engine reference coverage is sufficient."""
    pct: float = engine_reference_coverage_pct(
        samples,
        metadata=metadata,
        tire_circumference_m=tire_circumference_m,
    )
    return bool(pct >= SPEED_COVERAGE_MIN_PCT)


def prepare_analysis_samples(
    samples: list[Sample],
    *,
    per_sample_phases: PhaseLabels | None,
) -> tuple[list[Sample], Sequence[DrivingPhase], list[DrivingPhase], bool]:
    """Prepare filtered samples and aligned phase labels for findings analysis."""
    if per_sample_phases is not None and len(per_sample_phases) == len(samples):
        resolved_phases: list[DrivingPhase] = [
            phase if isinstance(phase, DrivingPhase) else DrivingPhase(str(phase))
            for phase in per_sample_phases
        ]
    else:
        resolved_phases, _ = segment_run_phases(samples)

    diagnostic_mask = diagnostic_sample_mask(resolved_phases)
    diagnostic_samples = [
        sample for sample, keep in zip(samples, diagnostic_mask, strict=True) if keep
    ]
    use_filtered_samples = len(diagnostic_samples) >= _MIN_DIAGNOSTIC_SAMPLES
    analysis_samples = diagnostic_samples if use_filtered_samples else samples
    if analysis_samples is diagnostic_samples:
        analysis_phases: Sequence[DrivingPhase] = [
            phase for phase, keep in zip(resolved_phases, diagnostic_mask, strict=True) if keep
        ]
    else:
        analysis_phases = list(resolved_phases)
    return analysis_samples, analysis_phases, resolved_phases, use_filtered_samples


def collect_order_frequencies(order_findings: list[Finding]) -> set[float]:
    """Collect matched order frequencies used to suppress duplicate persistent findings."""
    order_freqs: set[float] = set()
    for order_finding in order_findings:
        if (_as_float(order_finding.get("confidence")) or 0.0) < ORDER_SUPPRESS_PERSISTENT_MIN_CONF:
            continue
        points = order_finding.get("matched_points")
        if not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, dict):
                continue
            matched_hz = _as_float(point.get("matched_hz"))
            if matched_hz is not None and matched_hz > 0:
                order_freqs.add(matched_hz)
    return order_freqs


def finalize_findings(findings: list[Finding]) -> list[Finding]:
    """Partition, rank, and assign stable public finding IDs."""
    reference_findings: list[Finding] = []
    diagnostic_findings: list[Finding] = []
    informational_findings: list[Finding] = []
    for item in findings:
        finding_id = str(item.get("finding_id", ""))
        if finding_id.startswith("REF_"):
            reference_findings.append(item)
        elif str(item.get("severity") or "").strip().lower() == "info":
            informational_findings.append(item)
        else:
            diagnostic_findings.append(item)

    diagnostic_findings.sort(key=finding_sort_key, reverse=True)
    informational_findings.sort(key=finding_sort_key, reverse=True)
    ordered_findings = reference_findings + diagnostic_findings + informational_findings
    diag_counter = 0
    for finding in ordered_findings:
        finding_id = str(finding.get("finding_id", "")).strip()
        if not finding_id.startswith("REF_"):
            diag_counter += 1
            finding["finding_id"] = f"F{diag_counter:03d}"
    return ordered_findings


# ---------------------------------------------------------------------------
# Non-order persistent/transient frequency peak findings
# ---------------------------------------------------------------------------


PERSISTENT_PEAK_MIN_PRESENCE = 0.15

# Hoisted from per-bin loop to avoid repeated enum attribute access.
_CRUISE_PHASE_VAL: str = DrivingPhase.CRUISE.value
TRANSIENT_BURSTINESS_THRESHOLD = 5.0
PERSISTENT_PEAK_MAX_FINDINGS = 3
# Minimum SNR for a peak to be considered above baseline noise
BASELINE_NOISE_SNR_THRESHOLD = 1.5

# ── Peak classification thresholds ───────────────────────────────────────
# High spatial uniformity: present across most sensor locations → likely noise.
_SPATIAL_UNIFORMITY_HIGH = 0.85
# Medium spatial uniformity: used with speed-uniformity check.
_SPATIAL_UNIFORMITY_MED = 0.80
# Presence ratio below which a "high spatial uniformity" peak is noise.
_NOISE_PRESENCE_MIN_HIGH = 0.60
# Burstiness ceiling for "spatially uniform + high presence" noise check.
_NOISE_BURSTINESS_MAX_LOW = 2.0
# Speed-uniformity (std-dev) ceiling: flat across speed bins → noise.
_NOISE_SPEED_UNIFORMITY_MAX = 0.10
# Presence band for the "medium spatial + low speed variance" noise check.
_NOISE_PRESENCE_LOW_MIN = 0.20
_NOISE_PRESENCE_LOW_MAX = 0.40
# Burstiness band for the "medium spatial + low speed variance" noise check.
_NOISE_BURSTINESS_BAND_MIN = 3.0
_NOISE_BURSTINESS_BAND_MAX = 5.0
# Minimum presence and maximum burstiness for a "patterned" peak.
_PATTERNED_MIN_PRESENCE = 0.40
_PATTERNED_MAX_BURSTINESS = 3.0


# ---------------------------------------------------------------------------
# Frequency-bin accumulation helpers
# ---------------------------------------------------------------------------


def _make_nested_int_defaultdict() -> defaultdict:
    """Create a nested defaultdict(int).

    Use as ``defaultdict(_make_nested_int_defaultdict)`` to get a
    two-level defaultdict where inner values are ints.
    """
    return defaultdict(int)


class _PeakBinStats:
    """Accumulated per-frequency-bin statistics collected from samples.

    Populated by :func:`_accumulate_peak_bin_stats` and consumed by the
    per-bin scoring loop inside :func:`_build_persistent_peak_findings`.
    """

    __slots__ = (
        "bin_amps",
        "bin_floors",
        "bin_location_counts",
        "bin_phase_counts",
        "bin_speed_amp_pairs",
        "bin_speed_bin_counts",
        "bin_speeds",
        "n_samples",
        "total_location_sample_counts",
        "total_locations",
        "total_speed_bin_counts",
    )

    def __init__(self) -> None:
        self.bin_amps: dict[float, list[float]] = defaultdict(list)
        self.bin_floors: dict[float, list[float]] = defaultdict(list)
        self.bin_speeds: dict[float, list[float]] = defaultdict(list)
        self.bin_speed_amp_pairs: dict[float, list[tuple[float, float]]] = defaultdict(list)
        _dd_factory = _make_nested_int_defaultdict
        self.bin_location_counts: dict[float, dict[str, int]] = defaultdict(_dd_factory)
        self.bin_speed_bin_counts: dict[float, dict[str, int]] = defaultdict(_dd_factory)
        self.bin_phase_counts: dict[float, dict[str, int]] = defaultdict(_dd_factory)
        self.total_speed_bin_counts: dict[str, int] = defaultdict(int)
        self.total_locations: set[str] = set()
        self.total_location_sample_counts: dict[str, int] = defaultdict(int)
        self.n_samples: int = 0


def _accumulate_peak_bin_stats(
    samples: list[Sample],
    *,
    freq_bin_hz: float,
    freq_bin_hz_half: float,
    lang: str,
    per_sample_phases: PhaseLabels | None,
    has_phases: bool,
) -> _PeakBinStats:
    """Accumulate per-sample data into frequency-bin statistics.

    Iterates over every sample once and distributes peak amplitudes,
    location/speed/phase counts into their corresponding frequency bins.
    Returns a :class:`_PeakBinStats` that the caller then uses to score each
    bin.
    """
    stats = _PeakBinStats()

    # Local-bind frequently called helpers to avoid repeated global lookups.
    _local_as_float = _as_float
    _local_speed_bin = _speed_bin_label
    _local_location = _location_label
    _local_top_peaks = _sample_top_peaks
    _local_floor_est = _estimate_strength_floor_amp_g
    _local_phase_str = _phase_to_str
    _floor = _math_floor

    for i, sample in enumerate(samples):
        if not isinstance(sample, dict):
            continue
        stats.n_samples += 1
        speed = _local_as_float(sample.get("speed_kmh"))
        sample_speed_bin = _local_speed_bin(speed) if speed is not None and speed > 0 else None
        if sample_speed_bin is not None:
            stats.total_speed_bin_counts[sample_speed_bin] += 1
        _floor_raw = _local_floor_est(sample)
        floor_amp = _floor_raw if _floor_raw is not None else 0.0
        location = _local_location(sample, lang=lang)
        if location:
            stats.total_locations.add(location)
            stats.total_location_sample_counts[location] += 1
        sample_phase: str | None = None
        if has_phases and per_sample_phases is not None and i < len(per_sample_phases):
            sample_phase = _local_phase_str(per_sample_phases[i])
        for hz, amp in _local_top_peaks(sample):
            if hz <= 0 or amp <= 0:
                continue
            bin_center = _floor(hz / freq_bin_hz) * freq_bin_hz + freq_bin_hz_half
            stats.bin_amps[bin_center].append(amp)
            stats.bin_floors[bin_center].append(max(0.0, floor_amp))
            if speed is not None and speed > 0:
                stats.bin_speeds[bin_center].append(speed)
                stats.bin_speed_amp_pairs[bin_center].append((speed, amp))
            if location:
                stats.bin_location_counts[bin_center][location] += 1
            if sample_speed_bin is not None:
                stats.bin_speed_bin_counts[bin_center][sample_speed_bin] += 1
            if sample_phase is not None:
                stats.bin_phase_counts[bin_center][sample_phase] += 1

    return stats


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
        and spatial_uniformity > _SPATIAL_UNIFORMITY_HIGH
        and presence_ratio >= _NOISE_PRESENCE_MIN_HIGH
        and burstiness < _NOISE_BURSTINESS_MAX_LOW
    ):
        return "baseline_noise"
    if (
        spatial_uniformity is not None
        and speed_uniformity is not None
        and spatial_uniformity >= _SPATIAL_UNIFORMITY_MED
        and speed_uniformity <= _NOISE_SPEED_UNIFORMITY_MAX
        and _NOISE_PRESENCE_LOW_MIN <= presence_ratio <= _NOISE_PRESENCE_LOW_MAX
        and _NOISE_BURSTINESS_BAND_MIN <= burstiness <= _NOISE_BURSTINESS_BAND_MAX
    ):
        return "baseline_noise"

    if presence_ratio < PERSISTENT_PEAK_MIN_PRESENCE:
        return "transient"
    if burstiness > TRANSIENT_BURSTINESS_THRESHOLD:
        return "transient"
    if presence_ratio >= _PATTERNED_MIN_PRESENCE and burstiness < _PATTERNED_MAX_BURSTINESS:
        return "patterned"
    return "persistent"


def _build_persistent_peak_findings(
    *,
    samples: list[Sample],
    order_finding_freqs: set[float],
    lang: str,
    freq_bin_hz: float = 2.0,
    per_sample_phases: PhaseLabels | None = None,
    run_noise_baseline_g: float | None = None,
) -> list[Finding]:
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
    freq_bin_hz_half = freq_bin_hz * 0.5

    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)
    stats = _accumulate_peak_bin_stats(
        samples,
        freq_bin_hz=freq_bin_hz,
        freq_bin_hz_half=freq_bin_hz_half,
        lang=lang,
        per_sample_phases=per_sample_phases,
        has_phases=has_phases,
    )
    n_samples = stats.n_samples
    bin_amps = stats.bin_amps
    bin_floors = stats.bin_floors
    bin_speed_amp_pairs = stats.bin_speed_amp_pairs
    bin_location_counts = stats.bin_location_counts
    bin_speed_bin_counts = stats.bin_speed_bin_counts
    bin_phase_counts = stats.bin_phase_counts
    total_speed_bin_counts = stats.total_speed_bin_counts
    total_locations = stats.total_locations
    total_location_sample_counts = stats.total_location_sample_counts

    if n_samples == 0:
        return []
    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(samples)

    persistent_findings: list[tuple[float, Finding]] = []
    transient_findings: list[tuple[float, Finding]] = []

    for bin_center, amps in bin_amps.items():
        # Skip bins already claimed by order findings.
        # Exclusion radius = one full bin width (freq_bin_hz).  Bin centers are
        # at multiples of freq_bin_hz offset by freq_bin_hz_half, so adjacent
        # bins are always exactly freq_bin_hz apart; using the full width ensures
        # the bin containing the matched order frequency is suppressed while
        # leaving all other bins unaffected.
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
                    presence_ratio = max(presence_ratio, loc_presence)

        median_amp = percentile(sorted_amps, 0.50) if count >= 2 else sorted_amps[0]
        p95_amp = percentile(sorted_amps, 0.95) if count >= 2 else sorted_amps[-1]
        max_amp = sorted_amps[-1]
        burstiness = (max_amp / median_amp) if median_amp > 1e-9 else 0.0

        mean_floor_vals = bin_floors.get(bin_center)
        mean_floor = sum(mean_floor_vals) / len(mean_floor_vals) if mean_floor_vals else 0.0
        effective_floor = _effective_baseline_floor(run_noise_baseline_g, extra_fallback=mean_floor)
        raw_snr = p95_amp / effective_floor

        # Cache per-bin dict lookups used multiple times below.
        loc_counts_for_bin = bin_location_counts.get(bin_center, {})
        speed_bin_counts_for_bin = bin_speed_bin_counts.get(bin_center, {})
        phases_for_bin = bin_phase_counts.get(bin_center, {})

        spatial_uniformity: float | None = None
        n_total_locs = len(total_locations)
        if n_total_locs >= 2:
            spatial_uniformity = len(loc_counts_for_bin) / n_total_locs

        speed_uniformity: float | None = None
        if len(total_speed_bin_counts) >= 2:
            # Single-pass mean + variance to avoid two iterations.
            hr_sum = 0.0
            hr_sq_sum = 0.0
            hr_n = 0
            for speed_bin, total_count in total_speed_bin_counts.items():
                if total_count <= 0:
                    continue
                rate = speed_bin_counts_for_bin.get(speed_bin, 0) / total_count
                hr_sum += rate
                hr_sq_sum += rate * rate
                hr_n += 1
            if hr_n > 1:
                hr_mean = hr_sum / hr_n
                # Clamp before sqrt: floating-point subtraction can yield a
                # tiny negative value (e.g. -2e-16) that would raise ValueError.
                speed_uniformity = max(0.0, (hr_sq_sum / hr_n) - hr_mean * hr_mean) ** 0.5
            elif hr_n == 1:
                speed_uniformity = 0.0

        peak_type = _classify_peak_type(
            presence_ratio,
            burstiness,
            snr=raw_snr,
            spatial_uniformity=spatial_uniformity,
            speed_uniformity=speed_uniformity,
        )

        snr_score = min(1.0, log1p(raw_snr) / SNR_LOG_DIVISOR)
        spatial_concentration = (
            max(loc_counts_for_bin.values()) / count if loc_counts_for_bin and count > 0 else 1.0
        )
        spatial_penalty = (0.35 + 0.65 * spatial_concentration) if loc_counts_for_bin else 1.0

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
            if loc_counts_for_bin and spatial_concentration <= 0.35:
                confidence = min(confidence, 0.35)
            if peak_strength_db < NEGLIGIBLE_STRENGTH_MAX_DB:
                confidence = min(confidence, 0.40)

        peak_speed_kmh, speed_window_kmh, derived_speed_band = _speed_profile_from_points(
            bin_speed_amp_pairs.get(bin_center, []),
        )
        speed_band = derived_speed_band or "-"

        evidence = i18n_ref(
            "EVIDENCE_PEAK_PRESENT",
            freq=bin_center,
            pct=presence_ratio,
            p95=peak_strength_db,
            units="dB",
            burst=burstiness,
            cls=peak_type,
        )

        # Compute phase evidence for this frequency bin.
        _total_phase_hits = sum(phases_for_bin.values())
        _cruise_hits = phases_for_bin.get(_CRUISE_PHASE_VAL, 0)
        peak_phase_evidence: PhaseEvidence = {
            "cruise_fraction": _cruise_hits / _total_phase_hits if _total_phase_hits > 0 else 0.0,
            "phases_detected": sorted(k for k, v in phases_for_bin.items() if v > 0),
        }
        phase_presence: dict[str, float] | None = None
        if has_phases and _total_phase_hits > 0:
            phase_presence = {
                phase_key: phase_hits / _total_phase_hits
                for phase_key, phase_hits in phases_for_bin.items()
                if phase_hits > 0
            }

        evidence_metrics: FindingEvidenceMetrics = {
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
        }
        finding: Finding = {
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
                "definition": i18n_ref("METRIC_VIBRATION_STRENGTH_DB"),
            },
            "confidence": confidence,
            "quick_checks": [],
            "peak_classification": peak_type,
            "phase_evidence": peak_phase_evidence,
            "evidence_metrics": evidence_metrics,
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

    results: list[Finding] = []
    for _score, finding in persistent_findings[:PERSISTENT_PEAK_MAX_FINDINGS]:
        results.append(finding)
    for _score, finding in transient_findings[:PERSISTENT_PEAK_MAX_FINDINGS]:
        results.append(finding)
    return results


# ---------------------------------------------------------------------------
# Per-location intensity statistics and speed/phase breakdowns
# ---------------------------------------------------------------------------


def _mean(vals: list[float]) -> float:
    """Arithmetic mean for non-empty float lists (faster than statistics.mean)."""
    return sum(vals) / len(vals)


_MIN_COUNTER_PAIRS = 2
"""Minimum number of (timestamp, value) pairs needed to compute a counter delta."""


def _counter_delta(counter_values: list[tuple[float | None, float]]) -> int:
    """Sort timestamped counter pairs and delegate to shared helper."""
    if len(counter_values) < _MIN_COUNTER_PAIRS:
        return 0
    ordered = sorted(
        counter_values,
        # Treat NaN timestamps like None (sort last) to avoid undefined
        # comparison behaviour: Python's sort uses < internally, and
        # nan < x is False for all x, so NaN can end up anywhere in the
        # sort order.  Both None and NaN are non-informative timestamps;
        # placing them last keeps the meaningful (finite) timestamps first.
        key=lambda pair: (
            pair[0] is None or not math.isfinite(pair[0]),
            pair[0] if (pair[0] is not None and math.isfinite(pair[0])) else 0.0,
        ),
    )
    return counter_delta([float(v) for _t, v in ordered])


_EMPTY_BUCKET_COUNTS: dict[str, int] = {f"l{idx}": 0 for idx in range(6)}


def _phase_speed_breakdown(
    samples: list[Sample],
    per_sample_phases: list[DrivingPhase],
) -> list[PhaseSpeedBreakdownRow]:
    """Group vibration statistics by driving phase (temporal context).

    Unlike ``_speed_breakdown`` which bins by speed magnitude, this function
    groups by the temporal driving phase (IDLE, ACCELERATION, CRUISE, etc.)
    so callers can see how vibration differs across phases at the same speed.

    Addresses issue #189: adds temporal phase context to speed breakdown.
    """
    grouped_amp: dict[str, list[float]] = defaultdict(list)
    grouped_speeds: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)

    _as_float_local = _as_float
    _vib_db = _primary_vibration_strength_db
    n_phases = len(per_sample_phases)
    for idx, sample in enumerate(samples):
        phase = per_sample_phases[idx] if idx < n_phases else "unknown"
        phase_key = _phase_to_str(phase) or "unknown"
        counts[phase_key] += 1
        speed = _as_float_local(sample.get("speed_kmh"))
        if speed is not None and speed > 0:
            grouped_speeds[phase_key].append(speed)
        amp = _vib_db(sample)
        if amp is not None:
            grouped_amp[phase_key].append(amp)

    # Output in a canonical phase order
    phase_order = [p.value for p in DrivingPhase]
    phase_order_set = set(phase_order)
    rows: list[PhaseSpeedBreakdownRow] = []
    for phase_key in [*phase_order, *sorted(k for k in counts if k not in phase_order_set)]:
        if phase_key not in counts:
            continue
        amp_vals = grouped_amp.get(phase_key, [])
        speed_vals = grouped_speeds.get(phase_key, [])
        rows.append(
            {
                "phase": phase_key,
                "count": counts[phase_key],
                "mean_speed_kmh": _mean(speed_vals) if speed_vals else None,
                "max_speed_kmh": max(speed_vals) if speed_vals else None,
                "mean_vibration_strength_db": _mean(amp_vals) if amp_vals else None,
                "max_vibration_strength_db": max(amp_vals) if amp_vals else None,
            },
        )
    return rows


def _speed_breakdown(samples: list[Sample]) -> list[SpeedBreakdownRow]:
    grouped: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    _as_float_local = _as_float
    _vib_db = _primary_vibration_strength_db
    _bin_label = _speed_bin_label
    for sample in samples:
        speed = _as_float_local(sample.get("speed_kmh"))
        if speed is None or speed <= 0:
            continue
        label = _bin_label(speed)
        counts[label] += 1
        amp = _vib_db(sample)
        if amp is not None:
            grouped[label].append(amp)

    rows: list[SpeedBreakdownRow] = []
    for label in sorted(counts, key=_speed_bin_sort_key):
        values = grouped.get(label, [])
        rows.append(
            {
                "speed_range": label,
                "count": counts[label],
                "mean_vibration_strength_db": _mean(values) if values else None,
                "max_vibration_strength_db": max(values) if values else None,
            },
        )
    return rows


def _sensor_intensity_by_location(
    samples: list[Sample],
    include_locations: set[str] | None = None,
    *,
    lang: str = "en",
    connected_locations: set[str] | None = None,
    per_sample_phases: list[DrivingPhase] | None = None,
) -> list[IntensityRow]:
    """Compute per-location vibration intensity statistics.

    When ``per_sample_phases`` is provided, also computes per-phase intensity
    breakdown for each location so callers can see how vibration differs across
    IDLE, ACCELERATION, CRUISE, etc. at each sensor position.
    Addresses issue #192: aggregate entire run loses phase context.
    """
    grouped_amp: dict[str, list[float]] = defaultdict(list)
    sample_counts: dict[str, int] = defaultdict(int)
    dropped_totals: dict[str, list[tuple[float | None, float]]] = defaultdict(list)
    overflow_totals: dict[str, list[tuple[float | None, float]]] = defaultdict(list)
    strength_bucket_counts: dict[str, dict[str, int]] = defaultdict(_EMPTY_BUCKET_COUNTS.copy)
    strength_bucket_totals: dict[str, int] = defaultdict(int)
    # Per-phase intensity: {location: {phase_key: [amp_values]}}
    phase_amp: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)

    _as_float_local = _as_float
    _vib_db = _primary_vibration_strength_db
    _loc_label = _location_label
    for i, sample in enumerate(samples):
        if not isinstance(sample, dict):
            continue
        location = _loc_label(sample, lang=lang)
        if not location:
            continue
        if include_locations is not None and location not in include_locations:
            continue
        sample_counts[location] += 1
        amp = _vib_db(sample)
        if amp is not None:
            grouped_amp[location].append(amp)
            if has_phases and per_sample_phases is not None:
                phase_obj = per_sample_phases[i]
                phase_key = _phase_to_str(phase_obj) or "unknown"
                phase_amp[location][phase_key].append(amp)
        _get = sample.get
        sample_t_s = _as_float_local(_get("t_s"))
        dropped_total = _as_float_local(_get("frames_dropped_total"))
        if dropped_total is not None:
            dropped_totals[location].append((sample_t_s, dropped_total))
        overflow_total = _as_float_local(_get("queue_overflow_drops"))
        if overflow_total is not None:
            overflow_totals[location].append((sample_t_s, overflow_total))
        vibration_strength_db = _as_float_local(_get("vibration_strength_db"))
        bucket = str(_get("strength_bucket") or "")
        if vibration_strength_db is None:
            continue
        if bucket:
            strength_bucket_counts[location][bucket] = (
                strength_bucket_counts[location].get(bucket, 0) + 1
            )
            strength_bucket_totals[location] += 1

    rows: list[IntensityRow] = []
    target_locations = set(sample_counts.keys())
    if include_locations is not None:
        target_locations |= set(include_locations)
    max_sample_count = max(
        (sample_counts.get(location, 0) for location in target_locations),
        default=0,
    )

    for location in sorted(target_locations):
        values = grouped_amp.get(location, [])
        values_sorted = sorted(values)
        dropped_vals = dropped_totals.get(location, [])
        overflow_vals = overflow_totals.get(location, [])
        dropped_delta = _counter_delta(dropped_vals)
        overflow_delta = _counter_delta(overflow_vals)
        bucket_counts = strength_bucket_counts.get(location, _EMPTY_BUCKET_COUNTS)
        bucket_total = max(0, strength_bucket_totals.get(location, 0))
        bucket_distribution: JsonObject = {
            "total": bucket_total,
            "counts": dict(bucket_counts),
        }
        for idx in range(6):
            key = f"l{idx}"
            bucket_distribution[f"percent_time_{key}"] = (
                (bucket_counts.get(key, 0) / bucket_total * 100.0) if bucket_total > 0 else 0.0
            )
        sample_count = int(sample_counts.get(location, 0))
        sample_coverage_ratio = (sample_count / max_sample_count) if max_sample_count > 0 else 1.0
        sample_coverage_warning = max_sample_count >= 5 and sample_coverage_ratio <= 0.20
        partial_coverage = bool(
            connected_locations is not None and location not in connected_locations,
        )
        # Per-phase intensity summary for this location (issue #192)
        location_phase_intensity: JsonObject | None = None
        if has_phases:
            loc_phases = phase_amp.get(location, {})
            location_phase_intensity = {
                phase_key: {
                    "count": len(phase_vals),
                    "mean_intensity_db": _mean(phase_vals) if phase_vals else None,
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
                "mean_intensity_db": _mean(values) if values else None,
                "p50_intensity_db": percentile(values_sorted, 0.50) if values else None,
                "p95_intensity_db": percentile(values_sorted, 0.95) if values else None,
                "max_intensity_db": max(values) if values else None,
                "dropped_frames_delta": dropped_delta,
                "queue_overflow_drops_delta": overflow_delta,
                "strength_bucket_distribution": bucket_distribution,
                "phase_intensity": location_phase_intensity,
            },
        )
    rows.sort(
        key=lambda row: (
            1 if not bool(row.get("partial_coverage")) else 0,
            1 if not bool(row.get("sample_coverage_warning")) else 0,
            (
                row["p95_intensity_db"]
                if isinstance(row.get("p95_intensity_db"), (int, float))
                else 0.0
            ),
            (
                row["max_intensity_db"]
                if isinstance(row.get("max_intensity_db"), (int, float))
                else 0.0
            ),
        ),
        reverse=True,
    )
    return rows


# ---------------------------------------------------------------------------
# Main findings orchestrator
# ---------------------------------------------------------------------------


def _build_findings(
    *,
    metadata: MetadataDict,
    samples: list[Sample],
    speed_sufficient: bool,
    steady_speed: bool,
    speed_stddev_kmh: float | None,
    speed_non_null_pct: float,
    raw_sample_rate_hz: float | None,
    lang: str = "en",
    per_sample_phases: PhaseLabels | None = None,
    run_noise_baseline_g: float | None = None,
) -> list[Finding]:
    """Build and rank all findings for a completed run.

    Coordinates reference checks (speed, wheel, engine, sample-rate), order
    analysis, and persistent-peak detection.  Results are partitioned into
    reference / diagnostic / informational buckets and sorted so the most
    confident diagnostic finding appears first.

    Args:
        metadata: Run metadata dict (car settings, units, sample rate, etc.).
        samples: Per-metric-tick sample dicts for the run.
        speed_sufficient: Whether enough speed data was present for order analysis.
        steady_speed: Whether the speed was steady enough for reliable analysis.
        speed_stddev_kmh: Standard deviation of speed in km/h, or None.
        speed_non_null_pct: Percentage of samples with non-null speed (0-100).
        raw_sample_rate_hz: Accelerometer sample rate, or None if unknown.
        lang: ISO 639-1 language code for human-readable text (default "en").
        per_sample_phases: Optional pre-computed per-sample phase labels;
            recomputed from ``samples`` when not provided.
        run_noise_baseline_g: Optional ambient noise floor in g for this run.

    Returns:
        Ordered list of finding dicts: references first, then diagnostics sorted
        by (quantised confidence, ranking_score) descending, then informational.

    """
    tire_circumference_m, _ = _tire_reference_from_metadata(metadata)
    findings, engine_ref_sufficient = build_reference_findings(
        metadata=metadata,
        samples=samples,
        speed_sufficient=speed_sufficient,
        speed_non_null_pct=speed_non_null_pct,
        tire_circumference_m=tire_circumference_m,
        raw_sample_rate_hz=raw_sample_rate_hz,
    )
    analysis_samples, analysis_phases, _per_sample_phases, use_filtered_samples = (
        prepare_analysis_samples(
            samples,
            per_sample_phases=per_sample_phases,
        )
    )

    order_findings = _build_order_findings(
        metadata=metadata,
        samples=analysis_samples,
        speed_sufficient=speed_sufficient,
        steady_speed=steady_speed,
        speed_stddev_kmh=speed_stddev_kmh,
        tire_circumference_m=tire_circumference_m if speed_sufficient else None,
        engine_ref_sufficient=engine_ref_sufficient,
        raw_sample_rate_hz=raw_sample_rate_hz,
        connected_locations=_locations_connected_throughout_run(analysis_samples, lang=lang),
        lang=lang,
        per_sample_phases=list(analysis_phases),
    )
    findings.extend(order_findings)
    order_freqs = collect_order_frequencies(order_findings)
    findings.extend(
        _build_persistent_peak_findings(
            samples=analysis_samples,  # IDLE-filtered; issue #191
            order_finding_freqs=order_freqs,
            lang=lang,
            per_sample_phases=analysis_phases,
            run_noise_baseline_g=(run_noise_baseline_g if not use_filtered_samples else None),
        ),
    )
    return finalize_findings(findings)
