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


def _float_or(d: Mapping[str, object], key: str, default: float = 0.0) -> float:
    v = d.get(key)
    if v is None:
        return default
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


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
    vibration_strength_db: float = 0.0
    strength_bucket: str | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> StrengthPeak:
        return cls(
            hz=_float_or(d, "hz"),
            amp=_float_or(d, "amp"),
            vibration_strength_db=_float_or(d, "vibration_strength_db"),
            strength_bucket=_str_or_none(d, "strength_bucket"),
        )


# ---------------------------------------------------------------------------
# StrengthMetrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrengthMetrics:
    """Full strength-measurement summary for one finding or segment."""

    vibration_strength_db: float = 0.0
    peak_amp_g: float = 0.0
    noise_floor_amp_g: float = 0.0
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
            vibration_strength_db=_float_or(d, "vibration_strength_db"),
            peak_amp_g=_float_or(d, "peak_amp_g"),
            noise_floor_amp_g=_float_or(d, "noise_floor_amp_g"),
            strength_bucket=_str_or_none(d, "strength_bucket"),
            top_peaks=peaks,
        )

    @classmethod
    def from_typed_dict(cls, td: Mapping[str, object]) -> StrengthMetrics:
        """Convenience alias for ``from_dict`` — accepts the pipeline
        ``VibrationStrengthMetrics`` TypedDict directly."""
        return cls.from_dict(td)
