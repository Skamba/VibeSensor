"""Window-quality contracts and serialization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from vibesensor.live.payload_types import WindowQualityPayload

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
    "speed_unavailable",
    "speed_low",
    "speed_stale",
    "speed_unstable",
    "speed_assumed",
    "frequency_unstable",
]

AXIS_NAMES = ("x", "y", "z")


@dataclass(frozen=True, slots=True)
class WindowClippingAnalysis:
    """Clipping/saturation evidence for one raw or scaled sample window."""

    score: float
    sample_count: int
    sample_ratio: float
    axis_counts: tuple[int, int, int] = (0, 0, 0)

    def axis_counts_payload(self) -> dict[str, int]:
        return dict(zip(AXIS_NAMES, self.axis_counts, strict=True))


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

    def _clipping_axis_counts_payload(self) -> dict[str, int]:
        return dict(zip(AXIS_NAMES, self.clipping_axis_counts, strict=True))


def normalized_axis_counts(values: tuple[int, ...]) -> tuple[int, int, int]:
    padded = (*values, 0, 0, 0)
    return (
        max(0, int(padded[0])),
        max(0, int(padded[1])),
        max(0, int(padded[2])),
    )


def clamp01(value: float) -> float:
    if not isfinite(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))
