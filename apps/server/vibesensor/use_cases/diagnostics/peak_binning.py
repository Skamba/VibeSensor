"""Peak bin accumulation, scoring, and finding export helpers."""

from __future__ import annotations

from collections import defaultdict
from math import floor as _math_floor
from math import log1p

from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain.finding import (
    FindingEvidence,
    FindingKind,
    VibrationSource,
    speed_bin_label,
)
from vibesensor.shared.constants import NEGLIGIBLE_STRENGTH_MAX_DB, SNR_LOG_DIVISOR
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.use_cases.diagnostics._types import PhaseLabels, Sample
from vibesensor.use_cases.diagnostics.helpers import (
    _effective_baseline_floor,
    _estimate_strength_floor_amp_g,
    _location_label,
    _phase_to_str,
    _sample_top_peaks,
    _speed_profile_from_points,
)
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase
from vibesensor.vibration_strength import percentile
from vibesensor.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

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


def _make_nested_int_defaultdict() -> defaultdict:
    """Create a nested defaultdict(int).

    Use as ``defaultdict(_make_nested_int_defaultdict)`` to get a
    two-level defaultdict where inner values are ints.
    """
    return defaultdict(int)


class _PeakBinStats:
    """Accumulated per-frequency-bin statistics collected from samples.

    Populated by :func:`_accumulate_peak_bin_stats` and consumed by the
    per-bin scoring loop inside :class:`PeakFindingAnalyzer`.
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
    _local_speed_bin = speed_bin_label
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


class PeakBin:
    """Represents a single frequency bin with accumulated peak statistics.

    Owns presence ratio, burstiness, SNR, spatial/speed uniformity,
    classification, confidence computation, and export to a domain ``Finding``.
    Replaces the 200-line inner loop body that previously lived inside
    ``_build_persistent_peak_findings``.
    """

    __slots__ = (
        "_bin_center",
        "_count",
        "_sorted_amps",
        "_median_amp",
        "_p95_amp",
        "_max_amp",
        "_burstiness",
        "_presence_ratio",
        "_mean_floor",
        "_effective_floor",
        "_raw_snr",
        "_spatial_uniformity",
        "_speed_uniformity",
        "_spatial_concentration",
        "_loc_counts_for_bin",
        "_phases_for_bin",
        "_speed_amp_pairs",
        "_peak_type",
        "_has_phases",
        "_run_noise_baseline_g",
    )

    def __init__(
        self,
        *,
        bin_center: float,
        amps: list[float],
        floor_vals: list[float],
        speed_amp_pairs: list[tuple[float, float]],
        loc_counts_for_bin: dict[str, int],
        speed_bin_counts_for_bin: dict[str, int],
        phases_for_bin: dict[str, int],
        n_samples: int,
        total_locations: set[str],
        total_location_sample_counts: dict[str, int],
        total_speed_bin_counts: dict[str, int],
        run_noise_baseline_g: float | None,
        has_phases: bool,
    ) -> None:
        self._bin_center = bin_center
        self._sorted_amps = sorted(amps)
        self._count = len(self._sorted_amps)
        self._loc_counts_for_bin = loc_counts_for_bin
        self._phases_for_bin = phases_for_bin
        self._speed_amp_pairs = speed_amp_pairs
        self._has_phases = has_phases
        self._run_noise_baseline_g = run_noise_baseline_g

        # Amplitude statistics
        self._median_amp = (
            percentile(self._sorted_amps, 0.50) if self._count >= 2 else self._sorted_amps[0]
        )
        self._p95_amp = (
            percentile(self._sorted_amps, 0.95) if self._count >= 2 else self._sorted_amps[-1]
        )
        self._max_amp = self._sorted_amps[-1]
        self._burstiness = (self._max_amp / self._median_amp) if self._median_amp > 1e-9 else 0.0

        # Presence ratio with per-location rescue
        presence = self._count / max(1, n_samples)
        if total_location_sample_counts and loc_counts_for_bin:
            for loc in total_locations:
                loc_hits = loc_counts_for_bin.get(loc, 0)
                loc_total = total_location_sample_counts.get(loc, 0)
                if loc_total >= 3:
                    presence = max(presence, loc_hits / loc_total)
        self._presence_ratio = presence

        # Floor and SNR
        self._mean_floor = sum(floor_vals) / len(floor_vals) if floor_vals else 0.0
        self._effective_floor = _effective_baseline_floor(
            run_noise_baseline_g, extra_fallback=self._mean_floor
        )
        self._raw_snr = self._p95_amp / self._effective_floor

        # Spatial uniformity
        n_total_locs = len(total_locations)
        self._spatial_uniformity: float | None = (
            len(loc_counts_for_bin) / n_total_locs if n_total_locs >= 2 else None
        )

        # Speed uniformity
        self._speed_uniformity: float | None = None
        if len(total_speed_bin_counts) >= 2:
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
                self._speed_uniformity = max(0.0, (hr_sq_sum / hr_n) - hr_mean * hr_mean) ** 0.5
            elif hr_n == 1:
                self._speed_uniformity = 0.0

        # Spatial concentration
        self._spatial_concentration = (
            max(loc_counts_for_bin.values()) / self._count
            if loc_counts_for_bin and self._count > 0
            else 1.0
        )

        # Classification
        self._peak_type = _classify_peak_type(
            self._presence_ratio,
            self._burstiness,
            snr=self._raw_snr,
            spatial_uniformity=self._spatial_uniformity,
            speed_uniformity=self._speed_uniformity,
        )

    @property
    def bin_center(self) -> float:
        return self._bin_center

    @property
    def presence_ratio(self) -> float:
        return self._presence_ratio

    @property
    def burstiness(self) -> float:
        return self._burstiness

    @property
    def snr(self) -> float:
        return self._raw_snr

    @property
    def spatial_uniformity(self) -> float | None:
        return self._spatial_uniformity

    @property
    def speed_uniformity(self) -> float | None:
        return self._speed_uniformity

    @property
    def peak_type(self) -> str:
        return self._peak_type

    @property
    def is_transient(self) -> bool:
        return self._peak_type == "transient"

    @property
    def confidence(self) -> float:
        """Compute calibrated confidence for this peak bin."""
        snr_score = min(1.0, log1p(self._raw_snr) / SNR_LOG_DIVISOR)
        spatial_penalty = (
            (0.35 + 0.65 * self._spatial_concentration) if self._loc_counts_for_bin else 1.0
        )
        peak_strength_db = self._peak_strength_db

        if self._peak_type == "baseline_noise":
            return max(0.02, min(0.12, 0.02 + 0.05 * self._presence_ratio))
        if self._peak_type == "transient":
            return max(0.05, min(0.22, 0.05 + 0.10 * self._presence_ratio + 0.07 * snr_score))

        base_confidence = max(
            0.10,
            min(
                0.75,
                0.10
                + 0.35 * self._presence_ratio
                + 0.15 * snr_score
                + 0.15 * min(1.0, 1.0 - self._burstiness / 10.0),
            ),
        )
        conf = base_confidence * spatial_penalty
        if self._loc_counts_for_bin and self._spatial_concentration <= 0.35:
            conf = min(conf, 0.35)
        if peak_strength_db < NEGLIGIBLE_STRENGTH_MAX_DB:
            conf = min(conf, 0.40)
        return conf

    @property
    def ranking_score(self) -> float:
        return (self._presence_ratio**2) * self._p95_amp

    @property
    def _peak_strength_db(self) -> float:
        return canonical_vibration_db(
            peak_band_rms_amp_g=self._p95_amp,
            floor_amp_g=self._effective_floor,
        )

    def to_finding(self) -> DomainFinding:
        """Export this bin's analysis as a canonical domain ``Finding``."""
        peak_strength_db = self._peak_strength_db
        _peak_speed_kmh, _speed_window_kmh, derived_speed_band = _speed_profile_from_points(
            self._speed_amp_pairs,
        )
        speed_band = derived_speed_band or "-"

        # Phase evidence
        _total_phase_hits = sum(self._phases_for_bin.values())
        _cruise_hits = self._phases_for_bin.get(_CRUISE_PHASE_VAL, 0)
        cruise_fraction = _cruise_hits / _total_phase_hits if _total_phase_hits > 0 else 0.0

        suspected_source = (
            VibrationSource.BASELINE_NOISE
            if self._peak_type == "baseline_noise"
            else VibrationSource.TRANSIENT_IMPACT
            if self._peak_type == "transient"
            else VibrationSource.UNKNOWN_RESONANCE
        )
        return DomainFinding(
            finding_id="F_PEAK",
            finding_key=f"peak_{self._bin_center:.0f}hz",
            suspected_source=suspected_source,
            confidence=self.confidence,
            order=f"{self._bin_center:.1f} Hz",
            severity="info" if self._peak_type == "transient" else "diagnostic",
            strongest_speed_band=speed_band if speed_band != "-" else None,
            peak_classification=self._peak_type,
            kind=(
                FindingKind.INFORMATIONAL
                if self._peak_type == "transient"
                else FindingKind.DIAGNOSTIC
            ),
            ranking_score=self.ranking_score,
            vibration_strength_db=peak_strength_db,
            cruise_fraction=cruise_fraction,
            evidence=FindingEvidence(
                presence_ratio=self._presence_ratio,
                burstiness=self._burstiness,
                spatial_concentration=self._spatial_concentration,
                spatial_uniformity=self._spatial_uniformity or 0.0,
                speed_uniformity=self._speed_uniformity or 0.0,
            ),
        )
