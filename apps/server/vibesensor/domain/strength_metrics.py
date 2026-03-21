"""Domain value objects for vibration strength measurement results.

``StrengthPeak`` — a single identified vibration peak.
``StrengthMetrics`` — the full strength-measurement summary for one
    finding or analysis segment.

These are domain-layer interpretations of measurement results.  The
pipeline-layer ``StrengthPeak`` and ``VibrationStrengthMetrics``
TypedDicts in ``vibration_strength.py`` remain as hot-path serialization
shapes.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "StrengthMetrics",
    "StrengthPeak",
]

from ._numeric import coerce_float


def _float_or(d: Mapping[str, object], key: str, default: float = 0.0) -> float:
    v = d.get(key)
    if v is None:
        return default
    try:
        f = coerce_float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _float_or_none(d: Mapping[str, object], key: str) -> float | None:
    v = d.get(key)
    if v is None:
        return None
    try:
        f = coerce_float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _str_or_none(d: Mapping[str, object], key: str) -> str | None:
    v = d.get(key)
    if isinstance(v, str) and v:
        return v
    return None


# ---------------------------------------------------------------------------
# StrengthPeak
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrengthPeak:
    """A single identified vibration peak."""

    hz: float = 0.0
    amp: float = 0.0
    vibration_strength_db: float | None = None
    strength_bucket: str | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> StrengthPeak:
        return cls(
            hz=_float_or(d, "hz"),
            amp=_float_or(d, "amp"),
            vibration_strength_db=_float_or_none(d, "vibration_strength_db"),
            strength_bucket=_str_or_none(d, "strength_bucket"),
        )

    @property
    def is_valid(self) -> bool:
        return self.hz > 0.0 and self.amp > 0.0

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "hz": self.hz,
            "amp": self.amp,
        }
        if self.vibration_strength_db is not None:
            payload["vibration_strength_db"] = self.vibration_strength_db
        if self.strength_bucket is not None:
            payload["strength_bucket"] = self.strength_bucket
        return payload


# ---------------------------------------------------------------------------
# StrengthMetrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrengthMetrics:
    """Full strength-measurement summary for one finding or segment."""

    vibration_strength_db: float | None = None
    peak_amp_g: float | None = None
    noise_floor_amp_g: float | None = None
    strength_bucket: str | None = None
    top_peaks: tuple[StrengthPeak, ...] = ()

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> StrengthMetrics:
        raw_peaks = d.get("top_peaks")
        peaks: tuple[StrengthPeak, ...] = ()
        if isinstance(raw_peaks, (list, tuple)):
            parsed: list[StrengthPeak] = []
            for item in raw_peaks:
                if isinstance(item, Mapping):
                    parsed.append(StrengthPeak.from_dict(item))
            peaks = tuple(parsed)

        return cls(
            vibration_strength_db=_float_or_none(d, "vibration_strength_db"),
            peak_amp_g=_float_or_none(d, "peak_amp_g"),
            noise_floor_amp_g=_float_or_none(d, "noise_floor_amp_g"),
            strength_bucket=_str_or_none(d, "strength_bucket"),
            top_peaks=peaks,
        )

    @property
    def dominant_peak(self) -> StrengthPeak | None:
        return self.top_peaks[0] if self.top_peaks else None

    @property
    def dominant_hz(self) -> float | None:
        peak = self.dominant_peak
        if peak is None or peak.hz <= 0.0:
            return None
        return peak.hz

    def to_peak_payloads(self, *, max_items: int | None = None) -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        peaks = self.top_peaks if max_items is None else self.top_peaks[: max(0, max_items)]
        for peak in peaks:
            if peak.is_valid:
                payloads.append(peak.to_dict())
        return payloads
