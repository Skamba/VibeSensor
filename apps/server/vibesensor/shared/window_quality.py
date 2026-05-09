"""Shared per-window quality scoring for live and whole-run DSP evidence."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

import numpy as np

from vibesensor.shared.fft_analysis import broadband_energy_ratio, high_frequency_energy_ratio
from vibesensor.shared.types.json_types import JsonObject, JsonValue
from vibesensor.shared.types.payload_types import WindowQualityPayload

type WindowQualityState = Literal["usable", "limited", "excluded"]
type WindowQualityReason = Literal[
    "sample_incomplete",
    "packet_integrity_gap",
    "timing_gap",
    "late_packet_loss",
    "server_queue_drop",
    "sensor_reset",
    "sensor_clipping",
    "shock_transient",
    "mounting_artifact",
    "context_unavailable",
    "frequency_unstable",
]

WINDOW_QUALITY_STATE_VALUES: frozenset[WindowQualityState] = frozenset(
    {"usable", "limited", "excluded"}
)
WINDOW_QUALITY_REASON_VALUES: frozenset[WindowQualityReason] = frozenset(
    {
        "sample_incomplete",
        "packet_integrity_gap",
        "timing_gap",
        "late_packet_loss",
        "server_queue_drop",
        "sensor_reset",
        "sensor_clipping",
        "shock_transient",
        "mounting_artifact",
        "context_unavailable",
        "frequency_unstable",
    }
)

_WEIGHT_SAMPLE_COMPLETENESS = 0.16
_WEIGHT_PACKET_INTEGRITY = 0.14
_WEIGHT_TIMING_INTEGRITY = 0.14
_WEIGHT_CLIPPING = 0.13
_WEIGHT_TRANSIENT = 0.13
_WEIGHT_MOUNTING = 0.13
_WEIGHT_CONTEXT = 0.085
_WEIGHT_FREQUENCY = 0.085
_CLIPPING_FULL_SCALE_I16 = 32760
_CLIPPING_EXCLUDED_RATIO = 0.01
_CLIPPING_MIN_REPEATED_RAIL_SAMPLES = 3
_CLIPPING_MIN_FLAT_TOP_RUN = 2
_FLAT_TOP_MIN_PEAK_G = 0.5
_FLAT_TOP_MIN_P2P_G = 0.25
_FLAT_TOP_REL_TOLERANCE = 0.002
_FLAT_TOP_ABS_TOLERANCE_G = 0.02
_CREST_FACTOR_CLEAN = 6.0
_CREST_FACTOR_EXCLUDED = 12.0
_BROADBAND_RATIO_CLEAN = 0.55
_BROADBAND_RATIO_EXCLUDED = 0.82
_MOUNTING_HIGH_FREQUENCY_RATIO_CLEAN = 0.35
_MOUNTING_HIGH_FREQUENCY_RATIO_SUSPECT = 0.70
_MOUNTING_MIN_HIGH_FREQUENCY_HZ = 45.0
_AXIS_NAMES = ("x", "y", "z")


@dataclass(frozen=True, slots=True)
class _TransientAnalysis:
    score: float
    crest_factor: float | None
    broadband_ratio: float | None


@dataclass(frozen=True, slots=True)
class WindowClippingAnalysis:
    """Clipping/saturation evidence for one raw or scaled sample window."""

    score: float
    sample_count: int
    sample_ratio: float
    axis_counts: tuple[int, int, int] = (0, 0, 0)

    def axis_counts_payload(self) -> dict[str, int]:
        return dict(zip(_AXIS_NAMES, self.axis_counts, strict=True))


@dataclass(frozen=True, slots=True)
class _MountingArtifactAnalysis:
    score: float
    high_frequency_ratio: float | None


@dataclass(frozen=True, slots=True)
class WindowQuality:
    """Typed quality score for one analysis window."""

    score: float
    state: WindowQualityState
    sample_completeness_score: float
    packet_integrity_score: float
    timing_integrity_score: float
    clipping_score: float
    transient_score: float
    mounting_score: float
    context_score: float
    frequency_stability_score: float
    shock_crest_factor: float | None = None
    shock_broadband_ratio: float | None = None
    mounting_high_frequency_ratio: float | None = None
    clipping_sample_count: int = 0
    clipping_sample_ratio: float = 0.0
    clipping_axis_counts: tuple[int, int, int] = (0, 0, 0)
    reasons: tuple[WindowQualityReason, ...] = ()

    def to_payload(self) -> WindowQualityPayload:
        return {
            "score": self.score,
            "state": self.state,
            "sample_completeness_score": self.sample_completeness_score,
            "packet_integrity_score": self.packet_integrity_score,
            "timing_integrity_score": self.timing_integrity_score,
            "clipping_score": self.clipping_score,
            "clipping_sample_count": self.clipping_sample_count,
            "clipping_sample_ratio": self.clipping_sample_ratio,
            "clipping_axis_counts": self._clipping_axis_counts_payload(),
            "transient_score": self.transient_score,
            "shock_crest_factor": self.shock_crest_factor,
            "shock_broadband_ratio": self.shock_broadband_ratio,
            "mounting_score": self.mounting_score,
            "mounting_high_frequency_ratio": self.mounting_high_frequency_ratio,
            "context_score": self.context_score,
            "frequency_stability_score": self.frequency_stability_score,
            "reasons": list(self.reasons),
        }

    def to_json_object(self) -> JsonObject:
        return {
            "score": self.score,
            "state": self.state,
            "sample_completeness_score": self.sample_completeness_score,
            "packet_integrity_score": self.packet_integrity_score,
            "timing_integrity_score": self.timing_integrity_score,
            "clipping_score": self.clipping_score,
            "clipping_sample_count": self.clipping_sample_count,
            "clipping_sample_ratio": self.clipping_sample_ratio,
            "clipping_axis_counts": self._clipping_axis_counts_json(),
            "transient_score": self.transient_score,
            "shock_crest_factor": self.shock_crest_factor,
            "shock_broadband_ratio": self.shock_broadband_ratio,
            "mounting_score": self.mounting_score,
            "mounting_high_frequency_ratio": self.mounting_high_frequency_ratio,
            "context_score": self.context_score,
            "frequency_stability_score": self.frequency_stability_score,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_mapping(cls, data: JsonObject) -> WindowQuality:
        state = _state_or_default(data.get("state"), default="usable")
        reasons_raw = data.get("reasons")
        reasons: tuple[WindowQualityReason, ...]
        if isinstance(reasons_raw, list | tuple):
            reasons = tuple(
                reason
                for reason in reasons_raw
                if isinstance(reason, str) and reason in WINDOW_QUALITY_REASON_VALUES
            )
        else:
            reasons = ()
        return cls(
            score=_score_from_json(data.get("score"), default=1.0),
            state=state,
            sample_completeness_score=_score_from_json(
                data.get("sample_completeness_score"),
                default=1.0,
            ),
            packet_integrity_score=_score_from_json(
                data.get("packet_integrity_score"),
                default=1.0,
            ),
            timing_integrity_score=_score_from_json(
                data.get("timing_integrity_score"),
                default=1.0,
            ),
            clipping_score=_score_from_json(data.get("clipping_score"), default=1.0),
            clipping_sample_count=max(0, _int_from_json(data.get("clipping_sample_count")) or 0),
            clipping_sample_ratio=_score_from_json(
                data.get("clipping_sample_ratio"),
                default=0.0,
            ),
            clipping_axis_counts=_axis_counts_from_json(data.get("clipping_axis_counts")),
            transient_score=_score_from_json(data.get("transient_score"), default=1.0),
            shock_crest_factor=_nonnegative_float_from_json(data.get("shock_crest_factor")),
            shock_broadband_ratio=_optional_score_from_json(data.get("shock_broadband_ratio")),
            mounting_score=_score_from_json(data.get("mounting_score"), default=1.0),
            mounting_high_frequency_ratio=_optional_score_from_json(
                data.get("mounting_high_frequency_ratio")
            ),
            context_score=_score_from_json(data.get("context_score"), default=1.0),
            frequency_stability_score=_score_from_json(
                data.get("frequency_stability_score"),
                default=1.0,
            ),
            reasons=reasons,
        )

    def _clipping_axis_counts_payload(self) -> dict[str, int]:
        return dict(zip(_AXIS_NAMES, self.clipping_axis_counts, strict=True))

    def _clipping_axis_counts_json(self) -> dict[str, JsonValue]:
        return {
            axis_name: count
            for axis_name, count in zip(_AXIS_NAMES, self.clipping_axis_counts, strict=True)
        }


def clean_window_quality() -> WindowQuality:
    return WindowQuality(
        score=1.0,
        state="usable",
        sample_completeness_score=1.0,
        packet_integrity_score=1.0,
        timing_integrity_score=1.0,
        clipping_score=1.0,
        clipping_sample_count=0,
        clipping_sample_ratio=0.0,
        clipping_axis_counts=(0, 0, 0),
        transient_score=1.0,
        mounting_score=1.0,
        context_score=1.0,
        frequency_stability_score=1.0,
    )


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
    transient_analysis = _transient_analysis(samples_g)
    mounting_analysis = _mounting_artifact_analysis(samples_g, sample_rate_hz=sample_rate_hz)
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
        ),
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
) -> WindowQuality:
    sample_completeness_score = _clamp01(sample_completeness_score)
    packet_integrity_score = _clamp01(packet_integrity_score)
    timing_integrity_score = _clamp01(timing_integrity_score)
    clipping_score = _clamp01(clipping_score)
    clipping_sample_count = max(0, int(clipping_sample_count))
    clipping_sample_ratio = _clamp01(clipping_sample_ratio)
    clipping_axis_counts = _normalized_axis_counts(clipping_axis_counts)
    transient_score = _clamp01(transient_score)
    mounting_score = _clamp01(mounting_score)
    context_score = _clamp01(context_score)
    frequency_stability_score = _clamp01(frequency_stability_score)
    score = _clamp01(
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
    return _clamp01(float(returned) / float(expected))


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


def analyze_window_clipping(
    *,
    samples_i16: np.ndarray | None = None,
    samples_g: np.ndarray | None = None,
) -> WindowClippingAnalysis:
    """Detect repeated rail hits and flat-topped waveforms in one sample window."""

    raw_samples = _time_axis_samples_any(samples_i16)
    scaled_samples = _time_axis_samples_any(samples_g)
    raw_axis_counts = _raw_rail_axis_counts(raw_samples)
    flat_top_axis_counts = _flat_top_axis_counts(scaled_samples)
    axis_counts = (
        max(raw_axis_counts[0], flat_top_axis_counts[0]),
        max(raw_axis_counts[1], flat_top_axis_counts[1]),
        max(raw_axis_counts[2], flat_top_axis_counts[2]),
    )
    total_slots = max(
        int(raw_samples.size) if raw_samples is not None else 0,
        int(scaled_samples.size) if scaled_samples is not None else 0,
    )
    sample_count = sum(axis_counts)
    if sample_count <= 0 or total_slots <= 0:
        return WindowClippingAnalysis(score=1.0, sample_count=0, sample_ratio=0.0)
    sample_ratio = _clamp01(float(sample_count) / float(total_slots))
    score = _clamp01(1.0 - (sample_ratio / _CLIPPING_EXCLUDED_RATIO))
    return WindowClippingAnalysis(
        score=score,
        sample_count=sample_count,
        sample_ratio=sample_ratio,
        axis_counts=axis_counts,
    )


def _raw_rail_axis_counts(samples: np.ndarray | None) -> tuple[int, int, int]:
    if samples is None or samples.size == 0:
        return (0, 0, 0)
    raw = samples.astype(np.int32, copy=False)
    counts: list[int] = []
    for axis_index in range(3):
        axis = raw[:, axis_index]
        rail_mask = np.abs(axis) >= _CLIPPING_FULL_SCALE_I16
        count = int(np.count_nonzero(rail_mask))
        counts.append(count if count >= _CLIPPING_MIN_REPEATED_RAIL_SAMPLES else 0)
    return _normalized_axis_counts(tuple(counts))


def _flat_top_axis_counts(samples: np.ndarray | None) -> tuple[int, int, int]:
    if samples is None or samples.size == 0:
        return (0, 0, 0)
    arr = samples.astype(np.float64, copy=False)
    counts: list[int] = []
    for axis_index in range(3):
        axis_values = arr[:, axis_index]
        finite_axis = axis_values[np.isfinite(axis_values)]
        if finite_axis.size == 0:
            counts.append(0)
            continue
        upper = float(np.max(finite_axis))
        lower = float(np.min(finite_axis))
        peak = max(abs(upper), abs(lower))
        p2p = upper - lower
        if peak < _FLAT_TOP_MIN_PEAK_G or p2p < _FLAT_TOP_MIN_P2P_G:
            counts.append(0)
            continue
        tolerance = max(_FLAT_TOP_ABS_TOLERANCE_G, peak * _FLAT_TOP_REL_TOLERANCE)
        upper_mask = (
            finite_axis >= upper - tolerance
            if upper > 0.0
            else np.zeros_like(
                finite_axis,
                dtype=np.bool_,
            )
        )
        lower_mask = (
            finite_axis <= lower + tolerance
            if lower < 0.0
            else np.zeros_like(
                finite_axis,
                dtype=np.bool_,
            )
        )
        flat_mask = np.logical_or(upper_mask, lower_mask)
        count = int(np.count_nonzero(flat_mask))
        counts.append(count if _longest_true_run(flat_mask) >= _CLIPPING_MIN_FLAT_TOP_RUN else 0)
    return _normalized_axis_counts(tuple(counts))


def _longest_true_run(mask: np.ndarray) -> int:
    longest = 0
    current = 0
    for value in mask:
        if bool(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _transient_analysis(samples_g: np.ndarray | None) -> _TransientAnalysis:
    if samples_g is None or samples_g.size == 0:
        return _TransientAnalysis(score=1.0, crest_factor=None, broadband_ratio=None)
    samples = _time_axis_samples(samples_g)
    if samples.size == 0:
        return _TransientAnalysis(score=1.0, crest_factor=None, broadband_ratio=None)
    detrended = samples - np.mean(samples, axis=0, keepdims=True)
    magnitude = np.linalg.norm(detrended, axis=1)
    rms = float(np.sqrt(np.mean(np.square(magnitude, dtype=np.float64))))
    if not isfinite(rms) or rms <= 1e-12:
        return _TransientAnalysis(score=1.0, crest_factor=None, broadband_ratio=None)
    peak = float(np.max(np.abs(magnitude)))
    crest = peak / rms
    crest_score = _crest_factor_score(crest)
    broadband_ratio = broadband_energy_ratio(detrended.T.astype(np.float32, copy=False))
    broadband_score = _broadband_ratio_score(broadband_ratio)
    return _TransientAnalysis(
        score=min(crest_score, broadband_score),
        crest_factor=crest,
        broadband_ratio=broadband_ratio,
    )


def _mounting_artifact_analysis(
    samples_g: np.ndarray | None,
    *,
    sample_rate_hz: int | None,
) -> _MountingArtifactAnalysis:
    if samples_g is None or sample_rate_hz is None or sample_rate_hz <= 0:
        return _MountingArtifactAnalysis(score=1.0, high_frequency_ratio=None)
    samples = _time_axis_samples(samples_g)
    if samples.size == 0:
        return _MountingArtifactAnalysis(score=1.0, high_frequency_ratio=None)
    detrended = samples - np.mean(samples, axis=0, keepdims=True)
    high_frequency_start_hz = min(
        float(sample_rate_hz) * 0.45,
        max(_MOUNTING_MIN_HIGH_FREQUENCY_HZ, float(sample_rate_hz) * 0.20),
    )
    ratio = high_frequency_energy_ratio(
        detrended.T.astype(np.float32, copy=False),
        sample_rate_hz=sample_rate_hz,
        high_frequency_start_hz=high_frequency_start_hz,
    )
    if ratio is None:
        return _MountingArtifactAnalysis(score=1.0, high_frequency_ratio=None)
    return _MountingArtifactAnalysis(
        score=_mounting_high_frequency_score(ratio),
        high_frequency_ratio=ratio,
    )


def _mounting_high_frequency_score(ratio: float) -> float:
    if ratio <= _MOUNTING_HIGH_FREQUENCY_RATIO_CLEAN:
        return 1.0
    if ratio >= _MOUNTING_HIGH_FREQUENCY_RATIO_SUSPECT:
        return 0.0
    suspect_range = _MOUNTING_HIGH_FREQUENCY_RATIO_SUSPECT - _MOUNTING_HIGH_FREQUENCY_RATIO_CLEAN
    return _clamp01((_MOUNTING_HIGH_FREQUENCY_RATIO_SUSPECT - ratio) / suspect_range)


def _crest_factor_score(crest: float) -> float:
    if crest <= _CREST_FACTOR_CLEAN:
        return 1.0
    if crest >= _CREST_FACTOR_EXCLUDED:
        return 0.0
    transient_range = _CREST_FACTOR_EXCLUDED - _CREST_FACTOR_CLEAN
    return _clamp01((_CREST_FACTOR_EXCLUDED - crest) / transient_range)


def _broadband_ratio_score(ratio: float | None) -> float:
    if ratio is None:
        return 1.0
    if ratio <= _BROADBAND_RATIO_CLEAN:
        return 1.0
    if ratio >= _BROADBAND_RATIO_EXCLUDED:
        return 0.0
    transient_range = _BROADBAND_RATIO_EXCLUDED - _BROADBAND_RATIO_CLEAN
    return _clamp01((_BROADBAND_RATIO_EXCLUDED - ratio) / transient_range)


def _time_axis_samples(samples: np.ndarray) -> np.ndarray:
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim != 2:
        return np.empty((0, 3), dtype=np.float32)
    if arr.shape[1] == 3:
        return arr
    if arr.shape[0] == 3:
        return arr.T
    return np.empty((0, 3), dtype=np.float32)


def _time_axis_samples_any(samples: np.ndarray | None) -> np.ndarray | None:
    if samples is None:
        return None
    arr = np.asarray(samples)
    if arr.ndim != 2:
        return None
    if arr.shape[1] == 3:
        return arr
    if arr.shape[0] == 3:
        return arr.T
    return None


def _context_score(
    *,
    context_coverage: str | None,
    speed_validity: str | None,
    rpm_validity: str | None,
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
    return (coverage_score + speed_score + rpm_score) / 3.0


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


def _score_from_json(value: object, *, default: float) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool) and isfinite(float(value)):
        return _clamp01(float(value))
    return default


def _int_from_json(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _axis_counts_from_json(value: object) -> tuple[int, int, int]:
    if isinstance(value, dict):
        return _normalized_axis_counts(
            tuple(_int_from_json(value.get(axis_name)) or 0 for axis_name in _AXIS_NAMES)
        )
    if isinstance(value, list | tuple):
        return _normalized_axis_counts(tuple(_int_from_json(raw) or 0 for raw in value[:3]))
    return (0, 0, 0)


def _normalized_axis_counts(values: tuple[int, ...]) -> tuple[int, int, int]:
    padded = (*values, 0, 0, 0)
    return (
        max(0, int(padded[0])),
        max(0, int(padded[1])),
        max(0, int(padded[2])),
    )


def _optional_score_from_json(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and isfinite(float(value)):
        return _clamp01(float(value))
    return None


def _nonnegative_float_from_json(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and isfinite(float(value)):
        return max(0.0, float(value))
    return None


def _state_or_default(value: object, *, default: WindowQualityState) -> WindowQualityState:
    if isinstance(value, str) and value in WINDOW_QUALITY_STATE_VALUES:
        return value
    return default


def _clamp01(value: float) -> float:
    if not isfinite(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))
