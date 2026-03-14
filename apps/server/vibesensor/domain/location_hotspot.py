"""Spatial concentration of vibration evidence.

``LocationHotspot`` captures where vibration evidence is strongest,
whether the source is well-localised or ambiguous, and what
alternative locations compete.  This gives spatial reasoning a
domain-level identity instead of living in boundary TypedDicts.
"""

from __future__ import annotations

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

    # -- domain queries ----------------------------------------------------

    @property
    def is_well_localized(self) -> bool:
        """Evidence is clearly concentrated at one location."""
        if self.strongest_location.strip().lower() in self._UNKNOWN_LOCATIONS:
            return False
        return (
            not self.weak_spatial_separation
            and not self.ambiguous
            and (self.dominance_ratio is None or self.dominance_ratio >= 0.5)
        )

    @property
    def is_actionable(self) -> bool:
        """Location is known and clear enough to act on."""
        return (
            self.strongest_location.strip().lower() not in self._UNKNOWN_LOCATIONS
            and not self.ambiguous
        )

    @property
    def display_location(self) -> str:
        """Human-readable location string."""
        loc = self.strongest_location.strip()
        if loc.lower() in self._UNKNOWN_LOCATIONS:
            return "Unknown"
        return loc.replace("_", " ").title()

    # -- boundary adapter --------------------------------------------------

    @staticmethod
    def from_hotspot_dict(d: dict[str, object]) -> LocationHotspot:
        """Construct from a ``LocationHotspot`` payload dict (boundary adapter).

        Reads the ``location`` key (with fallback to ``top_location``) and
        normalises auxiliary fields defensively for historical payloads.
        """
        alts = d.get("alternative_locations") or d.get("ambiguous_locations") or []
        if not isinstance(alts, (list, tuple)):
            alts = []

        dom_raw = d.get("dominance_ratio")
        dom: float | None = None
        if dom_raw is not None:
            try:
                dom = float(dom_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass

        loc_conf_raw = d.get("localization_confidence")
        loc_conf: float | None = None
        if loc_conf_raw is not None:
            try:
                loc_conf = float(loc_conf_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass

        return LocationHotspot(
            strongest_location=str(
                d.get("location", d.get("top_location", "")) or ""
            ),
            dominance_ratio=dom,
            localization_confidence=loc_conf,
            weak_spatial_separation=bool(
                d.get("weak_spatial_separation", False)
            ),
            ambiguous=bool(d.get("ambiguous_location", d.get("ambiguous", False))),
            alternative_locations=tuple(str(a) for a in alts) if alts else (),
        )
