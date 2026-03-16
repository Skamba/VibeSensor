"""Source/origin semantics for a diagnostic finding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.domain.finding import VibrationSource
from vibesensor.domain.location_hotspot import LocationHotspot

if TYPE_CHECKING:
    from vibesensor.domain.finding import Finding

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

    @classmethod
    def from_analysis_inputs(
        cls,
        *,
        suspected_source: VibrationSource,
        hotspot: LocationHotspot | None = None,
        dominance_ratio: float | None = None,
        speed_band: str | None = None,
        dominant_phase: str | None = None,
        reason: str = "",
    ) -> VibrationOrigin:
        """Construct origin semantics from typed pre-finding analysis inputs."""
        return cls(
            suspected_source=suspected_source,
            hotspot=hotspot,
            dominance_ratio=dominance_ratio,
            speed_band=speed_band,
            dominant_phase=dominant_phase,
            reason=reason,
        )

    @classmethod
    def from_finding(cls, finding: Finding) -> VibrationOrigin | None:
        """Extract the best available origin from a diagnostic finding.

        Returns the finding's existing origin if present, or constructs
        one from the finding's location/source data.  Returns ``None`` if
        the finding has insufficient data for meaningful origin semantics.
        """
        if finding.origin is not None:
            return finding.origin
        if finding.location is not None:
            return cls(
                suspected_source=finding.suspected_source,
                hotspot=finding.location,
                dominance_ratio=finding.dominance_ratio,
                speed_band=finding.strongest_speed_band,
            )
        if finding.strongest_location:
            return cls(
                suspected_source=finding.suspected_source,
                dominance_ratio=finding.dominance_ratio,
                speed_band=finding.strongest_speed_band,
            )
        return None

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.hotspot and (self.hotspot.ambiguous or not self.hotspot.is_well_localized))

    @property
    def summary_location(self) -> str:
        if self.hotspot is None:
            return "unknown"
        return self.hotspot.summary_location

    @property
    def projected_location(self) -> str:
        if self.hotspot is None:
            return "Unknown"
        if self.hotspot.has_clear_separation:
            return self.hotspot.display_location
        display_locations = [self.hotspot.display_location]
        display_locations.extend(
            location.replace("_", " ").title() for location in self.alternative_locations
        )
        unique_locations: list[str] = []
        for candidate in display_locations:
            if candidate and candidate not in unique_locations:
                unique_locations.append(candidate)
        return " / ".join(unique_locations) if unique_locations else self.hotspot.display_location

    @property
    def alternative_locations(self) -> tuple[str, ...]:
        if self.hotspot is None:
            return ()
        return self.hotspot.supporting_locations

    @property
    def weak_spatial_separation(self) -> bool:
        return bool(self.hotspot and not self.hotspot.has_clear_separation)

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
