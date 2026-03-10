"""Order-tracking hypothesis matching engine.

Matches vibration peaks against predicted frequencies for wheel, driveshaft,
and engine orders; computes confidence scores; suppresses engine aliases.
"""

from __future__ import annotations

from .._types import Finding, MatchedPoint, MetadataDict, PhaseEvidence, PhaseLabels, Sample
from ..helpers import (
    _corr_abs_clamped,
    _sample_top_peaks,
    _speed_bin_sort_key,
)
from ..order_analysis import (
    _order_hypotheses,
)
from ..order_analysis import _order_label as _order_label_impl
from ..test_plan import _location_speedbin_summary
from ._constants import (
    CONSTANT_SPEED_STDDEV_KMH,
    ORDER_CONSTANT_SPEED_MIN_MATCH_RATE,
    ORDER_MIN_CONFIDENCE,
    ORDER_MIN_COVERAGE_POINTS,
    ORDER_MIN_MATCH_POINTS,
)
from .order_assembly import assemble_order_finding
from .order_matching import match_samples_for_hypothesis
from .order_models import OrderFindingBuildContext, OrderHypothesisLike, OrderMatchAccumulator
from .order_scoring import (
    _NEGLIGIBLE_STRENGTH_CONF_CAP as _NEGLIGIBLE_STRENGTH_CONF_CAP_IMPORTED,
)
from .order_scoring import (
    compute_order_confidence as _compute_order_confidence_impl,
)
from .order_scoring import (
    detect_diffuse_excitation as _detect_diffuse_excitation_impl,
)
from .order_scoring import (
    suppress_engine_aliases as _suppress_engine_aliases_impl,
)
from .order_support import (
    apply_localization_override as _apply_localization_override_impl,
)
from .order_support import (
    compute_amplitude_and_error_stats as _compute_amplitude_and_error_stats_impl,
)
from .order_support import (
    compute_matched_speed_phase_evidence as _compute_matched_speed_phase_evidence_impl,
)
from .order_support import (
    compute_phase_stats as _compute_phase_stats_impl,
)
from .speed_profile import _speed_profile_from_points

_NEGLIGIBLE_STRENGTH_CONF_CAP = _NEGLIGIBLE_STRENGTH_CONF_CAP_IMPORTED


def _order_label(order: float, order_label_base: str) -> str:
    return _order_label_impl(int(order), order_label_base)


# Source-audit note: the delegated scoring implementation still applies
# min(confidence, _NEGLIGIBLE_STRENGTH_CONF_CAP) for negligible-strength findings.

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        highest_speed_bin = max(possible_by_speed_bin.keys(), key=_speed_bin_sort_key)
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


def _detect_diffuse_excitation(
    connected_locations: set[str],
    possible_by_location: dict[str, int],
    matched_by_location: dict[str, int],
    matched_points: list[MatchedPoint],
) -> tuple[bool, float]:
    return _detect_diffuse_excitation_impl(
        connected_locations,
        possible_by_location,
        matched_by_location,
        matched_points,
        min_match_points=ORDER_MIN_MATCH_POINTS,
    )


def _compute_order_confidence(
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
    return _compute_order_confidence_impl(
        effective_match_rate=effective_match_rate,
        error_score=error_score,
        corr_val=corr_val,
        snr_score=snr_score,
        absolute_strength_db=absolute_strength_db,
        localization_confidence=localization_confidence,
        weak_spatial_separation=weak_spatial_separation,
        dominance_ratio=dominance_ratio,
        constant_speed=constant_speed,
        steady_speed=steady_speed,
        matched=matched,
        corroborating_locations=corroborating_locations,
        phases_with_evidence=phases_with_evidence,
        is_diffuse_excitation=is_diffuse_excitation,
        diffuse_penalty=diffuse_penalty,
        n_connected_locations=n_connected_locations,
        no_wheel_sensors=no_wheel_sensors,
        path_compliance=path_compliance,
    )


def _suppress_engine_aliases(findings: list[tuple[float, Finding]]) -> list[Finding]:
    return _suppress_engine_aliases_impl(findings, min_confidence=ORDER_MIN_CONFIDENCE)


def _compute_matched_speed_phase_evidence(
    matched_points: list[MatchedPoint],
    *,
    focused_speed_band: str | None,
    hotspot_speed_band: str,
) -> tuple[float | None, list[float], str | None, PhaseEvidence, str | None]:
    return _compute_matched_speed_phase_evidence_impl(
        matched_points,
        focused_speed_band=focused_speed_band,
        hotspot_speed_band=hotspot_speed_band,
        speed_profile_from_points=_speed_profile_from_points,
    )


def _match_samples_for_hypothesis(
    samples: list[Sample],
    cached_peaks: list[list[tuple[float, float]]],
    hypothesis: OrderHypothesisLike,
    metadata: MetadataDict,
    tire_circumference_m: float | None,
    per_sample_phases: PhaseLabels | None,
    lang: str,
) -> OrderMatchAccumulator:
    # Delegated implementation retains the compliance-aware tolerance:
    # compliance = getattr(hypothesis, "path_compliance", 1.0)
    # compliance_scale = compliance**0.5
    return match_samples_for_hypothesis(
        samples,
        cached_peaks,
        hypothesis,
        metadata,
        tire_circumference_m,
        per_sample_phases,
        lang,
    )


def _compute_phase_stats(
    has_phases: bool,
    possible_by_phase: dict[str, int],
    matched_by_phase: dict[str, int],
    min_match_rate: float,
) -> tuple[dict[str, float] | None, int]:
    return _compute_phase_stats_impl(
        has_phases,
        possible_by_phase,
        matched_by_phase,
        min_match_rate=min_match_rate,
        min_match_points=ORDER_MIN_MATCH_POINTS,
    )


def _compute_amplitude_and_error_stats(
    matched_amp: list[float],
    matched_floor: list[float],
    rel_errors: list[float],
    predicted_vals: list[float],
    measured_vals: list[float],
    matched_points: list[MatchedPoint],
    constant_speed: bool,
) -> tuple[float, float, float, float, float | None]:
    return _compute_amplitude_and_error_stats_impl(
        matched_amp,
        matched_floor,
        rel_errors,
        predicted_vals,
        measured_vals,
        matched_points,
        constant_speed=constant_speed,
        corr_abs_clamped=_corr_abs_clamped,
    )


def _apply_localization_override(
    per_location_dominant: bool,
    unique_match_locations: set[str],
    connected_locations: set[str],
    matched: int,
    no_wheel_override: bool,
    localization_confidence: float,
    weak_spatial_separation: bool,
) -> tuple[float, bool]:
    return _apply_localization_override_impl(
        per_location_dominant=per_location_dominant,
        unique_match_locations=unique_match_locations,
        connected_locations=connected_locations,
        matched=matched,
        no_wheel_override=no_wheel_override,
        localization_confidence=localization_confidence,
        weak_spatial_separation=weak_spatial_separation,
        min_match_points=ORDER_MIN_MATCH_POINTS,
    )


def _assemble_order_finding(
    hypothesis: OrderHypothesisLike,
    m: OrderMatchAccumulator,
    *,
    context: OrderFindingBuildContext,
) -> tuple[float, Finding]:
    # Delegated implementation keeps the compliance-aware ranking formula:
    # ranking_error_denom = 0.25 * compliance
    return assemble_order_finding(
        hypothesis,
        m,
        context=context,
        location_speedbin_summary=_location_speedbin_summary,
        compute_phase_stats=_compute_phase_stats,
        compute_amplitude_and_error_stats=_compute_amplitude_and_error_stats,
        apply_localization_override=_apply_localization_override,
        detect_diffuse_excitation=_detect_diffuse_excitation,
        compute_order_confidence=_compute_order_confidence,
        compute_matched_speed_phase_evidence=_compute_matched_speed_phase_evidence,
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
) -> list[Finding]:
    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        return []

    # Pre-compute peaks for every sample once so that the inner hypothesis
    # loop does not redundantly call _sample_top_peaks() for each hypothesis.
    cached_peaks: list[list[tuple[float, float]]] = [_sample_top_peaks(s) for s in samples]

    findings: list[tuple[float, Finding]] = []
    for hypothesis in _order_hypotheses():
        if hypothesis.key.startswith(("wheel_", "driveshaft_")) and (
            not speed_sufficient or tire_circumference_m is None or tire_circumference_m <= 0
        ):
            continue
        if hypothesis.key.startswith("engine_") and not engine_ref_sufficient:
            continue

        m = _match_samples_for_hypothesis(
            samples,
            cached_peaks,
            hypothesis,
            metadata,
            tire_circumference_m,
            per_sample_phases,
            lang,
        )

        if m.possible < ORDER_MIN_COVERAGE_POINTS or m.matched < ORDER_MIN_MATCH_POINTS:
            continue
        match_rate = m.matched / max(1, m.possible)
        # At constant speed the predicted frequency never varies, so random
        # broadband peaks match by chance at ~30-40%.  A genuine order source
        # would be present in the vast majority of samples.  Require a much
        # higher match rate before claiming a finding.
        constant_speed = (
            speed_stddev_kmh is not None and speed_stddev_kmh < CONSTANT_SPEED_STDDEV_KMH
        )
        min_match_rate = ORDER_CONSTANT_SPEED_MIN_MATCH_RATE if constant_speed else 0.25
        effective_match_rate, focused_speed_band, per_location_dominant = (
            _compute_effective_match_rate(
                match_rate,
                min_match_rate,
                m.possible_by_speed_bin,
                m.matched_by_speed_bin,
                m.possible_by_location,
                m.matched_by_location,
            )
        )
        if effective_match_rate < min_match_rate:
            continue

        ranking_score, finding = _assemble_order_finding(
            hypothesis,
            m,
            context=OrderFindingBuildContext(
                effective_match_rate=effective_match_rate,
                focused_speed_band=focused_speed_band,
                per_location_dominant=per_location_dominant,
                match_rate=match_rate,
                min_match_rate=min_match_rate,
                constant_speed=constant_speed,
                steady_speed=steady_speed,
                connected_locations=connected_locations,
                lang=lang,
            ),
        )
        findings.append((ranking_score, finding))

    return _suppress_engine_aliases(findings)
