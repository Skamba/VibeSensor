"""Order-tracking analysis: Hz helpers, hypotheses, matching, scoring, and assembly."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import log1p

from vibesensor.domain import LocationHotspot
from vibesensor.domain.diagnostics.finding import (
    VibrationSource,
    speed_band_sort_key,
    speed_bin_label,
)
from vibesensor.infra.config.analysis_settings import wheel_hz_from_speed_kmh
from vibesensor.infra.config.constants import (
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    CONSTANT_SPEED_STDDEV_KMH,
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
from vibesensor.shared.utils.json_utils import as_float_or_none as _as_float
from vibesensor.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ._types import (
    FindingPayload,
    I18nRef,
    JsonValue,
    MatchedPoint,
    MetadataDict,
    PhaseEvidence,
    PhaseLabels,
    Sample,
    TestStep,
    i18n_ref,
)
from .helpers import (
    _corr_abs_clamped,
    _effective_engine_rpm,
    _estimate_strength_floor_amp_g,
    _location_label,
    _phase_to_str,
    _sample_top_peaks,
    _speed_profile_from_points,
)
from .phase_segmentation import DrivingPhase

# ═══════════════════════════════════════════════════════════════════════════
# Hz helpers, hypotheses, and action plans
# ═══════════════════════════════════════════════════════════════════════════


def _wheel_hz(sample: Sample, tire_circumference_m: float | None) -> float | None:
    speed_kmh = _as_float(sample.get("speed_kmh"))
    if speed_kmh is None or speed_kmh <= 0:
        return None
    if tire_circumference_m is None or tire_circumference_m <= 0:
        return None
    wheel_hz = wheel_hz_from_speed_kmh(speed_kmh, tire_circumference_m)
    return float(wheel_hz) if wheel_hz is not None else None


def _driveshaft_hz(
    sample: Sample,
    metadata: MetadataDict,
    tire_circumference_m: float | None,
) -> float | None:
    whz = _wheel_hz(sample, tire_circumference_m)
    fd = _as_float(sample.get("final_drive_ratio")) or _as_float(metadata.get("final_drive_ratio"))
    if whz is None or fd is None or fd <= 0:
        return None
    return float(whz * fd)


def _engine_hz(
    sample: Sample,
    metadata: MetadataDict,
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
    suspected_source: str
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
        metadata: MetadataDict,
        tire_circumference_m: float | None,
    ) -> tuple[float | None, str]:
        if self.order_label_base == "wheel":
            base = _wheel_hz(sample, tire_circumference_m)
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


# Ordered (token, i18n_key) pairs for wheel-focus resolution.
# More-specific patterns come first so the first match wins.
_WHEEL_FOCUS_RULES: tuple[tuple[str, str], ...] = (
    ("front left wheel", "WHEEL_FOCUS_FRONT_LEFT"),
    ("front right wheel", "WHEEL_FOCUS_FRONT_RIGHT"),
    ("rear left wheel", "WHEEL_FOCUS_REAR_LEFT"),
    ("rear right wheel", "WHEEL_FOCUS_REAR_RIGHT"),
)


def _wheel_focus_from_location(location: str) -> I18nRef:
    """Return an i18n reference for the wheel focus label."""
    # Normalize hyphens/underscores to spaces for robust matching against
    # label_for_code() output which uses spaces (e.g. "Front Left Wheel").
    token = location.strip().lower().replace("-", " ").replace("_", " ")
    for pattern, key in _WHEEL_FOCUS_RULES:
        if pattern in token:
            return {"_i18n_key": key}
    if "rear" in token or "trunk" in token:
        return {"_i18n_key": "WHEEL_FOCUS_REAR"}
    if "front" in token or "engine" in token:
        return {"_i18n_key": "WHEEL_FOCUS_FRONT"}
    return {"_i18n_key": "WHEEL_FOCUS_ALL"}


def _finding_actions_for_source(
    source: str,
    *,
    strongest_location: str = "",
    strongest_speed_band: str = "",
    weak_spatial_separation: bool = False,
) -> list[TestStep]:
    """Return language-neutral action plan dicts with i18n references.

    Each ``what``, ``why``, ``confirm``, ``falsify`` field is an i18n reference
    dict (``{"_i18n_key": "KEY", ...params}``) that the report layer resolves
    at render time.

    Parameters
    ----------
    source:
        Vibration source string.
        Recognised values: ``"wheel/tire"``, ``"driveline"``, ``"engine"``.
    strongest_location:
        Sensor location code (e.g. ``"front_left"``) used to tailor action
        hints toward the most affected wheel or mounting position.
    strongest_speed_band:
        Speed band string (e.g. ``"80–100 km/h"``) injected into speed-focus
        action hints so the technician knows at which speed to reproduce the
        symptom.
    weak_spatial_separation:
        When ``True``, the action plan notes that sensor locations produced
        similar intensities, which weakens spatial localisation confidence.

    """
    location = strongest_location.strip()
    speed_band = strongest_speed_band.strip()
    # Only include speed_hint param when a speed band is available; passing an
    # empty string (the previous behaviour) included speed_hint="" in the i18n
    # ref dict, which is semantically different from the key being absent and
    # could confuse template renderers that check for key presence vs truthiness.
    _speed_hint_param: I18nRef = (
        {"speed_hint": i18n_ref("SPEED_HINT_FOCUS", speed_band=speed_band)} if speed_band else {}
    )
    if source == VibrationSource.WHEEL_TIRE:
        wheel_focus = _wheel_focus_from_location(location)
        location_hint = (
            i18n_ref("LOCATION_HINT_NEAR", location=location)
            if location
            else i18n_ref("LOCATION_HINT_AT_WHEEL_CORNERS")
        )
        return [
            {
                "action_id": "wheel_balance_and_runout",
                "what": i18n_ref(
                    "ACTION_WHEEL_BALANCE_WHAT",
                    wheel_focus=wheel_focus,
                    **_speed_hint_param,
                ),
                "why": i18n_ref("ACTION_WHEEL_BALANCE_WHY", location_hint=location_hint),
                "confirm": i18n_ref("ACTION_WHEEL_BALANCE_CONFIRM"),
                "falsify": i18n_ref("ACTION_WHEEL_BALANCE_FALSIFY"),
                "eta": "20-45 min",
            },
            {
                "action_id": "wheel_tire_condition",
                "what": i18n_ref("ACTION_TIRE_CONDITION_WHAT", wheel_focus=wheel_focus),
                "why": i18n_ref("ACTION_TIRE_CONDITION_WHY"),
                "confirm": i18n_ref("ACTION_TIRE_CONDITION_CONFIRM"),
                "falsify": i18n_ref("ACTION_TIRE_CONDITION_FALSIFY"),
                "eta": "10-20 min",
            },
        ]
    if source == VibrationSource.DRIVELINE:
        driveline_focus = (
            i18n_ref("LOCATION_HINT_NEAR_SHORT", location=location)
            if location
            else i18n_ref("LOCATION_HINT_ALONG_DRIVELINE")
        )
        return [
            {
                "action_id": "driveline_inspection",
                "what": i18n_ref(
                    "ACTION_DRIVELINE_INSPECTION_WHAT",
                    driveline_focus=driveline_focus,
                ),
                "why": i18n_ref("ACTION_DRIVELINE_INSPECTION_WHY"),
                "confirm": i18n_ref("ACTION_DRIVELINE_INSPECTION_CONFIRM"),
                "falsify": i18n_ref("ACTION_DRIVELINE_INSPECTION_FALSIFY"),
                "eta": "20-35 min",
            },
            {
                "action_id": "driveline_mounts_and_fasteners",
                "what": i18n_ref("ACTION_DRIVELINE_MOUNTS_WHAT"),
                "why": i18n_ref("ACTION_DRIVELINE_MOUNTS_WHY"),
                "confirm": i18n_ref("ACTION_DRIVELINE_MOUNTS_CONFIRM"),
                "falsify": i18n_ref("ACTION_DRIVELINE_MOUNTS_FALSIFY"),
                "eta": "10-20 min",
            },
        ]
    if source == VibrationSource.ENGINE:
        return [
            {
                "action_id": "engine_mounts_and_accessories",
                "what": i18n_ref("ACTION_ENGINE_MOUNTS_WHAT"),
                "why": i18n_ref("ACTION_ENGINE_MOUNTS_WHY"),
                "confirm": i18n_ref("ACTION_ENGINE_MOUNTS_CONFIRM"),
                "falsify": i18n_ref("ACTION_ENGINE_MOUNTS_FALSIFY"),
                "eta": "15-30 min",
            },
            {
                "action_id": "engine_combustion_quality",
                "what": i18n_ref("ACTION_ENGINE_COMBUSTION_WHAT"),
                "why": i18n_ref("ACTION_ENGINE_COMBUSTION_WHY"),
                "confirm": i18n_ref("ACTION_ENGINE_COMBUSTION_CONFIRM"),
                "falsify": i18n_ref("ACTION_ENGINE_COMBUSTION_FALSIFY"),
                "eta": "10-20 min",
            },
        ]
    fallback_why = i18n_ref("ACTION_GENERAL_FALLBACK_WHY")
    if weak_spatial_separation:
        fallback_why = i18n_ref("ACTION_GENERAL_WEAK_SPATIAL_WHY")
    return [
        {
            "action_id": "general_mechanical_inspection",
            "what": i18n_ref("ACTION_GENERAL_INSPECTION_WHAT"),
            "why": fallback_why,
            "confirm": i18n_ref("ACTION_GENERAL_INSPECTION_CONFIRM"),
            "falsify": i18n_ref("ACTION_GENERAL_INSPECTION_FALSIFY"),
            "eta": "20-35 min",
        },
    ]


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
    matched_points: list[MatchedPoint]
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
        return {
            str(point.get("location") or "")
            for point in self.matched_points
            if point.get("location")
        }

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
    metadata: MetadataDict,
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
    matched_points: list[MatchedPoint] = []
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
            {
                "t_s": _as_float(sample.get("t_s")),
                "speed_kmh": _as_float(sample.get("speed_kmh")),
                "predicted_hz": predicted_hz,
                "matched_hz": best_hz,
                "rel_error": delta_hz / max(1e-9, predicted_hz),
                "amp": best_amp,
                "location": sample_location,
                "phase": (
                    _phase_to_str(per_sample_phases[sample_idx])
                    if has_phases and per_sample_phases is not None
                    else None
                ),
            },
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


def _normalized_source(finding: FindingPayload) -> str:
    return str(finding.get("suspected_source") or "").strip().lower()


def detect_diffuse_excitation(
    connected_locations: set[str],
    possible_by_location: dict[str, int],
    matched_by_location: dict[str, int],
    matched_points: list[MatchedPoint],
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
                amp_val
                for point in matched_points
                if str(point.get("location") or "").strip() == location
                and (amp_val := _as_float(point.get("amp"))) is not None
                and amp_val > 0
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
    findings: list[tuple[float, FindingPayload]],
    *,
    min_confidence: float = ORDER_MIN_CONFIDENCE,
) -> list[FindingPayload]:
    """Suppress engine findings likely to be aliases of stronger wheel findings."""
    best_wheel_conf = max(
        (
            _as_float(finding.get("confidence")) or 0.0
            for _, finding in findings
            if _normalized_source(finding) == VibrationSource.WHEEL_TIRE
        ),
        default=0.0,
    )
    if best_wheel_conf > 0:
        for index, (ranking_score, finding) in enumerate(findings):
            if _normalized_source(finding) != VibrationSource.ENGINE:
                continue
            eng_conf = _as_float(finding.get("confidence")) or 0.0
            if eng_conf <= best_wheel_conf * _HARMONIC_ALIAS_RATIO:
                suppressed = eng_conf * _ENGINE_ALIAS_SUPPRESSION
                finding["confidence"] = suppressed
                new_ranking_score = ranking_score * _ENGINE_ALIAS_SUPPRESSION
                finding["ranking_score"] = new_ranking_score
                findings[index] = (new_ranking_score, finding)
    findings.sort(key=lambda item: item[0], reverse=True)
    valid = [
        item[1]
        for item in findings
        if (_as_float(item[1].get("confidence")) or 0.0) >= min_confidence
    ]
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
    matched_points: list[MatchedPoint],
    *,
    focused_speed_band: str | None,
    hotspot_speed_band: str,
) -> tuple[float | None, list[float], str | None, PhaseEvidence, str | None]:
    """Derive speed-profile and phase-evidence from matched points."""
    cruise_value = DrivingPhase.CRUISE.value
    speed_points: list[tuple[float, float]] = []
    speed_phase_weights: list[float] = []
    for point in matched_points:
        point_speed = _as_float(point.get("speed_kmh"))
        point_amp = _as_float(point.get("amp"))
        if point_speed is None or point_amp is None:
            continue
        speed_points.append((point_speed, point_amp))
        phase = str(point.get("phase") or "")
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

    matched_phase_strs = [
        str(point.get("phase") or "") for point in matched_points if point.get("phase")
    ]
    cruise_matched = sum(1 for phase in matched_phase_strs if phase == cruise_value)
    phase_evidence: PhaseEvidence = {
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
    matched_points: list[MatchedPoint],
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
) -> tuple[float, FindingPayload]:
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
    from .location_analysis import _location_speedbin_summary

    location_line, location_hotspot = _location_speedbin_summary(
        match.matched_points,
        lang=context.lang,
        relevant_speed_bins=relevant_speed_bins,
        connected_locations=context.connected_locations,
        suspected_source=hypothesis.suspected_source,
    )
    hotspot_dict = location_hotspot if isinstance(location_hotspot, dict) else None
    domain_hotspot = (
        LocationHotspot.from_analysis_inputs(
            strongest_location=str(hotspot_dict.get("top_location") or "").strip(),
            dominance_ratio=_as_float(hotspot_dict.get("dominance_ratio")),
            localization_confidence=_as_float(hotspot_dict.get("localization_confidence")) or 0.05,
            weak_spatial_separation=bool(hotspot_dict.get("weak_spatial_separation")),
            ambiguous=bool(hotspot_dict.get("ambiguous_location")),
            alternative_locations=list(hotspot_dict.get("ambiguous_locations") or []),
        )
        if hotspot_dict is not None
        else None
    )
    weak_spatial_separation = (
        domain_hotspot.weak_spatial_separation if domain_hotspot is not None else True
    )
    dominance_ratio = domain_hotspot.dominance_ratio if domain_hotspot is not None else None
    localization_confidence = (
        domain_hotspot.localization_confidence or 0.05 if domain_hotspot is not None else 0.05
    )

    unique_match_locations = match.unique_match_locations
    no_wheel_override = (
        bool(hotspot_dict.get("no_wheel_sensors")) if hotspot_dict is not None else False
    )
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

    strongest_location = str(hotspot_dict.get("location")) if hotspot_dict is not None else ""
    hotspot_speed_band = str(hotspot_dict.get("speed_range")) if hotspot_dict is not None else ""
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
    actions = _finding_actions_for_source(
        hypothesis.suspected_source,
        strongest_location=strongest_location,
        strongest_speed_band=strongest_speed_band or "",
        weak_spatial_separation=weak_spatial_separation,
    )
    quick_checks: list[JsonValue] = [action["what"] for action in actions if action.get("what")][:3]
    finding: FindingPayload = {
        "finding_id": "F_ORDER",
        "finding_key": hypothesis.key,
        "finding_kind": "diagnostic",
        "suspected_source": hypothesis.suspected_source,
        "evidence_summary": evidence,
        "frequency_hz_or_order": _order_label(hypothesis.order, hypothesis.order_label_base),
        "amplitude_metric": {
            "name": "vibration_strength_db",
            "value": absolute_strength_db,
            "units": "dB",
            "definition": i18n_ref("METRIC_VIBRATION_STRENGTH_DB"),
        },
        "confidence": confidence,
        "quick_checks": quick_checks,
        "matched_points": match.matched_points,
        "location_hotspot": hotspot_dict,
        "strongest_location": strongest_location or None,
        "strongest_speed_band": strongest_speed_band or None,
        "dominant_phase": dominant_phase,
        "peak_speed_kmh": peak_speed_kmh,
        "speed_window_kmh": list(speed_window_kmh) if speed_window_kmh else None,
        "dominance_ratio": dominance_ratio,
        "localization_confidence": localization_confidence,
        "weak_spatial_separation": weak_spatial_separation,
        "corroborating_locations": corroborating_locations,
        "diffuse_excitation": diffuse_excitation,
        "phase_evidence": phase_evidence,
        "evidence_metrics": {
            "match_rate": context.effective_match_rate,
            "global_match_rate": context.match_rate,
            "focused_speed_band": context.focused_speed_band,
            "mean_relative_error": mean_rel_err,
            "mean_noise_floor_db": canonical_vibration_db(
                peak_band_rms_amp_g=max(MEMS_NOISE_FLOOR_G, mean_floor),
                floor_amp_g=MEMS_NOISE_FLOOR_G,
            ),
            "vibration_strength_db": absolute_strength_db,
            "possible_samples": match.possible,
            "matched_samples": match.matched,
            "frequency_correlation": corr,
            "per_phase_confidence": per_phase_confidence,
            "phases_with_evidence": phases_with_evidence,
        },
        "next_sensor_move": (
            actions[0].get("what") if actions else i18n_ref("NEXT_SENSOR_MOVE_DEFAULT")
        ),
        "actions": actions,
        "ranking_score": ranking_score,
    }
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
    )

    def __init__(
        self,
        *,
        metadata: MetadataDict,
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
        # Pre-compute peaks once for all hypotheses
        self._cached_peaks: list[list[tuple[float, float]]] = [
            _sample_top_peaks(s) for s in samples
        ]

    def analyze(self) -> list[FindingPayload]:
        """Run all hypothesis tests and return suppressed, ranked findings."""
        if self._raw_sample_rate_hz is None or self._raw_sample_rate_hz <= 0:
            return []

        findings: list[tuple[float, FindingPayload]] = []
        for hypothesis in _order_hypotheses():
            if not self._should_test(hypothesis):
                continue
            result = self._test_hypothesis(hypothesis)
            if result is not None:
                findings.append(result)

        return suppress_engine_aliases(findings, min_confidence=ORDER_MIN_CONFIDENCE)

    def _should_test(self, hypothesis: OrderHypothesis) -> bool:
        """Whether to test this hypothesis given available references."""
        if hypothesis.key.startswith(("wheel_", "driveshaft_")):
            return (
                self._speed_sufficient
                and self._tire_circumference_m is not None
                and self._tire_circumference_m > 0
            )
        if hypothesis.key.startswith("engine_"):
            return self._engine_ref_sufficient
        return True

    def _test_hypothesis(self, hypothesis: OrderHypothesis) -> tuple[float, FindingPayload] | None:
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
    metadata: MetadataDict,
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
) -> list[FindingPayload]:
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
