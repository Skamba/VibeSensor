"""Window-quality contracts and serialization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

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
    "speed_unavailable",
    "speed_low",
    "speed_stale",
    "speed_unstable",
    "speed_assumed",
    "frequency_unstable",
]

AXIS_NAMES = ("x", "y", "z")
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
        "speed_unavailable",
        "speed_low",
        "speed_stale",
        "speed_unstable",
        "speed_assumed",
        "frequency_unstable",
    }
)


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
        return dict(zip(AXIS_NAMES, self.clipping_axis_counts, strict=True))

    def _clipping_axis_counts_json(self) -> dict[str, JsonValue]:
        return {
            axis_name: count
            for axis_name, count in zip(AXIS_NAMES, self.clipping_axis_counts, strict=True)
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


def _score_from_json(value: object, *, default: float) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool) and isfinite(float(value)):
        return clamp01(float(value))
    return default


def _int_from_json(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _axis_counts_from_json(value: object) -> tuple[int, int, int]:
    if isinstance(value, dict):
        return normalized_axis_counts(
            tuple(_int_from_json(value.get(axis_name)) or 0 for axis_name in AXIS_NAMES)
        )
    if isinstance(value, list | tuple):
        return normalized_axis_counts(tuple(_int_from_json(raw) or 0 for raw in value[:3]))
    return (0, 0, 0)


def _optional_score_from_json(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and isfinite(float(value)):
        return clamp01(float(value))
    return None


def _nonnegative_float_from_json(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and isfinite(float(value)):
        return max(0.0, float(value))
    return None


def _state_or_default(value: object, *, default: WindowQualityState) -> WindowQualityState:
    if isinstance(value, str) and value in WINDOW_QUALITY_STATE_VALUES:
        return value
    return default
