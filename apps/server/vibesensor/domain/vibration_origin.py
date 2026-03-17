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

    @classmethod
    def from_ranked_findings(
        cls,
        findings: tuple[Finding, ...],
    ) -> VibrationOrigin | None:
        """Build origin from the top-ranked findings.

        Constructs a ``LocationHotspot`` from the top finding, applies
        adaptive weak-spatial classification, and promotes near-ties
        when a second finding is close in confidence.  Returns ``None``
        when *findings* is empty.
        """
        if not findings:
            return None

        top = findings[0]

        # Build LocationHotspot from top finding
        if top.location is not None:
            loc = LocationHotspot.from_analysis_inputs(
                strongest_location=(
                    top.location.strongest_location or top.strongest_location or "unknown"
                ),
                dominance_ratio=(
                    top.location.dominance_ratio
                    if top.location.dominance_ratio is not None
                    else top.dominance_ratio
                ),
                localization_confidence=top.location.localization_confidence,
                weak_spatial_separation=top.location.weak_spatial_separation,
                ambiguous=top.location.ambiguous,
                alternative_locations=tuple(top.location.alternative_locations),
            )
        else:
            loc = LocationHotspot.from_analysis_inputs(
                strongest_location=top.strongest_location or "unknown",
                dominance_ratio=top.dominance_ratio,
                weak_spatial_separation=top.weak_spatial_separation,
            )

        # Adaptive weak spatial
        location_count = top.location.location_count if top.location else None
        loc = loc.with_adaptive_weak_spatial(location_count)

        # Near-tie promotion
        if len(findings) >= 2:
            second = findings[1]
            second_location = (
                (second.location.strongest_location if second.location else "")
                or second.strongest_location
                or ""
            ).strip()
            loc = loc.promote_near_tie(
                alternative_location=second_location,
                top_confidence=top.effective_confidence,
                alternative_confidence=second.effective_confidence,
            )

        speed_band = str(top.strongest_speed_band or "")
        dominant_phase = (
            str(top.origin.dominant_phase or "").strip() if top.origin else ""
        )

        return cls(
            suspected_source=top.suspected_source,
            hotspot=loc,
            dominance_ratio=loc.dominance_ratio,
            speed_band=speed_band or None,
            dominant_phase=dominant_phase or None,
        )

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.hotspot and (self.hotspot.ambiguous or not self.hotspot.is_well_localized))

    @property
    def has_sufficient_location(self) -> bool:
        """Whether this origin has structured location data (a hotspot)."""
        return self.hotspot is not None

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
