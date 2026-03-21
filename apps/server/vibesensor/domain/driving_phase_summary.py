"""Driving-phase summary snapshot used for reconstruction and interpretation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ._snapshot_parse import _float_or, _int_or
from .driving_segment import DrivingPhaseSegment

__all__ = ["DrivingPhaseSummary"]


@dataclass(frozen=True, slots=True)
class DrivingPhaseSummary:
    """Typed internal phase-summary snapshot for reconstruction and
    interpretation support.
    """

    phase_counts: Mapping[str, int] = field(default_factory=dict)
    phase_pcts: Mapping[str, float] = field(default_factory=dict)
    total_samples: int = 0
    segment_count: int = 0
    has_cruise: bool = False
    has_acceleration: bool = False
    cruise_pct: float = 0.0
    idle_pct: float = 0.0
    speed_unknown_pct: float = 0.0
    phase_type_summaries: tuple[DrivingPhaseSegment, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.phase_counts, MappingProxyType):
            object.__setattr__(self, "phase_counts", MappingProxyType(dict(self.phase_counts)))
        if not isinstance(self.phase_pcts, MappingProxyType):
            object.__setattr__(self, "phase_pcts", MappingProxyType(dict(self.phase_pcts)))

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict suitable for JSON / boundary payloads."""
        return {
            "phase_counts": dict(self.phase_counts),
            "phase_pcts": dict(self.phase_pcts),
            "total_samples": self.total_samples,
            "segment_count": self.segment_count,
            "has_cruise": self.has_cruise,
            "has_acceleration": self.has_acceleration,
            "cruise_pct": self.cruise_pct,
            "idle_pct": self.idle_pct,
            "speed_unknown_pct": self.speed_unknown_pct,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> DrivingPhaseSummary:
        """Parse from flat mapping. Missing keys default sensibly."""
        raw_counts = d.get("phase_counts")
        phase_counts: dict[str, int] = {}
        if isinstance(raw_counts, dict):
            for k, v in raw_counts.items():
                if isinstance(k, str):
                    try:
                        phase_counts[k] = int(v)
                    except (TypeError, ValueError):
                        pass

        raw_pcts = d.get("phase_pcts")
        phase_pcts: dict[str, float] = {}
        if isinstance(raw_pcts, dict):
            for k, v in raw_pcts.items():
                if isinstance(k, str):
                    try:
                        phase_pcts[k] = float(v)
                    except (TypeError, ValueError):
                        pass

        # Fall back to phase_counts/phase_pcts sub-dicts for historical
        # data that may lack top-level has_*/pct keys.
        def _flag_fb(key: str, phase_key: str) -> bool:
            v = d.get(key)
            if v is not None:
                return bool(v)
            return phase_counts.get(phase_key, 0) > 0

        def _pct_fb(key: str, phase_key: str) -> float:
            v = _float_or(d, key)
            if v != 0.0 or key in d:
                return v
            return phase_pcts.get(phase_key, 0.0)

        return cls(
            phase_counts=phase_counts,
            phase_pcts=phase_pcts,
            total_samples=_int_or(d, "total_samples"),
            segment_count=_int_or(d, "segment_count"),
            has_cruise=_flag_fb("has_cruise", "cruise"),
            has_acceleration=_flag_fb("has_acceleration", "acceleration"),
            cruise_pct=_pct_fb("cruise_pct", "cruise"),
            idle_pct=_pct_fb("idle_pct", "idle"),
            speed_unknown_pct=_pct_fb("speed_unknown_pct", "speed_unknown"),
        )
