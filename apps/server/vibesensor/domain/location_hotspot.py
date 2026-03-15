"""Spatial concentration of vibration evidence.

``LocationHotspot`` captures where vibration evidence is strongest,
whether the source is well-localised or ambiguous, and what
alternative locations compete.  This gives spatial reasoning a
domain-level identity instead of living in boundary TypedDicts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

__all__ = ["LocationHotspot"]


@dataclass(frozen=True, slots=True)
class LocationHotspot:
    """Where vibration evidence is spatially concentrated."""

    strongest_location: str = ""
    dominance_ratio: float | None = None
    localization_confidence: float | None = None
    weak_spatial_separation: bool = False
    ambiguous: bool = False
    alternative_locations: tuple[str, ...] = ()

    _UNKNOWN_LOCATIONS: ClassVar[frozenset[str]] = frozenset(
        {"", "unknown", "not available", "n/a"},
    )
    WEAK_SPATIAL_BASELINE: ClassVar[float] = 1.2
    _HIGH_CONFIDENCE_THRESHOLD: ClassVar[float] = 0.7
    _MEDIUM_CONFIDENCE_THRESHOLD: ClassVar[float] = 0.4
    _NEAR_TIE_CONFIDENCE_RATIO: ClassVar[float] = 0.7

    @staticmethod
    def weak_spatial_threshold(location_count: int | None) -> float:
        """Return the adaptive dominance threshold for weak separation."""
        baseline = LocationHotspot.WEAK_SPATIAL_BASELINE
        if location_count is None:
            return baseline
        n_locations = max(2, int(location_count))
        return baseline * (1.0 + (0.1 * (n_locations - 2)))

    # -- domain queries ----------------------------------------------------

    @property
    def has_clear_separation(self) -> bool:
        """Evidence is not spatially weak or ambiguous."""
        return not self.weak_spatial_separation and not self.ambiguous

    @property
    def is_well_localized(self) -> bool:
        """Evidence is clearly concentrated at one location."""
        if self.strongest_location.strip().lower() in self._UNKNOWN_LOCATIONS:
            return False
        return self.has_clear_separation and (
            self.dominance_ratio is None or self.dominance_ratio >= 0.5
        )

    @property
    def is_actionable(self) -> bool:
        """Location is known and clear enough to act on."""
        return (
            self.strongest_location.strip().lower() not in self._UNKNOWN_LOCATIONS
            and not self.ambiguous
        )

    @property
    def confidence_band(self) -> str:
        """Bucket localization confidence into high/medium/low bands."""
        confidence = self.localization_confidence or 0.0
        if confidence >= self._HIGH_CONFIDENCE_THRESHOLD:
            return "high"
        if confidence >= self._MEDIUM_CONFIDENCE_THRESHOLD:
            return "medium"
        return "low"

    @property
    def supporting_locations(self) -> tuple[str, ...]:
        """Alternative locations excluding the primary location."""
        primary = self.strongest_location.strip()
        supporting: list[str] = []
        for candidate in self.alternative_locations:
            location = str(candidate).strip()
            if not location or location == primary or location in supporting:
                continue
            supporting.append(location)
        return tuple(supporting)

    @property
    def summary_location(self) -> str:
        """Location string used by summarized origin projections."""
        primary = self.strongest_location.strip() or "unknown"
        if self.has_clear_separation:
            return primary
        display_locations = [primary, *self.supporting_locations]
        unique_locations: list[str] = []
        for candidate in display_locations:
            if candidate and candidate not in unique_locations:
                unique_locations.append(candidate)
        return " / ".join(unique_locations) if unique_locations else primary

    @property
    def display_location(self) -> str:
        """Human-readable location string."""
        loc = self.strongest_location.strip()
        if loc.lower() in self._UNKNOWN_LOCATIONS:
            return "Unknown"
        return loc.replace("_", " ").title()

    @classmethod
    def from_analysis_inputs(
        cls,
        *,
        strongest_location: str,
        dominance_ratio: float | None = None,
        localization_confidence: float | None = None,
        weak_spatial_separation: bool = False,
        ambiguous: bool = False,
        alternative_locations: Sequence[str] = (),
    ) -> LocationHotspot:
        """Construct from typed analysis-side inputs.

        Any ambiguity promotion driven by a second finding must be resolved
        before this method is called because ``LocationHotspot`` is frozen.
        """
        return cls(
            strongest_location=strongest_location,
            dominance_ratio=dominance_ratio,
            localization_confidence=localization_confidence,
            weak_spatial_separation=weak_spatial_separation,
            ambiguous=ambiguous,
            alternative_locations=tuple(str(loc) for loc in alternative_locations if loc),
        )

    def promote_near_tie(
        self,
        *,
        alternative_location: str,
        top_confidence: float,
        alternative_confidence: float,
    ) -> LocationHotspot:
        """Return a hotspot promoted to ambiguous when a second finding is near-tied."""
        contender = alternative_location.strip()
        primary = self.strongest_location.strip()
        if (
            not contender
            or not primary
            or contender == primary
            or top_confidence <= 0.0
            or alternative_confidence / top_confidence < self._NEAR_TIE_CONFIDENCE_RATIO
        ):
            return self
        return LocationHotspot(
            strongest_location=self.strongest_location,
            dominance_ratio=self.dominance_ratio,
            localization_confidence=self.localization_confidence,
            weak_spatial_separation=True,
            ambiguous=True,
            alternative_locations=(*self.alternative_locations, contender),
        )

    def with_adaptive_weak_spatial(self, location_count: int | None) -> LocationHotspot:
        """Return a hotspot with adaptive weak-spatial classification applied."""
        if self.dominance_ratio is None:
            return self
        threshold = self.weak_spatial_threshold(location_count)
        if self.weak_spatial_separation or self.dominance_ratio < threshold:
            return LocationHotspot(
                strongest_location=self.strongest_location,
                dominance_ratio=self.dominance_ratio,
                localization_confidence=self.localization_confidence,
                weak_spatial_separation=True,
                ambiguous=self.ambiguous,
                alternative_locations=self.alternative_locations,
            )
        return self
