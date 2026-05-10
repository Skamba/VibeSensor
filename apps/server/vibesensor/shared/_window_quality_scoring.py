"""Window-quality scoring policy and reason assembly."""

from __future__ import annotations

from math import isfinite
from typing import cast

import numpy as np

from vibesensor.shared._window_quality_metrics import (
    analyze_mounting_artifact,
    analyze_window_clipping,
    analyze_window_transient,
)
from vibesensor.shared._window_quality_types import (
    WindowQuality,
    WindowQualityReason,
    WindowQualityState,
    clamp01,
    normalized_axis_counts,
)

_WEIGHT_SAMPLE_COMPLETENESS = 0.16
_WEIGHT_PACKET_INTEGRITY = 0.14
_WEIGHT_TIMING_INTEGRITY = 0.14
_WEIGHT_CLIPPING = 0.13
_WEIGHT_TRANSIENT = 0.13
_WEIGHT_MOUNTING = 0.13
_WEIGHT_CONTEXT = 0.085
_WEIGHT_FREQUENCY = 0.085


def score_window_quality(
    *,
    expected_sample_count: int,
    returned_sample_count: int,
    coverage_state: str,
    coverage_reason: str | None = None,
    samples_i16: np.ndarray | None = None,
    samples_g: np.ndarray | None = None,
    context_coverage: str | None = None,
    speed_validity: str | None = None,
    rpm_validity: str | None = None,
    sample_rate_hz: int | None = None,
    peak_amp_g: float | None = None,
    noise_floor_amp_g: float | None = None,
    dropped_frame_count: int = 0,
    late_packet_chunk_count: int = 0,
    server_queue_drop_count: int = 0,
    reset_detected: bool = False,
) -> WindowQuality:
    """Score one FFT/order-analysis window from available signal and context facts."""

    sample_score = _sample_completeness_score(
        expected_sample_count=expected_sample_count,
        returned_sample_count=returned_sample_count,
    )
    packet_score = _packet_integrity_score(
        coverage_state=coverage_state,
        coverage_reason=coverage_reason,
    )
    timing_score, timing_reasons = _timing_integrity_score(
        coverage_reason=coverage_reason,
        dropped_frame_count=dropped_frame_count,
        late_packet_chunk_count=late_packet_chunk_count,
        server_queue_drop_count=server_queue_drop_count,
        reset_detected=reset_detected,
    )
    clipping_analysis = analyze_window_clipping(samples_i16=samples_i16, samples_g=samples_g)
    transient_analysis = analyze_window_transient(samples_g)
    mounting_analysis = analyze_mounting_artifact(samples_g, sample_rate_hz=sample_rate_hz)
    context_score = _context_score(
        context_coverage=context_coverage,
        speed_validity=speed_validity,
        rpm_validity=rpm_validity,
    )
    frequency_score = _frequency_stability_score(
        peak_amp_g=peak_amp_g,
        noise_floor_amp_g=noise_floor_amp_g,
    )
    return _quality_from_component_scores(
        sample_completeness_score=sample_score,
        packet_integrity_score=packet_score,
        timing_integrity_score=timing_score,
        timing_reasons=timing_reasons,
        clipping_score=clipping_analysis.score,
        clipping_sample_count=clipping_analysis.sample_count,
        clipping_sample_ratio=clipping_analysis.sample_ratio,
        clipping_axis_counts=clipping_analysis.axis_counts,
        transient_score=transient_analysis.score,
        shock_crest_factor=transient_analysis.crest_factor,
        shock_broadband_ratio=transient_analysis.broadband_ratio,
        mounting_score=mounting_analysis.score,
        mounting_high_frequency_ratio=mounting_analysis.high_frequency_ratio,
        context_score=context_score,
        frequency_stability_score=frequency_score,
    )


def window_quality_with_context(
    quality: WindowQuality,
    *,
    context_coverage: str | None,
    speed_validity: str | None,
    rpm_validity: str | None,
    speed_context_reasons: tuple[str, ...] = (),
) -> WindowQuality:
    """Return ``quality`` with the context component updated for a window label."""

    return _quality_from_component_scores(
        sample_completeness_score=quality.sample_completeness_score,
        packet_integrity_score=quality.packet_integrity_score,
        timing_integrity_score=quality.timing_integrity_score,
        timing_reasons=_timing_reasons_from(quality.reasons),
        clipping_score=quality.clipping_score,
        clipping_sample_count=quality.clipping_sample_count,
        clipping_sample_ratio=quality.clipping_sample_ratio,
        clipping_axis_counts=quality.clipping_axis_counts,
        transient_score=quality.transient_score,
        shock_crest_factor=quality.shock_crest_factor,
        shock_broadband_ratio=quality.shock_broadband_ratio,
        mounting_score=quality.mounting_score,
        mounting_high_frequency_ratio=quality.mounting_high_frequency_ratio,
        context_score=_context_score(
            context_coverage=context_coverage,
            speed_validity=speed_validity,
            rpm_validity=rpm_validity,
            speed_context_reasons=speed_context_reasons,
        ),
        context_reasons=_window_quality_reasons_from(speed_context_reasons),
        frequency_stability_score=quality.frequency_stability_score,
    )


def _quality_from_component_scores(
    *,
    sample_completeness_score: float,
    packet_integrity_score: float,
    timing_integrity_score: float,
    clipping_score: float,
    transient_score: float,
    mounting_score: float,
    context_score: float,
    frequency_stability_score: float,
    clipping_sample_count: int = 0,
    clipping_sample_ratio: float = 0.0,
    clipping_axis_counts: tuple[int, int, int] = (0, 0, 0),
    shock_crest_factor: float | None = None,
    shock_broadband_ratio: float | None = None,
    mounting_high_frequency_ratio: float | None = None,
    timing_reasons: tuple[WindowQualityReason, ...] = (),
    context_reasons: tuple[WindowQualityReason, ...] = (),
) -> WindowQuality:
    sample_completeness_score = clamp01(sample_completeness_score)
    packet_integrity_score = clamp01(packet_integrity_score)
    timing_integrity_score = clamp01(timing_integrity_score)
    clipping_score = clamp01(clipping_score)
    clipping_sample_count = max(0, int(clipping_sample_count))
    clipping_sample_ratio = clamp01(clipping_sample_ratio)
    clipping_axis_counts = normalized_axis_counts(clipping_axis_counts)
    transient_score = clamp01(transient_score)
    mounting_score = clamp01(mounting_score)
    context_score = clamp01(context_score)
    frequency_stability_score = clamp01(frequency_stability_score)
    score = clamp01(
        (_WEIGHT_SAMPLE_COMPLETENESS * sample_completeness_score)
        + (_WEIGHT_PACKET_INTEGRITY * packet_integrity_score)
        + (_WEIGHT_TIMING_INTEGRITY * timing_integrity_score)
        + (_WEIGHT_CLIPPING * clipping_score)
        + (_WEIGHT_TRANSIENT * transient_score)
        + (_WEIGHT_MOUNTING * mounting_score)
        + (_WEIGHT_CONTEXT * context_score)
        + (_WEIGHT_FREQUENCY * frequency_stability_score)
    )
    reasons: list[WindowQualityReason] = []
    if sample_completeness_score < 0.98:
        reasons.append("sample_incomplete")
    if packet_integrity_score < 0.98:
        reasons.append("packet_integrity_gap")
    if timing_integrity_score < 0.98:
        reasons.extend(timing_reasons or ("timing_gap",))
    if clipping_score < 0.98:
        reasons.append("sensor_clipping")
    if transient_score < 0.70:
        reasons.append("shock_transient")
    if mounting_score < 0.98:
        reasons.append("mounting_artifact")
    reasons.extend(context_reasons)
    if context_score < 0.70:
        reasons.append("context_unavailable")
    if frequency_stability_score < 0.70:
        reasons.append("frequency_unstable")
    state: WindowQualityState = "usable"
    if (
        sample_completeness_score < 0.75
        or packet_integrity_score <= 0.05
        or timing_integrity_score < 0.20
        or clipping_score < 0.20
        or transient_score < 0.25
        or context_score < 0.25
    ):
        state = "excluded"
    elif score < 0.75 or reasons:
        state = "limited"
    return WindowQuality(
        score=score,
        state=state,
        sample_completeness_score=sample_completeness_score,
        packet_integrity_score=packet_integrity_score,
        timing_integrity_score=timing_integrity_score,
        clipping_score=clipping_score,
        clipping_sample_count=clipping_sample_count,
        clipping_sample_ratio=clipping_sample_ratio,
        clipping_axis_counts=clipping_axis_counts,
        transient_score=transient_score,
        mounting_score=mounting_score,
        context_score=context_score,
        frequency_stability_score=frequency_stability_score,
        shock_crest_factor=shock_crest_factor,
        shock_broadband_ratio=shock_broadband_ratio,
        mounting_high_frequency_ratio=mounting_high_frequency_ratio,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _sample_completeness_score(
    *,
    expected_sample_count: int,
    returned_sample_count: int,
) -> float:
    expected = max(0, int(expected_sample_count))
    returned = max(0, int(returned_sample_count))
    if expected <= 0:
        return 0.0
    return clamp01(float(returned) / float(expected))


def _packet_integrity_score(*, coverage_state: str, coverage_reason: str | None) -> float:
    if coverage_state == "full" and coverage_reason is None:
        return 1.0
    if coverage_state == "full":
        return 0.85
    if coverage_state == "partial":
        return 0.45
    return 0.0


_TIMING_GAP_REASONS = frozenset(
    {
        "assembled_window_short",
        "sample_rate_unverified",
        "window_crosses_gap",
    }
)
_TIMING_RESET_REASONS = frozenset({"window_crosses_overlap"})
_TIMING_REASON_VALUES = frozenset(
    {
        "timing_gap",
        "late_packet_loss",
        "server_queue_drop",
        "sensor_reset",
    }
)


def _timing_integrity_score(
    *,
    coverage_reason: str | None,
    dropped_frame_count: int,
    late_packet_chunk_count: int,
    server_queue_drop_count: int,
    reset_detected: bool,
) -> tuple[float, tuple[WindowQualityReason, ...]]:
    score = 1.0
    reasons: list[WindowQualityReason] = []
    if coverage_reason in _TIMING_GAP_REASONS or dropped_frame_count > 0:
        score = min(score, 0.35)
        reasons.append("timing_gap")
    if coverage_reason in _TIMING_RESET_REASONS or reset_detected:
        score = min(score, 0.20)
        reasons.append("sensor_reset")
    if late_packet_chunk_count > 0:
        score = min(score, 0.65)
        reasons.append("late_packet_loss")
    if server_queue_drop_count > 0:
        score = min(score, 0.55)
        reasons.append("server_queue_drop")
    return score, tuple(dict.fromkeys(reasons))


def _timing_reasons_from(
    reasons: tuple[WindowQualityReason, ...],
) -> tuple[WindowQualityReason, ...]:
    return tuple(reason for reason in reasons if reason in _TIMING_REASON_VALUES)


def _context_score(
    *,
    context_coverage: str | None,
    speed_validity: str | None,
    rpm_validity: str | None,
    speed_context_reasons: tuple[str, ...] = (),
) -> float:
    if context_coverage is None and speed_validity is None and rpm_validity is None:
        return 1.0
    coverage_score = {"full": 1.0, "partial": 0.65, "missing": 0.35}.get(
        str(context_coverage or "missing"),
        0.35,
    )
    speed_score = {"measured": 1.0, "assumed": 0.75, "missing": 0.35}.get(
        str(speed_validity or "missing"),
        0.50,
    )
    rpm_score = {"measured": 1.0, "estimated": 0.75, "missing": 0.50}.get(
        str(rpm_validity or "missing"),
        0.50,
    )
    context_score = (coverage_score + speed_score + rpm_score) / 3.0
    for reason in speed_context_reasons:
        context_score = min(context_score, _SPEED_CONTEXT_REASON_SCORE_CAPS.get(reason, 1.0))
    return context_score


_SPEED_CONTEXT_REASON_SCORE_CAPS: dict[str, float] = {
    "speed_unavailable": 0.35,
    "speed_low": 0.55,
    "speed_stale": 0.45,
    "speed_unstable": 0.55,
    "speed_assumed": 0.75,
}


def _window_quality_reasons_from(reasons: tuple[str, ...]) -> tuple[WindowQualityReason, ...]:
    return tuple(
        cast(WindowQualityReason, reason)
        for reason in reasons
        if reason in _SPEED_CONTEXT_REASON_SCORE_CAPS
    )


def _frequency_stability_score(
    *,
    peak_amp_g: float | None,
    noise_floor_amp_g: float | None,
) -> float:
    if peak_amp_g is None or not isfinite(peak_amp_g) or peak_amp_g <= 0.0:
        return 0.45
    if noise_floor_amp_g is None or not isfinite(noise_floor_amp_g) or noise_floor_amp_g <= 0.0:
        return 0.80
    ratio = peak_amp_g / max(1e-12, noise_floor_amp_g)
    if ratio >= 6.0:
        return 1.0
    if ratio <= 1.5:
        return 0.35
    return 0.35 + ((ratio - 1.5) / (6.0 - 1.5) * 0.65)
