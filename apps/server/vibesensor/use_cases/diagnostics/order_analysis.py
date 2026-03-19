"""Order-tracking analysis: Hz helpers, hypotheses, matching, scoring, and assembly."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from math import log1p

from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain import OrderMatchObservation, OrderReferenceSpec, VibrationOrigin
from vibesensor.domain.finding import (
    FindingEvidence,
    FindingKind,
    VibrationSource,
    speed_band_sort_key,
    speed_bin_label,
)
from vibesensor.shared.constants import (
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    CONSTANT_SPEED_STDDEV_KMH,
    KMH_TO_MPS,
    LIGHT_STRENGTH_MAX_DB,
    MEMS_NOISE_FLOOR_G,
    NEGLIGIBLE_STRENGTH_MAX_DB,
    ORDER_CONSTANT_SPEED_MIN_MATCH_RATE,
    ORDER_MIN_CONFIDENCE,
    ORDER_MIN_COVERAGE_POINTS,
    ORDER_MIN_MATCH_POINTS,
    ORDER_TOLERANCE_MIN_HZ,
    ORDER_TOLERANCE_REL,
    SECONDS_PER_MINUTE,
    SNR_LOG_DIVISOR,
    SPEED_BIN_WIDTH_KMH,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.diagnostics._types import (
    PhaseLabels,
    Sample,
)
from vibesensor.use_cases.diagnostics.helpers import (
    _corr_abs_clamped,
    _effective_engine_rpm,
    _estimate_strength_floor_amp_g,
    _location_label,
    _order_reference_spec_from_context,
    _phase_to_str,
    _sample_top_peaks,
    _speed_profile_from_points,
)
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase
from vibesensor.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

# ═══════════════════════════════════════════════════════════════════════════
# Hz helpers, hypotheses, and action plans
# ═══════════════════════════════════════════════════════════════════════════


def _wheel_hz(
    sample: Sample,
    tire_circumference_m: float | None,
    metadata: JsonObject | None = None,
    order_reference_spec: OrderReferenceSpec | None = None,
) -> float | None:
    speed_kmh = _as_float(sample.get("speed_kmh"))
    if speed_kmh is None or speed_kmh <= 0:
        return None
    spec = order_reference_spec
    if spec is None and metadata is not None:
        spec = _order_reference_spec_from_context(metadata, sample)
    if spec is not None and spec.supports_wheel_reference:
        return spec.wheel_hz_from_speed_kmh(speed_kmh)
    if tire_circumference_m is None or tire_circumference_m <= 0:
        return None
    return float(speed_kmh * KMH_TO_MPS / tire_circumference_m)


def _driveshaft_hz(
    sample: Sample,
    metadata: JsonObject,
    tire_circumference_m: float | None,
) -> float | None:
    speed_kmh = _as_float(sample.get("speed_kmh"))
    spec = _order_reference_spec_from_context(metadata, sample)
    if (
        speed_kmh is not None
        and speed_kmh > 0
        and spec is not None
        and spec.supports_driveshaft_reference
    ):
        return spec.driveshaft_hz_from_speed_kmh(speed_kmh)
    whz = _wheel_hz(
        sample,
        tire_circumference_m,
        metadata,
        order_reference_spec=spec,
    )
    fd = _as_float(sample.get("final_drive_ratio")) or _as_float(metadata.get("final_drive_ratio"))
    if whz is None or fd is None or fd <= 0:
        return None
    return float(whz * fd)


def _engine_hz(
    sample: Sample,
    metadata: JsonObject,
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    rpm, src = _effective_engine_rpm(sample, metadata, tire_circumference_m)
    if rpm is None or rpm <= 0:
        return None, src
    return float(rpm / SECONDS_PER_MINUTE), src


def _order_label(order: int, base: str) -> str:
    """Return a language-neutral order label like ``'1x wheel'``."""
    return f"{order}x {base}"


@dataclass(slots=True, frozen=True)
class OrderHypothesis:
    key: str
    suspected_source: VibrationSource
    order_label_base: str
    order: int
    # Path compliance factor: models how much the mechanical transmission
    # path between the vibration source and the sensor dampens/broadens
    # the frequency peak.  1.0 = stiff direct coupling (driveshaft), higher
    # values = softer compliant path (wheel through suspension bushings).
    # Used to widen match tolerance and soften error/correlation penalties.
    path_compliance: float = 1.0

    def predicted_hz(
        self,
        sample: Sample,
        metadata: JsonObject,
        tire_circumference_m: float | None,
    ) -> tuple[float | None, str]:
        if self.order_label_base == "wheel":
            base = _wheel_hz(sample, tire_circumference_m, metadata)
            return (base * self.order, "speed+tire") if base is not None else (None, "missing")
        if self.order_label_base == "driveshaft":
            base = _driveshaft_hz(sample, metadata, tire_circumference_m)
            if base is None:
                return None, "missing"
            return base * self.order, "speed+tire+final_drive"
        if self.order_label_base == "engine":
            base, src = _engine_hz(sample, metadata, tire_circumference_m)
            return (base * self.order, src) if base is not None else (None, "missing")
        return None, "missing"


# Pre-built hypothesis objects – avoids re-creating 6 frozen dataclass
# instances on every call.  The thin wrapper function below is kept so that
# test monkeypatches (which replace the callable) keep working.
_ORDER_HYPOTHESES: tuple[OrderHypothesis, ...] = (
    # Wheel orders travel through tire sidewall → hub → knuckle → control
    # arms → bushings → subframe → body → sensor.  Each rubber component
    # broadens the peak and reduces tracking precision.
    OrderHypothesis("wheel_1x", VibrationSource.WHEEL_TIRE, "wheel", 1, path_compliance=1.5),
    OrderHypothesis("wheel_2x", VibrationSource.WHEEL_TIRE, "wheel", 2, path_compliance=1.5),
    # Driveshaft has a shorter, stiffer path: shaft → diff → subframe → body.
    OrderHypothesis(
        "driveshaft_1x",
        VibrationSource.DRIVELINE,
        "driveshaft",
        1,
        path_compliance=1.0,
    ),
    OrderHypothesis(
        "driveshaft_2x",
        VibrationSource.DRIVELINE,
        "driveshaft",
        2,
        path_compliance=1.0,
    ),
    # Engine is stiffly mounted on most vehicles.
    OrderHypothesis("engine_1x", VibrationSource.ENGINE, "engine", 1, path_compliance=1.0),
    OrderHypothesis("engine_2x", VibrationSource.ENGINE, "engine", 2, path_compliance=1.0),
)


def _order_hypotheses() -> tuple[OrderHypothesis, ...]:
    return _ORDER_HYPOTHESES


# ═══════════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class OrderMatchAccumulator:
    """Accumulated statistics from matching one hypothesis across samples.

    In addition to raw accumulation fields, provides computed properties
    for match rate, eligibility checks, and unique match locations.
    """

    possible: int
    matched: int
    matched_amp: list[float]
    matched_floor: list[float]
    rel_errors: list[float]
    predicted_vals: list[float]
    measured_vals: list[float]
    matched_points: list[OrderMatchObservation]
    ref_sources: set[str]
    possible_by_speed_bin: dict[str, int]
    matched_by_speed_bin: dict[str, int]
    possible_by_phase: dict[str, int]
    matched_by_phase: dict[str, int]
    possible_by_location: dict[str, int]
    matched_by_location: dict[str, int]
    has_phases: bool
    compliance: float

    # -- computed properties -----------------------------------------------

    @property
    def match_rate(self) -> float:
        """Global match rate (matched / possible)."""
        return self.matched / max(1, self.possible)

    @property
    def unique_match_locations(self) -> set[str]:
        """Set of distinct sensor locations that produced matches."""
        return {(point.location or "").strip() for point in self.matched_points if point.location}

    def is_eligible(
        self,
        *,
        min_coverage: int = ORDER_MIN_COVERAGE_POINTS,
        min_matched: int = ORDER_MIN_MATCH_POINTS,
    ) -> bool:
        """Whether this match has enough data to produce a finding."""
        return self.possible >= min_coverage and self.matched >= min_matched


@dataclass(frozen=True)
class OrderFindingBuildContext:
    """Stable context for assembling a matched order hypothesis into a finding."""

    effective_match_rate: float
    focused_speed_band: str | None
    per_location_dominant: bool
    match_rate: float
    min_match_rate: float
    constant_speed: bool
    steady_speed: bool
    connected_locations: set[str]
    lang: str


# ═══════════════════════════════════════════════════════════════════════════
# Matching
# ═══════════════════════════════════════════════════════════════════════════


def match_samples_for_hypothesis(
    samples: list[Sample],
    cached_peaks: list[list[tuple[float, float]]],
    hypothesis: OrderHypothesis,
    metadata: JsonObject,
    tire_circumference_m: float | None,
    per_sample_phases: PhaseLabels | None,
    lang: str,
) -> OrderMatchAccumulator:
    """Match one hypothesis against all samples and accumulate evidence."""
    possible = 0
    matched = 0
    matched_amp: list[float] = []
    matched_floor: list[float] = []
    rel_errors: list[float] = []
    predicted_vals: list[float] = []
    measured_vals: list[float] = []
    matched_points: list[OrderMatchObservation] = []
    ref_sources: set[str] = set()
    possible_by_speed_bin: dict[str, int] = defaultdict(int)
    matched_by_speed_bin: dict[str, int] = defaultdict(int)
    possible_by_phase: dict[str, int] = defaultdict(int)
    matched_by_phase: dict[str, int] = defaultdict(int)
    possible_by_location: dict[str, int] = defaultdict(int)
    matched_by_location: dict[str, int] = defaultdict(int)
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)
    compliance = getattr(hypothesis, "path_compliance", 1.0)
    compliance_scale = compliance**0.5

    for sample_idx, sample in enumerate(samples):
        peaks = cached_peaks[sample_idx]
        if not peaks:
            continue
        predicted_hz, ref_source = hypothesis.predicted_hz(sample, metadata, tire_circumference_m)
        if predicted_hz is None or predicted_hz <= 0:
            continue
        possible += 1
        ref_sources.add(ref_source)

        sample_location = _location_label(sample, lang=lang)
        if sample_location:
            possible_by_location[sample_location] += 1
        sample_speed = _as_float(sample.get("speed_kmh"))
        sample_speed_bin = (
            speed_bin_label(sample_speed, bin_width=SPEED_BIN_WIDTH_KMH)
            if sample_speed is not None and sample_speed > 0
            else None
        )
        if sample_speed_bin is not None:
            possible_by_speed_bin[sample_speed_bin] += 1

        phase_key: str | None = None
        if has_phases:
            assert per_sample_phases is not None
            phase = per_sample_phases[sample_idx]
            phase_key = str(phase.value if hasattr(phase, "value") else phase)
            possible_by_phase[phase_key] += 1

        tolerance_hz = max(
            ORDER_TOLERANCE_MIN_HZ,
            predicted_hz * ORDER_TOLERANCE_REL * compliance_scale,
        )
        best_hz, best_amp = min(peaks, key=lambda item: abs(item[0] - predicted_hz))
        delta_hz = abs(best_hz - predicted_hz)
        if delta_hz > tolerance_hz:
            continue

        matched += 1
        if sample_location:
            matched_by_location[sample_location] += 1
        if sample_speed_bin is not None:
            matched_by_speed_bin[sample_speed_bin] += 1
        if has_phases and phase_key is not None:
            matched_by_phase[phase_key] += 1

        rel_errors.append(delta_hz / max(1e-9, predicted_hz))
        matched_amp.append(best_amp)
        floor_amp = _estimate_strength_floor_amp_g(sample)
        matched_floor.append(max(0.0, floor_amp if floor_amp is not None else 0.0))
        predicted_vals.append(predicted_hz)
        measured_vals.append(best_hz)
        matched_points.append(
            OrderMatchObservation(
                t_s=_as_float(sample.get("t_s")),
                speed_kmh=_as_float(sample.get("speed_kmh")),
                predicted_hz=predicted_hz,
                matched_hz=best_hz,
                rel_error=delta_hz / max(1e-9, predicted_hz),
                amp=best_amp,
                location=sample_location,
                phase=(
                    _phase_to_str(per_sample_phases[sample_idx])
                    if has_phases and per_sample_phases is not None
                    else None
                ),
            ),
        )

    return OrderMatchAccumulator(
        possible=possible,
        matched=matched,
        matched_amp=matched_amp,
        matched_floor=matched_floor,
        rel_errors=rel_errors,
        predicted_vals=predicted_vals,
        measured_vals=measured_vals,
        matched_points=matched_points,
        ref_sources=ref_sources,
        possible_by_speed_bin=dict(possible_by_speed_bin),
        matched_by_speed_bin=dict(matched_by_speed_bin),
        possible_by_phase=dict(possible_by_phase),
        matched_by_phase=dict(matched_by_phase),
        possible_by_location=dict(possible_by_location),
        matched_by_location=dict(matched_by_location),
        has_phases=has_phases,
        compliance=compliance,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Scoring
# ═══════════════════════════════════════════════════════════════════════════

# Local type bindings so mypy resolves correct types under follow_imports=skip.
_CONF_FLOOR: float = CONFIDENCE_FLOOR
_CONF_CEIL: float = CONFIDENCE_CEILING

# ── Diffuse excitation detection constants ──────────────────────────────
_DIFFUSE_AMPLITUDE_DOMINANCE_RATIO = 2.0
_DIFFUSE_MATCH_RATE_RANGE_THRESHOLD = 0.15
_DIFFUSE_MIN_MEAN_RATE = 0.15
_DIFFUSE_PENALTY_BASE = 0.85
_DIFFUSE_PENALTY_PER_SENSOR = 0.04
_DIFFUSE_PENALTY_FLOOR = 0.65
_SINGLE_SENSOR_CONFIDENCE_SCALE = 0.85
_DUAL_SENSOR_CONFIDENCE_SCALE = 0.92
_CONF_BASE = 0.10
_MATCH_BASE_WEIGHT = 0.35
_ERROR_WEIGHT = 0.20
_CORR_BASE_WEIGHT = 0.10
_SNR_WEIGHT = 0.20
_CORR_MAX_SHIFT = 0.05
_CORR_COMPLIANCE_FACTOR = 0.10
_NEGLIGIBLE_STRENGTH_CONF_CAP = 0.40
_LIGHT_STRENGTH_PENALTY = 0.80
_LOCALIZATION_BASE = 0.70
_LOCALIZATION_SPREAD = 0.30
_WEAK_SEP_DOMINANCE_THRESHOLD = 1.5
_WEAK_SEP_STRONG_PENALTY = 0.90
_WEAK_SEP_UNIFORM_DOMINANCE = 1.05
_WEAK_SEP_UNIFORM_PENALTY = 0.70
_WEAK_SEP_MILD_PENALTY = 0.80
_NO_WHEEL_SENSOR_PENALTY = 0.75
_CONSTANT_SPEED_PENALTY = 0.75
_STEADY_SPEED_PENALTY = 0.82
_SAMPLE_SATURATION_COUNT = 20
_SAMPLE_WEIGHT_BASE = 0.70
_SAMPLE_WEIGHT_RANGE = 0.30
_CORROBORATING_3_BONUS = 1.08
_CORROBORATING_2_BONUS = 1.04
_PHASES_3_BONUS = 1.06
_PHASES_2_BONUS = 1.03
_LOCALIZATION_MIN_SCALE_THRESHOLD = 0.30
_HARMONIC_ALIAS_RATIO = 1.15
_ENGINE_ALIAS_SUPPRESSION = 0.60


def _mean(values: list[float]) -> float:
    """Arithmetic mean returning 0.0 for empty inputs."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _normalized_source(finding: DomainFinding) -> str:
    src: str = finding.source_normalized
    return src


def detect_diffuse_excitation(
    connected_locations: set[str],
    possible_by_location: dict[str, int],
    matched_by_location: dict[str, int],
    matched_points: list[OrderMatchObservation],
    *,
    min_match_points: int = ORDER_MIN_MATCH_POINTS,
) -> tuple[bool, float]:
    """Detect diffuse, non-localized excitation across multiple sensors."""
    if len(connected_locations) < 2 or not possible_by_location:
        return False, 1.0
    loc_rates: list[float] = []
    loc_mean_amps: dict[str, float] = {}
    min_loc_points = max(3, min_match_points)
    for location in connected_locations:
        loc_possible = possible_by_location.get(location, 0)
        loc_matched = matched_by_location.get(location, 0)
        if loc_possible >= min_loc_points:
            loc_rates.append(loc_matched / max(1, loc_possible))
            loc_amps = [
                point.amp
                for point in matched_points
                if (point.location or "").strip() == location and point.amp > 0
            ]
            if loc_amps:
                loc_mean_amps[location] = _mean(loc_amps)
    if len(loc_rates) < 2:
        return False, 1.0
    rate_range = max(loc_rates) - min(loc_rates)
    mean_rate = _mean(loc_rates)
    amp_uniform = True
    if loc_mean_amps and len(loc_mean_amps) >= 2:
        max_amp = max(loc_mean_amps.values())
        min_amp = min(loc_mean_amps.values())
        if min_amp > 0 and max_amp / min_amp > _DIFFUSE_AMPLITUDE_DOMINANCE_RATIO:
            amp_uniform = False
    if (
        rate_range < _DIFFUSE_MATCH_RATE_RANGE_THRESHOLD
        and mean_rate > _DIFFUSE_MIN_MEAN_RATE
        and amp_uniform
    ):
        penalty = max(
            _DIFFUSE_PENALTY_FLOOR,
            _DIFFUSE_PENALTY_BASE - _DIFFUSE_PENALTY_PER_SENSOR * len(loc_rates),
        )
        return True, penalty
    return False, 1.0


def compute_order_confidence(
    *,
    effective_match_rate: float,
    error_score: float,
    corr_val: float,
    snr_score: float,
    absolute_strength_db: float,
    localization_confidence: float,
    weak_spatial_separation: bool,
    dominance_ratio: float | None,
    constant_speed: bool,
    steady_speed: bool,
    matched: int,
    corroborating_locations: int,
    phases_with_evidence: int,
    is_diffuse_excitation: bool,
    diffuse_penalty: float,
    n_connected_locations: int,
    no_wheel_sensors: bool = False,
    path_compliance: float = 1.0,
) -> float:
    """Compute calibrated confidence for an order-tracking finding."""
    corr_shift = max(
        0.0,
        min(_CORR_MAX_SHIFT, _CORR_COMPLIANCE_FACTOR * (path_compliance - 1.0)),
    )
    match_weight = _MATCH_BASE_WEIGHT + corr_shift
    corr_weight = _CORR_BASE_WEIGHT - corr_shift
    confidence = (
        _CONF_BASE
        + (match_weight * effective_match_rate)
        + (_ERROR_WEIGHT * error_score)
        + (corr_weight * corr_val)
        + (_SNR_WEIGHT * snr_score)
    )
    if absolute_strength_db < NEGLIGIBLE_STRENGTH_MAX_DB:
        confidence = min(confidence, _NEGLIGIBLE_STRENGTH_CONF_CAP)
    elif absolute_strength_db < LIGHT_STRENGTH_MAX_DB:
        confidence *= _LIGHT_STRENGTH_PENALTY
    confidence *= _LOCALIZATION_BASE + (
        _LOCALIZATION_SPREAD * max(0.0, min(1.0, localization_confidence))
    )
    if weak_spatial_separation:
        if (
            no_wheel_sensors
            and dominance_ratio is not None
            and dominance_ratio >= _WEAK_SEP_DOMINANCE_THRESHOLD
        ):
            confidence *= _WEAK_SEP_STRONG_PENALTY
        else:
            uniform = dominance_ratio is not None and dominance_ratio < _WEAK_SEP_UNIFORM_DOMINANCE
            confidence *= _WEAK_SEP_UNIFORM_PENALTY if uniform else _WEAK_SEP_MILD_PENALTY
    if no_wheel_sensors and not weak_spatial_separation:
        confidence *= _NO_WHEEL_SENSOR_PENALTY
    if constant_speed:
        confidence *= _CONSTANT_SPEED_PENALTY
    elif steady_speed:
        confidence *= _STEADY_SPEED_PENALTY
    sample_factor = min(1.0, matched / _SAMPLE_SATURATION_COUNT)
    confidence = confidence * (_SAMPLE_WEIGHT_BASE + _SAMPLE_WEIGHT_RANGE * sample_factor)
    if corroborating_locations >= 3:
        confidence *= _CORROBORATING_3_BONUS
    elif corroborating_locations >= 2:
        confidence *= _CORROBORATING_2_BONUS
    if phases_with_evidence >= 3:
        confidence *= _PHASES_3_BONUS
    elif phases_with_evidence >= 2:
        confidence *= _PHASES_2_BONUS
    if is_diffuse_excitation:
        confidence *= diffuse_penalty
    if n_connected_locations <= 1 and localization_confidence >= _LOCALIZATION_MIN_SCALE_THRESHOLD:
        confidence *= _SINGLE_SENSOR_CONFIDENCE_SCALE
    elif (
        n_connected_locations == 2 and localization_confidence >= _LOCALIZATION_MIN_SCALE_THRESHOLD
    ):
        confidence *= _DUAL_SENSOR_CONFIDENCE_SCALE
    return max(_CONF_FLOOR, min(_CONF_CEIL, confidence))


def suppress_engine_aliases(
    findings: list[tuple[float, DomainFinding]],
    *,
    min_confidence: float = ORDER_MIN_CONFIDENCE,
) -> list[DomainFinding]:
    """Suppress engine findings likely to be aliases of stronger wheel findings."""
    best_wheel_conf = max(
        (
            finding.effective_confidence
            for _, finding in findings
            if _normalized_source(finding) == VibrationSource.WHEEL_TIRE
        ),
        default=0.0,
    )
    if best_wheel_conf > 0:
        for index, (ranking_score, finding) in enumerate(findings):
            if _normalized_source(finding) != VibrationSource.ENGINE:
                continue
            eng_conf = finding.effective_confidence
            if eng_conf <= best_wheel_conf * _HARMONIC_ALIAS_RATIO:
                suppressed = eng_conf * _ENGINE_ALIAS_SUPPRESSION
                new_ranking_score = ranking_score * _ENGINE_ALIAS_SUPPRESSION
                finding = replace(
                    finding,
                    confidence=suppressed,
                    ranking_score=new_ranking_score,
                )
                findings[index] = (new_ranking_score, finding)
    findings.sort(key=lambda item: item[0], reverse=True)
    valid = [item[1] for item in findings if item[1].effective_confidence >= min_confidence]
    return valid[:5]


# ═══════════════════════════════════════════════════════════════════════════
# Support helpers
# ═══════════════════════════════════════════════════════════════════════════

_PHASE_ONSET_RELEVANT: frozenset[str] = frozenset(
    {
        DrivingPhase.ACCELERATION.value,
        DrivingPhase.DECELERATION.value,
        DrivingPhase.COAST_DOWN.value,
    },
)


def compute_matched_speed_phase_evidence(
    matched_points: list[OrderMatchObservation],
    *,
    focused_speed_band: str | None,
    hotspot_speed_band: str,
) -> tuple[float | None, list[float], str | None, dict[str, object], str | None]:
    """Derive speed-profile and phase-evidence from matched points."""
    cruise_value = DrivingPhase.CRUISE.value
    speed_points: list[tuple[float, float]] = []
    speed_phase_weights: list[float] = []
    for point in matched_points:
        point_speed = point.speed_kmh
        point_amp = point.amp
        if point_speed is None or point_amp is None:
            continue
        speed_points.append((point_speed, point_amp))
        phase = str(point.phase or "")
        if phase == cruise_value:
            speed_phase_weights.append(3.0)
        elif phase in _PHASE_ONSET_RELEVANT:
            speed_phase_weights.append(0.3)
        else:
            speed_phase_weights.append(1.0)

    peak_speed_kmh, speed_window_kmh, strongest_speed_band = _speed_profile_from_points(
        speed_points,
        allowed_speed_bins=[focused_speed_band] if focused_speed_band else None,
        phase_weights=speed_phase_weights or None,
    )
    if not strongest_speed_band:
        strongest_speed_band = hotspot_speed_band
    if focused_speed_band and not strongest_speed_band:
        strongest_speed_band = focused_speed_band

    matched_phase_strs = [str(point.phase or "") for point in matched_points if point.phase]
    cruise_matched = sum(1 for phase in matched_phase_strs if phase == cruise_value)
    phase_evidence: dict[str, object] = {
        "cruise_fraction": cruise_matched / len(matched_phase_strs) if matched_phase_strs else 0.0,
        "phases_detected": sorted(set(matched_phase_strs)),
    }
    dominant_phase: str | None = None
    onset_phase_labels = [phase for phase in matched_phase_strs if phase in _PHASE_ONSET_RELEVANT]
    if onset_phase_labels and len(onset_phase_labels) >= max(2, len(matched_points) // 2):
        top_phase, top_count = Counter(onset_phase_labels).most_common(1)[0]
        if top_count / len(matched_points) >= 0.50:
            dominant_phase = top_phase

    return (
        peak_speed_kmh,
        list(speed_window_kmh) if speed_window_kmh is not None else [],
        strongest_speed_band or None,
        phase_evidence,
        dominant_phase,
    )


def compute_phase_stats(
    has_phases: bool,
    possible_by_phase: dict[str, int],
    matched_by_phase: dict[str, int],
    *,
    min_match_rate: float,
    min_match_points: int = ORDER_MIN_MATCH_POINTS,
) -> tuple[dict[str, float] | None, int]:
    """Compute per-phase confidence and count phases with sufficient evidence."""
    if not has_phases or not possible_by_phase:
        return None, 0
    per_phase_confidence: dict[str, float] = {}
    phases_with_evidence = 0
    for phase_key, phase_possible in possible_by_phase.items():
        phase_matched = matched_by_phase.get(phase_key, 0)
        per_phase_confidence[phase_key] = phase_matched / max(1, phase_possible)
        if phase_matched >= min_match_points and per_phase_confidence[phase_key] >= min_match_rate:
            phases_with_evidence += 1
    return per_phase_confidence, phases_with_evidence


def compute_amplitude_and_error_stats(
    matched_amp: list[float],
    matched_floor: list[float],
    rel_errors: list[float],
    predicted_vals: list[float],
    measured_vals: list[float],
    matched_points: list[OrderMatchObservation],
    *,
    constant_speed: bool,
) -> tuple[float, float, float, float, float | None]:
    """Compute amplitude, floor, relative-error, and correlation statistics."""
    mean_amp = (sum(matched_amp) / len(matched_amp)) if matched_amp else 0.0
    mean_floor = (sum(matched_floor) / len(matched_floor)) if matched_floor else 0.0
    mean_rel_err = (sum(rel_errors) / len(rel_errors)) if rel_errors else 1.0
    corr = _corr_abs_clamped(predicted_vals, measured_vals) if len(matched_points) >= 3 else None
    if constant_speed:
        corr = None
    corr_val = corr if corr is not None else 0.0
    return mean_amp, mean_floor, mean_rel_err, corr_val, corr


def apply_localization_override(
    *,
    per_location_dominant: bool,
    unique_match_locations: set[str],
    connected_locations: set[str],
    matched: int,
    no_wheel_override: bool,
    localization_confidence: float,
    weak_spatial_separation: bool,
    min_match_points: int = ORDER_MIN_MATCH_POINTS,
) -> tuple[float, bool]:
    """Adjust localization confidence when only one connected sensor matched."""
    if (
        per_location_dominant
        and len(unique_match_locations) == 1
        and len(connected_locations) >= 2
        and not no_wheel_override
    ):
        localization_confidence = min(1.0, 0.50 + 0.15 * (len(connected_locations) - 1))
        weak_spatial_separation = False
    elif (
        len(unique_match_locations) == 1
        and len(connected_locations) >= 2
        and matched >= min_match_points
        and not no_wheel_override
    ):
        localization_confidence = max(
            localization_confidence,
            min(1.0, 0.40 + 0.10 * (len(connected_locations) - 1)),
        )
        weak_spatial_separation = False
    return localization_confidence, weak_spatial_separation


# ═══════════════════════════════════════════════════════════════════════════
# Hypothesis assembly and order-finding builder
# ═══════════════════════════════════════════════════════════════════════════


def assemble_order_finding(
    hypothesis: OrderHypothesis,
    match: OrderMatchAccumulator,
    *,
    context: OrderFindingBuildContext,
) -> tuple[float, DomainFinding]:
    """Build a single order finding from a successful match result."""
    per_phase_confidence, phases_with_evidence = compute_phase_stats(
        match.has_phases,
        match.possible_by_phase,
        match.matched_by_phase,
        min_match_rate=context.min_match_rate,
    )
    mean_amp, mean_floor, mean_rel_err, corr_val, corr = compute_amplitude_and_error_stats(
        match.matched_amp,
        match.matched_floor,
        match.rel_errors,
        match.predicted_vals,
        match.measured_vals,
        match.matched_points,
        constant_speed=context.constant_speed,
    )

    relevant_speed_bins = [context.focused_speed_band] if context.focused_speed_band else None

    # Lazy import to avoid circular dependency (location_analysis imports from this module).
    from vibesensor.use_cases.diagnostics.location_analysis import _location_speedbin_summary

    location_line, location_hotspot = _location_speedbin_summary(
        match.matched_points,
        lang=context.lang,
        relevant_speed_bins=relevant_speed_bins,
        connected_locations=context.connected_locations,
        suspected_source=hypothesis.suspected_source,
    )
    loc_result = location_hotspot  # LocationAnalysisResult | None
    domain_hotspot = loc_result.hotspot if loc_result is not None else None
    if domain_hotspot is not None and loc_result is not None:
        supporting_locations = list(domain_hotspot.alternative_locations)
        if loc_result.second_location and loc_result.second_location not in supporting_locations:
            supporting_locations.append(loc_result.second_location)
        domain_hotspot = replace(
            domain_hotspot,
            alternative_locations=tuple(supporting_locations),
            location_count=max(
                1,
                len({domain_hotspot.strongest_location, *supporting_locations} - {""}),
            ),
        )
    weak_spatial_separation = (
        domain_hotspot.weak_spatial_separation if domain_hotspot is not None else True
    )
    dominance_ratio = domain_hotspot.dominance_ratio if domain_hotspot is not None else None
    localization_confidence = (
        domain_hotspot.localization_confidence or 0.05 if domain_hotspot is not None else 0.05
    )

    unique_match_locations = match.unique_match_locations
    no_wheel_override = loc_result.no_wheel_sensors if loc_result is not None else False
    localization_confidence, weak_spatial_separation = apply_localization_override(
        per_location_dominant=context.per_location_dominant,
        unique_match_locations=unique_match_locations,
        connected_locations=context.connected_locations,
        matched=match.matched,
        no_wheel_override=no_wheel_override,
        localization_confidence=localization_confidence,
        weak_spatial_separation=weak_spatial_separation,
    )

    corroborating_locations = len(unique_match_locations)
    error_denominator = 0.25 * match.compliance
    error_score = max(0.0, 1.0 - min(1.0, mean_rel_err / error_denominator))
    snr_score = min(1.0, log1p(mean_amp / max(MEMS_NOISE_FLOOR_G, mean_floor)) / SNR_LOG_DIVISOR)
    if mean_amp <= 2 * MEMS_NOISE_FLOOR_G:
        snr_score = min(snr_score, 0.40)
    absolute_strength_db = canonical_vibration_db(
        peak_band_rms_amp_g=mean_amp,
        floor_amp_g=max(MEMS_NOISE_FLOOR_G, mean_floor),
    )

    diffuse_excitation, diffuse_penalty = detect_diffuse_excitation(
        context.connected_locations,
        match.possible_by_location,
        match.matched_by_location,
        match.matched_points,
    )
    confidence = compute_order_confidence(
        effective_match_rate=context.effective_match_rate,
        error_score=error_score,
        corr_val=corr_val,
        snr_score=snr_score,
        absolute_strength_db=absolute_strength_db,
        localization_confidence=localization_confidence,
        weak_spatial_separation=weak_spatial_separation,
        dominance_ratio=dominance_ratio,
        constant_speed=context.constant_speed,
        steady_speed=context.steady_speed,
        matched=match.matched,
        corroborating_locations=corroborating_locations,
        phases_with_evidence=phases_with_evidence,
        is_diffuse_excitation=diffuse_excitation,
        diffuse_penalty=diffuse_penalty,
        n_connected_locations=len(context.connected_locations),
        no_wheel_sensors=no_wheel_override,
        path_compliance=match.compliance,
    )

    ranking_score = (
        context.effective_match_rate
        * log1p(mean_amp / max(MEMS_NOISE_FLOOR_G, mean_floor))
        * max(0.0, (1.0 - min(1.0, mean_rel_err / (0.25 * match.compliance))))
    )

    ref_text = ", ".join(sorted(match.ref_sources))
    evidence = i18n_ref(
        "EVIDENCE_ORDER_TRACKED",
        order_label=_order_label(hypothesis.order, hypothesis.order_label_base),
        matched=match.matched,
        possible=match.possible,
        match_rate=context.effective_match_rate,
        mean_rel_err=mean_rel_err,
        ref_text=ref_text,
    )
    if location_line:
        evidence = dict(evidence)
        evidence["_suffix"] = f" {location_line}"

    strongest_location = loc_result.display_location if loc_result is not None else ""
    hotspot_speed_band = loc_result.speed_range if loc_result is not None else ""
    (
        peak_speed_kmh,
        speed_window_kmh,
        strongest_speed_band,
        phase_evidence,
        dominant_phase,
    ) = compute_matched_speed_phase_evidence(
        match.matched_points,
        focused_speed_band=context.focused_speed_band,
        hotspot_speed_band=hotspot_speed_band,
    )
    phases_raw = phase_evidence.get("phases_detected")
    phases_detected = tuple(phases_raw) if isinstance(phases_raw, list) else ()
    finding = DomainFinding(
        finding_id="F_ORDER",
        finding_key=hypothesis.key,
        suspected_source=hypothesis.suspected_source,
        confidence=confidence,
        order=_order_label(hypothesis.order, hypothesis.order_label_base),
        strongest_location=strongest_location or None,
        strongest_speed_band=strongest_speed_band or None,
        kind=FindingKind.DIAGNOSTIC,
        dominant_phase=dominant_phase,
        ranking_score=ranking_score,
        dominance_ratio=dominance_ratio,
        diffuse_excitation=diffuse_excitation,
        weak_spatial_separation=weak_spatial_separation,
        vibration_strength_db=absolute_strength_db,
        cruise_fraction=_as_float(phase_evidence["cruise_fraction"]) or 0.0,
        phases_detected=phases_detected,
        matched_points=tuple(match.matched_points),
        evidence=FindingEvidence(
            match_rate=context.effective_match_rate,
            global_match_rate=context.match_rate,
            focused_speed_band=context.focused_speed_band,
            mean_relative_error=mean_rel_err,
            mean_noise_floor_db=canonical_vibration_db(
                peak_band_rms_amp_g=max(MEMS_NOISE_FLOOR_G, mean_floor),
                floor_amp_g=MEMS_NOISE_FLOOR_G,
            ),
            possible_samples=match.possible,
            matched_samples=match.matched,
            frequency_correlation=corr or 0.0,
            phases_with_evidence=phases_with_evidence,
            phase_confidences=(
                tuple(sorted(per_phase_confidence.items())) if per_phase_confidence else ()
            ),
            vibration_strength_db=absolute_strength_db,
        ),
        location=domain_hotspot,
        origin=VibrationOrigin.from_analysis_inputs(
            suspected_source=hypothesis.suspected_source,
            hotspot=domain_hotspot,
            dominance_ratio=dominance_ratio,
            speed_band=strongest_speed_band or None,
            dominant_phase=dominant_phase,
        ),
    )
    return ranking_score, finding


def _compute_effective_match_rate(
    match_rate: float,
    min_match_rate: float,
    possible_by_speed_bin: dict[str, int],
    matched_by_speed_bin: dict[str, int],
    possible_by_location: dict[str, int],
    matched_by_location: dict[str, int],
) -> tuple[float, str | None, bool]:
    """Rescue a below-threshold match rate via focused speed-band or per-location evidence.

    Returns (effective_match_rate, focused_speed_band, per_location_dominant).
    """
    effective_match_rate = match_rate
    focused_speed_band: str | None = None
    if match_rate < min_match_rate and possible_by_speed_bin:
        highest_speed_bin = max(
            possible_by_speed_bin.keys(),
            key=lambda k: speed_band_sort_key(k),
        )
        focused_possible = int(possible_by_speed_bin[highest_speed_bin])
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
    per_location_dominant: bool = False
    if effective_match_rate < min_match_rate and possible_by_location:
        best_loc_rate = 0.0
        for loc, loc_possible in possible_by_location.items():
            loc_matched = matched_by_location.get(loc, 0)
            if loc_possible >= ORDER_MIN_COVERAGE_POINTS and loc_matched >= ORDER_MIN_MATCH_POINTS:
                loc_rate = loc_matched / max(1, loc_possible)
                best_loc_rate = max(best_loc_rate, loc_rate)
        if best_loc_rate >= min_match_rate:
            effective_match_rate = best_loc_rate
            per_location_dominant = True
    return effective_match_rate, focused_speed_band, per_location_dominant


class OrderAnalysisSession:
    """Coordinates hypothesis testing across samples to produce order findings.

    Owns the hypothesis loop, per-hypothesis matching, eligibility filtering,
    effective-rate computation, finding assembly, and engine-alias suppression.
    """

    __slots__ = (
        "_metadata",
        "_samples",
        "_speed_sufficient",
        "_steady_speed",
        "_speed_stddev_kmh",
        "_tire_circumference_m",
        "_engine_ref_sufficient",
        "_raw_sample_rate_hz",
        "_connected_locations",
        "_lang",
        "_per_sample_phases",
        "_cached_peaks",
        "_order_reference_spec",
    )

    def __init__(
        self,
        *,
        metadata: JsonObject,
        samples: list[Sample],
        speed_sufficient: bool,
        steady_speed: bool,
        speed_stddev_kmh: float | None,
        tire_circumference_m: float | None,
        engine_ref_sufficient: bool,
        raw_sample_rate_hz: float | None,
        connected_locations: set[str],
        lang: str,
        per_sample_phases: PhaseLabels | None = None,
    ) -> None:
        self._metadata = metadata
        self._samples = samples
        self._speed_sufficient = speed_sufficient
        self._steady_speed = steady_speed
        self._speed_stddev_kmh = speed_stddev_kmh
        self._tire_circumference_m = tire_circumference_m
        self._engine_ref_sufficient = engine_ref_sufficient
        self._raw_sample_rate_hz = raw_sample_rate_hz
        self._connected_locations = connected_locations
        self._lang = lang
        self._per_sample_phases = per_sample_phases
        self._order_reference_spec = _order_reference_spec_from_context(metadata)
        # Pre-compute peaks once for all hypotheses
        self._cached_peaks: list[list[tuple[float, float]]] = [
            _sample_top_peaks(s) for s in samples
        ]

    def analyze(self) -> list[DomainFinding]:
        """Run all hypothesis tests and return suppressed, ranked findings."""
        if self._raw_sample_rate_hz is None or self._raw_sample_rate_hz <= 0:
            return []

        findings: list[tuple[float, DomainFinding]] = []
        for hypothesis in _order_hypotheses():
            if not self._should_test(hypothesis):
                continue
            result = self._test_hypothesis(hypothesis)
            if result is not None:
                findings.append(result)

        return suppress_engine_aliases(findings, min_confidence=ORDER_MIN_CONFIDENCE)

    def _should_test(self, hypothesis: OrderHypothesis) -> bool:
        """Whether to test this hypothesis given available references."""
        spec = self._order_reference_spec
        if hypothesis.key.startswith("wheel_"):
            return self._speed_sufficient and (
                (spec is not None and spec.supports_wheel_reference)
                or (self._tire_circumference_m is not None and self._tire_circumference_m > 0)
            )
        if hypothesis.key.startswith("driveshaft_"):
            return self._speed_sufficient and (
                (spec is not None and spec.supports_driveshaft_reference)
                or (self._tire_circumference_m is not None and self._tire_circumference_m > 0)
            )
        if hypothesis.key.startswith("engine_"):
            return self._engine_ref_sufficient
        return True

    def _test_hypothesis(
        self,
        hypothesis: OrderHypothesis,
    ) -> tuple[float, DomainFinding] | None:
        """Match, evaluate, and assemble a finding for one hypothesis.

        Returns ``(ranking_score, finding)`` or ``None`` if the hypothesis
        does not meet eligibility or match-rate thresholds.
        """
        m = match_samples_for_hypothesis(
            self._samples,
            self._cached_peaks,
            hypothesis,
            self._metadata,
            self._tire_circumference_m,
            self._per_sample_phases,
            self._lang,
        )
        if not m.is_eligible():
            return None

        # At constant speed the predicted frequency never varies, so random
        # broadband peaks match by chance at ~30-40%.  Require a much higher
        # match rate before claiming a finding.
        constant_speed = (
            self._speed_stddev_kmh is not None
            and self._speed_stddev_kmh < CONSTANT_SPEED_STDDEV_KMH
        )
        min_match_rate = ORDER_CONSTANT_SPEED_MIN_MATCH_RATE if constant_speed else 0.25

        effective_match_rate, focused_speed_band, per_location_dominant = (
            _compute_effective_match_rate(
                m.match_rate,
                min_match_rate,
                m.possible_by_speed_bin,
                m.matched_by_speed_bin,
                m.possible_by_location,
                m.matched_by_location,
            )
        )
        if effective_match_rate < min_match_rate:
            return None

        return assemble_order_finding(
            hypothesis,
            m,
            context=OrderFindingBuildContext(
                effective_match_rate=effective_match_rate,
                focused_speed_band=focused_speed_band,
                per_location_dominant=per_location_dominant,
                match_rate=m.match_rate,
                min_match_rate=min_match_rate,
                constant_speed=constant_speed,
                steady_speed=self._steady_speed,
                connected_locations=self._connected_locations,
                lang=self._lang,
            ),
        )


def _build_order_findings(
    *,
    metadata: JsonObject,
    samples: list[Sample],
    speed_sufficient: bool,
    steady_speed: bool,
    speed_stddev_kmh: float | None,
    tire_circumference_m: float | None,
    engine_ref_sufficient: bool,
    raw_sample_rate_hz: float | None,
    connected_locations: set[str],
    lang: str,
    per_sample_phases: PhaseLabels | None = None,
) -> list[DomainFinding]:
    """Build order-tracking findings by testing all hypotheses.

    Delegates to :class:`OrderAnalysisSession` which owns the hypothesis
    loop, matching, eligibility, and engine-alias suppression.
    """
    session = OrderAnalysisSession(
        metadata=metadata,
        samples=samples,
        speed_sufficient=speed_sufficient,
        steady_speed=steady_speed,
        speed_stddev_kmh=speed_stddev_kmh,
        tire_circumference_m=tire_circumference_m,
        engine_ref_sufficient=engine_ref_sufficient,
        raw_sample_rate_hz=raw_sample_rate_hz,
        connected_locations=connected_locations,
        lang=lang,
        per_sample_phases=per_sample_phases,
    )
    return session.analyze()
