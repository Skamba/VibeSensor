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

from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain import LocationIntensitySummary
from vibesensor.domain.finding import (
    FindingEvidence,
    FindingKind,
    VibrationSource,
    speed_band_sort_key,
    speed_bin_label,
)
from vibesensor.shared.boundaries.analysis_payload import (
    PhaseSpeedBreakdownRow,
    SpeedBreakdownRow,
)
from vibesensor.shared.constants import (
    NEGLIGIBLE_STRENGTH_MAX_DB,
    ORDER_SUPPRESS_PERSISTENT_MIN_CONF,
    SNR_LOG_DIVISOR,
    SPEED_COVERAGE_MIN_PCT,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.diagnostics._types import (
    PhaseLabels,
    Sample,
)
from vibesensor.use_cases.diagnostics.helpers import (
    _effective_baseline_floor,
    _effective_engine_rpm,
    _estimate_strength_floor_amp_g,
    _location_label,
    _locations_connected_throughout_run,
    _phase_to_str,
    _primary_vibration_strength_db,
    _run_noise_baseline_g,
    _sample_top_peaks,
    _speed_profile_from_points,
    _tire_reference_from_metadata,
    counter_delta,
)
from vibesensor.use_cases.diagnostics.order_analysis import _build_order_findings
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    DrivingPhase,
    diagnostic_sample_mask,
    segment_run_phases,
)
from vibesensor.vibration_strength import percentile
from vibesensor.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

# ---------------------------------------------------------------------------
# Finding finalization
# ---------------------------------------------------------------------------


def finalize_findings(
    findings: list[DomainFinding],
) -> tuple[DomainFinding, ...]:
    """Partition, rank by confidence, and assign stable ``F###`` IDs.

    Returns domain ``Finding`` objects in canonical order: references first,
    then diagnostics sorted by confidence/score, then informational.
    """
    refs = [finding for finding in findings if finding.is_reference]
    diags = sorted(
        [finding for finding in findings if finding.is_diagnostic],
        key=lambda finding: finding.rank_key,
        reverse=True,
    )
    infos = sorted(
        [finding for finding in findings if finding.is_informational],
        key=lambda finding: finding.rank_key,
        reverse=True,
    )
    counter = 0
    result: list[DomainFinding] = []
    for finding in refs + diags + infos:
        if not finding.is_reference:
            counter += 1
            finding = finding.with_id(f"F{counter:03d}")
        result.append(finding)
    return tuple(result)


# ---------------------------------------------------------------------------
# Builder support helpers
# ---------------------------------------------------------------------------


_MIN_DIAGNOSTIC_SAMPLES = 5


def _reference_missing_finding(
    *,
    finding_id: str,
    suspected_source: str,
    kind: FindingKind = FindingKind.REFERENCE,
) -> DomainFinding:
    return DomainFinding(
        finding_id=finding_id,
        suspected_source=suspected_source,
        confidence=None,
        kind=kind,
    )


def build_reference_findings(
    *,
    metadata: JsonObject,
    samples: list[Sample],
    speed_sufficient: bool,
    tire_circumference_m: float | None,
    raw_sample_rate_hz: float | None,
) -> tuple[list[DomainFinding], bool]:
    """Build reference-missing findings and return engine reference sufficiency."""
    findings: list[DomainFinding] = []
    if not speed_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SPEED",
                suspected_source="unknown",
            ),
        )

    if speed_sufficient and not (tire_circumference_m and tire_circumference_m > 0):
        findings.append(
            _reference_missing_finding(
                finding_id="REF_WHEEL",
                suspected_source="wheel/tire",
            ),
        )

    engine_ref_sufficient = has_engine_reference(
        samples,
        metadata=metadata,
        tire_circumference_m=tire_circumference_m,
    )
    if not engine_ref_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_ENGINE",
                suspected_source="engine",
            ),
        )

    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SAMPLE_RATE",
                suspected_source="unknown",
            ),
        )
    return findings, engine_ref_sufficient


def engine_reference_coverage_pct(
    samples: list[Sample],
    *,
    metadata: JsonObject,
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
    metadata: JsonObject,
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


def collect_order_frequencies(order_findings: list[DomainFinding]) -> set[float]:
    """Collect matched order frequencies used to suppress duplicate persistent findings."""
    order_freqs: set[float] = set()
    for order_finding in order_findings:
        conf = order_finding.effective_confidence
        if conf < ORDER_SUPPRESS_PERSISTENT_MIN_CONF:
            continue
        for point in order_finding.matched_points:
            matched_hz = point.matched_hz
            if matched_hz is not None and matched_hz > 0:
                order_freqs.add(matched_hz)
    return order_freqs


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


def _build_persistent_peak_findings(
    *,
    samples: list[Sample],
    order_finding_freqs: set[float],
    lang: str,
    freq_bin_hz: float = 2.0,
    per_sample_phases: PhaseLabels | None = None,
    run_noise_baseline_g: float | None = None,
) -> list[DomainFinding]:
    """Build findings for non-order persistent frequency peaks.

    Uses the same confidence-style scoring as order findings (presence_ratio,
    error/SNR) so the report is consistent.  Peaks already claimed by order
    findings are excluded.  Transient peaks are returned separately.

    When ``per_sample_phases`` is provided, each finding records
    phase-aware cruise context through ``Finding.cruise_fraction``.
    """
    analyzer = PeakFindingAnalyzer(
        samples=samples,
        order_finding_freqs=order_finding_freqs,
        lang=lang,
        freq_bin_hz=freq_bin_hz,
        per_sample_phases=per_sample_phases,
        run_noise_baseline_g=run_noise_baseline_g,
    )
    return analyzer.analyze()


# ---------------------------------------------------------------------------
# PeakBin – per-frequency-bin scoring and finding export
# ---------------------------------------------------------------------------


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

    # -- read-only properties -----------------------------------------------

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

    # -- scoring -----------------------------------------------------------

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

    # -- export to domain Finding ------------------------------------------

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


# ---------------------------------------------------------------------------
# PeakFindingAnalyzer – coordinates accumulation and per-bin scoring
# ---------------------------------------------------------------------------


class PeakFindingAnalyzer:
    """Coordinates frequency-bin accumulation from samples and produces findings.

    Wraps :class:`_PeakBinStats` accumulation and per-bin :class:`PeakBin`
    scoring.  The ``analyze()`` method returns the final list of findings,
    sorted and capped by :data:`PERSISTENT_PEAK_MAX_FINDINGS`.
    """

    __slots__ = (
        "_samples",
        "_order_finding_freqs",
        "_lang",
        "_freq_bin_hz",
        "_per_sample_phases",
        "_run_noise_baseline_g",
    )

    def __init__(
        self,
        *,
        samples: list[Sample],
        order_finding_freqs: set[float],
        lang: str,
        freq_bin_hz: float = 2.0,
        per_sample_phases: PhaseLabels | None = None,
        run_noise_baseline_g: float | None = None,
    ) -> None:
        self._samples = samples
        self._order_finding_freqs = order_finding_freqs
        self._lang = lang
        self._freq_bin_hz = max(freq_bin_hz, 0.01)  # Guard against values < 0.01
        self._per_sample_phases = per_sample_phases
        self._run_noise_baseline_g = run_noise_baseline_g

    def analyze(self) -> list[DomainFinding]:
        """Run the full peak-finding analysis and return ordered findings."""
        freq_bin_hz = self._freq_bin_hz
        freq_bin_hz_half = freq_bin_hz * 0.5
        has_phases = self._per_sample_phases is not None and len(self._per_sample_phases) == len(
            self._samples
        )

        stats = _accumulate_peak_bin_stats(
            self._samples,
            freq_bin_hz=freq_bin_hz,
            freq_bin_hz_half=freq_bin_hz_half,
            lang=self._lang,
            per_sample_phases=self._per_sample_phases,
            has_phases=has_phases,
        )
        if stats.n_samples == 0:
            return []

        run_noise_baseline_g = self._run_noise_baseline_g
        if run_noise_baseline_g is None:
            run_noise_baseline_g = _run_noise_baseline_g(self._samples)

        bins = self._score_bins(
            stats, run_noise_baseline_g=run_noise_baseline_g, has_phases=has_phases
        )
        return self._select_top_findings(bins, n_samples=stats.n_samples)

    def _score_bins(
        self,
        stats: _PeakBinStats,
        *,
        run_noise_baseline_g: float | None,
        has_phases: bool,
    ) -> list[PeakBin]:
        """Build a PeakBin for each frequency bin not claimed by order findings."""
        freq_bin_hz = self._freq_bin_hz
        bins: list[PeakBin] = []
        for bin_center, amps in stats.bin_amps.items():
            if any(abs(bin_center - of) < freq_bin_hz for of in self._order_finding_freqs):
                continue
            peak_bin = PeakBin(
                bin_center=bin_center,
                amps=amps,
                floor_vals=stats.bin_floors.get(bin_center, []),
                speed_amp_pairs=stats.bin_speed_amp_pairs.get(bin_center, []),
                loc_counts_for_bin=stats.bin_location_counts.get(bin_center, {}),
                speed_bin_counts_for_bin=stats.bin_speed_bin_counts.get(bin_center, {}),
                phases_for_bin=stats.bin_phase_counts.get(bin_center, {}),
                n_samples=stats.n_samples,
                total_locations=stats.total_locations,
                total_location_sample_counts=stats.total_location_sample_counts,
                total_speed_bin_counts=stats.total_speed_bin_counts,
                run_noise_baseline_g=run_noise_baseline_g,
                has_phases=has_phases,
            )
            bins.append(peak_bin)
        return bins

    @staticmethod
    def _select_top_findings(bins: list[PeakBin], *, n_samples: int) -> list[DomainFinding]:
        """Sort bins by ranking score and return top findings."""
        persistent: list[tuple[float, PeakBin]] = []
        transient: list[tuple[float, PeakBin]] = []
        for peak_bin in bins:
            bucket = transient if peak_bin.is_transient else persistent
            bucket.append((peak_bin.ranking_score, peak_bin))

        persistent.sort(key=lambda item: item[0], reverse=True)
        transient.sort(key=lambda item: item[0], reverse=True)

        del n_samples
        results: list[DomainFinding] = []
        for _score, peak_bin in persistent[:PERSISTENT_PEAK_MAX_FINDINGS]:
            results.append(peak_bin.to_finding())
        for _score, peak_bin in transient[:PERSISTENT_PEAK_MAX_FINDINGS]:
            results.append(peak_bin.to_finding())
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
    _bin_label = speed_bin_label
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
    for label in sorted(counts, key=speed_band_sort_key):
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
) -> list[LocationIntensitySummary]:
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

    rows: list[LocationIntensitySummary] = []
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
            LocationIntensitySummary(
                location=location,
                partial_coverage=partial_coverage,
                sample_count=sample_count,
                sample_coverage_ratio=sample_coverage_ratio,
                sample_coverage_warning=sample_coverage_warning,
                mean_intensity_db=_mean(values) if values else None,
                p50_intensity_db=percentile(values_sorted, 0.50) if values else None,
                p95_intensity_db=percentile(values_sorted, 0.95) if values else None,
                max_intensity_db=max(values) if values else None,
                dropped_frames_delta=dropped_delta,
                queue_overflow_drops_delta=overflow_delta,
                strength_bucket_distribution=bucket_distribution,
                phase_intensity=location_phase_intensity,
            ),
        )
    rows.sort(
        key=lambda row: (
            0 if row.partial_coverage else 1,
            0 if row.sample_coverage_warning else 1,
            row.p95_intensity_db if isinstance(row.p95_intensity_db, (int, float)) else 0.0,
            row.max_intensity_db if isinstance(row.max_intensity_db, (int, float)) else 0.0,
        ),
        reverse=True,
    )
    return rows


# ---------------------------------------------------------------------------
# Main findings orchestrator
# ---------------------------------------------------------------------------


def _build_findings(
    *,
    metadata: JsonObject,
    samples: list[Sample],
    speed_sufficient: bool,
    steady_speed: bool,
    speed_stddev_kmh: float | None,
    speed_non_null_pct: float,
    raw_sample_rate_hz: float | None,
    lang: str = "en",
    per_sample_phases: PhaseLabels | None = None,
    run_noise_baseline_g: float | None = None,
) -> tuple[DomainFinding, ...]:
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
        Domain Finding objects: references first, then diagnostics sorted
        by (quantised confidence, ranking_score) descending, then informational.

    """
    tire_circumference_m, _ = _tire_reference_from_metadata(metadata)
    findings: list[DomainFinding]
    findings, engine_ref_sufficient = build_reference_findings(
        metadata=metadata,
        samples=samples,
        speed_sufficient=speed_sufficient,
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
