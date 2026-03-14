"""Source/origin semantics for a diagnostic finding."""

from __future__ import annotations

from dataclasses import dataclass

from .finding import VibrationSource
from .location_hotspot import LocationHotspot

__all__ = ["VibrationOrigin"]


@dataclass(frozen=True, slots=True)
class VibrationOrigin:
    """Suspected source/origin conclusion with ambiguity and rationale."""

    suspected_source: VibrationSource
    hotspot: LocationHotspot | None = None
    dominance_ratio: float | None = None
    speed_band: str | None = None
    dominant_phase: str | None = None
    reason: str = ""

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.hotspot and (self.hotspot.ambiguous or not self.hotspot.is_well_localized))

    @property
    def display_location(self) -> str:
        if self.hotspot is None:
            return "Unknown"
        return self.hotspot.display_location

    @property
    def explanation(self) -> str:
        parts: list[str] = []
        if self.reason:
            parts.append(self.reason)
        if self.speed_band:
            parts.append(f"speed band {self.speed_band}")
        if self.dominant_phase:
            parts.append(f"dominant phase {self.dominant_phase}")
        return "; ".join(parts)
