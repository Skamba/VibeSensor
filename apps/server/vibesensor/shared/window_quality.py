"""Shared per-window quality scoring for live and whole-run DSP evidence."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

import numpy as np

from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.payload_types import WindowQualityPayload

type WindowQualityState = Literal["usable", "limited", "excluded"]
type WindowQualityReason = Literal[
    "sample_incomplete",
    "packet_integrity_gap",
    "sensor_clipping",
    "shock_transient",
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
        "sensor_clipping",
        "shock_transient",
        "context_unavailable",
        "frequency_unstable",
    }
)

_WEIGHT_SAMPLE_COMPLETENESS = 0.20
_WEIGHT_PACKET_INTEGRITY = 0.20
_WEIGHT_CLIPPING = 0.15
_WEIGHT_TRANSIENT = 0.15
_WEIGHT_CONTEXT = 0.15
_WEIGHT_FREQUENCY = 0.15
_CLIPPING_FULL_SCALE_I16 = 32760
_CLIPPING_EXCLUDED_RATIO = 0.01
_CREST_FACTOR_CLEAN = 6.0
_CREST_FACTOR_EXCLUDED = 12.0


@dataclass(frozen=True, slots=True)
class WindowQuality:
    """Typed quality score for one analysis window."""

    score: float
    state: WindowQualityState
    sample_completeness_score: float
    packet_integrity_score: float
    clipping_score: float
    transient_score: float
    context_score: float
    frequency_stability_score: float
    reasons: tuple[WindowQualityReason, ...] = ()

    def to_payload(self) -> WindowQualityPayload:
        return {
            "score": self.score,
            "state": self.state,
            "sample_completeness_score": self.sample_completeness_score,
            "packet_integrity_score": self.packet_integrity_score,
            "clipping_score": self.clipping_score,
            "transient_score": self.transient_score,
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
            "clipping_score": self.clipping_score,
            "transient_score": self.transient_score,
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
            clipping_score=_score_from_json(data.get("clipping_score"), default=1.0),
            transient_score=_score_from_json(data.get("transient_score"), default=1.0),
            context_score=_score_from_json(data.get("context_score"), default=1.0),
            frequency_stability_score=_score_from_json(
                data.get("frequency_stability_score"),
                default=1.0,
            ),
            reasons=reasons,
        )


def clean_window_quality() -> WindowQuality:
    return WindowQuality(
        score=1.0,
        state="usable",
        sample_completeness_score=1.0,
        packet_integrity_score=1.0,
        clipping_score=1.0,
        transient_score=1.0,
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
    peak_amp_g: float | None = None,
    noise_floor_amp_g: float | None = None,
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
    clipping_score = _clipping_score(samples_i16)
    transient_score = _transient_score(samples_g)
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
        clipping_score=clipping_score,
        transient_score=transient_score,
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
        clipping_score=quality.clipping_score,
        transient_score=quality.transient_score,
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
    clipping_score: float,
    transient_score: float,
    context_score: float,
    frequency_stability_score: float,
) -> WindowQuality:
    sample_completeness_score = _clamp01(sample_completeness_score)
    packet_integrity_score = _clamp01(packet_integrity_score)
    clipping_score = _clamp01(clipping_score)
    transient_score = _clamp01(transient_score)
    context_score = _clamp01(context_score)
    frequency_stability_score = _clamp01(frequency_stability_score)
    score = _clamp01(
        (_WEIGHT_SAMPLE_COMPLETENESS * sample_completeness_score)
        + (_WEIGHT_PACKET_INTEGRITY * packet_integrity_score)
        + (_WEIGHT_CLIPPING * clipping_score)
        + (_WEIGHT_TRANSIENT * transient_score)
        + (_WEIGHT_CONTEXT * context_score)
        + (_WEIGHT_FREQUENCY * frequency_stability_score)
    )
    reasons: list[WindowQualityReason] = []
    if sample_completeness_score < 0.98:
        reasons.append("sample_incomplete")
    if packet_integrity_score < 0.98:
        reasons.append("packet_integrity_gap")
    if clipping_score < 0.98:
        reasons.append("sensor_clipping")
    if transient_score < 0.70:
        reasons.append("shock_transient")
    if context_score < 0.70:
        reasons.append("context_unavailable")
    if frequency_stability_score < 0.70:
        reasons.append("frequency_unstable")
    state: WindowQualityState = "usable"
    if (
        sample_completeness_score < 0.75
        or packet_integrity_score <= 0.05
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
        clipping_score=clipping_score,
        transient_score=transient_score,
        context_score=context_score,
        frequency_stability_score=frequency_stability_score,
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


def _clipping_score(samples_i16: np.ndarray | None) -> float:
    if samples_i16 is None or samples_i16.size == 0:
        return 1.0
    clipped_mask = np.abs(samples_i16.astype(np.int32)) >= _CLIPPING_FULL_SCALE_I16
    clipped_count = int(np.count_nonzero(clipped_mask))
    if clipped_count <= 0:
        return 1.0
    ratio = float(clipped_count) / float(samples_i16.size)
    return _clamp01(1.0 - (ratio / _CLIPPING_EXCLUDED_RATIO))


def _transient_score(samples_g: np.ndarray | None) -> float:
    if samples_g is None or samples_g.size == 0:
        return 1.0
    samples = _time_axis_samples(samples_g)
    if samples.size == 0:
        return 1.0
    detrended = samples - np.mean(samples, axis=0, keepdims=True)
    magnitude = np.linalg.norm(detrended, axis=1)
    rms = float(np.sqrt(np.mean(np.square(magnitude, dtype=np.float64))))
    if not isfinite(rms) or rms <= 1e-12:
        return 1.0
    peak = float(np.max(np.abs(magnitude)))
    crest = peak / rms
    if crest <= _CREST_FACTOR_CLEAN:
        return 1.0
    if crest >= _CREST_FACTOR_EXCLUDED:
        return 0.0
    transient_range = _CREST_FACTOR_EXCLUDED - _CREST_FACTOR_CLEAN
    return _clamp01((_CREST_FACTOR_EXCLUDED - crest) / transient_range)


def _time_axis_samples(samples: np.ndarray) -> np.ndarray:
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim != 2:
        return np.empty((0, 3), dtype=np.float32)
    if arr.shape[1] == 3:
        return arr
    if arr.shape[0] == 3:
        return arr.T
    return np.empty((0, 3), dtype=np.float32)


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


def _state_or_default(value: object, *, default: WindowQualityState) -> WindowQualityState:
    if isinstance(value, str) and value in WINDOW_QUALITY_STATE_VALUES:
        return value
    return default


def _clamp01(value: float) -> float:
    if not isfinite(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))
